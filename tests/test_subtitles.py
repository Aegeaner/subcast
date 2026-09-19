"""The caption fallback, and subtitles worked out while playback runs."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from subcast import subtitles
from subcast.sources import Captions, Media, youtube

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Good morning.
"""


def prepared() -> subtitles.Prepared:
    return subtitles.Prepared(
        srt_path=Path("/tmp/example.srt"),
        chapters_path=None,
        cues=[(1.0, 3.0, "Good morning.")],
        segments=[],
    )


def test_work_started_in_the_background_reports_when_it_is_done():
    release = threading.Event()

    def work():
        release.wait(timeout=5)
        return prepared()

    job = subtitles.PendingSubtitles(work)
    job.start()

    assert job.done_yet() is False
    assert job.prepared() is None

    release.set()

    assert job.wait() == prepared()
    assert job.done_yet() is True


def test_starting_twice_runs_the_work_once():
    runs: list[int] = []

    job = subtitles.PendingSubtitles(lambda: runs.append(1))
    job.start()
    job.start()

    job.wait()

    assert runs == [1]


def test_a_job_that_finished_before_playback_is_ready_at_once():
    job = subtitles.PendingSubtitles.done(prepared())

    assert job.done_yet() is True
    assert job.prepared() == prepared()


def test_a_failure_is_carried_rather_than_raised():
    """
    Playback is already under way when this is noticed: a caption problem
    is a line to print, not a reason to stop the video.
    """

    def work():
        raise RuntimeError("the published captions were empty")

    job = subtitles.PendingSubtitles(work)
    job.start()

    assert job.wait() is None
    assert job.failure_message() == (
        "    Subtitles failed: the published captions were empty; "
        "playing without them."
    )


def test_a_job_that_worked_reports_no_failure():
    job = subtitles.PendingSubtitles.done(prepared())

    assert job.failure_message() is None


def media() -> Media:
    return Media(
        source="youtube",
        key="abc",
        title="A video",
        url=f"{youtube.WATCH_URL}abc",
    )


def test_a_webvtt_caption_url_is_parsed_as_it_is(monkeypatch):
    monkeypatch.setattr(
        subtitles,
        "_download_caption_text",
        lambda url, session: VTT,
    )

    assert subtitles.fetch_captions(
        Captions(language="en", url="https://example.test/en.vtt")
    ) == [(1.0, 3.0, "Good morning.")]


def test_the_source_fetches_captions_a_url_cannot_give(
    monkeypatch,
    tmp_path: Path,
):
    """
    The URL in a player payload is often json3 or a playlist rather than
    WebVTT - the shape YouTube hands over for automatic captions - so the
    source gets the last word.
    """

    monkeypatch.setattr(
        subtitles,
        "_download_caption_text",
        lambda url, session: '{"events": []}',
    )

    asked: list[tuple[str, str, Path]] = []

    def caption_file(url, language, stem):
        asked.append((url, language, stem))
        written = Path(stem).with_suffix(".en.vtt")
        written.write_text(VTT)
        return written

    monkeypatch.setattr(youtube.SOURCE, "caption_file", caption_file)

    stem = tmp_path / "abc"

    assert subtitles.fetch_captions(
        Captions(language="en", url="https://example.test/en.json3"),
        media(),
        stem,
    ) == [(1.0, 3.0, "Good morning.")]

    assert asked == [(f"{youtube.WATCH_URL}abc", "en", stem)]


def test_no_captions_from_either_route_says_so(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        subtitles,
        "_download_caption_text",
        lambda url, session: "",
    )

    monkeypatch.setattr(
        youtube.SOURCE,
        "caption_file",
        lambda url, language, stem: None,
    )

    with pytest.raises(RuntimeError) as error:
        subtitles.fetch_captions(
            Captions(language="en", url="https://example.test/en.vtt"),
            media(),
            tmp_path / "abc",
        )

    assert "the published captions were empty" in str(error.value)
