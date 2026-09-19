"""Audio naming, extension guessing, and cache lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast.media import (
    find_cached_audio,
    guess_audio_extension,
    sanitize_filename,
)


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
