"""Podcast feeds: the items they publish, and what an item carries.

Everything here is made up: no test carries an episode a feed published,
and no URL that resolves to one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import cli
from subcast.sources import podcast
from subcast.sources.podcast import (
    SOURCE,
    duration_seconds,
    feed_link,
    parse_feed,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "podcast_feed.rss"
)


def feed_text() -> str:

    return FIXTURE.read_text(encoding="utf-8")


def test_a_feed_is_read_as_the_episodes_it_publishes():
    title, items = parse_feed(feed_text())

    assert title == "Example Podcast"

    assert [
        item.title
        for item in items
    ] == [
        "Episode One",
        "Episode Two",
        "Episode Three",
    ]

    assert [
        item.key
        for item in items
    ] == [
        "clip-1",
        "clip-2",
        "clip-4",
    ]

    assert [
        item.url
        for item in items
    ] == [
        "https://example.test/one.mp3",
        "https://example.test/two.m4a",
        "https://example.test/three.m4a",
    ]

    # "26:29", plain seconds and "01:02:03" are all lengths a feed states
    assert [
        item.duration
        for item in items
    ] == [
        1589.0,
        1589.0,
        3723.0,
    ]

    assert all(
        item.kind == "audio" and item.stream is False
        for item in items
    )


def test_an_item_with_nothing_to_play_is_not_an_episode():
    _title, items = parse_feed(feed_text())

    # a feed carries text posts and videos too
    assert "A written post" not in [
        item.title
        for item in items
    ]


def test_the_audio_is_the_enclosure_or_the_audio_media_content():
    _title, items = parse_feed(feed_text())

    # the enclosure is taken at its word when it states no type, and a
    # media:content has to say it is audio: the same element carries the
    # item's image
    assert items[1].url == "https://example.test/two.m4a"


def test_a_transcript_a_feed_publishes_is_not_read():
    """
    A published transcript is timed against the file the publisher made,
    and the file a client fetches is not always that one: Bloomberg's
    arrives with ads stitched round the content, and its own transcript
    ran a sentence ahead of what plays (measured). Captions are heard
    from the audio the run plays instead, which is in pace with it.
    """

    _title, items = parse_feed(feed_text())

    # the fixture publishes both WebVTT and SubRip tracks
    assert items[0].captions == ()
    assert items[1].captions == ()


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ("1589", 1589.0),
        ("26:29", 1589.0),
        ("01:02:03", 3723.0),
        ("00:05:00.000", 300.0),
        ("", None),
        ("not a length", None),
        ("1:2:3:4", None),
    ],
)
def test_a_length_a_feed_states_is_read(
    stated: str,
    expected: float | None,
):
    assert duration_seconds(stated) == expected


def test_a_feed_names_itself(monkeypatch):
    monkeypatch.setattr(
        podcast,
        "fetch_text",
        lambda url, session=None: feed_text(),
    )

    assert SOURCE.listing_title(
        "https://example.test/show.rss"
    ) == "Example Podcast"


def test_a_listing_reads_the_feed_it_was_pointed_at(monkeypatch):
    asked: list[str] = []

    def fetch(url, session=None):
        asked.append(url)
        return feed_text()

    monkeypatch.setattr(
        podcast,
        "fetch_text",
        fetch,
    )

    items = SOURCE.episodes("https://example.test/show.rss")

    assert len(items) == 3
    assert asked == ["https://example.test/show.rss"]


def test_a_feed_item_is_played_from_the_audio_the_feed_states(monkeypatch):
    """
    The listing says everything a resolve could find, so there is no
    resolve to wait for: playback streams the enclosure.
    """

    monkeypatch.setattr(
        podcast,
        "fetch_text",
        lambda url, session=None: feed_text(),
    )

    item = SOURCE.episodes(
        "https://example.test/show.rss",
        limit=1,
    )[0]

    assert SOURCE.resolve(item) is item

    # mpv is handed the mp3, not a page it would run yt-dlp for
    assert cli.plays_while_preparing(item, playing=True) is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.test/show.rss", True),
        ("https://example.test/feed.xml", True),
        ("https://example.test/atom.atom", True),
        ("https://example.test/feed", True),
        ("https://example.test/rss", True),
        ("https://feeds.megaphone.fm/BLM4711", True),
        (
            "https://www.omnycontent.com/d/playlist/x/y/podcast.rss",
            True,
        ),
        ("https://example.test/index.html", False),
        ("https://example.test/", False),
        ("https://www.youtube.com/watch?v=example", False),
        ("", False),
    ],
)
def test_a_url_that_is_a_feed_is_recognised(
    url: str,
    expected: bool,
):
    assert SOURCE.matches(url) is expected


def test_something_that_is_not_an_rss_feed_is_refused():
    with pytest.raises(RuntimeError) as error:
        parse_feed(
            '<?xml version="1.0"?><feed><entry>'
            "<title>Atom</title></entry></feed>"
        )

    assert "RSS" in str(error.value)


def test_something_that_is_not_xml_is_refused():
    with pytest.raises(RuntimeError) as error:
        parse_feed("<rss><channel><item>")

    assert "did not answer with a feed" in str(error.value)


def test_the_feed_a_page_links_is_taken_from_the_page():
    """
    A source whose show page is the only thing naming its feed reads the
    feed out of the page, which is what the page is for.
    """

    assert feed_link(
        '<link type="application/rss+xml" rel="alternate" '
        'href="https://example.test/podcast.rss" />'
    ) == "https://example.test/podcast.rss"

    # the attributes are in whatever order the page writes them
    assert feed_link(
        '<link href="https://example.test/podcast.rss" '
        'type="application/rss+xml" />'
    ) == "https://example.test/podcast.rss"


def test_a_page_that_links_no_feed_says_so():
    with pytest.raises(RuntimeError) as error:
        feed_link("<html><head></head></html>")

    assert "links no feed" in str(error.value)
