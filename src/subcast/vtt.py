"""Read WebVTT captions, including YouTube's rolling auto-captions.

Published subtitles arrive as WebVTT: a header line, then cue blocks of
an optional identifier, a timing line, and the cue text. YouTube's
auto-generated captions are different in spirit - the current line is
redrawn every few hundred milliseconds, each redraw repeating the words
already shown - so a rolling sequence is folded down to the words that
are new, each timed where it first appeared. Cues come back as
(start, end, text) in seconds, the shape the rest of the pipeline speaks.
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path


# A timing line. Cue settings ("align:start position:0%") trail the end
# timestamp, so they are simply not part of the match.
_TIMING = re.compile(
    r"^\s*(?P<start>(?:\d+:)?\d{1,2}:\d{1,2}(?:[.,]\d{1,3})?)"
    r"\s*-->\s*"
    r"(?P<end>(?:\d+:)?\d{1,2}:\d{1,2}(?:[.,]\d{1,3})?)"
)

# Inline markup: <c>, <v Name>, <00:00:01.000>, and anything else in
# angle brackets. Replaced by a space rather than deleted, so a tag that
# sits between two words does not glue them together.
_MARKUP = re.compile(r"<[^>]*>")

# Keywords that open a run of lines ending at the next blank line, which
# is never a cue.
_BLOCK_KEYWORDS = (
    "NOTE",
    "STYLE",
    "REGION",
)


def parse_vtt(
    text: str,
) -> list[tuple[float, float, str]]:
    """
    Speech cues from WebVTT text, as (start, end, text).

    Headers, notes, styles and regions carry no speech and are dropped,
    as are cues with no text left after cleaning and cues that do not
    advance the clock. What remains then passes through the rolling
    fold, so a cue that only repeats the line already shown contributes
    nothing.
    """

    cues: list[tuple[float, float, str]] = []
    lines = text.splitlines()
    index = 0

    while index < len(lines):

        line = lines[index].strip()
        index += 1

        if not line:
            continue

        if _is_header(line):
            continue

        if line.split(maxsplit=1)[0] in _BLOCK_KEYWORDS:

            index = _skip_block(
                lines,
                index,
            )

            continue

        times = _cue_times(line)

        if times is None:
            # A cue identifier; its timing line comes next.
            continue

        start, end = times
        body: list[str] = []

        while index < len(lines) and lines[index].strip():

            body.append(lines[index])
            index += 1

        cue = _clean_text(body)

        if cue and end > start:

            cues.append(
                (
                    start,
                    end,
                    cue,
                )
            )

    return _fold_rolling(cues)


def read_vtt(
    path: Path,
) -> list[tuple[float, float, str]]:
    """
    Cues from a WebVTT file, or an empty list if it cannot be read.

    Caption files come from many hands, so undecodable bytes are
    replaced rather than raising: a mangled character in one cue is not
    a reason to lose the other nine hundred.
    """

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    except OSError:
        return []

    return parse_vtt(text)


def _is_header(
    line: str,
) -> bool:
    """Whether a line belongs to the file header rather than a cue."""

    return line.startswith(
        (
            "WEBVTT",
            "X-TIMESTAMP-MAP",
        )
    )


def _skip_block(
    lines: list[str],
    index: int,
) -> int:
    """The index of the blank line that ends a NOTE/STYLE/REGION block."""

    while index < len(lines) and lines[index].strip():
        index += 1

    return index


def _cue_times(
    line: str,
) -> tuple[float, float] | None:
    """The (start, end) seconds of a timing line, or None."""

    match = _TIMING.match(line)

    if match is None:
        return None

    return (
        _seconds(match.group("start")),
        _seconds(match.group("end")),
    )


def _seconds(
    stamp: str,
) -> float:
    """
    Seconds from a WebVTT timestamp.

    Both MM:SS.mmm and HH:MM:SS.mmm are accepted: reading the parts as
    base sixty makes the hours column optional, since a leading "00:" is
    just another sixty seconds.
    """

    seconds = 0.0

    for part in stamp.replace(",", ".").split(":"):

        seconds = seconds * 60 + float(part)

    return seconds


def _clean_text(
    body: list[str],
) -> str:
    """Cue text with markup stripped, entities decoded, spacing tidied."""

    plain = _MARKUP.sub(
        " ",
        " ".join(body),
    )

    return _collapse_repeats(
        unescape(plain).split()
    )


def _collapse_repeats(
    words: list[str],
) -> str:
    """
    Join words, dropping any word that repeats the one before it.

    Rolling captions resend the current line word by word inside a
    single cue ("the the the cat"), which reads as a stutter rather
    than speech.
    """

    kept: list[str] = []

    for word in words:

        if kept and kept[-1].casefold() == word.casefold():
            continue

        kept.append(word)

    return " ".join(kept)


def _fold_rolling(
    cues: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    """
    Fold a rolling caption stream down to the words it adds.

    Auto-captions redraw the current line as it grows, so one sentence
    arrives as many cues that each repeat what came before, sometimes
    with the line redrawn shorter as YouTube revises it. The line as
    last shown is tracked whole-word: a cue that repeats it is dropped,
    a cue that extends it keeps only the newly revealed words at that
    cue's time, and a cue that diverges starts a fresh line. Comparing
    words rather than characters means a half-redrawn word ("hel" on the
    way to "hello") is not emitted as a fragment.
    """

    kept: list[tuple[float, float, str]] = []
    shown: list[str] = []

    for start, end, text in cues:

        words = text.split()

        if words == shown:
            continue

        if words[:len(shown)] == shown:

            fresh = words[len(shown):]
            shown = words

            if fresh:

                kept.append(
                    (
                        start,
                        end,
                        " ".join(fresh),
                    )
                )

            continue

        if shown[:len(words)] == words:
            continue

        shown = words

        kept.append(
            (
                start,
                end,
                text,
            )
        )

    return kept
