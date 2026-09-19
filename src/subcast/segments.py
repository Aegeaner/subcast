"""Align the published segment list with the transcribed audio."""

from __future__ import annotations

import json
import re
from pathlib import Path


# Morning Ireland airs 07:00-09:00 and the podcast audio starts with the
# 7am bulletin, so a published clock time ("8am News Bulletin") maps onto
# an audio offset by subtracting this hour.
SHOW_START_HOUR = 7

def clip_start_from_title(
    title: str,
) -> float | None:
    """
    Scheduled slot of a segment whose title carries a clock time.

    "7.35am Sports News" -> 35 * 60. The clip list is the planned
    running order, so these are slot times: the bulletins do go out
    close to the clock, but an overrunning interview pushes them a
    minute or two late.
    """

    match = re.match(
        r"\s*(\d{1,2})(?:[.:](\d{2}))?\s*([ap]m)\b",
        title,
        flags=re.I,
    )

    if not match:
        return None

    hour = int(
        match.group(1)
    )

    minute = int(
        match.group(2) or 0
    )

    if (
        match.group(3).lower() == "pm"
        and hour < 12
    ):
        hour += 12

    seconds = (
        (hour - SHOW_START_HOUR) * 3600
        + minute * 60
    )

    if seconds < 0:
        return None

    return float(seconds)

def build_segments(
    clips: list[tuple[str, float]],
    duration: float,
) -> list[tuple[float, float, str]]:
    """
    Place the published segments on the episode timeline.

    Clock-titled segments pin their window. The rest are packed in
    published order from the previous pin, which leaves the unused time
    of a window (ad breaks, headlines, music) in front of the next pin.

    Without a single pin the whole list is stretched across the episode
    instead, which is the only thing left to go on.

    These are estimates: snap_segments corrects them against the
    transcript. Returns (start, end, title) in seconds.
    """

    if not clips:
        return []

    starts: list[float | None] = [
        clip_start_from_title(title)
        for title, _ in clips
    ]

    anchors = [
        index
        for index, start in enumerate(starts)
        if start is not None
    ]

    if not anchors:

        scale = (
            duration
            / sum(
                clip[1]
                for clip in clips
            )
        )

        cursor = 0.0

        for index, (_, clip_duration) in enumerate(
            clips
        ):

            starts[index] = cursor

            cursor += (
                clip_duration * scale
            )

    else:

        cursor = 0.0
        previous = -1

        for index in anchors + [len(clips)]:

            for clipped in range(
                previous + 1,
                index,
            ):

                starts[clipped] = cursor

                cursor += clips[clipped][1]

            if index < len(clips):
                cursor = (
                    starts[index] or 0.0
                ) + clips[index][1]

            previous = index

    positions = [
        float(start)
        if start is not None
        else 0.0
        for start in starts
    ]

    segments: list[tuple[float, float, str]] = []

    for index, (title, clip_duration) in enumerate(
        clips
    ):

        start = positions[index]

        end = (
            positions[index + 1]
            if index + 1 < len(clips)
            else min(
                start + clip_duration,
                duration,
            )
        )

        segments.append(
            (
                start,
                max(end, start),
                title,
            )
        )

    return segments

def place(
    segments,
    duration: float,
) -> tuple[list[tuple[float, float, str]], bool]:
    """
    Put published segments on the timeline.

    Sources that publish start times (YouTube chapters) are taken at their
    word and need no aligning; sources that publish only lengths (RTÉ's
    clip list) are packed and later snapped onto the transcript.

    Returns the placed segments as (start, end, title) and whether their
    starts are exact.
    """

    if any(segment.start is not None for segment in segments):

        ordered = sorted(
            segments,
            key=lambda segment: segment.start or 0.0,
        )

        placed: list[tuple[float, float, str]] = []

        for index, segment in enumerate(ordered):

            start = float(segment.start or 0.0)

            if index + 1 < len(ordered):
                end = float(ordered[index + 1].start or start)

            elif segment.duration:
                end = start + segment.duration

            else:
                end = max(duration, start)

            placed.append(
                (
                    start,
                    max(end, start + 1.0),
                    segment.title,
                )
            )

        return placed, True

    clips = [
        (
            segment.title,
            segment.duration or 0.0,
        )
        for segment in segments
    ]

    return build_segments(clips, duration), False


def segment_keywords(
    title: str,
) -> list[str]:
    """
    Distinctive words of a segment title, used to find the segment in
    the transcript.
    """

    words = re.findall(
        r"[a-z0-9']+",
        title.lower(),
    )

    keys = [
        word
        for word in words
        if len(word) >= 5
        and word
        not in {
            "about",
            "could",
            "found",
            "ireland",
            "might",
            "party",
            "today",
            "tonight",
            "under",
            "where",
            "which",
            "would",
        }
    ]

    return keys or [
        word
        for word in words
        if len(word) >= 4
    ]

def save_segments(
    segments: list[tuple[float, float, str]],
    path: Path,
) -> Path:
    """
    Cache the placed segments next to the subtitles.

    A replay then rebuilds the chapter marks from the same positions the
    transcript was aligned to, instead of transcribing the episode again.
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
                    "title": title,
                }
                for start, end, title in segments
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temp_path.replace(path)

    return path


def load_segments(
    path: Path,
) -> list[tuple[float, float, str]]:
    """
    Segments cached by save_segments, or an empty list.
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

    segments: list[tuple[float, float, str]] = []

    for item in raw:

        if not isinstance(item, dict):
            return []

        try:
            segments.append(
                (
                    float(item["start"]),
                    float(item["end"]),
                    str(item["title"]),
                )
            )

        except (KeyError, TypeError, ValueError):
            return []

    return segments


def closest_keyword_cue(
    cues: list[tuple[float, float, str]],
    keywords: list[str],
    center: float,
    tolerance: float,
) -> tuple[float, float, str] | None:
    """
    Transcript cue nearest to center (within tolerance) that mentions
    one of the keywords.
    """

    best = None
    best_distance = None

    for cue in cues:

        start = cue[0]

        if not (
            center - tolerance
            <= start
            <= center + tolerance
        ):
            continue

        low = cue[2].lower()

        if not any(
            keyword in low
            for keyword in keywords
        ):
            continue

        distance = abs(
            start - center
        )

        if (
            best_distance is None
            or distance < best_distance
        ):
            best = cue
            best_distance = distance

    return best

def snap_segments(
    segments: list[tuple[float, float, str]],
    cues: list[tuple[float, float, str]],
    tolerance: float = 180.0,
) -> list[tuple[float, float, str]]:
    """
    Move each published segment onto the transcript.

    The clip list is the planned running order, so its clock times are
    slot times rather than start times ("7.50am Business News" can go
    out at 7.52) and the ads and trails between segments are not
    published at all. The nearest transcript cue that mentions the
    segment title is its real start; a segment whose words are never
    spoken keeps the derived position, so the error stays within
    tolerance either way.
    """

    if not segments or not cues:
        return segments

    starts: list[float] = []
    previous = -1.0

    for start, _, title in segments:

        hit = closest_keyword_cue(
            cues,
            segment_keywords(title),
            start,
            tolerance,
        )

        snapped = (
            hit[0]
            if hit is not None
            else start
        )

        # Keep the running order intact; a mention in the segment
        # before this one is not this segment.
        if snapped <= previous + 20.0:
            snapped = start

        starts.append(
            max(snapped, previous + 20.0)
            if previous >= 0.0
            else snapped
        )

        previous = starts[-1]

    last_end = segments[-1][1]

    snapped_segments: list[tuple[float, float, str]] = []

    for index, (_, _, title) in enumerate(
        segments
    ):

        start = starts[index]

        end = (
            starts[index + 1]
            if index + 1 < len(segments)
            else max(start + 1.0, last_end)
        )

        snapped_segments.append(
            (
                start,
                max(end, start + 1.0),
                title,
            )
        )

    return snapped_segments
