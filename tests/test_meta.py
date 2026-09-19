"""What a resolve learned: metadata, and the streams mpv can be given."""

from __future__ import annotations

import time
from pathlib import Path

from subcast import config, meta
from subcast.sources import Media

VIDEO = {
    "format_id": "137",
    "url": "https://example.test/video?expire=9999999999",
    "protocol": "https",
    "vcodec": "avc1",
    "acodec": "none",
    "height": 1080,
    "tbr": 4000.0,
}
SMALLER = {**VIDEO, "format_id": "136", "height": 720, "tbr": 2000.0}
AUDIO = {
    "format_id": "140",
    "url": "https://example.test/audio?expire=9999999999",
    "protocol": "https",
    "vcodec": "none",
    "acodec": "opus",
    "tbr": 128.0,
}
MUXED = {
    "format_id": "18",
    "url": "https://example.test/muxed?expire=9999999999",
    "protocol": "https",
    "vcodec": "avc1",
    "acodec": "mp4a",
    "height": 360,
    "tbr": 600.0,
}
LIVE = {
    **AUDIO,
    "format_id": "95",
    "protocol": "m3u8_native",
}


def in_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        config,
        "CACHE_DIR",
        tmp_path,
    )


def media(
    title: str = "A video",
    duration: float | None = 300.0,
) -> Media:
    return Media(
        source="youtube",
        key="abc123",
        title=title,
        url="https://www.youtube.com/watch?v=abc123",
        duration=duration,
    )


def test_what_a_resolve_learned_is_known_next_time(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    assert meta.read("youtube", "abc123") is None
    assert meta.fresh(media()) is False

    meta.save(media(), [VIDEO, AUDIO])

    known = meta.read("youtube", "abc123")

    assert meta.fresh(media()) is True
    assert known.duration == 300.0
    assert [entry["format_id"] for entry in known.formats] == ["137", "140"]


def test_a_title_that_changed_is_asked_about_again(monkeypatch, tmp_path: Path):
    """
    The title is the one thing we can check a cached video against, and what
    a re-upload changes.
    """

    in_cache(monkeypatch, tmp_path)

    meta.save(media("A talk"))

    assert meta.fresh(media("A different talk")) is False
    assert meta.fresh(media("  a TALK ")) is True


def test_a_resolve_older_than_the_ttl_is_asked_about_again(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    meta.save(media())

    written = meta.path("youtube", "abc123")
    written.write_text(
        written.read_text().replace(
            f'"resolved": {meta.read("youtube", "abc123").resolved}',
            f'"resolved": {time.time() - meta.RESOLVE_TTL - 1}',
        )
    )

    assert meta.fresh(media()) is False


def test_a_file_that_cannot_be_read_is_asked_about_again(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    target = meta.path("youtube", "abc123")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{ half a file")

    assert meta.read("youtube", "abc123") is None
    assert meta.fresh(media()) is False


def test_the_picture_is_capped_and_the_sound_is_the_best(
    monkeypatch,
    tmp_path: Path,
):
    """
    The same choice mpv's format argument would have made, so handing mpv
    URLs does not change what is played: `--quality` caps the picture, and
    the best sound comes with it.
    """

    in_cache(monkeypatch, tmp_path)

    meta.save(media(), [VIDEO, SMALLER, AUDIO])

    streams = meta.streams(media(), quality=720)

    assert streams.video == SMALLER["url"]
    assert streams.audio == AUDIO["url"]
    assert streams.first == SMALLER["url"]


def test_sound_only_asks_for_sound(monkeypatch, tmp_path: Path):
    in_cache(monkeypatch, tmp_path)

    meta.save(media(), [VIDEO, SMALLER, AUDIO])

    streams = meta.streams(media(), quality=None)

    assert streams.video is None
    assert streams.audio == AUDIO["url"]
    assert streams.first == AUDIO["url"]


def test_one_stream_with_both_is_played_on_its_own(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    meta.save(media(), [MUXED])

    streams = meta.streams(media(), quality=1080)

    assert streams.video == MUXED["url"]
    assert streams.audio is None


def test_a_manifest_is_left_to_mpv(monkeypatch, tmp_path: Path):
    """
    A live stream's formats are manifests, not URLs mpv can be pointed at:
    this is what leaves the extraction to mpv there.
    """

    in_cache(monkeypatch, tmp_path)

    meta.save(media(), [LIVE])

    assert meta.read("youtube", "abc123").streams_live is False
    assert meta.streams(media(), quality=None) is None


def test_stream_urls_that_are_about_to_expire_are_not_used(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    meta.save(
        media(),
        [{**AUDIO, "url": f"https://example.test/a?expire={int(time.time()) + 60}"}],
    )

    assert meta.streams(media(), quality=None) is None
