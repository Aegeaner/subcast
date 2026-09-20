"""Bloomberg podcasts, read as the feed the show is published as.

Everything here is made up: no test carries an episode Bloomberg
published, and no URL that resolves to one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import cli, sources
from subcast.sources import bloomberg
from subcast.sources.bloomberg import (
    SOURCE,
    series_slug,
    sized,
)

FIXTURES = Path(__file__).parent / "fixtures"

SERIES = (
    "https://www.bloomberg.com/podcasts/"
    "series/example-show"
)

SHOW = "https://omny.fm/shows/example-show"

FEED = "https://www.omnycontent.com/d/playlist/example/podcast.rss"


def show_page() -> str:

    return (
        FIXTURES / "bloomberg_show.html"
    ).read_text(encoding="utf-8")


def feed_text() -> str:

    return (
        FIXTURES / "podcast_feed.rss"
    ).read_text(encoding="utf-8")


def fake_fetch(
    pages: dict[str, str],
):
    def fetch(
        url,
        session=None,
    ) -> str:

        if url not in pages:

            raise AssertionError(
                f"fetched {url}"
            )

        return pages[url]

    return fetch


def test_a_series_page_is_read_as_the_show_it_is_published_as(
    monkeypatch,
):
    """
    Bloomberg's own page answers 403 to anything that is not a browser
    bot check, so the show is read where it is hosted, and the slug is
    what the two have in common.
    """

    monkeypatch.setattr(
        bloomberg,
        "fetch_text",
        fake_fetch(
            {
                SHOW: show_page(),
                FEED: feed_text(),
            }
        ),
    )

    items = SOURCE.episodes(SERIES)

    assert [
        item.title
        for item in items
    ] == [
        "Episode One",
        "Episode Two",
        "Episode Three",
    ]

    # what the feed states, the item carries: the audio and how long it is
    assert items[0].duration == 1589.0
    assert items[0].kind == "audio"
    assert items[0].stream is False


def test_a_shallow_listing_asks_the_feed_for_no_more_than_it_plays(
    monkeypatch,
):
    """
    The feed of a show that updates all day holds a thousand items, so
    the count the run needs is stated rather than downloaded and cut.
    """

    asked: list[str] = []

    def fetch(url, session=None) -> str:

        asked.append(url)

        if url == SHOW:

            return show_page()

        return feed_text()

    monkeypatch.setattr(bloomberg, "fetch_text", fetch)

    SOURCE.episodes(SERIES, limit=2)

    assert asked == [
        SHOW,
        f"{FEED}?pageSize=2",
    ]


def test_a_show_names_a_feed_after_itself(monkeypatch):
    monkeypatch.setattr(
        bloomberg,
        "fetch_text",
        fake_fetch(
            {
                SHOW: show_page(),
                FEED: feed_text(),
            }
        ),
    )

    assert SOURCE.listing_title(SERIES) == "Example Podcast"


def test_a_feed_item_is_played_from_the_audio_the_feed_states(monkeypatch):
    monkeypatch.setattr(
        bloomberg,
        "fetch_text",
        fake_fetch(
            {
                SHOW: show_page(),
                f"{FEED}?pageSize=1": feed_text(),
            }
        ),
    )

    item = SOURCE.episodes(SERIES, limit=1)[0]

    assert SOURCE.resolve(item) is item
    assert cli.plays_while_preparing(item, playing=True) is False


def test_the_pipeline_finds_this_source_for_its_series_pages():
    assert sources.detect(SERIES) is SOURCE


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (SERIES, True),
        (
            "https://www.bloomberg.com/podcasts/series/example-show/",
            True,
        ),
        ("https://www.bloomberg.com/news/articles/example", False),
        ("https://www.bloomberg.com/podcasts", False),
    ],
)
def test_a_bloomberg_series_page_is_recognised(
    url: str,
    expected: bool,
):
    assert SOURCE.matches(url) is expected


def test_a_url_that_is_not_a_series_page_is_refused():
    with pytest.raises(RuntimeError) as error:
        series_slug("https://www.bloomberg.com/news/articles/example")

    assert "/podcasts/series/" in str(error.value)


def test_a_feed_is_asked_for_the_count_that_is_wanted():
    assert sized(FEED, 5) == f"{FEED}?pageSize=5"
    assert sized(FEED, None) == FEED
    assert sized(FEED, 0) == FEED
