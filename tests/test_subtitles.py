"""Published captions, and what happens when the URL is not WebVTT."""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import subtitles
from subcast.sources import Captions, Media, youtube

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Good morning.
"""


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
