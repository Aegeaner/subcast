"""SubRip subtitle writing."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

# Columns per caption line: one terminal line, kept short enough to read
# without moving your eyes across the screen.
LINE_WIDTH = 42

def srt_timestamp(
    seconds: float,
) -> str:
    milliseconds = round(seconds * 1000)

    hours, milliseconds = divmod(
        milliseconds,
        3_600_000,
    )

    minutes, milliseconds = divmod(
        milliseconds,
        60_000,
    )

    whole, milliseconds = divmod(
        milliseconds,
        1000,
    )

    return (
        f"{hours:02d}:{minutes:02d}:"
        f"{whole:02d},{milliseconds:03d}"
    )

def split_cues(
    cues: list[tuple[float, float, str]],
    min_duration: float = 0.8,
    width: int = LINE_WIDTH,
    min_tail: int = 24,
) -> list[tuple[float, float, str]]:
    """
    Keep every cue inside two terminal lines.

    Whisper thinks in sentences, not captions: a single cue often runs to
    three or four lines of terminal text, which reads as a wall. The cue
    is laid out first, then cut at line boundaries, and its time is
    shared out evenly, the way subtitle timing normally works.

    Two things are avoided: a piece left with a couple of words (words
    are pulled back from the previous piece until the tail reads as a
    phrase again), and pieces too brief to read (a cue with too little
    time to split is left whole rather than blinking in and out).
    """

    fitted: list[tuple[float, float, str]] = []

    for start, end, text in cues:

        lines = textwrap.wrap(
            " ".join(text.split()),
            width=width,
        )

        if not lines:
            continue

        if len(lines) <= 2:

            fitted.append((start, end, " ".join(lines)))
            continue

        chunks = [
            " ".join(lines[index:index + 2])
            for index in range(0, len(lines), 2)
        ]

        while (
            len(chunks) > 1
            and len(chunks[-1]) < min_tail
        ):

            head, _, word = chunks[-2].rpartition(" ")

            if not head:
                break

            candidate = word + " " + chunks[-1]

            if len(textwrap.wrap(candidate, width=width)) > 2:
                break

            chunks[-2] = head
            chunks[-1] = candidate

        span = max(end - start, 0.0)

        if span / len(chunks) < min_duration:

            fitted.append((start, end, " ".join(lines)))
            continue

        # Equal shares, not shares by text length: pieces are two lines
        # each, so they carry similar text anyway, and weighing by length
        # starves the short trailing piece (a cue that flashes for a
        # tenth of a second).
        piece_span = span / len(chunks)
        cursor = start

        for index, chunk in enumerate(chunks):

            piece_end = (
                end
                if index == len(chunks) - 1
                else cursor + piece_span
            )

            fitted.append(
                (
                    cursor,
                    piece_end,
                    chunk,
                )
            )

            cursor = piece_end

    return fitted


def split_heard(
    start: float,
    end: float,
    text: str,
    words=None,
    after: float = 0.0,
    min_duration: float = 0.8,
    width: int = LINE_WIDTH,
    min_tail: int = 24,
) -> list[tuple[float, float, str]]:
    """
    One cue the model timed word by word, in the pieces a caption line holds.

    The pieces are the ones `split_cues` makes - the same text, wrapped the
    same way - and each is timed by the words it holds rather than by an
    equal share of the cue. A share is even, and speech is not: a sentence
    with a pause in the middle, or a phrase said quickly, has its second half
    on screen a second or two before or after it is said. On one 42 minute
    programme, one cue in four was long enough to be split, and the error
    inside those reached two seconds - captions that lead the voice.

    A cue the model gave no timing for is left to `split_cues`, which is all
    there is to go on. `after` is the second of the cue the words belong to
    from (a stretch heard with the tail of the one before it says that tail
    again, and only what comes after is new).
    """

    pieces = split_cues(
        [(start, end, text)],
        min_duration=min_duration,
        width=width,
        min_tail=min_tail,
    )

    held = [
        word
        for word in (words or [])
        if float(word.start) >= after
    ]

    if not held:

        return pieces

    taken = 0
    timed: list[tuple[float, float, str]] = []

    for piece_start, piece_end, piece in pieces:

        count = len(piece.split())

        held_by_piece = held[taken:taken + count]
        taken += count

        if held_by_piece:

            piece_start = float(held_by_piece[0].start)
            piece_end = float(held_by_piece[-1].end)

        timed.append((piece_start, piece_end, piece))

    return timed


def save_cues(
    cues: list[tuple[float, float, str]],
    path: Path,
) -> Path:
    """
    Cache the transcript, so captions can be re-rendered (and re-timed)
    later without running Whisper over the episode again.
    """

    temp_path = path.with_name(
        path.name + ".part"
    )

    temp_path.write_text(
        json.dumps(
            [
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                }
                for start, end, text in cues
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temp_path.replace(path)

    return path


def load_cues(
    path: Path,
) -> list[tuple[float, float, str]]:
    """
    Transcript cached by save_cues, or an empty list.
    """

    try:
        raw = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (OSError, ValueError):
        return []

    if not isinstance(raw, list):
        return []

    cues: list[tuple[float, float, str]] = []

    for item in raw:

        if not isinstance(item, dict):
            return []

        try:
            cues.append(
                (
                    float(item["start"]),
                    float(item["end"]),
                    str(item["text"]),
                )
            )

        except (KeyError, TypeError, ValueError):
            return []

    return cues


def write_srt(
    cues: list[tuple[float, float, str]],
    path: Path,
    width: int = LINE_WIDTH,
) -> Path:
    """
    Write SRT cues. Segment titles are cues too, spanning their whole
    segment, so they stay on screen above the dialogue while it plays.
    """

    blocks = []

    for index, (start, end, text) in enumerate(
        sorted(
            cues,
            key=lambda cue: cue[0],
        ),
        start=1,
    ):

        blocks.append(
            f"{index}\n"
            f"{srt_timestamp(start)} --> "
            f"{srt_timestamp(end)}\n"
            f"{textwrap.fill(text, width)}\n"
        )

    temp_path = path.with_name(
        path.name + ".part"
    )

    temp_path.write_text(
        "\n".join(blocks),
        encoding="utf-8",
    )

    temp_path.replace(path)

    return path
