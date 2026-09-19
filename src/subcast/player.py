"""Playback through mpv."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .meta import Streams
from .subtitles import PendingSubtitles

# How often where an item got to is written down. Often enough that a run
# cut short costs seconds, rarely enough to leave the socket alone.
SAVE_SECONDS = 5.0

# How often to look while subtitles are still being prepared: the file is
# usually seconds away, and attaching it late is worse than asking often.
SUBTITLES_POLL_SECONDS = 0.5

# Reaching within this much of the end counts as watched: resuming there
# would start at the credits.
FINISHED_SECONDS = 15.0

# mpv's exit code for "the file passed to mpv couldn't be played". A stream
# that fails this way gets one more go: YouTube hands out signed URLs that
# answer 403 from time to time - a fresh extraction is what cures it, and
# mpv gives up on the first one.
LOAD_ERROR = 2


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


def run_mpv(
    command: list[str],
    positions: Positions | None = None,
    subtitles: PendingSubtitles | None = None,
    rebuild: Callable[[], list[str]] | None = None,
) -> int:
    """
    Play through mpv, remembering where the item gets to and handing it the
    subtitles once they are ready.

    With neither, mpv is left entirely to itself, which is what every
    caller did before resumes and background subtitles existed. `rebuild`
    builds the command again for a retry, which is what a run holding signed
    stream URLs wants.
    """

    def play() -> int:

        return _run_once(
            command,
            positions,
            subtitles,
        )

    def refresh() -> int:

        return _run_once(
            rebuild(),
            positions,
            subtitles,
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
) -> int:

    if positions is None and subtitles is None:

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

    if problem is not None:

        print(
            f"    mpv would not take the subtitles ({problem}).",
            flush=True,
        )

    return True


def follow(
    process: subprocess.Popen,
    socket_path: Path,
    positions: Positions | None,
    subtitles: PendingSubtitles | None = None,
) -> int:
    """
    Write down where mpv is up to while it plays, so a run that ends
    abruptly still resumes where it stopped - and give mpv the subtitles
    once they are ready.
    """

    client = connect(
        socket_path
    )

    if client is None:
        return process.wait()

    waiting = subtitles is not None

    try:

        while process.poll() is None:

            seconds = client.get(
                "time-pos"
            )

            if positions is not None and seconds is not None:

                positions.update(
                    float(seconds),
                    client.get("duration"),
                    bool(client.get("eof-reached")),
                )

            if waiting:

                waiting = not attach_subtitles(
                    client,
                    subtitles,
                )

            time.sleep(
                SUBTITLES_POLL_SECONDS
                if waiting
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


def play_with_mpv(
    url: str,
    subtitle_path: Path | None = None,
    chapters_path: Path | None = None,
    stream: bool = False,
    positions: Positions | None = None,
    subtitles: PendingSubtitles | None = None,
    streams: Streams | None = None,
) -> int:
    """
    Play audio through mpv's own terminal output.

    `streams` are the URLs our own resolve found, which save mpv the same
    extraction. A stream mpv cannot load - sites turn one down now and then -
    falls back to the page URL, which mpv extracts for itself, so a refusal
    costs a retry rather than the run.
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
        "    Streams: resolved by subcast"
        if streams is not None
        else "    Streams: mpv extracts them from the page"
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

        if streams is None:

            if stream:

                command.extend(
                    [
                        "--ytdl=yes",
                        "--ytdl-format=bestaudio/best",
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
) -> int:
    """
    Play video in an mpv window, with the subtitles we produced.

    Terminal captions only make sense for audio: with video, mpv renders
    them itself, over the picture, using the user's own mpv settings.

    `streams` are the URLs our own resolve found, which save mpv the same
    extraction. A stream mpv cannot load - sites turn one down now and then -
    falls back to the page URL, which mpv extracts for itself, so a refusal
    costs a retry rather than the run.
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
        "    Streams: resolved by subcast"
        if streams is not None
        else "    Streams: mpv extracts them from the page"
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
        ]

        if streams is None:

            # `[protocol^=https]` keeps yt-dlp off YouTube's HLS
            # renditions: the height filter alone lands on its 1080p
            # "premium" one, 4600k of HLS where the DASH formats next to
            # it are 1417k (AV1) and 2130k (VP9) - measured on the video
            # from the report. The wait before the first frame here is
            # mpv filling its cache, so it is that bitrate the wait is
            # made of; `/best` is the fallback for a source that offers
            # nothing else.
            #
            command.append(
                f"--ytdl-format=bestvideo[height<={quality}]"
                f"[protocol^=https]+bestaudio/"
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
    )
