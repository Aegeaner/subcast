"""Segment placement: published slots, packing, and transcript snapping."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from subcast.segments import (
    build_segments,
    clip_start_from_title,
    closest_keyword_cue,
    load_segments,
    save_segments,
    snap_segments,
)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("7.10am It Says in the Papers", 600.0),
        ("7.35am Sports News", 2100.0),
        ("8am News Bulletin", 3600.0),
        ("12.05pm News", 5 * 3600 + 300),
        ("21st Culture Night tonight", None),
        ("Weather Forecast", None),
    ],
)
def test_titles_that_carry_a_slot_time(title: str, expected: float | None):
    assert clip_start_from_title(title) == expected


def test_clock_titled_segments_keep_their_slot():
    clips = [
        ("7.10am It Says in the Papers", 183.0),
        ("Taoiseach to meet Burnham", 300.0),
        ("7.35am Sports News", 341.0),
    ]

    segments = build_segments(clips, duration=3000.0)

    assert [start for start, _, _ in segments] == [
        600.0,
        783.0,
        2100.0,
    ]


def test_segments_stay_ordered_and_inside_the_episode():
    clips = [
        ("7.10am It Says in the Papers", 183.0),
        ("An interview", 300.0),
        ("Taoiseach to meet Burnham", 310.0),
        ("8am News Bulletin", 367.0),
        ("21st Culture Night tonight", 416.0),
    ]

    segments = build_segments(clips, duration=4200.0)

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
        (520.0, 523.0, "Burnham arrives later this morning"),
        (700.0, 703.0, "Burnham is in Manchester"),
    ]

    hit = closest_keyword_cue(
        cues,
        ["burnham"],
        center=600.0,
        tolerance=180.0,
    )

    assert hit is not None
    assert hit[0] == 520.0


def test_snapping_moves_a_segment_onto_the_transcript():
    segments = [
        (600.0, 900.0, "Potato production plummets, prices to rise"),
    ]
    cues = [
        (598.0, 601.0, "and now, potato production across Europe is down"),
    ]

    assert snap_segments(segments, cues)[0][0] == 598.0


def test_mentions_outside_the_tolerance_are_ignored():
    segments = [
        (600.0, 900.0, "Potato production plummets, prices to rise"),
    ]
    cues = [
        (100.0, 103.0, "potato production, and a reminder"),
    ]

    assert snap_segments(segments, cues)[0][0] == 600.0


def test_snapping_never_reorders_segments():
    segments = [
        (600.0, 900.0, "Taoiseach to meet Burnham"),
        (900.0, 1200.0, "Could Merz's party be in trouble?"),
    ]
    cues = [
        (700.0, 703.0, "the Taoiseach says Burnham agreed"),
        (750.0, 753.0, "the Merz party is in trouble"),
    ]

    snapped = snap_segments(segments, cues)

    assert [start for start, _, _ in snapped] == [700.0, 750.0]
    assert all(
        0.0 < end - start
        for start, end, _ in snapped
    )


def test_segments_are_untouched_without_a_transcript():
    segments = [
        (600.0, 900.0, "Potato production plummets, prices to rise"),
    ]

    assert snap_segments(segments, []) == segments


def test_cached_segments_survive_a_round_trip(tmp_path: Path):
    segments = [
        (535.32, 818.98, "7.10am It Says in the Papers"),
        (818.98, 1332.95, "Taoiseach to meet Burnham; No. 10 = Manchester"),
    ]

    path = save_segments(segments, tmp_path / "episode.segments.json")

    assert load_segments(path) == segments
    assert not list(tmp_path.glob("*.part"))


def test_cached_segments_are_ignored_when_unusable(tmp_path: Path):
    assert load_segments(tmp_path / "missing.json") == []

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_segments(broken) == []

    partial = tmp_path / "partial.json"
    partial.write_text('[{"start": 1.0, "end": 2.0}]', encoding="utf-8")
    assert load_segments(partial) == []
