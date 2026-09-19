"""Align the published segment list with the transcribed audio."""

from __future__ import annotations

import json
import re
from pathlib import Path

# A published clock time ("8am News Bulletin") is a slot in the
# programme's own schedule, which the source reads off the programme's
# page and hands over as `Media.clock_start`: a clip is placed at the time
# it names, less the time its programme went on air.

def clip_clock_seconds(
    title: str,
) -> float | None:
    """
    The time of day a segment title names, in seconds since midnight.
    """

    match = re.match(
        r"\s*(\d{1,2})(?:[.:](\d{2}))?\s*([ap]m)\b",
        title,
        flags=re.IGNORECASE,
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

    if hour > 23 or minute > 59:
        return None

    return float(
        hour * 3600
        + minute * 60
    )

def clip_start_from_title(
    title: str,
    clock_start: float | None,
) -> float | None:
    """
    Scheduled slot of a segment whose title carries a clock time, as an
    offset into the episode.

    "7.35am Sports News" is 35 minutes into a programme that goes on air
    at 7. The clip list is the planned running order, so these are slot
    times: the bulletins do go out close to the clock, but an overrunning
    interview pushes them a minute or two late.

    A programme whose schedule is not known gets no slots at all, rather
    than slots measured against the wrong hour.
    """

    clock = clip_clock_seconds(title)

    if clock is None or clock_start is None:
        return None

    seconds = clock - clock_start

    if seconds < 0:
        return None

    return seconds

# How often a word may be said in an episode and still place the segment
# that names it. A title the whole programme is about ("Trump visit ...",
# on a broadcast that says "Trump" 81 times) has no such word: every
# mention of it belongs to some other part of the programme.
ANCHOR_LIMIT = 12

def build_segments(
    clips: list[tuple[str, float]],
    duration: float,
    clock_start: float | None = None,
) -> list[tuple[float, float, str]]:
    """
    Place the published segments on the episode timeline.

    Clock-titled segments pin their window. The rest are packed in
    published order from the previous pin, which leaves the unused time
    of a window (ad breaks, headlines, music) in front of the next pin.

    Without a single pin the whole list is stretched across the episode
    instead, which is the only thing left to go on - and the only thing
    to go on for a programme whose clips name no clock time.

    These are estimates: snap_segments corrects them against the
    transcript. Returns (start, end, title) in seconds.
    """

    if not clips:
        return []

    starts: list[float | None] = [
        clip_start_from_title(
            title,
            clock_start,
        )
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
    clock_start: float | None = None,
) -> tuple[list[tuple[float, float, str]], bool, bool]:
    """
    Put published segments on the timeline.

    Sources that publish start times (YouTube chapters) are taken at their
    word and need no aligning; sources that publish only lengths (RTÉ's
    clip list) are packed and later snapped onto the transcript.

    Returns the placed segments as (start, end, title), whether their
    starts are exact, and whether the list is a running order - which it
    is when its titles carry clock times, since only a programme airing to
    a schedule publishes those.
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

    running_order = any(
        clip_start_from_title(title, clock_start) is not None
        for title, _ in clips
    )

    return (
        build_segments(clips, duration, clock_start),
        False,
        running_order,
    )


def segment_keywords(
    title: str,
) -> list[str]:
    """
    Distinctive words of a segment title, used to find the segment in
    the transcript.

    A quote around a word is the site's, not the speaker's: the title
    "'Appalling' - Clare protestors say Trump not welcome" has to match
    "It is appalling", so the apostrophes come off the ends.
    """

    words = [
        word.strip("'")
        for word in re.findall(
            r"[a-z0-9']+",
            title.lower(),
        )
    ]

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

def mentioned_at(
    cues: list[tuple[float, float, str]],
    keyword: str,
) -> list[float]:
    """
    When a word is said in the episode.
    """

    return [
        start
        for start, _, text in cues
        if keyword in text.lower()
    ]


def anchor_of(
    cues: list[tuple[float, float, str]],
    keywords: list[str],
    expected: float,
) -> float | None:
    """
    Where a segment starts, from the words its title uses.

    The mention nearest the derived position wins, among the words this
    episode does not say all the time: a title naming something the whole
    programme is about ("Trump visit ..." on a broadcast that says
    "Trump" 81 times) is placed by the word it does not share, and a title
    with nothing but shared words is not placed at all.

    There is no window. A clip list that names no clock time is a menu of
    highlights rather than the running order - five clips This Week
    published after the broadcast, whose order is not the order they aired
    in - so a mention 300 seconds from the derived position is the answer,
    not something to be refused.
    """

    candidates = [
        (moment, len(times))
        for keyword in keywords
        for times in [mentioned_at(cues, keyword)]
        if times and len(times) <= ANCHOR_LIMIT
        for moment in times
    ]

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda candidate: (
            abs(candidate[0] - expected),
            candidate[1],
        ),
    )[0]


def slot_starts(
    segments: list[tuple[float, float, str]],
    cues: list[tuple[float, float, str]],
    tolerance: float,
) -> list[float]:
    """
    Where each segment starts, in the published order: its slot, refined
    onto the nearest mention of its title.
    """

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

    return starts


def transcript_starts(
    segments: list[tuple[float, float, str]],
    cues: list[tuple[float, float, str]],
) -> list[tuple[int, float, tuple[float, float, str]]]:
    """
    Each segment with where the transcript says it belongs, in the order
    the transcript puts them, as (published index, start, segment).

    A segment the transcript cannot place keeps its derived position, and
    is ordered by that position among the ones that could be placed.
    """

    placed: list[tuple[int, float, tuple[float, float, str]]] = []

    for index, segment in enumerate(segments):

        start, _, title = segment

        anchor = anchor_of(
            cues,
            segment_keywords(title),
            start,
        )

        placed.append(
            (
                index,
                anchor if anchor is not None else start,
                segment,
            )
        )

    placed.sort(
        key=lambda entry: (entry[1], entry[0])
    )

    return placed


def snap_segments(
    segments: list[tuple[float, float, str]],
    cues: list[tuple[float, float, str]],
    tolerance: float = 180.0,
    running_order: bool = True,
) -> list[tuple[float, float, str]]:
    """
    Move each published segment onto the transcript.

    A clip list whose titles carry clock times is the running order: those
    are slot times rather than start times ("7.50am Business News" can go
    out at 7.52), the ads and trails between segments are not published at
    all, and each segment is refined onto the nearest mention of its title
    without leaving its place in the list.

    A clip list whose titles name no clock time is a menu of highlights,
    and its order is the order RTÉ published them in rather than the order
    they aired in. Those segments are placed at the mention of their own
    titles, wherever in the episode that is, and the list follows the
    transcript. A segment whose words are never spoken keeps its derived
    position and its place among the others, which is the honest answer
    for it either way.
    """

    if not segments or not cues:
        return segments

    if running_order:

        ordered = [
            (
                index,
                start,
                segment,
            )
            for index, (start, segment) in enumerate(
                zip(
                    slot_starts(
                        segments,
                        cues,
                        tolerance,
                    ),
                    segments,
                )
            )
        ]

    else:

        ordered = transcript_starts(
            segments,
            cues,
        )

    starts = [
        start
        for _, start, _ in ordered
    ]

    last_end = max(
        end
        for _, end, _ in segments
    )

    laid: list[tuple[float, float, str]] = []

    for index, (_, start, (_, _, title)) in enumerate(ordered):

        end = (
            starts[index + 1]
            if index + 1 < len(starts)
            else max(start + 1.0, last_end)
        )

        laid.append(
            (
                start,
                max(end, start + 1.0),
                title,
            )
        )

    return laid
