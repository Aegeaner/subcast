"""Acast shows: the feed the pages of Acast and of its publishers name.

Everything here is made up: no test carries an episode a show published,
and no URL that resolves to one. The page shapes, though, are the ones
served - Acast's own page for a show, and a publisher's page whose own
episodes play from the stream one show is published on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import cli, sources
from subcast.sources import acast, podcast
from subcast.sources.acast import (
    SOURCE,
    page_feed,
)

FIXTURES = Path(__file__).parent / "fixtures"

SHOW = "https://shows.acast.com/example-show"

PAGE = "https://www.irishtimes.com/podcasts/example-show/"

# The feed the show page links, which is not the name its path carries: a
# show's slug on acast.com and the slug of its feed are not the same
# (`inside-politics` is published as `inside-politics-2`).
FEED = "https://feeds.acast.com/public/shows/example-show-feed"

# The show a publisher's page carries, and the feed the page advertises
# instead - one show's, on every page of the site.
STREAM = "111122223333444455556666"

STREAM_FEED = f"https://feeds.acast.com/public/shows/{STREAM}"

ADVERTISED = "https://feeds.acast.com/public/shows/000000000000000000000099"

OTHER_SHOW = "https://feeds.acast.com/public/shows/aaaabbbbccccddddeeeeffff"

OTHER_STREAM = (
    OTHER_SHOW.replace("/shows/", "/streams/")
    + "/episodes/cccccccccccccccccccccccc.mp3"
)


def show_page() -> str:

    return (
        FIXTURES / "acast_show_page.html"
    ).read_text(encoding="utf-8")


def publisher_page() -> str:

    return (
        FIXTURES / "acast_publisher_page.html"
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


def patch(
    monkeypatch,
    pages: dict[str, str],
):
    """
    Both fetches a run makes: this source reads the page, and the feed
    source reads the feed the page named.
    """

    fetch = fake_fetch(pages)

    monkeypatch.setattr(acast, "fetch_text", fetch)
    monkeypatch.setattr(podcast, "fetch_text", fetch)


def test_a_publishers_page_is_read_as_the_feed_its_episodes_play_from(
    monkeypatch,
):
    patch(
        monkeypatch,
        {
            PAGE: publisher_page(),
            STREAM_FEED: feed_text(),
        },
    )

    items = SOURCE.episodes(PAGE)

    assert [
        item.title
        for item in items
    ] == [
        "Episode One",
        "Episode Two",
        "Episode Three",
    ]

    # what the feed states, the item carries: the audio, its length, and
    # the source whose cache it is
    assert items[0].source == "acast"
    assert items[0].duration == 1589.0
    assert items[0].kind == "audio"
    assert items[0].stream is False

    assert SOURCE.resolve(items[0]) is items[0]
    assert cli.plays_while_preparing(items[0], playing=True) is False


def test_the_feed_a_page_carries_is_the_one_its_own_episodes_play_from():
    """
    A publisher's page advertises another show's feed beside its own
    episodes - the same one on every page of the site - so the show it is
    about is the one its cards play, without exception.
    """

    page = publisher_page()

    assert ADVERTISED in page
    assert page_feed(page) == STREAM_FEED


def test_an_acast_show_page_is_read_as_the_feed_it_links(monkeypatch):
    patch(
        monkeypatch,
        {
            SHOW: show_page(),
            FEED: feed_text(),
        },
    )

    assert [
        item.title
        for item in SOURCE.episodes(SHOW, limit=1)
    ] == ["Episode One"]


def test_a_page_that_carries_no_podcast_audio_says_so():
    with pytest.raises(RuntimeError) as error:
        page_feed("<html><body>nothing to listen to</body></html>")

    assert "no podcast audio" in str(error.value)


def test_a_page_that_carries_more_than_one_podcast_offers_their_feeds():
    """
    A page about several shows has no one feed to be read as, and taking
    the first would play another show's episodes without saying so.
    """

    page = publisher_page() + f'<script>"{OTHER_STREAM}"</script>'

    with pytest.raises(RuntimeError) as error:
        page_feed(page)

    message = str(error.value)

    assert "more than one podcast" in message
    assert STREAM_FEED in message
    assert OTHER_SHOW in message


def test_a_show_names_a_feed_after_itself(monkeypatch):
    patch(
        monkeypatch,
        {
            SHOW: show_page(),
            FEED: feed_text(),
        },
    )

    assert SOURCE.listing_title(SHOW) == "Example Podcast"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (SHOW, True),
        ("https://shows.acast.com/example-show/", True),
        ("https://shows.acast.com/61409400444fd9068ff27e5f", True),
        (PAGE, True),
        ("https://www.irishtimes.com/podcasts/example-show", True),
        ("https://www.irishtimes.com/podcasts/example-show/?page=2", True),
        # a page that lists no audio of its own is not this source's
        ("https://shows.acast.com/", False),
        ("https://shows.acast.com/example-show/episodes", False),
        ("https://www.irishtimes.com/podcasts/", False),
        (
            "https://www.irishtimes.com/podcasts/example-show/episode/",
            False,
        ),
        ("https://www.irishtimes.com/news/example", False),
        # a feed is the feed source's, not a page to be read
        ("https://feeds.acast.com/public/shows/example-show-feed", False),
        ("https://www.youtube.com/watch?v=example", False),
    ],
)
def test_a_page_of_a_show_is_recognised(
    url: str,
    expected: bool,
):
    assert SOURCE.matches(url) is expected


def test_the_pipeline_finds_this_source_for_its_pages():
    """
    A show page on acast.com is a URL on a feed host, which the feed
    source takes at its word: the source that reads such a page has to be
    the one asked first, or the page is read as a feed and fails.
    """

    assert podcast.SOURCE.matches(SHOW) is True

    for url in (SHOW, PAGE):

        assert sources.detect(url) is SOURCE
