"""Audio naming, extension guessing, and cache lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import media
from subcast.media import (
    find_cached_audio,
    guess_audio_extension,
    sanitize_filename,
)


class Response:
    """A response whose body is whatever the test says it is."""

    def __init__(self, chunks) -> None:

        self.headers = {"Content-Type": "audio/mpeg"}
        self.url = "https://example.test/x.mp3"
        self._chunks = chunks

    def raise_for_status(self) -> None:

        return None

    def iter_content(self, chunk_size: int):

        return self._chunks()

    def __enter__(self):

        return self

    def __exit__(self, *exc) -> bool:

        return False


class Session:
    """A session that answers with the response it was built around."""

    def __init__(self, response: Response) -> None:

        self._response = response

    def get(self, *args, **kwargs) -> Response:

        return self._response


@pytest.mark.parametrize(
    "content_type, url, expected",
    [
        ("audio/mpeg", "https://example.com/x", ".mp3"),
        ("application/octet-stream", "https://example.com/x.mp3", ".mp3"),
        ("audio/mp4", "https://example.com/x", ".m4a"),
        ("audio/aac", "https://example.com/x", ".aac"),
        ("audio/ogg", "https://example.com/x", ".ogg"),
        ("application/octet-stream", "https://example.com/x", ".mp3"),
    ],
)
def test_extension_from_content_type_or_url(
    content_type: str,
    url: str,
    expected: str,
):
    assert guess_audio_extension(content_type, url) == expected


def test_filenames_lose_illegal_characters():
    assert sanitize_filename('Morning/Ireland: "live"') == (
        "Morning_Ireland_ _live"
    )
    assert sanitize_filename("   spaced   out   ") == "spaced out"
    assert sanitize_filename("...") == "episode"
    assert len(sanitize_filename("x" * 400)) == 180


def test_cache_lookup_ignores_partial_and_subtitle_files(tmp_path: Path):
    key = "00000001-0000-4000-8000-000000000001"

    (tmp_path / f"{key}.mp3").write_bytes(b"")
    (tmp_path / f"{key}.mp3.part").write_bytes(b"")
    (tmp_path / f"{key}.srt").write_text("1\n")

    assert find_cached_audio(tmp_path, key) == tmp_path / f"{key}.mp3"
    assert find_cached_audio(tmp_path, "other") is None
    assert find_cached_audio(tmp_path / "missing", key) is None


def test_an_interrupted_download_leaves_nothing_behind(
    tmp_path: Path,
    monkeypatch,
):
    """
    A download nobody waited for is not wanted half-finished - a run that
    played the stream instead of the audio it was hearing leaves nothing -
    and what interrupted it is raised on unchanged.
    """

    def chunks():

        yield b"x" * 1024

        raise KeyboardInterrupt

    monkeypatch.setattr(
        media.requests,
        "Session",
        lambda: Session(Response(chunks)),
    )

    with pytest.raises(KeyboardInterrupt):

        media.download_audio(
            "https://example.test/x.mp3",
            tmp_path / "key",
            {},
        )

    assert list(tmp_path.iterdir()) == []
