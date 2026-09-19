"""The listing cache: what a menu shows before the source answers."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from subcast import config, listing
from subcast.sources import Media

URL = "https://www.youtube.com/@BBCNews"


def in_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        config,
        "CACHE_DIR",
        tmp_path,
    )


def entry(
    key: str,
    duration: float | None = 300.0,
) -> Media:
    return Media(
        source="youtube",
        key=key,
        title=f"A video called {key}",
        url=f"https://www.youtube.com/watch?v={key}",
        duration=duration,
    )


def test_a_listing_survives_to_the_next_run(monkeypatch, tmp_path: Path):
    in_cache(monkeypatch, tmp_path)

    assert listing.read("youtube", URL) is None

    listing.save("youtube", URL, 30, [entry("one"), entry("two")])

    known = listing.read("youtube", URL)

    assert known is not None
    assert known.url == URL
    assert known.limit == 30
    assert [item.key for item in known.items] == ["one", "two"]
    assert known.items[0].title == "A video called one"
    assert known.items[0].duration == 300.0


def test_a_listing_is_only_read_for_the_url_it_belongs_to(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    listing.save("youtube", URL, None, [entry("one")])

    assert listing.read("youtube", "https://www.youtube.com/@SkyNews") is None


def test_a_listing_kept_too_long_is_not_shown(monkeypatch, tmp_path: Path):
    in_cache(monkeypatch, tmp_path)

    listing.save("youtube", URL, None, [entry("one")])

    target = listing.path("youtube", URL)
    target.write_text(
        target.read_text().replace(
            f'"fetched": {listing.read("youtube", URL).fetched}',
            f'"fetched": {time.time() - listing.KEEP_FOR - 1}',
        )
    )

    assert listing.read("youtube", URL) is None


@pytest.mark.parametrize(
    ("fetched", "wanted", "covers"),
    [
        # as many as the source offered answers any question
        (None, None, True),
        (None, 30, True),
        # a listing of the newest 30 answers a question about 30, not 50
        (30, 30, True),
        (30, 50, False),
        (30, None, False),
        (5, 3, True),
    ],
)
def test_a_listing_only_answers_questions_it_is_deep_enough_for(
    fetched: int | None,
    wanted: int | None,
    covers: bool,
):
    known = listing.Cached(
        url=URL,
        fetched=time.time(),
        limit=fetched,
        items=[entry("one")],
    )

    assert known.covers(wanted) is covers


def test_reading_a_listing_gives_back_only_as_many_as_were_asked_for(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    listing.save(
        "youtube",
        URL,
        None,
        [entry("one"), entry("two"), entry("three")],
    )

    known = listing.read("youtube", URL)

    assert [item.key for item in known.taking(2)] == ["one", "two"]
    assert len(known.taking(None)) == 3


def test_a_listing_file_that_cannot_be_read_is_not_used(
    monkeypatch,
    tmp_path: Path,
):
    in_cache(monkeypatch, tmp_path)

    target = listing.path("youtube", URL)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{ half a file")

    assert listing.read("youtube", URL) is None
