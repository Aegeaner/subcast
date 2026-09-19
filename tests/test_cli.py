"""What the command line decides before anything is played."""

from __future__ import annotations

import argparse
import time
from dataclasses import replace

from subcast import cli, player
from subcast.sources import Captions, Media

PUBLISHED = (
    Captions(language="en", url="https://example.test/en.vtt"),
)


def args(
    subs: bool = False,
    subs_from: str = "auto",
    resume: bool = True,
    limit: int | None = None,
    listing: bool = False,
    pick: bool | None = None,
    search: str = "",
    feed: str = "",
    url: str = "",
) -> argparse.Namespace:
    return argparse.Namespace(
        subs=subs,
        subs_from=subs_from,
        resume=resume,
        limit=limit,
        list=listing,
        pick=pick,
        search=search,
        feed=feed,
        url=url,
    )


def media(
    captions: tuple[Captions, ...] = (),
    duration: float | None = 300.0,
    title: str = "A video",
) -> Media:
    return Media(
        source="youtube",
        key="abc",
        title=title,
        url="https://youtu.be/abc",
        duration=duration,
        captions=captions,
    )


def test_published_captions_are_used_without_being_asked_for():
    """
    A site that already times its own captions should not need a flag:
    fetching them costs a download, not a transcription.
    """

    assert cli.wants_subtitles(media(PUBLISHED), args())


def test_transcribing_needs_to_be_asked_for():
    assert not cli.wants_subtitles(media(), args())
    assert cli.wants_subtitles(media(), args(subs=True))
    assert cli.wants_subtitles(media(), args(subs_from="asr"))


def test_a_cached_transcript_is_subtitles_too(monkeypatch):
    """
    An item whose transcript is on disk needs no resolve, so nothing about
    it says it has captions - the cache is what says so.
    """

    monkeypatch.setattr(cli, "has_transcript", lambda media: False)

    assert not cli.wants_subtitles(media(), args())

    monkeypatch.setattr(cli, "has_transcript", lambda media: True)

    assert cli.wants_subtitles(media(), args())


def test_a_replay_does_not_ask_youtube_again(monkeypatch):
    """
    mpv resolves the stream URL itself, and the captions, chapters and
    length are on disk, so a cached item is played as the listing gave it.
    """

    monkeypatch.setattr(cli, "has_transcript", lambda media: True)
    monkeypatch.setattr(cli.meta, "fresh", lambda media: True)
    monkeypatch.setattr(cli.meta, "save", lambda media: None)

    class Source:
        def resolve(self, media):
            raise AssertionError("resolved an item that was already known")

    item = media()

    assert cli.resolve_item(Source(), item) is item


def test_a_replay_does_not_ask_what_a_url_points_at(monkeypatch):
    """
    A watch link and a cached transcript name everything a replay needs,
    so the listing call - the last round trip before mpv starts - goes too.
    """

    monkeypatch.setattr(cli, "has_transcript", lambda media: True)

    monkeypatch.setattr(
        cli.meta,
        "read",
        lambda source, key: cli.meta.Known(
            title="A talk",
            duration=812.5,
            resolved=time.time(),
        ),
    )

    class Source:
        name = "youtube"

        @staticmethod
        def video_id(url):
            return "abc123"

        def episodes(self, url, limit=None):
            raise AssertionError("listed a URL whose item was cached")

    item = cli.cached_item(Source(), "https://www.youtube.com/watch?v=abc123")

    assert item.key == "abc123"
    assert item.title == "A talk"
    assert item.duration == 812.5
    assert item.stream


def test_a_stale_resolve_is_listed_again(monkeypatch):
    monkeypatch.setattr(cli, "has_transcript", lambda media: True)

    monkeypatch.setattr(
        cli.meta,
        "read",
        lambda source, key: cli.meta.Known(
            title="A talk",
            duration=812.5,
            resolved=time.time() - cli.meta.RESOLVE_TTL - 1,
        ),
    )

    class Source:
        name = "youtube"

        @staticmethod
        def video_id(url):
            return "abc123"

    assert cli.cached_item(Source(), "https://youtu.be/abc123") is None


def test_a_url_that_names_no_video_is_listed(monkeypatch):
    """A playlist or channel has to be asked about: it names no one video."""

    monkeypatch.setattr(cli, "has_transcript", lambda media: True)
    monkeypatch.setattr(
        cli.meta,
        "read",
        lambda source, key: (_ for _ in ()).throw(
            AssertionError("read metadata for a listing")
        ),
    )

    class Source:
        name = "youtube"

        @staticmethod
        def video_id(url):
            return None

    assert cli.cached_item(Source(), "https://www.youtube.com/@BBCNews") is None


def test_an_item_whose_stream_url_we_must_find_is_resolved(monkeypatch):
    """
    RTÉ is stream=False: its listing URL is a page, so playback needs the
    stream URL a resolve finds, cached transcript or not.
    """

    monkeypatch.setattr(cli, "has_transcript", lambda media: True)
    monkeypatch.setattr(cli.meta, "fresh", lambda media: True)

    saved: list[str] = []
    monkeypatch.setattr(cli.meta, "save", lambda media: saved.append(media.title))

    resolved = media(title="Resolved")

    class Source:
        def resolve(self, media):
            return resolved

    item = replace(resolved, kind="audio", stream=False)

    assert cli.resolve_item(Source(), item) is resolved
    assert saved == ["Resolved"]


def test_playing_starts_where_the_item_was_left(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media: tmp_path / media.key,
    )

    player.Positions(tmp_path / "abc").update(754.0, 3600.0)

    assert cli.saved_positions(media(), args()).start == 754.0


def test_starting_over_forgets_the_position_for_this_run(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media: tmp_path / media.key,
    )

    player.Positions(tmp_path / "abc").update(754.0, 3600.0)

    assert cli.saved_positions(
        media(),
        args(resume=False),
    ).start == 0.0


def test_a_stream_of_unknown_length_is_not_remembered(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media: tmp_path / media.key,
    )

    assert cli.saved_positions(media(duration=None), args()) is None


def test_playing_fetches_what_it_will_play():
    assert cli.fetch_limit(args()) == 1
    assert cli.fetch_limit(args(limit=5)) == 5
    assert cli.fetch_limit(args(limit=0)) == 0


def test_browsing_fetches_a_page_of_the_listing():
    assert cli.fetch_limit(args(listing=True)) == cli.config.list_limit()
    assert cli.fetch_limit(args(pick=True)) == cli.config.list_limit()
    assert cli.fetch_limit(args(listing=True, limit=20)) == 20
    assert cli.fetch_limit(args(listing=True, limit=0)) == 0


def test_a_saved_feed_is_opened_for_browsing():
    """
    A feed is the listing you keep to come back to, so opening one shows
    what is in it; a URL still plays what it points at.
    """

    assert cli.browsing(args(feed="c4"))
    assert cli.browsing(args(feed="c4", pick=True))
    assert cli.browsing(args(listing=True))
    assert cli.browsing(args(pick=True))

    assert not cli.browsing(args())
    assert not cli.browsing(args(feed="c4", pick=False))
    assert not cli.browsing(args(search="morning ireland"))


def test_opening_a_feed_fetches_a_page_unless_told_otherwise():
    assert cli.fetch_limit(args(feed="c4")) == cli.config.list_limit()
    assert cli.fetch_limit(args(feed="c4", limit=3)) == 3
    assert cli.fetch_limit(args(feed="c4", limit=0)) == 0

    # --no-pick plays straight through, so only what it plays is fetched
    assert cli.fetch_limit(args(feed="c4", pick=False)) == 1


def test_a_search_asks_youtube_for_as_much_as_the_run_uses():
    source, url, description = cli.resolve_target(
        args(search="morning ireland", pick=True)
    )

    assert source.name == "youtube"
    assert url == f"ytsearch{cli.config.list_limit()}:morning ireland"
    assert description == 'search "morning ireland"'

    # playback alone needs the top hit, not the whole page
    _, url, _ = cli.resolve_target(
        args(search="morning ireland")
    )

    assert url == "ytsearch1:morning ireland"

    _, url, _ = cli.resolve_target(
        args(search="news", limit=50)
    )

    assert url == "ytsearch50:news"


def test_a_feed_plays_the_url_it_saved(monkeypatch):
    monkeypatch.setattr(
        cli.feeds,
        "find",
        lambda name: cli.feeds.Feed(
            name=name,
            url="https://www.youtube.com/@SkyNews",
        ),
    )

    target = cli.resolve_target(args(feed="sky"))

    assert target.url == "https://www.youtube.com/@SkyNews"
    assert target.description.startswith("sky: ")
