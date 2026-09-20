"""BBC Audio pages: what they list, and the mp3 an episode plays from.

Everything here is made up: no test carries an episode BBC published,
and no URL that resolves to one. The page shapes, though, are the ones
the site serves - a brand page listing its episodes, a category page
listing programmes, and a page for one episode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from subcast import cli, sources
from subcast.sources import bbc
from subcast.sources.bbc import (
    PAGE_SIZE,
    SOURCE,
    episode_id,
    iso_seconds,
    playable_version,
    stream_url,
)

FIXTURES = Path(__file__).parent / "fixtures"

BRAND = "https://www.bbc.com/audio/brand/p0000001"

CATEGORY = "https://www.bbc.com/audio/category/example"

PLAY = "https://www.bbc.com/audio/play/p0000002"

SCHEDULES = "https://www.bbc.com/audio/schedules/bbc_radio_example"

PROGRAMME = bbc.PROGRAMME_API.format(pid="p0000002")


def brand_page() -> str:

    return (
        FIXTURES / "bbc_brand_page.html"
    ).read_text(encoding="utf-8")


def category_page() -> str:

    return (
        FIXTURES / "bbc_category_page.html"
    ).read_text(encoding="utf-8")


def play_page() -> str:

    return (
        FIXTURES / "bbc_play_page.html"
    ).read_text(encoding="utf-8")


def schedules_page() -> str:

    return (
        FIXTURES / "bbc_schedules_page.html"
    ).read_text(encoding="utf-8")


def paged_brand(count: int, first: int = 1) -> str:
    """
    A programme page carrying `count` episodes, newest first.
    """

    contents = [
        {
            "type": "audio-brand",
            "model": {
                "id": "p0000001",
                "title": "Example Programme",
                "path": "/audio/brand/p0000001",
            },
        }
    ]

    for number in range(first, first + count):

        contents.append(
            {
                "type": "audio-episode",
                "model": {
                    "id": f"p{number:07d}",
                    "title": f"Example Programme - episode {number}",
                    "path": f"/audio/play/p{number:07d}",
                    "blocks": [
                        {
                            "type": "mediaMetadata",
                            "model": {
                                "versions": [
                                    {
                                        "versionId": f"v{number:07d}",
                                        "duration": "00:30:00.000",
                                    }
                                ]
                            },
                        }
                    ],
                },
            }
        )

    page = {
        "props": {
            "pageProps": {
                "pageKey": '@"audio","brand","p0000001",',
                "page": {
                    '@"audio","brand","p0000001",': {
                        "id": "p0000001",
                        "contents": contents,
                    }
                },
            }
        }
    }

    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(page)}</script>"
    )


def programme_json(
    versions: object = "one",
) -> str:
    """
    What the programme API says about one episode.
    """

    if versions == "one":

        versions = [
            {
                "pid": "v0000002",
                "duration": 1589,
                "types": ["Podcast version"],
            }
        ]

    if versions == "aired":

        # what a programme that has aired lists: the version it aired as,
        # and the one published for download beside it
        versions = [
            {
                "pid": "v0000001",
                "duration": 1590,
                "types": ["Original version"],
            },
            {
                "pid": "v0000002",
                "duration": 1589,
                "types": ["Podcast version"],
            },
        ]

    return json.dumps(
        {
            "programme": {
                "pid": "p0000002",
                "type": "episode",
                "title": "The Example Episode",
                "versions": versions,
            }
        }
    )


def fake_fetch(
    pages: dict[str, str],
):
    """
    The page fetch, with a fixed page per URL - and a failure for any URL
    the test did not expect to be asked for.
    """

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


def test_a_programme_page_lists_its_episodes_newest_first(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({BRAND: brand_page()}),
    )

    items = SOURCE.episodes(BRAND)

    assert [
        item.title
        for item in items
    ] == [
        "Example Programme - 19 September 2026",
        "Example Programme - 18 September 2026",
    ]

    assert [
        item.key
        for item in items
    ] == [
        "p0000002",
        "p0000003",
    ]

    assert [
        item.url
        for item in items
    ] == [
        PLAY,
        "https://www.bbc.com/audio/play/p0000003",
    ]

    assert [
        item.duration
        for item in items
    ] == [
        1589.0,
        1440.0,
    ]

    # the page's own card is not an episode, and the episode page is what
    # is resolved later
    assert all(
        item.kind == "audio" and item.stream is False
        for item in items
    )


def test_a_category_page_lists_the_programmes_it_is_a_directory_of(
    monkeypatch,
):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({CATEGORY: category_page()}),
    )

    items = SOURCE.episodes(CATEGORY)

    # the featured episode plays, and a programme plays its newest episode
    assert [
        item.title
        for item in items
    ] == [
        "The Featured Episode",
        "Example Programme",
        "Example Series",
    ]

    assert [
        item.url
        for item in items
    ] == [
        "https://www.bbc.com/audio/play/p0000009",
        BRAND,
        "https://www.bbc.com/audio/series/p0000004",
    ]

    # a programme has no length of its own to state
    assert [
        item.duration
        for item in items
    ] == [1589.0, None, None]


def test_a_page_lists_the_one_episode_it_is_for(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({PLAY: play_page()}),
    )

    items = SOURCE.episodes(PLAY)

    assert [
        item.key
        for item in items
    ] == ["p0000002"]

    assert items[0].duration == 1589.0


def test_a_deeper_listing_asks_for_the_pages_it_needs(monkeypatch):
    asked: list[str] = []

    def fetch(url, session=None) -> str:

        asked.append(url)

        page = (
            int(url.split("page=")[-1])
            if "page=" in url
            else 0
        )

        return paged_brand(
            PAGE_SIZE,
            first=page * PAGE_SIZE + 1,
        )

    monkeypatch.setattr(bbc, "fetch_text", fetch)

    items = SOURCE.episodes(BRAND, limit=PAGE_SIZE + 2)

    assert len(items) == PAGE_SIZE + 2

    assert asked == [
        BRAND,
        f"{BRAND}?page=1",
    ]


def test_a_shallow_listing_reads_one_page(monkeypatch):
    asked: list[str] = []

    def fetch(url, session=None) -> str:

        asked.append(url)

        return paged_brand(PAGE_SIZE)

    monkeypatch.setattr(bbc, "fetch_text", fetch)

    assert len(SOURCE.episodes(BRAND, limit=1)) == 1

    assert asked == [BRAND]


def test_a_page_that_adds_nothing_ends_the_listing(monkeypatch):
    """
    A listing that has run out of pages must stop asking for more: the
    guard is what keeps it from asking forever.
    """

    asked: list[str] = []

    def fetch(url, session=None) -> str:

        asked.append(url)

        # every page is the same ten episodes
        return paged_brand(PAGE_SIZE)

    monkeypatch.setattr(bbc, "fetch_text", fetch)

    assert len(SOURCE.episodes(BRAND)) == PAGE_SIZE

    assert asked == [
        BRAND,
        f"{BRAND}?page=1",
    ]


def test_an_episode_resolves_to_the_mp3_its_version_is_served_as(
    monkeypatch,
):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch(
            {
                PLAY: play_page(),
                PROGRAMME: programme_json(),
            }
        ),
    )

    item = SOURCE.episodes(PLAY)[0]

    resolved = SOURCE.resolve(item)

    assert resolved.url == stream_url("v0000002")

    assert resolved.key == "p0000002"
    assert resolved.title == "The Example Episode"
    assert resolved.duration == 1589.0
    assert resolved.kind == "audio"
    assert resolved.stream is False
    assert resolved.referer == PLAY


def test_a_programme_item_plays_its_newest_episode(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch(
            {
                CATEGORY: category_page(),
                BRAND: brand_page(),
                PROGRAMME: programme_json(),
            }
        ),
    )

    item = next(
        entry
        for entry in SOURCE.episodes(CATEGORY)
        if entry.title == "Example Programme"
    )

    resolved = SOURCE.resolve(item)

    assert resolved.key == "p0000002"
    assert resolved.url == stream_url("v0000002")


def test_an_episode_bbc_offers_no_audio_for_says_so(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch(
            {
                PLAY: play_page(),
                PROGRAMME: programme_json(versions=None),
            }
        ),
    )

    item = SOURCE.episodes(PLAY)[0]

    with pytest.raises(RuntimeError) as error:
        SOURCE.resolve(item)

    assert "no playable version" in str(error.value)


def test_the_version_bbc_publishes_is_the_one_that_is_played(monkeypatch):
    """
    A schedule entry names a programme that has aired, whose first version
    is the one it aired as - and the syndication URL answers 404 for that
    one. The podcast version listed beside it is what a client is served.
    """

    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch(
            {
                PLAY: play_page(),
                PROGRAMME: programme_json("aired"),
            }
        ),
    )

    resolved = SOURCE.resolve(SOURCE.episodes(PLAY)[0])

    assert resolved.url == stream_url("v0000002")
    assert resolved.duration == 1589.0


def test_a_programme_with_one_version_plays_that_one():
    assert playable_version(
        {
            "versions": [
                {
                    "pid": "v0000003",
                    "duration": 60,
                }
            ]
        }
    ) == (
        "v0000003",
        60.0,
    )

    assert playable_version({"versions": []}) is None


def test_a_page_that_carries_no_listing_says_so(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({BRAND: "<html><body>nothing</body></html>"}),
    )

    with pytest.raises(RuntimeError) as error:
        SOURCE.episodes(BRAND)

    assert "carried no listing" in str(error.value)


def test_a_programme_names_a_feed_after_itself(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({BRAND: brand_page()}),
    )

    assert SOURCE.listing_title(BRAND) == "Example Programme"


def test_a_category_names_a_feed_after_itself(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({CATEGORY: category_page()}),
    )

    assert SOURCE.listing_title(CATEGORY) == "Example"


def test_a_schedules_page_lists_the_day_the_station_runs(monkeypatch):
    """
    A station's day is in the payload like any other listing, so reading
    it is one request for the whole running order.
    """

    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({SCHEDULES: schedules_page()}),
    )

    items = SOURCE.episodes(SCHEDULES)

    # the programme each part of the day is, in the order the day runs
    assert [
        item.title
        for item in items
    ] == [
        "Example Programme",
        "Example Segment",
    ]

    assert [
        item.key
        for item in items
    ] == [
        "p0000002",
        "p0000007",
    ]

    assert [
        item.url
        for item in items
    ] == [
        PLAY,
        "https://www.bbc.com/audio/play/p0000007",
    ]

    # the length is the slot's own, not the episode's
    assert [
        item.duration
        for item in items
    ] == [
        1800.0,
        240.0,
    ]

    assert all(
        item.kind == "audio" and item.stream is False
        for item in items
    )


def test_a_schedule_entry_plays_the_programme_it_names(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch(
            {
                SCHEDULES: schedules_page(),
                PROGRAMME: programme_json(),
            }
        ),
    )

    item = SOURCE.episodes(SCHEDULES, limit=1)[0]

    resolved = SOURCE.resolve(item)

    assert resolved.url == stream_url("v0000002")
    assert resolved.key == "p0000002"
    assert resolved.title == "The Example Episode"
    assert resolved.referer == PLAY


def test_a_schedules_page_names_a_feed_after_the_station(monkeypatch):
    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({SCHEDULES: schedules_page()}),
    )

    assert SOURCE.listing_title(SCHEDULES) == "Example Radio"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (BRAND, True),
        ("https://www.bbc.co.uk/audio/brand/p0000001", True),
        ("https://www.bbc.com/audio/series/p0000004/", True),
        ("https://www.bbc.com/audio/category/example", True),
        (SCHEDULES, True),
        ("https://www.bbc.co.uk/audio/schedules/bbc_radio_example", True),
        (PLAY, True),
        # a page that lists no audio is not this source's
        ("https://www.bbc.com/news/articles/example", False),
        ("https://www.bbc.co.uk/sounds/play/p0000002", False),
    ],
)
def test_a_page_of_the_audio_site_is_recognised(
    url: str,
    expected: bool,
):
    assert SOURCE.matches(url) is expected


def test_the_pipeline_finds_this_source_for_its_pages():
    """
    A source nothing looks up is a source that never runs: the lookup
    happens on the source objects `detect` knows about.
    """

    for url in (BRAND, CATEGORY, PLAY):

        assert sources.detect(url) is SOURCE


def test_an_episode_is_what_a_play_url_names():
    assert episode_id(PLAY) == "p0000002"
    assert episode_id(BRAND) is None
    assert episode_id(CATEGORY) is None


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ("00:26:29.000", 1589.0),
        ("00:05:00.000", 300.0),
        ("01:00:00.000", 3600.0),
        ("00:00:00.000", None),
        ("5 minutes", None),
        ("PT5M", None),
        ("", None),
    ],
)
def test_a_length_a_card_states_is_read(
    stated: str,
    expected: float | None,
):
    assert iso_seconds(stated) == expected


def test_a_listed_episode_is_not_played_before_it_is_resolved(monkeypatch):
    """
    An item of this source is a page URL, and mpv cannot play a page: the
    mp3 only comes out of the resolve. A listing that said otherwise
    would hand mpv the page and play nothing at all.
    """

    monkeypatch.setattr(
        bbc,
        "fetch_text",
        fake_fetch({BRAND: brand_page()}),
    )

    item = SOURCE.episodes(BRAND, limit=1)[0]

    assert cli.plays_while_preparing(item, playing=True) is False
