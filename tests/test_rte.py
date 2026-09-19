"""Episode page parsing and the per-episode cache key."""

from __future__ import annotations

from pathlib import Path

from subcast.rte import episode_key, find_episode_clips


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "episode_page.html"
)

UUID_URL = (
    "https://www.rte.ie/radio/radio1/morning-ireland/"
    "episodes/3b5345aa-D0E1-4e5a-9cb1-b4c900a4d056/"
)


def test_clip_list_is_read_in_broadcast_order():
    clips = find_episode_clips(
        FIXTURE.read_text(encoding="utf-8")
    )

    assert len(clips) == 5

    assert [title for title, _ in clips] == [
        "7.10am It Says in the Papers",
        "Taoiseach to meet Burnham",
        "EU propose under-18's chatbot ban",
        "7.35am Sports News",
        "8am News Bulletin",
    ]

    # durations arrive in milliseconds and come out in seconds
    assert clips[0] == ("7.10am It Says in the Papers", 183.0)
    assert clips[-1] == ("8am News Bulletin", 367.0)


def test_page_without_a_clip_list():
    assert find_episode_clips("<html><body>nothing</body></html>") == []


def test_reverse_ordered_list_is_put_back_into_broadcast_order():
    page = (
        "<script>"
        'var other = [{"title": "8.35am Sports News",'
        ' "duration": 368000}];'
        'var clips = [{"title": "8.35am Sports News",'
        ' "duration": 368000},'
        '{"title": "7.35am Sports News", "duration": 341000}];'
        'var title = "Episode Clips";'
        "</script>"
    )

    assert [
        title
        for title, _ in find_episode_clips(page)
    ] == [
        "7.35am Sports News",
        "8.35am Sports News",
    ]


def test_cache_key_is_the_episode_uuid():
    assert episode_key(
        UUID_URL,
        "Morning Ireland - 18 September 2026",
    ) == "3b5345aa-d0e1-4e5a-9cb1-b4c900a4d056"


def test_cache_key_falls_back_to_the_title():
    assert episode_key(
        "https://www.rte.ie/radio/radio1/morning-ireland/"
        "episodes/11812176/",
        "Morning Ireland",
    ) == "Morning_Ireland"
