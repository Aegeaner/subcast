"""Segment placement: published slots, packing, and transcript snapping."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from subcast.segments import (
    build_segments,
    clip_clock_seconds,
    clip_start_from_title,
    closest_keyword_cue,
    place,
    save_segments,
    segment_keywords,
    snap_segments,
)
from subcast.sources import Segment

# A programme that goes on air at 07:00, as the source reads it off its
# own page.
FROM_SEVEN = 7 * 3600.0


@pytest.mark.parametrize(
    "title, expected",
    [
        ("7.10am Headlines", 600.0),
        ("7.35am Weather", 2100.0),
        ("8am News Bulletin", 3600.0),
        ("12.05pm News", 5 * 3600 + 300),
        ("21st Birthday special", None),
        ("Weather Forecast", None),
    ],
)
def test_titles_that_carry_a_slot_time(title: str, expected: float | None):
    assert clip_start_from_title(title, FROM_SEVEN) == expected


@pytest.mark.parametrize(
    "title, expected",
    [
        ("7.10am Headlines", 7 * 3600 + 600.0),
        ("12.05pm News", 12 * 3600 + 300.0),
        ("21st Birthday special", None),
    ],
)
def test_the_time_of_day_a_title_names(title: str, expected: float | None):
    assert clip_clock_seconds(title) == expected


def test_a_programme_without_a_known_schedule_has_no_slots():
    assert clip_start_from_title("8am News Bulletin", None) is None

    # a clock time before the programme went on air is not this episode
    assert clip_start_from_title("6.50am Weather", FROM_SEVEN) is None


def test_clock_titled_segments_keep_their_slot():
    clips = [
        ("7.10am Headlines", 183.0),
        ("Ferry terminal opens in Kilbride", 300.0),
        ("7.35am Weather", 341.0),
    ]

    segments = build_segments(
        clips,
        duration=3000.0,
        clock_start=FROM_SEVEN,
    )

    assert [start for start, _, _ in segments] == [
        600.0,
        783.0,
        2100.0,
    ]


def test_a_programme_whose_clips_name_no_slot_is_packed_in_order():
    """
    Another programme's clip titles carry no clock time at all: they are
    packed across the episode in the order they were published.
    """

    clips = [
        ("Ferry terminal opens in Kilbride", 942.0),
        ("Harbour tunnel under review", 195.0),
        ("Council vote on the harbour", 839.0),
    ]

    segments = build_segments(clips, duration=3593.0)

    starts = [start for start, _, _ in segments]

    assert starts[0] == 0.0
    assert starts == sorted(starts)
    assert segments[-1][1] <= 3593.0
    assert [title for _, _, title in segments] == [
        title for title, _ in clips
    ]


def test_a_clock_titled_list_without_a_schedule_is_not_pinned():
    """
    A programme's schedule is what makes "8am" mean anything: without it
    the times are not slots in this episode, so the clips are packed.
    """

    clips = [
        ("8am News Bulletin", 300.0),
        ("9am News Bulletin", 300.0),
    ]

    packed = build_segments(clips, duration=600.0)

    assert [start for start, _, _ in packed] == [0.0, 300.0]

    pinned = build_segments(
        clips,
        duration=600.0,
        clock_start=FROM_SEVEN,
    )

    assert [start for start, _, _ in pinned] == [3600.0, 7200.0]


def test_segments_stay_ordered_and_inside_the_episode():
    clips = [
        ("7.10am Headlines", 183.0),
        ("An interview", 300.0),
        ("Ferry terminal opens in Kilbride", 310.0),
        ("8am News Bulletin", 367.0),
        ("21st Birthday special", 416.0),
    ]

    segments = build_segments(
        clips,
        duration=4200.0,
        clock_start=FROM_SEVEN,
    )

    assert all(
        0.0 <= start <= end
        for start, end, _ in segments
    )

    assert all(
        first[0] <= second[0]
        for first, second in pairwise(segments)
    )

    assert segments[-1][1] <= 4200.0


def test_hit_nearest_the_expected_position_wins():
    cues = [
        (520.0, 523.0, "Kilbride is on the coast"),
        (700.0, 703.0, "Kilbride gets a ferry"),
    ]

    hit = closest_keyword_cue(
        cues,
        ["kilbride"],
        center=600.0,
        tolerance=180.0,
    )

    assert hit is not None
    assert hit[0] == 520.0


def test_snapping_moves_a_segment_onto_the_transcript():
    segments = [
        (600.0, 900.0, "Harbour tunnel under review"),
    ]
    cues = [
        (598.0, 601.0, "and now, the harbour tunnel is under review"),
    ]

    assert snap_segments(segments, cues)[0][0] == 598.0


def test_mentions_outside_the_tolerance_are_ignored():
    segments = [
        (600.0, 900.0, "Harbour tunnel under review"),
    ]
    cues = [
        (100.0, 103.0, "the harbour tunnel, and a reminder"),
    ]

    assert snap_segments(segments, cues)[0][0] == 600.0


def test_snapping_never_reorders_segments():
    segments = [
        (600.0, 900.0, "Ferry terminal opens in Kilbride"),
        (900.0, 1200.0, "Council vote on the harbour"),
    ]
    cues = [
        (700.0, 703.0, "the council says Kilbride agreed"),
        (750.0, 753.0, "the harbour vote is in trouble"),
    ]

    snapped = snap_segments(segments, cues)

    assert [start for start, _, _ in snapped] == [700.0, 750.0]
    assert all(
        0.0 < end - start
        for start, end, _ in snapped
    )


def test_segments_are_untouched_without_a_transcript():
    segments = [
        (600.0, 900.0, "Harbour tunnel under review"),
    ]

    assert snap_segments(segments, []) == segments


def test_a_quoted_word_is_the_word_that_gets_said():
    """
    A site quotes a word in a clip title; the speaker does not. The
    keyword has to survive the quotes, or the segment can never be found
    ("'Appalling' - Clare protestors say Trump not welcome" against "It is
    appalling that we are spending taxpayers' money").
    """

    keywords = segment_keywords(
        "'Appalling' - Clare protestors say Trump not welcome"
    )

    assert "appalling" in keywords
    assert "'appalling'" not in keywords


def test_a_clip_list_that_is_not_a_running_order_follows_the_transcript():
    """
    Clips from a programme that names no clock time are a menu of
    highlights, not the order they aired in: each segment goes where its
    own words are said, and the list follows the transcript.
    """

    segments = [
        (0.0, 300.0, "Ferry terminal opens in Kilbride"),
        (600.0, 900.0, "Harbour tunnel under review"),
        (1200.0, 1500.0, "Councillors debate the bylaw"),
    ]

    cues = [
        (300.0, 303.0, "the harbour tunnel is under review this morning"),
        (900.0, 903.0, "councillors debate the bylaw tonight"),
        (1500.0, 1503.0, "the ferry terminal at Kilbride opens today"),
    ]

    placed = snap_segments(
        segments,
        cues,
        running_order=False,
    )

    assert [start for start, _, _ in placed] == [300.0, 900.0, 1500.0]

    assert [title for _, _, title in placed] == [
        "Harbour tunnel under review",
        "Councillors debate the bylaw",
        "Ferry terminal opens in Kilbride",
    ]


def test_a_running_order_keeps_its_order_and_only_refines():
    """
    Clock-titled segments are slots in a published schedule, so their list
    is the order they went out in: a mention far from the slot belongs to
    some other part of the programme, and is not this segment's place.
    """

    segments = [
        (600.0, 900.0, "7.10am Headlines"),
        (900.0, 1200.0, "8am News Bulletin"),
    ]

    cues = [
        (598.0, 601.0, "and now, the headlines"),
        (5000.0, 5003.0, "the news bulletin at the end of the programme"),
    ]

    placed = snap_segments(segments, cues)

    assert [start for start, _, _ in placed] == [598.0, 900.0]


def test_a_clip_list_that_names_a_clock_time_is_a_running_order():
    """
    The clock times are what tell the two kinds of clip list apart: only a
    programme airing to a schedule publishes them, and only then is the
    list an order worth keeping.
    """

    _, exact, clocked = place(
        [
            Segment(title="7.10am Headlines", duration=120.0),
            Segment(title="8am News Bulletin", duration=300.0),
        ],
        duration=3600.0,
        clock_start=FROM_SEVEN,
    )

    assert exact is False
    assert clocked is True

    _, _, packed = place(
        [Segment(title="Ferry terminal opens in Kilbride", duration=300.0)],
        duration=3600.0,
    )

    assert packed is False


def test_the_placed_segments_are_written_down_whole(tmp_path: Path):
    segments = [
        (535.32, 818.98, "7.10am Headlines"),
        (
            818.98,
            1332.95,
            "Ferry terminal opens in Kilbride; No. 10 = Harbour",
        ),
    ]

    path = save_segments(segments, tmp_path / "episode.segments.json")

    assert json.loads(path.read_text(encoding="utf-8")) == [
        {
            "start": 535.32,
            "end": 818.98,
            "title": "7.10am Headlines",
        },
        {
            "start": 818.98,
            "end": 1332.95,
            "title": "Ferry terminal opens in Kilbride; No. 10 = Harbour",
        },
    ]

    # a half-written file is never the one left behind
    assert not list(tmp_path.glob("*.part"))
