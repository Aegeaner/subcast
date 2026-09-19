"""What a resolve wrote down, and whether it is still worth trusting."""

from __future__ import annotations

import time
from pathlib import Path

from subcast import config, meta
from subcast.sources import Media


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
    title: str = "A talk",
    duration: float | None = 812.5,
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

    assert meta.fresh(media()) is False

    meta.save(media())

    assert meta.fresh(media()) is True
    assert meta.read('youtube', 'abc123').duration == 812.5


def test_a_title_that_changed_is_asked_about_again(
    monkeypatch,
    tmp_path: Path,
):
    """
    The title is the one thing we can check a cached video against, and
    what a re-upload changes.
    """

    in_cache(monkeypatch, tmp_path)

    meta.save(media("A talk"))

    assert meta.fresh(media("A different talk")) is False

    # the same title, told differently, is the same video
    assert meta.fresh(media("  a TALK ")) is True


def test_a_resolve_older_than_the_ttl_is_asked_about_again(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    meta.save(media())

    written = tmp_path / "youtube" / "abc123.meta.json"
    text = written.read_text()
    written.write_text(
        text.replace(
            f'"resolved": {meta.read("youtube", "abc123").resolved}',
            f'"resolved": {time.time() - meta.RESOLVE_TTL - 1}',
        )
    )

    assert meta.fresh(media()) is False


def test_a_metadata_file_that_cannot_be_read_is_asked_about_again(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    target = tmp_path / "youtube" / "abc123.meta.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{ half a file")

    assert meta.read("youtube", "abc123") is None
    assert meta.fresh(media()) is False
