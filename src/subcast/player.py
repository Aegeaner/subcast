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

# How often where an item got to is written down. Often enough that a run
# cut short costs seconds, rarely enough to leave the socket alone.
SAVE_SECONDS = 5.0

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
) -> int:
    """
    Run an mpv attempt, giving a stream it could not load one more go.

    Only mpv's own "couldn't be played" is retried: quitting normally, a
    bad option, or Ctrl-C all come back with their own status.
    """

    status = play()

    if status != LOAD_ERROR:

        return status

    print(
        "    mpv could not load that stream; trying once more...",
        flush=True,
    )

    return play()


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

        self.request_id += 1

        request = {
            "command": ["get_property", name],
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
                return message.get("data")

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
) -> int:
    """
    Play through mpv, remembering where the item gets to.

    Without `positions` mpv is left entirely to itself, which is what
    every caller did before resumes existed.
    """

    return retry_load_error(
        lambda: _run_once(
            command,
            positions,
        )
    )


def _run_once(
    command: list[str],
    positions: Positions | None = None,
) -> int:

    if positions is None:

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
        )

    finally:

        if process.poll() is None:
            process.terminate()

        process.wait()

        shutil.rmtree(
            directory,
            ignore_errors=True,
        )


def follow(
    process: subprocess.Popen,
    socket_path: Path,
    positions: Positions,
) -> int:
    """
    Write down where mpv is up to while it plays, so a run that ends
    abruptly still resumes where it stopped.
    """

    client = connect(
        socket_path
    )

    if client is None:
        return process.wait()

    try:

        while process.poll() is None:

            seconds = client.get(
                "time-pos"
            )

            if seconds is not None:

                positions.update(
                    float(seconds),
                    client.get("duration"),
                    bool(client.get("eof-reached")),
                )

            time.sleep(
                SAVE_SECONDS
            )

        return process.returncode

    finally:

        client.close()


def play_with_mpv(
    url: str,
    subtitle_path: Path | None = None,
    chapters_path: Path | None = None,
    stream: bool = False,
    positions: Positions | None = None,
) -> int:

    mpv = mpv_path()

    print()
    print(
        "Starting mpv..."
    )
    print(
        f"    {url}"
    )

    if subtitle_path is not None:
        print(
            f"    {subtitle_path}"
        )

    print()

    command = [
        mpv,
        "--no-video",
        "--force-window=no",
        "--cache=yes",
    ]

    if stream:

        command.extend(
            [
                "--ytdl=yes",
                "--ytdl-format=bestaudio/best",
            ]
        )

    if subtitle_path is not None:

        command.extend(
            [
                f"--sub-file={subtitle_path}",

                # Print the subtitles in the terminal, and keep the
                # status line quiet so it does not redraw them.
                "--term-osd=force",
                "--term-status-msg=",
            ]
        )

    if chapters_path is not None:

        command.append(
            f"--chapters-file={chapters_path}"
        )

    command.append(
        str(url)
    )

    return run_mpv(
        command,
        positions,
    )


def play_window(
    url: str,
    subtitle_path: Path | None = None,
    chapters_path: Path | None = None,
    quality: int = 1080,
    stream: bool = False,
    positions: Positions | None = None,
) -> int:
    """
    Play video in an mpv window, with the subtitles we produced.

    Terminal captions only make sense for audio: with video, mpv renders
    them itself, over the picture, using the user's own mpv settings.
    """

    mpv = mpv_path()

    print()
    print(
        "Starting mpv..."
    )
    print(
        f"    {url}"
    )

    if subtitle_path is not None:
        print(
            f"    {subtitle_path}"
        )

    print()

    command = [
        mpv,
        "--force-window=yes",
        (
            f"--ytdl-format=bestvideo[height<={quality}]+bestaudio/"
            f"best"
        ),
    ]

    if stream:

        command.append(
            "--ytdl=yes"
        )

    if subtitle_path is not None:

        command.extend(
            [
                f"--sub-file={subtitle_path}",
                "--sid=1",
            ]
        )

    if chapters_path is not None:

        command.append(
            f"--chapters-file={chapters_path}"
        )

    command.append(
        str(url)
    )

    return run_mpv(
        command,
        positions,
    )
