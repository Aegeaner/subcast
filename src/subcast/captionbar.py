"""Captions drawn by us at the bottom of the terminal.

mpv's terminal OSD cannot be styled and reprints its whole block on every
redraw. This draws a fixed block instead - a dim segment title, up to two
lines of dialogue under it, and the playback clock at the bottom - and
rewrites it only when the text changes, so the captions sit still and can
carry colour.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import termios
import textwrap
import time
import tty
from pathlib import Path

from .player import mpv_path

# Rows the block occupies: one title line, the previous line of dialogue,
# up to two lines of what is being said now, and the playback clock. Kept
# constant so the terminal does not reflow as captions come and go.
BLOCK_ROWS = 5

# The clock sits on the bottom row of the block.
PROGRESS_ROWS = 1

CAPTION_LINES = BLOCK_ROWS - 1 - PROGRESS_ROWS

# A bar narrower than this says nothing the clock either side of it has
# not already said, so a narrow window gets the two times alone.
MIN_BAR_CELLS = 12

# How many lines the current cue may occupy before it pushes the previous
# one off the block.
CURRENT_LINES = 2

# Scale used for the block when the terminal can render scaled text and
# the user did not say otherwise.
DEFAULT_SCALE = 2

# A line needs enough cells to be worth reading, so the scale is capped
# by the space the terminal actually has.
MIN_COLUMNS = 20

# How much wider a window has to be before the captions step up a size, and
# how big they may get. Extra width goes into bigger text rather than ever
# longer lines, so the block keeps filling a similar share of the window
# however it is sized — maximise the terminal and the captions grow with it.
SCALE_STEP_COLUMNS = 45

MAX_SCALE = 3

SIZING_QUERY = "\x1b[6n"

TITLE_COLOUR = "\x1b[2;36m"  # faint cyan: readable, not competing
HISTORY_COLOUR = "\x1b[2;37m"  # the line that just finished
CAPTION_COLOUR = "\x1b[97m"  # bright white
PROGRESS_COLOUR = "\x1b[2;37m"  # faint: reference, not reading matter
MUTED_MARK = " [muted]"

CLEAR_LINE = "\x1b[2K"
SAVE_CURSOR = "\x1b7"
RESTORE_CURSOR = "\x1b8"
RESET = "\x1b[0m"

POLL_SECONDS = 0.15

_STOPPING = False


def _request_stop(signum, frame) -> None:
    """
    Ask the loop to finish, so the block is cleared on the way out.
    """

    global _STOPPING

    _STOPPING = True


def auto_scale(
    columns: int,
) -> int:
    """
    Caption size that suits a window this wide.
    """

    return min(
        max(columns // SCALE_STEP_COLUMNS, 1),
        MAX_SCALE,
    )


def caption_width(
    columns: int,
    scale: int = 1,
) -> int:
    """
    Characters that fit on one caption line of a `columns` wide terminal.

    The block spans the window: maximise the terminal and the captions use
    all of it, with a single cell of margin so a line cannot wrap.
    """

    return max(
        columns // max(scale, 1) - 1,
        MIN_COLUMNS,
    )


def terminal_size() -> tuple[int, int]:
    """
    Size of the terminal being drawn on, asked of the terminal itself.

    `shutil.get_terminal_size()` prefers the COLUMNS and LINES environment
    variables, which go stale when the window is resized: maximise kitty
    and the block would keep drawing at the old width.
    """

    for stream in (sys.stdout, sys.stderr, sys.stdin):

        try:
            size = os.get_terminal_size(
                stream.fileno()
            )

        except (AttributeError, OSError, ValueError):
            continue

        if size.columns > 0 and size.lines > 0:
            return size.columns, size.lines

    fallback = shutil.get_terminal_size(
        fallback=(80, 24)
    )

    return fallback.columns, fallback.lines


def effective_scale(
    requested: int,
    rows: int,
    columns: int,
) -> int:
    """
    The largest scale the terminal has room for.

    A scaled line occupies `scale` rows and `scale` cells per character,
    and a block that does not fit is dropped by the terminal, so the
    request is capped rather than trusted.
    """

    fits_rows = max(rows // BLOCK_ROWS, 1)
    fits_columns = max(
        columns // MIN_COLUMNS,
        1,
    )

    return max(
        1,
        min(
            requested,
            fits_rows,
            fits_columns,
        ),
    )


def scaled_text(
    text: str,
    scale: int,
) -> str:
    """
    Wrap text in kitty's text sizing protocol, which renders it `scale`
    times the base font size without touching the terminal's settings.
    """

    if scale <= 1:
        return text

    return f"\x1b]66;s={scale};{text}\x07"


def in_kitty() -> bool:
    """
    Whether this process runs inside kitty, which is what the sizing
    protocol belongs to.
    """

    return bool(
        os.environ.get("KITTY_WINDOW_ID")
    ) or "kitty" in os.environ.get(
        "TERM",
        "",
    )


def supports_scaled_text(
    timeout: float = 0.4,
) -> bool:
    """
    Ask the terminal whether it can render scaled text.

    This is the detection procedure kitty documents: draw a space twice
    the width of a cell and a space in a 2x2 block, and see how far the
    cursor moves according to the terminal's own cursor reports.
    """

    if not in_kitty():
        return False

    if not (
        sys.stdin.isatty()
        and sys.stdout.isatty()
    ):
        return False

    descriptor = sys.stdin.fileno()
    saved = termios.tcgetattr(descriptor)

    try:
        tty.setraw(descriptor)

        return _probe_scaled_text(
            timeout
        )

    except (OSError, termios.error):
        return False

    finally:

        termios.tcsetattr(
            descriptor,
            termios.TCSADRAIN,
            saved,
        )


def _probe_scaled_text(
    timeout: float,
) -> bool:

    sys.stdout.write(
        f"{SAVE_CURSOR}{SIZING_QUERY}"
    )

    sys.stdout.write(
        "\x1b]66;w=2; \x07"
        f"{SIZING_QUERY}"
    )

    sys.stdout.write(
        "\x1b]66;s=2; \x07"
        f"{SIZING_QUERY}"
        f"{CLEAR_LINE}{RESTORE_CURSOR}"
    )

    sys.stdout.flush()

    positions = _read_positions(
        3,
        timeout,
    )

    if len(positions) < 3:
        return False

    first, second, third = positions

    return (
        second - first >= 2
        and third - second >= 2
    )


def _read_positions(
    count: int,
    timeout: float,
) -> list[int]:
    """
    Column of each cursor position report the terminal sends back.
    """

    deadline = time.monotonic() + timeout
    columns: list[int] = []
    buffer = ""

    descriptor = sys.stdin.fileno()

    while (
        len(columns) < count
        and time.monotonic() < deadline
    ):

        remaining = deadline - time.monotonic()

        # A terminal that never answers must not hold up playback, so
        # the read is bounded rather than blocking forever.
        readable, _, _ = select.select(
            [descriptor],
            [],
            [],
            max(remaining, 0.0),
        )

        if not readable:
            break

        try:
            chunk = os.read(
                descriptor,
                64,
            )

        except OSError:
            break

        if not chunk:
            break

        buffer += chunk.decode(
            "utf-8",
            "replace",
        )

        while "R" in buffer:

            report, _, buffer = buffer.partition(
                "R"
            )

            _, _, tail = report.rpartition(
                "["
            )

            parts = tail.split(";")

            if len(parts) == 2 and parts[1].isdigit():
                columns.append(int(parts[1]))

    return columns


def clock(
    seconds: float,
) -> str:
    """
    A playback position the way a listener reads it: 0:05, 4:07, 2:00:35.
    """

    total = max(
        int(seconds),
        0,
    )

    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


def progress_line(
    position: float,
    duration: float | None,
    width: int,
) -> str:
    """
    The bottom row of the block: how far in, how long, and a bar between
    the two.

    mpv's own progress display goes quiet when it is asked to stay out of
    the terminal, so the clock is ours. A stream whose length is not known
    (a live feed) shows the position alone.
    """

    elapsed = clock(position)

    if not duration or duration <= 0:
        return elapsed

    fraction = min(
        max(position / duration, 0.0),
        1.0,
    )

    label = f"{elapsed} / {clock(duration)}"
    percent = f"  {round(fraction * 100)}%"

    # Two spaces either side of the bar, and one cell of margin.
    cells = width - len(label) - len(percent) - 2

    if cells < MIN_BAR_CELLS:
        return label + percent

    filled = round(fraction * cells)

    bar = (
        "  "
        + "█" * filled
        + "░" * (cells - filled)
    )

    return label + bar + percent


def frame(
    cues: list[tuple[float, float, str]],
    segments: list[tuple[float, float, str]],
    position: float,
    width: int,
) -> tuple[str, list[str], list[str]]:
    """
    What belongs on screen at `position`: the segment title playing, the
    line that has just finished, and the line being spoken.

    The previous line lingers under the title until the next one takes its
    place, so a caption never vanishes mid-read. Returns the rows in the
    order they are drawn, top first.
    """

    title = ""

    for start, end, segment_title in segments:

        if start <= position < end:
            title = segment_title
            break

    active: int | None = None

    for index, (start, end, text) in enumerate(cues):

        if start <= position < end:
            active = index
            break

    if active is None:
        return title, [], []

    current = textwrap.wrap(
        " ".join(cues[active][2].split()),
        width=width,
    )[:CURRENT_LINES]

    history: list[str] = []

    room = CAPTION_LINES - len(current)

    if active > 0 and room > 0:

        previous = textwrap.wrap(
            " ".join(cues[active - 1][2].split()),
            width=width,
        )

        # What was being read most recently is the tail of the previous
        # cue; when the current one is short there is room for all of it.
        history = previous[-room:]

    return title, history, current


def clear_block(
    rows: int,
    columns: int,
    scale: int = 1,
) -> str:
    """
    Escape sequence that erases a block previously drawn on a terminal of
    this size.

    Needed when the window is resized: the block moves to the new bottom
    rows, and the rows it used to occupy would otherwise keep their last
    captions.
    """

    first_row = max(
        rows - BLOCK_ROWS * scale + 1,
        1,
    )

    parts = [SAVE_CURSOR]

    for offset in range(BLOCK_ROWS * scale):

        parts.append(
            f"\x1b[{first_row + offset};1H{CLEAR_LINE}"
        )

    parts.append(RESTORE_CURSOR)

    return "".join(parts)


def draw(
    title: str,
    history: list[str],
    current: list[str],
    rows: int,
    columns: int,
    muted: bool = False,
    scale: int = 1,
    progress: str = "",
) -> str:
    """
    Escape sequence that paints the block on the last rows of the
    terminal and puts the cursor back where it was.

    Each line takes `scale` rows: at scale 2 a character is drawn as a
    2x2 block of cells by the terminal, which is how the captions get
    bigger without touching the terminal's font settings.

    `progress` is the playback clock, drawn on the bottom row of the
    block whatever else is showing.

    Deliberately contains no newline: a newline at the bottom row would
    scroll the screen out from under the playback.
    """

    lines = [
        title + (MUTED_MARK if muted else "")
    ]

    lines.extend(history)
    lines.extend(current)

    while len(lines) < BLOCK_ROWS - PROGRESS_ROWS:
        lines.append("")

    lines = lines[:BLOCK_ROWS - PROGRESS_ROWS]

    lines.append(progress)

    # One cell of margin, so a line never wraps into the next row.
    width = max(
        columns // scale - 1,
        1,
    )

    first_row = max(
        rows - BLOCK_ROWS * scale + 1,
        1,
    )

    parts = [SAVE_CURSOR]

    colours = [TITLE_COLOUR]

    for index in range(1, BLOCK_ROWS - PROGRESS_ROWS):

        colours.append(
            HISTORY_COLOUR
            if index <= len(history)
            else CAPTION_COLOUR
        )

    colours.append(PROGRESS_COLOUR)

    for index, (line, colour) in enumerate(
        zip(
            lines,
            colours,
        )
    ):

        row = first_row + index * scale

        # Every row the line occupies is cleared, otherwise a longer
        # line would leave its tail behind.
        for offset in range(scale):

            parts.append(
                f"\x1b[{row + offset};1H{CLEAR_LINE}"
            )

        parts.append(
            f"\x1b[{row};1H"
            f"{colour}"
            f"{scaled_text(line[:width], scale)}"
            f"{RESET}"
        )

    parts.append(RESTORE_CURSOR)

    return "".join(parts)


class _Ipc:
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


def play(
    url: Path,
    cues: list[tuple[float, float, str]],
    segments: list[tuple[float, float, str]],
    chapters_path: Path | None = None,
    scale: int | None = None,
    warn_about_scale: bool = False,
    stream: bool = False,
) -> int:
    """
    Play url through mpv with our own caption block. Returns mpv's exit
    status.

    `scale` is the caption size multiplier, or None to size the captions
    to the window (a wider window gets bigger captions, not ever longer
    lines). It needs a terminal that renders scaled text (kitty 0.40+) and
    is dropped back to 1 anywhere else. The width of the block always
    follows the window.
    """

    if (
        scale is None
        or scale > 1
    ) and not supports_scaled_text():

        if (
            warn_about_scale
            and scale is not None
            and scale > 1
        ):

            print(
                f"    This terminal cannot render text at {scale}x; "
                "captions stay at normal size.",
                flush=True,
            )

        scale = 1


    mpv = mpv_path()

    socket_path = Path(
        tempfile.gettempdir()
    ) / f"subcast-{os.getpid()}.sock"

    socket_path.unlink(
        missing_ok=True
    )

    command = [
        mpv,
        "--no-video",
        "--force-window=no",
        "--cache=yes",

        # The block is ours. mpv prints subtitle text in the terminal
        # whatever --term-osd says, and would also auto-load the .srt
        # sitting next to the episode, so both have to be turned off.
        "--sub-auto=no",
        "--term-osd=no",
        "--term-status-msg=",

        # Informational output would scroll the screen and move the
        # rows the block is pinned to; warnings and errors still show.
        "--msg-level=all=warn",
        f"--input-ipc-server={socket_path}",
    ]

    if stream:

        # A page URL (YouTube): mpv resolves it through yt-dlp, and the
        # block only cares about the audio.
        command.extend(
            [
                "--ytdl=yes",
                "--ytdl-format=bestaudio/best",
            ]
        )

    if chapters_path is not None:

        command.append(
            f"--chapters-file={chapters_path}"
        )

    command.append(
        str(url)
    )

    for name in ("SIGTERM", "SIGHUP"):

        number = getattr(signal, name, None)

        if number is not None:
            signal.signal(number, _request_stop)

    process = subprocess.Popen(
        command
    )

    try:
        return _follow(
            process,
            socket_path,
            cues,
            segments,
            scale,
        )

    finally:

        if process.poll() is None:
            process.terminate()

        process.wait()

        socket_path.unlink(
            missing_ok=True
        )


def _follow(
    process: subprocess.Popen,
    socket_path: Path,
    cues: list[tuple[float, float, str]],
    segments: list[tuple[float, float, str]],
    scale: int,
) -> int:

    client = _connect(
        socket_path
    )

    if client is None:

        print(
            "    Could not reach mpv over IPC; "
            "captions will not be drawn.",
            flush=True,
        )

        return process.wait()

    drawn = ""
    geometry: tuple[int, int, int] | None = None

    try:

        while (
            process.poll() is None
            and not _STOPPING
        ):

            position = client.get(
                "time-pos"
            )

            duration = client.get(
                "duration"
            )

            muted = bool(
                client.get("mute")
            )

            if position is None:

                time.sleep(POLL_SECONDS)
                continue

            columns, lines = terminal_size()

            board_scale = effective_scale(
                scale
                if scale is not None
                else auto_scale(columns),
                max(lines, BLOCK_ROWS),
                columns,
            )

            width = caption_width(
                columns,
                board_scale,
            )

            seconds = float(position)

            title, history, current = frame(
                cues,
                segments,
                seconds,
                width=width,
            )

            screen = draw(
                title,
                history,
                current,
                rows=max(lines, BLOCK_ROWS),
                columns=columns,
                muted=muted,
                scale=board_scale,
                progress=progress_line(
                    seconds,
                    duration,
                    width,
                ),
            )

            if geometry != (lines, columns, board_scale):

                if geometry is not None:

                    # The window changed size: wipe the block where it
                    # used to sit before moving it.
                    sys.stdout.write(
                        clear_block(
                            geometry[0],
                            geometry[1],
                            geometry[2],
                        )
                    )

                    drawn = ""

                geometry = (lines, columns, board_scale)

            if screen != drawn:

                drawn = screen

                sys.stdout.write(screen)
                sys.stdout.flush()

            time.sleep(POLL_SECONDS)

        return process.returncode

    except KeyboardInterrupt:

        return 130

    finally:

        # Hand the bottom rows back, and remember where the shell left
        # the cursor.
        final_columns, final_lines = terminal_size()

        sys.stdout.write(
            draw(
                "",
                [],
                [],
                rows=max(
                    final_lines,
                    BLOCK_ROWS,
                ),
                columns=final_columns,
                scale=effective_scale(
                    scale
                    if scale is not None
                    else auto_scale(final_columns),
                    max(final_lines, BLOCK_ROWS),
                    final_columns,
                ),
            )
        )

        sys.stdout.flush()

        client.close()


def _connect(
    socket_path: Path,
    timeout: float = 10.0,
) -> _Ipc | None:

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:

        if socket_path.exists():

            try:
                return _Ipc(socket_path)

            except OSError:
                pass

        if time.monotonic() >= deadline:
            break

        time.sleep(0.05)

    return None
