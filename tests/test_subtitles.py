"""The caption fallback, and subtitles worked out while playback runs."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import requests

from subcast import subtitles
from subcast.sources import Captions, Media, youtube

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Good morning.
"""


class FakeResponse:
    """Just enough of a response for the status code to be read."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


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
    assert job.value() is None

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
    job = subtitles.PendingSubtitles.finished(prepared())

    assert job.done_yet() is True
    assert job.value() == prepared()


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
    job = subtitles.PendingSubtitles.finished(prepared())

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
        (Captions(language="en", url="https://example.test/en.vtt"),)
    ) == [(1.0, 3.0, "Good morning.")]


def test_a_track_youtube_refuses_is_followed_by_the_one_it_came_from(
    monkeypatch,
    tmp_path: Path,
):
    """
    Translated tracks are the ones YouTube rate-limits; the track they were
    translated from answers instead, which saves an extraction.
    """

    asked: list[str] = []

    def download(url: str, session) -> str:

        asked.append(url)

        if "tlang=" in url:

            raise requests.HTTPError(
                "429 Too Many Requests",
                response=FakeResponse(429),
            )

        return VTT

    monkeypatch.setattr(subtitles, "_download_caption_text", download)

    translated = Captions(
        language="en",
        url="https://example.test/en?lang=zh&tlang=en&fmt=vtt",
    )
    native = Captions(
        language="zh-Hant",
        url="https://example.test/zh?lang=zh-Hant&fmt=vtt",
    )

    assert subtitles.fetch_captions(
        (translated, native),
        media(),
        tmp_path / "abc",
    ) == [(1.0, 3.0, "Good morning.")]

    assert asked == [translated.url, native.url]


def test_being_told_to_come_back_later_is_said_as_that(
    monkeypatch,
    tmp_path: Path,
):
    """
    Rate limiting is not the same as captions that turned out to be empty:
    one is worth trying again, the other is how the video is.
    """

    def download(url: str, session) -> str:

        raise requests.HTTPError(
            "429 Too Many Requests",
            response=FakeResponse(429),
        )

    monkeypatch.setattr(subtitles, "_download_caption_text", download)
    monkeypatch.setattr(
        youtube.SOURCE,
        "caption_file",
        lambda url, language, stem: None,
    )

    with pytest.raises(RuntimeError) as error:
        subtitles.fetch_captions(
            (Captions(language="en", url="https://example.test/en.vtt"),),
            media(),
            tmp_path / "abc",
        )

    assert "rate-limiting" in str(error.value)
    assert "429" in str(error.value)


def test_an_empty_track_that_is_not_rate_limited_says_so(
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
            (Captions(language="en", url="https://example.test/en.vtt"),),
            media(),
            tmp_path / "abc",
        )

    assert "the published captions were empty" in str(error.value)


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
        (Captions(language="en", url="https://example.test/en.json3"),),
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
            (Captions(language="en", url="https://example.test/en.vtt"),),
            media(),
            tmp_path / "abc",
        )

    assert "the published captions were empty" in str(error.value)


def test_settings_replace_the_defaults_rather_than_sitting_beside_them():
    """
    A live chunk is heard without the voice filter and an episode with it,
    and both go through the same reader: a setting has to replace a default
    rather than be passed twice, which is a TypeError - and one broadcast
    lost its captions to exactly that.
    """

    class FakeModel:
        """Records what the reader was asked for."""

        def __init__(self) -> None:
            self.seen: dict = {}

        def transcribe(self, path, **options):
            self.seen = options
            return iter([]), None

    model = FakeModel()

    subtitles.transcribe_cues(
        model,
        Path("/tmp/chunk.wav"),
        vad_filter=False,
        beam_size=1,
        best_of=1,
    )

    assert model.seen["vad_filter"] is False
    assert model.seen["beam_size"] == 1
    assert model.seen["language"] == "en"
    assert model.seen["condition_on_previous_text"] is False
