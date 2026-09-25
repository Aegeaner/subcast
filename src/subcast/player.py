"""Playback through mpv."""

from __future__ import annotations

import json
import select
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .background import say
from .meta import Streams
from .subtitles import GrowingCaptions, PendingSubtitles

# How often where an item got to is written down. Often enough that a run
# cut short costs seconds, rarely enough to leave the socket alone.
SAVE_SECONDS = 5.0

# How often to look while subtitles are still being prepared: the file is
# usually seconds away, and attaching it late is worse than asking often.
SUBTITLES_POLL_SECONDS = 0.5

# mpv opens its IPC socket before it will take a file, and answers a
# command that arrives in between with "error running command": measured,
# commands sent the moment the socket appears were refused 17 times out
# of 30, and the same command a moment later always worked. A run whose
# captions were ready before playback began asks on its first poll, which
# is inside that window, so a refusal is asked about again rather than
# left as a run that plays without its captions.
ATTACH_TRIES = 3
ATTACH_PAUSE = 0.2

# Reaching within this much of the end counts as watched: resuming there
# would start at the credits.
FINISHED_SECONDS = 15.0

# mpv's exit code for "the file passed to mpv couldn't be played". A stream
# that fails this way gets one more go: YouTube hands out signed URLs that
# answer 403 from time to time - a fresh extraction is what cures it, and
# mpv gives up on the first one.
LOAD_ERROR = 2

# What mpv is asked for when only the sound of a broadcast is wanted. A live
# item has no audio-only format at all - its formats are muxed - so the
# cheapest one carrying sound is the cheapest way at the audio: 144p at 290k
# against the 1080p the plain `bestaudio/best` falls back to, which is 5421k
# on the same stream.
LIVE_AUDIO_FORMAT = "worstaudio/worst"

# How big the captions are drawn over a video, in mpv's own unit for
# `--sub-font-size`: the size in scaled pixels at a window height of 720,
# which mpv scales with the window from there. mpv's default is 38, and the
# captions are the reason the item was opened, so a run asks for more.
SUB_FONT_SIZE = 64

# What mpv's on-screen controller does while an item plays: kept on screen,
# out of the way until the mouse moves, or not drawn at all. It is the title
# bar of a window that has none - a compositor that does not decorate mpv
# (GNOME on Wayland) draws no title, and mpv hides its own the moment the
# mouse stops moving - so a run keeps it up and names the item with it.
OSC_VISIBILITY = "always"

# How much bigger mpv draws that controller (`osc-scalewindowed` and
# `osc-scalefullscreen` multiply the sizes it draws itself with; its own
# `--osd-font-size` is not what these are). Its title and clock are read at
# a glance, so they are drawn a third larger, in step with the captions.
OSC_SCALE = 1.33

# The key that asks for what is playing to be cached with its subtitles, and
# the message mpv sends back when it is pressed. mpv's own `d` binds a weak
# `cycle deinterlace`, and a binding made over IPC is stronger than a weak
# one, so the run's key is the one that runs.
CACHE_KEY = "d"

CACHE_MESSAGE = "subcast-cache"

# How long a player's wait may run before it says what the cache work has
# said: short enough that a line lands while it is worth reading, long enough
# that waiting costs nothing.
CACHE_POLL_SECONDS = 0.5


class CacheWork(NamedTuple):
    """
    What a run has for the item playing: what its `d` key asks for, and the
    lines the cache work has to say.

    Both belong to the run rather than to the player: the key asks the same
    queue a marked entry goes into, and where the lines come from is that
    queue. The player is what says them, because the caption block is drawn
    on the terminal they would otherwise land in.
    """

    press: Callable[[], None] | None
    notes: Callable[[], list[str]]


def retry_load_error(
    play: Callable[[], int],
    again: Callable[[], int] | None = None,
) -> int:
    """
    Run an mpv attempt, giving a stream it could not load one more go.

    Only mpv's own "couldn't be played" is retried: quitting normally, a bad
    option, or Ctrl-C all come back with their own status. `again` is what
    the second attempt runs instead - for a run that was given stream URLs,
    the same command with the page URL, which mpv resolves for itself.
    """

    status = play()

    if status != LOAD_ERROR:

        return status

    print(
        "    mpv could not load that stream; trying once more...",
        flush=True,
    )

    return (again or play)()


def mpv_path() -> str:
    """
    Absolute path to mpv, or a RuntimeError explaining it is missing.
    """

    mpv = shutil.which(
        "mpv"
    )

    if not mpv:

        raise RuntimeError(
            "mpv was not found in PATH."
        )

    return mpv


class Positions:
    """
    Where an item got to, so the next run can pick it up from there.

    Keyed by the item rather than by its URL: a source whose stream URL is
    signed and short-lived (RTÉ) would never match its own last position,
    the way mpv's watch-later files do.
    """

    def __init__(
        self,
        stem: Path,
        resume: bool = True,
    ) -> None:

        self.path = stem.with_suffix(
            ".position"
        )

        self.start = (
            self._read()
            if resume
            else 0.0
        )

    def _read(self) -> float:

        try:

            seconds = float(
                self.path.read_text().strip()
            )

        except (OSError, ValueError):
            return 0.0

        return max(seconds, 0.0)

    def update(
        self,
        seconds: float,
        duration: float | None = None,
        eof: bool = False,
    ) -> None:
        """
        Write down where playback is up to, unless the item has ended:
        reaching the end should not resume at the credits next time.
        """

        if eof or (
            duration
            and seconds >= duration - FINISHED_SECONDS
        ):

            self.clear()
            return

        try:

            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.path.write_text(
                f"{max(seconds, 0.0):.1f}\n"
            )

        except OSError:

            # Forgetting where you are is a poor reason to stop playing.
            pass

    def clear(self) -> None:

        try:

            self.path.unlink()

        except OSError:
            pass


def start_arguments(
    positions: Positions | None,
) -> list[str]:
    """
    The mpv option that picks an item up where it was left.
    """

    if positions is None or positions.start <= 0:

        return []

    return [
        f"--start={positions.start:.1f}"
    ]


class Ipc:
    """Minimal mpv IPC client: one request at a time."""

    def __init__(self, path: Path) -> None:

        self.socket = socket.socket(
            socket.AF_UNIX
        )

        self.socket.connect(
            str(path)
        )

        self.buffer = b""
        self.request_id = 0

        # What mpv said that was not an answer to a request: a key binding's
        # `client-message`, kept until the player asks for it.
        self._events: list[list[str]] = []

    def get(self, name: str):
        """
        A property's value, or None when mpv has no answer to give - which
        is what an unavailable property is, and what a dead socket is.

        Every mpv reply carries an `error` field, and "success" is what it
        says when it is answering: reading that field as a verdict rather
        than as its value is what made this return None for every property
        there is, which quietly turned resumes and end-of-file detection
        into no-ops.
        """

        message = self._request(
            ["get_property", name]
        )

        if message is None or message.get("error") not in (None, "success"):

            return None

        return message.get("data")

    def command(self, *command: str) -> str | None:
        """
        Run a command, returning what mpv said went wrong, or None.
        """

        message = self._request(
            list(command)
        )

        if message is None:

            return "mpv is not answering"

        error = message.get("error")

        if error in (None, "success"):

            return None

        return str(error)

    def _request(self, command: list) -> dict | None:

        self.request_id += 1

        request = {
            "command": command,
            "request_id": self.request_id,
        }

        try:
            self.socket.sendall(
                (
                    json.dumps(request) + "\n"
                ).encode()
            )

        except OSError:
            # mpv is on its way out. The question has no answer worth
            # having, and failing here would only turn quitting into an
            # error message.
            return None

        while True:

            line = self._read_line()

            if line is None:
                return None

            try:
                message = json.loads(line)

            except ValueError:
                continue

            if (
                message.get("request_id")
                == self.request_id
            ):
                return message

            # Not this request's answer: mpv sent something of its own -
            # a binding's message - while it was answering.
            self._keep(message)

    def messages(
        self,
        timeout: float = 0.0,
    ) -> list[list[str]]:
        """
        The `client-message` events mpv has sent, each as its arguments, and
        waits up to `timeout` seconds for the first of them.

        This is how a key reaches the run: mpv is told to bind it to
        `script-message`, and the key is run by mpv whoever took the press -
        its own window, or the terminal it was started from - so a run only
        learns about it this way.

        A message that arrived while a property was being asked for is
        waiting here already, because it was made room for rather than
        dropped; `timeout` then decides whether to sit on the socket for
        one that has not come yet.
        """

        deadline = time.monotonic() + max(timeout, 0.0)

        while True:

            if self._events:

                found = self._events
                self._events = []

                return found

            remaining = deadline - time.monotonic()

            if remaining <= 0:

                return []

            readable, _, _ = select.select(
                [self.socket],
                [],
                [],
                remaining,
            )

            if not readable:

                return []

            line = self._read_line()

            if line is None:

                return []

            try:
                message = json.loads(line)

            except ValueError:
                continue

            self._keep(message)

    def _keep(self, message: dict) -> None:
        """
        Note what mpv sent on its own account, for the next look.
        """

        if message.get("event") != "client-message":

            return

        self._events.append(
            [
                str(argument)
                for argument in message.get("args") or []
            ]
        )

    def _read_line(self) -> str | None:

        while b"\n" not in self.buffer:

            try:
                chunk = self.socket.recv(4096)

            except OSError:
                return None

            if not chunk:
                return None

            self.buffer += chunk

        line, _, self.buffer = (
            self.buffer.partition(b"\n")
        )

        return line.decode(
            "utf-8",
            "replace",
        )

    def close(self) -> None:

        try:
            self.socket.close()

        except OSError:
            pass


def connect(
    socket_path: Path,
    timeout: float = 10.0,
) -> Ipc | None:
    """
    The IPC client, once mpv has opened its end of the socket.
    """

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:

        if socket_path.exists():

            try:
                return Ipc(socket_path)

            except OSError:
                pass

        if time.monotonic() >= deadline:
            break

        time.sleep(0.05)

    return None


def socket_directory() -> Path:
    """
    A private directory for this run's IPC socket: a stale socket from an
    earlier run must not be mistaken for this run's mpv.
    """

    return Path(
        tempfile.mkdtemp(
            prefix="subcast-"
        )
    )


class CacheKey:
    """
    `d`: the key that puts the item being played into the cache.

    The binding is made over IPC as playback starts, rather than written
    into an input file, so nothing of the user's own mpv configuration is
    replaced. mpv is what runs the key - its window and the terminal it was
    started from both give it the press - and it reports the press back
    through the same socket as a `client-message`, which is the only way a
    key the window took ever reaches the run.

    `wait` is the sleep the player would have taken anyway, spent waiting
    for mpv to say something instead: a press ends it at once, and a player
    with nothing to watch sleeps exactly as long as it asked to. It is also
    where the run's cache work is heard from: the lines are printed here,
    from the thread that owns the screen, rather than from the worker that
    said them, and `wait` says whether any of them went over the block.
    """

    def __init__(
        self,
        client: Ipc,
        work: CacheWork | None = None,
    ) -> None:

        self._client = client
        self._work = work

        if work is None or work.press is None:

            return

        problem = client.command(
            "keybind",
            CACHE_KEY,
            f"script-message {CACHE_MESSAGE}",
        )

        if problem is not None:

            print(
                f"    mpv would not bind {CACHE_KEY} ({problem}); "
                "what plays cannot be cached with a key.",
                flush=True,
            )

    def wait(
        self,
        seconds: float,
    ) -> bool:
        """
        Spend `seconds` waiting: keep what plays if the key was pressed, and
        say what the cache work has to say.

        True means a line was printed over whatever is drawing, so the
        caption block has to be drawn again. The wait is taken in steps
        while those lines are coming, because a line said at the end of a
        long wait is a line said late.
        """

        if self._work is None:

            time.sleep(seconds)

            return False

        said = False
        deadline = time.monotonic() + seconds

        while True:

            step = max(
                min(
                    deadline - time.monotonic(),
                    CACHE_POLL_SECONDS,
                ),
                0.0,
            )

            if self._work.press is not None:

                for message in self._client.messages(step):

                    if message[:1] == [CACHE_MESSAGE]:

                        # The press says a line of its own - what became of
                        # it - and the block has to be drawn again over it.
                        self._work.press()
                        said = True

            elif step > 0:

                time.sleep(step)

            for line in self._work.notes():

                say(line)

                said = True

            if time.monotonic() >= deadline:

                return said


def run_mpv(
    command: list[str],
    positions: Positions | None = None,
    subtitles: PendingSubtitles | None = None,
    rebuild: Callable[[], list[str]] | None = None,
    cache: CacheWork | None = None,
) -> int:
    """
    Play through mpv, remembering where the item gets to, handing it the
    subtitles once they are ready, and caching it if the key is pressed.

    With none of them, mpv is left entirely to itself, which is what every
    caller did before resumes, background subtitles and the cache key
    existed. `rebuild` builds the command again for a retry, which is what a
    run holding signed stream URLs wants.
    """

    def play() -> int:

        return _run_once(
            command,
            positions,
            subtitles,
            cache,
        )

    def refresh() -> int:

        return _run_once(
            rebuild(),
            positions,
            subtitles,
            cache,
        )

    return retry_load_error(
        play,
        again=(
            refresh
            if rebuild is not None
            else None
        ),
    )


def _run_once(
    command: list[str],
    positions: Positions | None = None,
    subtitles: PendingSubtitles | None = None,
    cache: CacheWork | None = None,
) -> int:

    if positions is None and subtitles is None and cache is None:

        return subprocess.run(
            command,
            check=False,
        ).returncode

    directory = socket_directory()

    socket_path = directory / "mpv.sock"

    command = [
        *command,
        f"--input-ipc-server={socket_path}",
        *start_arguments(positions),
    ]

    process = subprocess.Popen(
        command
    )

    try:
        return follow(
            process,
            socket_path,
            positions,
            subtitles,
            cache,
        )

    finally:

        if process.poll() is None:
            process.terminate()

        process.wait()

        shutil.rmtree(
            directory,
            ignore_errors=True,
        )


def attach_subtitles(
    client: Ipc,
    subtitles: PendingSubtitles,
) -> bool:
    """
    Hand mpv the subtitles a job has finished, once. False means they are
    still being worked out, and the caller should ask again.

    mpv takes an external file mid-playback with `sub-add`, which is what
    makes playing first possible at all: the file's own timings are what
    they are, so the captions line up from the moment they arrive.
    """

    if not subtitles.done_yet():

        return False

    failure = subtitles.failure_message()

    if failure is not None:

        print(failure, flush=True)

        return True

    prepared = subtitles.value()

    if prepared is None:

        return True

    problem = client.command(
        "sub-add",
        str(prepared.srt_path),
        "select",
    )

    # A refusal this early is mpv not being ready rather than the file
    # being wrong (see ATTACH_TRIES), so the same file is offered again.
    for _attempt in range(ATTACH_TRIES - 1):

        if problem is None:

            break

        time.sleep(ATTACH_PAUSE)

        problem = client.command(
            "sub-add",
            str(prepared.srt_path),
            "select",
        )

    if problem is not None:

        print(
            f"    mpv would not take the subtitles ({problem}).",
            flush=True,
        )

    return True


def settled_live(
    subtitles: PendingSubtitles,
) -> GrowingCaptions | None:
    """
    The captions a preparation turned into, when they are made while the
    item plays - a broadcast's, or a file's being heard - once the resolve
    is done.

    Until then there is nothing to hand mpv either way, and a video that
    was not a broadcast gets its subtitle file the way it always has.
    """

    if not subtitles.done_yet():

        return None

    value = subtitles.value()

    return value if isinstance(value, GrowingCaptions) else None


class LiveView:
    """
    mpv's side of captions that arrive while the item plays: where it has
    read up to, and the captions that have landed since the last look.

    `cache-time` is the position mpv has read up to, which is the audio
    being captured at that moment - the one reading that says where a piece
    of it belongs, because the audio of a broadcast carries no clock of its
    own. A source that does not report it leaves the playback position,
    which is the same thing less mpv's own buffer.
    """

    def __init__(
        self,
        client: Ipc,
        live: GrowingCaptions,
    ) -> None:

        self.client = client
        self.live = live
        self.attached = False
        self.reported = False

        # Nothing has been handed to mpv yet, whatever the job has already
        # heard: the first look is what attaches it.
        self.revision = 0

        # The capture begins when something is watching the broadcast: an
        # item prepared for later has nothing playing to be in step with.
        live.start()

    def pass_over(self) -> None:
        """
        One look: sample the live edge, say what went wrong once, and hand
        the captions over when there are new ones.
        """

        edge = self.client.get(
            "demuxer-cache-time"
        )

        position = self.client.get(
            "time-pos"
        )

        seen = edge if edge is not None else position

        if seen is not None:

            self.live.sample(
                time.monotonic(),
                float(seen),
            )

        for note in self.live.take_notes():

            print(note, flush=True)

        if not self.reported:

            failure = self.live.failure_message()

            if failure is not None:

                self.reported = True

                print(failure, flush=True)

        revision = self.live.revision()

        if revision == self.revision:

            return

        self.revision = revision

        if revision == 0:

            # Nothing has been said yet, so there is no file to hand over.
            return

        if self.attached:

            problem = self.client.command(
                "sub-reload"
            )

            if problem is None:

                return

            print(
                "    mpv would not read the live captions again "
                f"({problem}).",
                flush=True,
            )

            return

        problem = self.client.command(
            "sub-add",
            str(self.live.srt_path),
            "select",
        )

        if problem is None:

            self.attached = True

            return

        print(
            f"    mpv would not take the live captions ({problem}).",
            flush=True,
        )


def follow(
    process: subprocess.Popen,
    socket_path: Path,
    positions: Positions | None,
    subtitles: PendingSubtitles | None = None,
    cache: CacheWork | None = None,
) -> int:
    """
    Write down where mpv is up to while it plays, so a run that ends
    abruptly still resumes where it stopped - give mpv the subtitles once
    they are ready - and keep an ear out for the key that caches the item.

    A broadcast is the case that never becomes ready: its captions are made
    while it airs, so the file is handed over as soon as the first cues are
    in it and reloaded each time it grows.
    """

    client = connect(
        socket_path
    )

    if client is None:
        return process.wait()

    key = CacheKey(client, cache)

    waiting = subtitles is not None

    view: LiveView | None = None

    try:

        while process.poll() is None:

            if positions is not None:

                seconds = client.get(
                    "time-pos"
                )

                if seconds is not None:

                    positions.update(
                        float(seconds),
                        client.get("duration"),
                        bool(client.get("eof-reached")),
                    )

            if view is not None:

                view.pass_over()

            elif waiting:

                live = settled_live(
                    subtitles
                )

                if live is None:

                    waiting = not attach_subtitles(
                        client,
                        subtitles,
                    )

                else:

                    waiting = False
                    view = LiveView(client, live)

            key.wait(
                SUBTITLES_POLL_SECONDS
                if waiting or view is not None
                else SAVE_SECONDS
            )

        if waiting:

            attach_subtitles(
                client,
                subtitles,
            )

        return process.returncode

    finally:

        client.close()


def stream_arguments(
    streams: Streams,
) -> list[str]:
    """
    What mpv needs to play streams we resolved ourselves instead of being
    handed the page URL and extracting them for itself: the URLs are not a
    page, so yt-dlp is switched off.

    The picture and the sound arrive separately on most sources, so the
    second URL is mpv's external audio track.

    The headers a resolve reported are deliberately left out. Sending them
    is what made YouTube answer `HTTP error 400 Bad Request` on the stream
    URL, every time, where the same URL plays when mpv asks for it with its
    own headers - so the fewer of ours on the request, the better.
    """

    arguments = ["--ytdl=no"]

    if streams.video is not None and streams.audio is not None:

        arguments.append(
            f"--audio-file={streams.audio}"
        )

    return arguments


def streams_message(
    url: str,
    streams: Streams | None,
    stream: bool,
) -> str:
    """
    What mpv was given to play, and so what it has to extract for itself:
    URLs a resolve found and kept, a page URL it extracts from, the stream
    URL a resolve just found, or - for a captioned item - the audio that
    was transcribed, which is the only audio the captions are in pace with.
    """

    if streams is not None:

        return "    Streams: resolved by subcast"

    if stream:

        return "    Streams: mpv extracts them from the page"

    if url.startswith(("http://", "https://")):

        return "    Streams: the stream URL subcast resolved"

    return "    Streams: the audio the captions were timed against"


def play_with_mpv(
    url: str,
    subtitle_path: Path | None = None,
    chapters_path: Path | None = None,
    stream: bool = False,
    positions: Positions | None = None,
    subtitles: PendingSubtitles | None = None,
    streams: Streams | None = None,
    live: bool = False,
    reloading: bool = False,
    title: str | None = None,
    cache: CacheWork | None = None,
) -> int:
    """
    Play audio through mpv's own terminal output.

    `streams` are the URLs our own resolve found, which save mpv the same
    extraction. A stream mpv cannot load - sites turn one down now and then -
    falls back to the page URL, which mpv extracts for itself, so a refusal
    costs a retry rather than the run.

    `live` is a broadcast: its formats are muxed, so the sound is what the
    cheapest one carries.

    `reloading` is any item whose captions arrive while it plays - a
    broadcast's, or a file being heard: mpv answers every reload by logging
    its whole track list - four lines of terminal between the captions -
    so playback's own informational logging is turned down for one. Only
    that module: turning every module down (`all=warn`) takes the
    terminal's subtitles with it, and warnings and errors show either way.

    `title` names the item to mpv. Nothing a run draws itself shows it -
    the captions are ours and the status line is off - so it is there for
    the surfaces mpv has that we do not: the OSD, and the window title a
    user's own settings build from `media-title`.

    `cache` is what the key that caches the item asks for (`CacheKey`).
    """

    mpv = mpv_path()

    print()
    print(
        "Starting mpv..."
    )
    print(
        f"    {url}"
    )

    print(
        streams_message(
            url,
            streams,
            stream,
        )
    )

    if subtitle_path is not None:
        print(
            f"    {subtitle_path}"
        )

    print()

    def command_for(
        streams: Streams | None,
    ) -> list[str]:

        command = [
            mpv,
            "--no-video",
            "--force-window=no",
            "--cache=yes",
        ]

        if live or reloading:

            command.append(
                "--msg-level=cplayer=warn"
            )

        if title is not None:

            # What mpv would otherwise call the item is the URL it was
            # handed, which for a resolved stream is a signed link.
            command.append(
                f"--force-media-title={title}"
            )

        if streams is None:

            if stream:

                command.extend(
                    [
                        "--ytdl=yes",
                        (
                            f"--ytdl-format={LIVE_AUDIO_FORMAT}"
                            if live
                            else "--ytdl-format=bestaudio/best"
                        ),
                    ]
                )

            target = str(url)

        else:

            command.extend(
                stream_arguments(streams)
            )

            target = streams.first

        if subtitle_path is not None or subtitles is not None:

            command.extend(
                [
                    *(
                        [f"--sub-file={subtitle_path}"]
                        if subtitle_path is not None
                        else []
                    ),

                    # Print the subtitles in the terminal, and keep the
                    # status line quiet so it does not redraw them. This
                    # is set either way: a file added later is printed the
                    # same.
                    "--term-osd=force",
                    "--term-status-msg=",
                ]
            )

        if chapters_path is not None:

            command.append(
                f"--chapters-file={chapters_path}"
            )

        command.append(
            target
        )

        return command

    def rebuild() -> list[str]:
        # The second attempt drops our streams: mpv extracts the page for
        # itself, which is the path that always works.

        return command_for(None)

    return run_mpv(
        command_for(streams),
        positions,
        subtitles,
        rebuild=(
            rebuild
            if streams is not None
            else None
        ),
        cache=cache,
    )


def play_window(
    url: str,
    subtitle_path: Path | None = None,
    chapters_path: Path | None = None,
    quality: int = 1080,
    stream: bool = False,
    positions: Positions | None = None,
    subtitles: PendingSubtitles | None = None,
    streams: Streams | None = None,
    live: bool = False,
    reloading: bool = False,
    title: str | None = None,
    osc: str = OSC_VISIBILITY,
    cache: CacheWork | None = None,
) -> int:
    """
    Play video in an mpv window, with the subtitles we produced.

    Terminal captions only make sense for audio: with video, mpv renders
    them itself, over the picture, and asks for `SUB_FONT_SIZE` rather than
    mpv's own smaller default. `osc` is what mpv's on-screen controller
    does - the title bar of a window a compositor does not decorate, which
    draws the item's name that `title` forces onto `media-title` - and it is
    drawn at `OSC_SCALE`.

    `streams` are the URLs our own resolve found, which save mpv the same
    extraction. A stream mpv cannot load - sites turn one down now and then -
    falls back to the page URL, which mpv extracts for itself, so a refusal
    costs a retry rather than the run.

    `live` is a broadcast, whose captions are reloaded as they are made:
    mpv answers every reload by logging its whole track list, so playback's
    own informational logging is turned down for one. Only that module:
    turning every module down (`all=warn`) takes the terminal's subtitles
    with it, and warnings and errors show either way.

    `title` names the item in the window instead of the URL mpv was handed
    - a signed stream link, or a page - which is what the title bar would
    otherwise show. It is forced onto `media-title`, so the title the
    user's own `--title` builds from that property is what is drawn.

    `cache` is what the key that caches the item asks for (`CacheKey`),
    bound to mpv's own keyboard so it works while the window has it.
    """

    mpv = mpv_path()

    print()
    print(
        "Starting mpv..."
    )
    print(
        f"    {url}"
    )

    print(
        streams_message(
            url,
            streams,
            stream,
        )
    )

    if subtitle_path is not None:
        print(
            f"    {subtitle_path}"
        )

    print()

    def command_for(
        streams: Streams | None,
    ) -> list[str]:

        command = [
            mpv,
            "--force-window=yes",

            # Appended rather than set, so settings a user keeps for other
            # scripts survive.
            (
                f"--script-opts-add=osc-visibility={osc},"
                f"osc-scalewindowed={OSC_SCALE},"
                f"osc-scalefullscreen={OSC_SCALE}"
            ),

            # mpv renders these captions itself, over the picture.
            f"--sub-font-size={SUB_FONT_SIZE}",
        ]

        if live or reloading:

            command.append(
                "--msg-level=cplayer=warn"
            )

        if title is not None:

            # Without this the window is titled after the googlevideo URL
            # a resolve found, or the page mpv is extracting.
            command.append(
                f"--force-media-title={title}"
            )

        if streams is None:

            # `[protocol^=https]` keeps yt-dlp off YouTube's HLS
            # renditions: the height filter alone lands on its 1080p
            # "premium" one, 4600k of HLS where the DASH formats next to
            # it are 1417k (AV1) and 2130k (VP9) - measured on the video
            # from the report. The wait before the first frame here is
            # mpv filling its cache, so it is that bitrate the wait is
            # made of.
            #
            # A broadcast has HLS and nothing else - while it airs and
            # after it ends - so that filter matches none of its formats
            # and yt-dlp answers "Requested format is not available",
            # which is a run that plays nothing. The same request without
            # the filter is what plays one; `/best` is the fallback for a
            # source that offers neither.
            #
            command.append(
                f"--ytdl-format=bestvideo[height<={quality}]"
                f"[protocol^=https]+bestaudio/"
                f"bestvideo[height<={quality}]+bestaudio/"
                f"best"
            )

            if stream:

                command.append(
                    "--ytdl=yes"
                )

            target = str(url)

        else:

            command.extend(
                stream_arguments(streams)
            )

            target = streams.first

        if subtitle_path is not None:

            command.extend(
                [
                    f"--sub-file={subtitle_path}",
                    "--sid=1",
                ]
            )

        elif subtitles is not None:

            # Ours are on the way, so nothing else should take the screen
            # in the meantime: the file is added with `sub-add` when it
            # lands.
            command.append(
                "--sid=no"
            )

        if chapters_path is not None:

            command.append(
                f"--chapters-file={chapters_path}"
            )

        command.append(
            target
        )

        return command

    def rebuild() -> list[str]:
        # The second attempt drops our streams: mpv extracts the page for
        # itself, which is the path that always works.

        return command_for(None)

    return run_mpv(
        command_for(streams),
        positions,
        subtitles,
        rebuild=(
            rebuild
            if streams is not None
            else None
        ),
        cache=cache,
    )
