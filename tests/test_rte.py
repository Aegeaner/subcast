"""Programme and episode pages, and the per-episode cache key.

Everything here is made up: no test carries an episode RTÉ published, and
no URL that resolves to one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast.sources import rte
from subcast.sources.rte import (
    SOURCE,
    card_duration,
    episode_duration,
    episode_key,
    extract_episode_title,
    find_episode_clips,
    programme_name,
    scheduled_start,
    show_url,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "episode_page.html"
)

SHOW_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "show_page.html"
)

HERO_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "show_page_hero_only.html"
)


def episode(
    number: int,
) -> str:
    """
    A made-up episode URL of the shape the site serves.
    """

    return (
        "https://www.rte.ie/radio/radio1/example-show/episodes/"
        f"{number:08x}-0000-4000-8000-{number:012x}/"
    )


SHOW = "https://www.rte.ie/radio/radio1/example-show/"

EPISODE = episode(1)

SECOND = episode(2)

THIRD = episode(3)

# An identifier in the case a page may spell it, to prove the cache key
# comes out lower case.
UPPER = episode(0xABC).upper()


class FakeResponse:
    """
    One page, as the fetcher hands it over.
    """

    def __init__(
        self,
        text: str,
    ) -> None:

        self.text = text


def fake_http_get(
    pages: dict[str, str],
):
    """
    The page fetch, with a fixed page per URL - and a failure for any URL
    the test did not expect to be asked for.
    """

    def get(
        session,
        url,
        referer=None,
    ) -> FakeResponse:

        if url not in pages:

            raise AssertionError(
                f"fetched {url}"
            )

        return FakeResponse(
            pages[url]
        )

    return get


def test_clip_list_is_read_in_broadcast_order():
    clips = find_episode_clips(
        FIXTURE.read_text(encoding="utf-8")
    )

    assert len(clips) == 5

    assert [title for title, _ in clips] == [
        "7.10am Headlines",
        "Ferry terminal opens in Kilbride",
        "Harbour tunnel under review",
        "7.35am Weather",
        "8am News Bulletin",
    ]

    # durations arrive in milliseconds and come out in seconds
    assert clips[0] == ("7.10am Headlines", 183.0)
    assert clips[-1] == ("8am News Bulletin", 367.0)


def test_page_without_a_clip_list():
    assert find_episode_clips("<html><body>nothing</body></html>") == []


def test_reverse_ordered_list_is_put_back_into_broadcast_order():
    page = (
        "<script>"
        'var other = [{"title": "8.35am Weather",'
        ' "duration": 368000}];'
        'var clips = [{"title": "8.35am Weather",'
        ' "duration": 368000},'
        '{"title": "7.35am Weather", "duration": 341000}];'
        'var title = "Episode Clips";'
        "</script>"
    )

    assert [
        title
        for title, _ in find_episode_clips(page)
    ] == [
        "7.35am Weather",
        "8.35am Weather",
    ]


def test_cache_key_is_the_episode_uuid():
    assert episode_key(
        UPPER,
        "Example Show - 18 September 2026",
    ) == "00000abc-0000-4000-8000-000000000abc"


def test_cache_key_falls_back_to_the_title():
    assert episode_key(
        "https://www.rte.ie/radio/radio1/example-show/"
        "episodes/11812176/",
        "Example Show",
    ) == "Example_Show"


def test_a_programme_page_lists_its_episodes_newest_first(monkeypatch):
    monkeypatch.setattr(
        rte,
        "http_get",
        fake_http_get(
            {SHOW: SHOW_FIXTURE.read_text(encoding="utf-8")}
        ),
    )

    items = SOURCE.episodes(SHOW)

    assert [item.title for item in items] == [
        "Example Show - 13th September 2026",
        "Example Show - 6 September 2026",
        "Example Show - 30 August 2026",
    ]

    # the hero card links the newest episode too, and the dated card is
    # the one that names it
    assert [item.key for item in items] == [
        "00000001-0000-4000-8000-000000000001",
        "00000002-0000-4000-8000-000000000002",
        "00000003-0000-4000-8000-000000000003",
    ]

    assert [item.duration for item in items] == [
        3540.0,
        3900.0,
        3900.0,
    ]

    # the clip list RTÉ publishes beside the episodes is not episodes
    assert all(
        "/episodes/" in item.url
        for item in items
    )

    # what the programme airs, for a clip list that names a clock time
    assert [
        item.clock_start
        for item in items
    ] == [13 * 3600.0] * 3


def test_a_hero_that_is_nowhere_else_is_named_by_its_own_page(monkeypatch):
    monkeypatch.setattr(
        rte,
        "http_get",
        fake_http_get(
            {
                SHOW: HERO_FIXTURE.read_text(encoding="utf-8"),
                EPISODE: (
                    '<meta property="og:title"'
                    ' content="Example Show - 13th September 2026">'
                ),
            }
        ),
    )

    items = SOURCE.episodes(SHOW)

    assert [item.title for item in items] == [
        "Example Show - 13th September 2026",
        "Example Show - 6 September 2026",
    ]


def test_one_episode_url_is_one_item_and_no_listing_fetch(monkeypatch):
    # an empty page set: any fetch at all fails the test
    monkeypatch.setattr(
        rte,
        "http_get",
        fake_http_get({}),
    )

    items = SOURCE.episodes(EPISODE)

    assert len(items) == 1
    assert items[0].url == EPISODE
    assert items[0].key == "00000001-0000-4000-8000-000000000001"
    assert items[0].title == "Example Show"
    assert items[0].kind == "audio"


@pytest.mark.parametrize(
    "card, expected",
    [
        ("1 Hr 5 Mins", 3900.0),
        ("2 Hr 0 Mins", 7200.0),
        ("59 Mins", 3540.0),
        ("Example Show", None),
    ],
)
def test_a_card_states_its_length(card: str, expected: float | None):
    assert card_duration(card) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        (EPISODE, "Example Show"),
        (SHOW, "Example Show"),
        (
            "https://www.rte.ie/radio/radio1/another-show",
            "Another Show",
        ),
    ],
)
def test_a_programme_is_named_after_its_slug(url: str, expected: str):
    assert programme_name(url) == expected


def test_an_episode_belongs_to_its_programme_page():
    assert show_url(EPISODE) == SHOW
    assert show_url(SHOW) == SHOW
    assert show_url(SHOW.rstrip("/")) == SHOW


@pytest.mark.parametrize(
    "page, expected",
    [
        ("Mon - Fri • 07:00 - 09:00", 7 * 3600.0),
        ("Sundays • 13:00 - 14:00", 13 * 3600.0),
        ("Episode • 2 Hr 0 Mins • 18 SEP • Example Show", None),
        ("<p>no schedule here</p>", None),
    ],
)
def test_the_schedule_is_read_off_the_programme_page(
    page: str,
    expected: float | None,
):
    assert scheduled_start(page) == expected


def test_a_title_comes_from_the_page_that_names_itself():
    # the page states the name the site uses everywhere else, and the
    # headings around it say things like "Listen"
    assert extract_episode_title(
        "<h1>Listen</h1>"
        '<meta property="og:title" content="Example Show - RTÉ Radio 1">',
        "Example Show",
    ) == "Example Show"

    assert extract_episode_title(
        '<meta property="og:title"'
        ' content="Example Show - 13th September 2026">',
        "Example Show",
    ) == "Example Show - 13th September 2026"

    # a page with no page title falls back to its heading, then to what
    # it calls itself, then to what the caller knows
    assert extract_episode_title(
        "<h1>Example Show - 18 September 2026</h1>",
        "Example Show",
    ) == "Example Show - 18 September 2026"

    assert extract_episode_title(
        "<title>Example Show - RTÉ Radio 1</title>",
        "Example Show",
    ) == "Example Show"

    assert extract_episode_title(
        "<html></html>",
        "Example Show",
    ) == "Example Show"


@pytest.mark.parametrize(
    "url, expected",
    [
        (SHOW, True),
        (EPISODE, True),
        ("https://www.rte.ie/radio/radio1/", False),
        ("https://www.rte.ie/news/2026/0919/some-story/", False),
        ("https://www.youtube.com/watch?v=abc", False),
        (
            (
                "https://www.rte.ie/radio1/example-show/programmes/"
                "2019/0204/1027398-some-programme/"
            ),
            False,
        ),
    ],
)
def test_what_this_source_handles(url: str, expected: bool):
    assert SOURCE.matches(url) is expected


def test_episode_duration_is_read_as_milliseconds():
    # 7235000 is the value RTÉ serves for a 2:00:35 episode.
    page = '<meta name="duration" content="7235000"/>'

    assert episode_duration(page) == 7235.0


def test_episode_duration_is_absent_when_the_page_omits_it():
    assert episode_duration("<html><body>no duration</body></html>") is None
