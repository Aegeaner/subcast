"""Remembering where an item got to, so the next run picks it up."""

from __future__ import annotations

from pathlib import Path

from subcast import player


def test_a_position_survives_to_the_next_run(tmp_path: Path):
    stem = tmp_path / "abc123"

    player.Positions(stem).update(754.0, 3600.0)

    assert player.Positions(stem).start == 754.0


def test_an_item_that_was_never_started_begins_at_the_beginning(
    tmp_path: Path,
):
    stem = tmp_path / "abc123"

    assert player.Positions(stem).start == 0.0

    # a truncated or hand-edited file is no reason to start somewhere odd
    (tmp_path / "abc123.position").write_text("half a number\n")

    assert player.Positions(stem).start == 0.0


def test_an_item_watched_to_the_end_is_not_resumed(tmp_path: Path):
    stem = tmp_path / "abc123"

    # a minute from the end: still worth resuming
    player.Positions(stem).update(3540.0, 3600.0)
    assert player.Positions(stem).start == 3540.0

    # inside the last stretch: that is watched
    player.Positions(stem).update(
        3600.0 - player.FINISHED_SECONDS,
        3600.0,
    )
    assert player.Positions(stem).start == 0.0

    # and so is anything mpv reports as having reached the end
    player.Positions(stem).update(1800.0, 3600.0)
    player.Positions(stem).update(1800.0, 3600.0, eof=True)
    assert player.Positions(stem).start == 0.0


def test_a_stream_of_unknown_length_keeps_its_position(
    tmp_path: Path,
):
    """
    mpv reporting no length is no reason to lose the position: the end
    simply cannot be recognised, and the position is all we have.
    """

    stem = tmp_path / "abc123"

    player.Positions(stem).update(754.0, None)

    assert player.Positions(stem).start == 754.0


def test_the_player_is_told_where_to_start(tmp_path: Path):
    stem = tmp_path / "abc123"
    positions = player.Positions(stem)

    assert player.start_arguments(positions) == []
    assert player.start_arguments(None) == []

    positions.update(754.04, 3600.0)

    assert player.start_arguments(
        player.Positions(stem)
    ) == ["--start=754.0"]


def test_starting_over_ignores_what_was_remembered(tmp_path: Path):
    stem = tmp_path / "abc123"

    player.Positions(stem).update(754.0, 3600.0)

    positions = player.Positions(stem, resume=False)

    assert positions.start == 0.0

    # and it takes over from there as it plays
    positions.update(60.0, 3600.0)

    assert player.Positions(stem).start == 60.0


def test_a_position_that_cannot_be_written_is_not_fatal(
    tmp_path: Path,
):
    """
    Playback is the point; being unable to remember where you are is not
    worth stopping for (a read-only cache, a full disk).
    """

    directory = tmp_path / "locked"
    directory.mkdir()
    directory.chmod(0o500)

    try:
        player.Positions(directory / "abc123").update(10.0, 3600.0)

    finally:
        directory.chmod(0o700)
