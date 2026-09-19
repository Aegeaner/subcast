"""SRT output: what mpv and other players have to be able to read back."""

from __future__ import annotations

import textwrap
from itertools import pairwise
from pathlib import Path

import pytest

from subcast.srt import (
    load_cues,
    save_cues,
    split_cues,
    srt_timestamp,
    write_srt,
)


def read_srt(text: str) -> list[tuple[str, str, str]]:
    """Minimal SubRip reader: (start, end, text) per cue."""

    cues = []

    for block in text.strip().split("\n\n"):

        lines = block.splitlines()

        assert lines[0].isdigit()

        start, _, end = lines[1].partition(" --> ")

        cues.append((start, end, " ".join(lines[2:])))

    return cues


def test_timestamps_roll_over_correctly():
    assert srt_timestamp(0) == "00:00:00,000"
    assert srt_timestamp(3661.5) == "01:01:01,500"
    assert srt_timestamp(3599.999) == "00:59:59,999"
    assert srt_timestamp(3600) == "01:00:00,000"


def test_cues_survive_a_read_back(tmp_path: Path):
    wrapped = "a line long enough that it has to be broken before it is shown"
    cues = [
        (600.0, 783.0, ">> 7.10am Headlines"),
        (600.0, 603.5, "Good morning and welcome to the programme."),
        (603.5, 610.0, wrapped),
    ]

    path = write_srt(cues, tmp_path / "episode.srt")
    text = path.read_text(encoding="utf-8")
    parsed = read_srt(text)

    assert [cue[0] for cue in parsed] == [
        "00:10:00,000",
        "00:10:00,000",
        "00:10:03,500",
    ]
    assert parsed[0][2] == ">> 7.10am Headlines"
    assert parsed[2][1] == "00:10:10,000"
    assert parsed[2][2].split() == wrapped.split()

    # A segment cue spans its segment and keeps its place ahead of the
    # dialogue that starts at the same moment.
    assert parsed[0][2].startswith(">>")

    assert all(
        len(line) <= 42
        for line in text.splitlines()
    )


def test_writing_leaves_no_partial_file(tmp_path: Path):
    write_srt(
        [(0.0, 1.0, "hello")],
        tmp_path / "episode.srt",
    )

    assert not list(tmp_path.glob("*.part"))


def test_no_cues_writes_an_empty_file(tmp_path: Path):
    path = write_srt([], tmp_path / "empty.srt")

    assert path.read_text(encoding="utf-8") == ""


def test_long_cues_are_split_into_two_line_pieces():
    long_text = (
        "As you could imagine, the harbour tunnel has been closed since "
        "early this morning, and it may stay closed for longer because "
        "the survey is not finished, so it is unknown when it reopens."
    )
    cues = [(10.0, 21.0, long_text)]

    fitted = split_cues(cues)

    assert len(fitted) > 1
    assert all(
        len(textwrap.fill(text, 42).splitlines()) <= 2
        for _, _, text in fitted
    )
    assert " ".join(text for _, _, text in fitted) == " ".join(
        long_text.split()
    )
    assert fitted[0][0] == 10.0
    assert fitted[-1][1] == 21.0
    assert all(
        first[1] == pytest.approx(second[0])
        for first, second in pairwise(fitted)
    )


def test_short_cues_are_left_alone():
    cues = [(0.0, 3.0, "Good morning and welcome to the programme.")]

    assert split_cues(cues) == cues


def test_fast_dense_cues_are_not_split_into_blinks():
    cues = [(0.0, 1.2, " ".join(["word"] * 40))]

    assert split_cues(cues) == [(0.0, 1.2, " ".join(["word"] * 40))]


def test_split_drops_blank_cues():
    assert split_cues([(0.0, 1.0, "   ")]) == []


def test_transcript_cues_survive_a_round_trip(tmp_path: Path):
    cues = [
        (10.0, 13.5, "The harbour tunnel is under review."),
        (13.5, 17.0, "It reopens when the survey is done."),
    ]

    path = save_cues(cues, tmp_path / "episode.cues.json")

    assert load_cues(path) == cues
    assert not list(tmp_path.glob("*.part"))


def test_unusable_transcript_cache_is_ignored(tmp_path: Path):
    assert load_cues(tmp_path / "missing.json") == []

    broken = tmp_path / "broken.json"
    broken.write_text("nonsense", encoding="utf-8")
    assert load_cues(broken) == []

    partial = tmp_path / "partial.json"
    partial.write_text('[{"start": 1.0, "end": 2.0}]', encoding="utf-8")
    assert load_cues(partial) == []


def test_every_piece_of_a_split_cue_is_readable():
    text = " ".join(["word"] * 60)
    cues = [(0.0, 8.0, text)]

    fitted = split_cues(cues, min_duration=0.8)

    assert len(fitted) > 1
    assert all(
        end - start >= 0.8
        for start, end, _ in fitted
    )


def test_no_split_piece_is_left_as_a_lone_word():
    cue = (
        "when he was approached by a man who assaulted him through "
        "the window of the vehicle."
    )

    fitted = split_cues([(0.0, 5.0, cue)])

    assert len(fitted) > 1
    assert all(
        len(text) >= 24
        for _, _, text in fitted
    )
    assert all(
        len(textwrap.wrap(text, 42)) <= 2
        for _, _, text in fitted
    )
    assert " ".join(text for _, _, text in fitted) == cue
