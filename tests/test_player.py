"""Remembering where an item got to, so the next run picks it up."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from subcast import player
from subcast.subtitles import PendingSubtitles, Prepared


class FakeClient:
    """An mpv that only remembers what it was told."""

    def __init__(self, problem: str | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.problem = problem

    def command(self, *command: str) -> str | None:
        self.commands.append(command)
        return self.problem


def prepared() -> Prepared:
    return Prepared(
        srt_path=Path("/tmp/example.srt"),
        chapters_path=None,
        cues=[],
        segments=[],
    )


def test_subtitles_that_are_not_ready_are_asked_about_again():
    release = threading.Event()

    def work():
        release.wait(timeout=5)
        return prepared()

    job = PendingSubtitles(work)
    job.start()

    client = FakeClient()

    assert player.attach_subtitles(client, job) is False
    assert client.commands == []

    release.set()
    job.wait()

    assert player.attach_subtitles(client, job) is True
    assert client.commands == [
        ("sub-add", "/tmp/example.srt", "select"),
    ]


def test_subtitles_that_are_ready_are_added_once():
    job = PendingSubtitles.finished(prepared())
    client = FakeClient()

    assert player.attach_subtitles(client, job) is True
    assert player.attach_subtitles(client, job) is True

    # the caller stops asking once this says so, but a second call is
    # harmless: mpv replaces the track it was given
    assert len(client.commands) == 2


def test_a_failed_preparation_is_reported_not_retried(capsys):
    def work():
        raise RuntimeError("the published captions were empty")

    job = PendingSubtitles(work)
    job.start()
    job.wait()

    client = FakeClient()

    assert player.attach_subtitles(client, job) is True
    assert client.commands == []
    assert "playing without them" in capsys.readouterr().out


def test_mpv_refusing_the_file_is_said_out_loud(capsys):
    job = PendingSubtitles.finished(prepared())
    client = FakeClient(problem="invalid parameter")

    assert player.attach_subtitles(client, job) is True
    assert "invalid parameter" in capsys.readouterr().out


def test_a_stream_mpv_cannot_load_is_tried_once_more():
    """
    YouTube hands out signed stream URLs that answer 403 from time to
    time; a fresh extraction is the cure, and mpv stops at the first one.
    """

    attempts: list[int] = []

    def play() -> int:
        attempts.append(1)
        return player.LOAD_ERROR if len(attempts) == 1 else 0

    assert player.retry_load_error(play) == 0
    assert len(attempts) == 2


def test_a_second_load_failure_is_reported_as_it_stands():
    attempts: list[int] = []

    def play() -> int:
        attempts.append(1)
        return player.LOAD_ERROR

    assert player.retry_load_error(play) == player.LOAD_ERROR
    assert len(attempts) == 2


@pytest.mark.parametrize("status", [0, 1, 3, 4, 130])
def test_anything_else_is_not_a_stream_to_fetch_again(status: int):
    """A quit, a bad option or Ctrl-C must not start playback over."""

    attempts: list[int] = []

    def play() -> int:
        attempts.append(1)
        return status

    assert player.retry_load_error(play) == status
    assert len(attempts) == 1


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
