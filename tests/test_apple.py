"""Apple Podcasts: the feed a page says the show is published as.

Everything here is made up: no test carries an episode Apple serves, and
no URL that resolves to one. The page shape, though, is the one served -
the payload a page is rendered from, which states the feed the show is
published as and, on an episode's page, the guid the feed gives it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import cli, sources
from subcast.sources import apple, podcast
from subcast.sources.apple import (
    SOURCE,
    page_feed,
)

FIXTURES = Path(__file__).parent / "fixtures"

SHOW = "https://podcasts.apple.com/us/podcast/example-show/id1234567890"

EPISODE = f"{SHOW}?i=1000000000002"

CHANNEL = "https://podcasts.apple.com/us/channel/example/id4242"

FEED = "https://example.test/show.rss"

# The feed another show's card on the page names, which is not this page's
# show: every card a page carries has a feed of its own.
OTHER_FEED = "https://example.test/another.rss"


def show_page() -> str:

    return (
        FIXTURES / "apple_show_page.html"
    ).read_text(encoding="utf-8")


def episode_page() -> str:

    return (
        FIXTURES / "apple_episode_page.html"
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
    source reads the feed the page named - which is what a feed saved
    under its own name is read by.
    """

    fetch = fake_fetch(pages)

    monkeypatch.setattr(apple, "fetch_text", fetch)
    monkeypatch.setattr(podcast, "fetch_text", fetch)


def test_a_show_page_is_read_as_the_feed_it_names(monkeypatch):
    patch(
        monkeypatch,
        {
            SHOW: show_page(),
            FEED: feed_text(),
        },
    )

    items = SOURCE.episodes(SHOW)

    assert [
        item.title
        for item in items
    ] == [
        "Episode One",
        "Episode Two",
        "Episode Three",
    ]

    # what the feed states, the item carries: the audio and how long it is
    assert items[0].source == "apple"
    assert items[0].duration == 1589.0
    assert items[0].kind == "audio"
    assert items[0].stream is False

    assert SOURCE.resolve(items[0]) is items[0]
    assert cli.plays_while_preparing(items[0], playing=True) is False


def test_a_listing_reads_the_page_and_then_the_feed_it_named(monkeypatch):
    """
    One page fetch names the feed, and one feed fetch is the listing: a
    card beside the page's own show states another feed, and it is not
    the one a run goes to.
    """

    asked: list[str] = []

    def fetch(url, session=None) -> str:

        asked.append(url)

        if url == SHOW:

            return show_page()

        return feed_text()

    monkeypatch.setattr(apple, "fetch_text", fetch)

    SOURCE.episodes(SHOW)

    assert asked == [
        SHOW,
        FEED,
    ]


def test_the_feed_is_the_one_the_pages_own_show_is_published_as():
    page = show_page()

    assert OTHER_FEED in page
    assert page_feed(page) == (FEED, "")


def test_the_episode_a_link_names_is_the_one_item_it_is(monkeypatch):
    """
    A link to an episode is that episode, by the guid the feed gives it -
    not the newest episode of the show, which is what the feed leads with.
    """

    patch(
        monkeypatch,
        {
            EPISODE: episode_page(),
            FEED: feed_text(),
        },
    )

    items = SOURCE.episodes(EPISODE)

    assert [
        (item.key, item.title)
        for item in items
    ] == [
        ("clip-2", "Episode Two"),
    ]


def test_an_episode_the_feed_does_not_carry_is_refused(monkeypatch):
    patch(
        monkeypatch,
        {
            EPISODE: episode_page().replace("clip-2", "clip-9"),
            FEED: feed_text(),
        },
    )

    with pytest.raises(RuntimeError) as error:
        SOURCE.episodes(EPISODE)

    assert "names an episode the feed does not carry" in str(error.value)


def test_a_page_that_names_no_feed_says_so():
    with pytest.raises(RuntimeError) as error:
        page_feed(
            show_page().replace(FEED, "")
        )

    assert "names no feed" in str(error.value)


def test_a_channel_is_refused_by_what_it_is():
    """
    A channel is a group of shows rather than one of them, so a link to
    one is answered with what it is rather than as a page to read.
    """

    with pytest.raises(RuntimeError) as error:
        page_feed(
            show_page().replace(
                "ShowPageIntent",
                "ChannelPageIntent",
            )
        )

    assert "channel" in str(error.value)


def test_a_page_that_carries_no_payload_says_so():
    with pytest.raises(RuntimeError) as error:
        page_feed("<html><body>nothing to play</body></html>")

    assert "carried no show to read" in str(error.value)


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
        (f"{SHOW}/", True),
        (EPISODE, True),
        # the storefront and the slug are parts of the path a link may not
        # carry, and the site serves the ones that do not
        ("https://podcasts.apple.com/podcast/id1234567890", True),
        ("https://podcasts.apple.com/ie/podcast/example-show/id1234567890", True),
        ("https://itunes.apple.com/us/podcast/id1234567890", True),
        # a channel is one, and is refused by what it is
        (CHANNEL, True),
        ("https://podcasts.apple.com/us/podcast/", False),
        ("https://podcasts.apple.com/us/genre/podcasts/id26", False),
        ("https://podcasts.apple.com/", False),
        ("https://example.test/podcast/example-show/id1234567890", False),
        ("https://www.youtube.com/watch?v=example", False),
    ],
)
def test_a_page_of_a_show_is_recognised(
    url: str,
    expected: bool,
):
    assert SOURCE.matches(url) is expected


def test_the_pipeline_finds_this_source_for_its_pages():
    for url in (SHOW, EPISODE, CHANNEL):

        assert sources.detect(url) is SOURCE
