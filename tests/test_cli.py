"""What the command line decides before anything is played."""

from __future__ import annotations

import argparse
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from subcast import cli, config, player
from subcast.sources import Captions, Media, rte

PUBLISHED = (
    Captions(language="en", url="https://example.test/en.vtt"),
)

PREPARED = cli.Prepared(
    srt_path=Path("/tmp/example.srt"),
    chapters_path=None,
    cues=[],
    segments=[],
)


class Source:
    """A source whose resolve is whatever the test says it is."""

    name = "youtube"

    def resolve(self, media):
        return media


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
        audio_only=False,
        quality=1080,
        subs_style="auto",
        subs_scale="auto",
        whisper_model="small.en",
        whisper_device="auto",
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
            formats=[],
            expires=0.0,
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
            formats=[],
            expires=0.0,
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

    resolved = media(title="Resolved")

    class Source:
        def resolve(self, media):
            return resolved

    item = replace(resolved, kind="audio", stream=False)

    # the resolve is what writes down what it learned, so this must happen
    assert cli.resolve_item(Source(), item) is resolved


def test_a_source_mpv_resolves_plays_before_being_prepared():
    """
    A YouTube page URL is mpv's to resolve, so the run does not wait for
    subcast's own resolve and transcript. RTÉ is the other way round: its
    stream URL only comes out of the resolve.
    """

    assert cli.plays_while_preparing(media(), playing=True)
    assert cli.plays_while_preparing(media(), playing=False) is False

    audio = replace(media(), kind="audio", stream=False)

    assert cli.plays_while_preparing(audio, playing=True) is False


def test_a_listed_rte_episode_is_not_played_before_it_is_resolved():
    """
    An RTÉ item's URL is a page, and mpv cannot play a page: the stream
    URL only comes out of the resolve. A listing that forgot to say so
    would hand mpv the page and play nothing at all.
    """

    item = rte.SOURCE.episodes(
        "https://www.rte.ie/radio/radio1/example-show/"
        "episodes/00000001-0000-4000-8000-000000000001/"
    )[0]

    assert cli.plays_while_preparing(item, playing=True) is False


def test_the_preparation_runs_beside_playback(monkeypatch):
    release = threading.Event()
    resolved: list[str] = []

    def resolve(source, item):
        resolved.append(item.key)
        return item

    def prepare(media, args, saved):
        release.wait(timeout=5)
        return PREPARED

    monkeypatch.setattr(cli, "resolve_item", resolve)
    monkeypatch.setattr(cli, "prepare_item", prepare)
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: True)

    job = cli.start_preparation(Source(), media(), args(), None)

    # nothing is waited for: not the resolve, not the transcript
    assert job.done_yet() is False

    release.set()

    assert job.wait() is PREPARED
    assert resolved == ["abc"]


def test_no_subtitles_wanted_means_no_preparation(monkeypatch):
    monkeypatch.setattr(cli, "resolve_item", lambda source, item: item)
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: False)
    monkeypatch.setattr(
        cli,
        "prepare_item",
        lambda media, args, saved: pytest.fail("prepared anyway"),
    )

    assert cli.start_preparation(Source(), media(), args(), None).wait() is None
    assert cli.ready_subtitles(media(), args(), None) is None


def test_an_item_that_must_be_resolved_is_ready_before_playback(monkeypatch):
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: True)
    monkeypatch.setattr(
        cli,
        "prepare_item",
        lambda media, args, saved: PREPARED,
    )

    job = cli.ready_subtitles(media(), args(), None)

    assert job is not None
    assert job.done_yet() is True
    assert job.wait() is PREPARED


def test_a_captioned_episode_plays_the_audio_it_transcribed(
    monkeypatch,
    tmp_path,
):
    """
    RTÉ stitches ads into an episode per request - one URL answered with two
    different files a second apart - so the audio a run transcribed and the
    audio mpv would stream are not the same, and captions timed against one
    cannot be in pace with the other. What plays is the file they were timed
    against.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)

    key = "098de349-266a-49e1-bdd3-b4c40107e6c4"

    audio = tmp_path / "rte" / f"{key}.mp3"

    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    played: list[str] = []

    monkeypatch.setattr(
        cli,
        "play_with_mpv",
        lambda url, *rest, **kwargs: played.append(url) or 0,
    )

    item = rte.SOURCE.episodes(
        "https://www.rte.ie/radio/radio1/example-show/"
        f"episodes/{key}/"
    )[0]

    assert cli.play_item(
        rte.SOURCE,
        item,
        replace(item, duration=3593.0),
        args(),
        cli.PendingSubtitles.finished(PREPARED),
    ) == 0

    assert played == [str(audio)]


def test_an_episode_nobody_captions_is_streamed(monkeypatch, tmp_path):
    """
    A plain play downloads nothing and streams, whatever is in the cache:
    there are no captions to be in pace with.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)

    key = "098de349-266a-49e1-bdd3-b4c40107e6c4"

    audio = tmp_path / "rte" / f"{key}.mp3"

    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    played: list[str] = []

    monkeypatch.setattr(
        cli,
        "play_with_mpv",
        lambda url, *rest, **kwargs: played.append(url) or 0,
    )

    item = rte.SOURCE.episodes(
        "https://www.rte.ie/radio/radio1/example-show/"
        f"episodes/{key}/"
    )[0]

    media = replace(
        item,
        url="https://example.test/audio.mp3",
        duration=3593.0,
    )

    assert cli.play_item(
        rte.SOURCE,
        item,
        media,
        args(),
        None,
    ) == 0

    assert played == ["https://example.test/audio.mp3"]


def test_the_next_item_is_prepared_while_this_one_plays(monkeypatch):
    """
    A feed or a playlist is watched one item after another, so the run
    gets the following item ready during the current one - but not both at
    once: the next preparation waits for this one's.
    """

    current_done = threading.Event()
    order: list[str] = []

    def resolve(source, item):
        order.append(item.key)
        return item

    def prepare(media, args, saved):
        if media.key == "abc":
            current_done.wait(timeout=5)
        return PREPARED

    monkeypatch.setattr(cli, "resolve_item", resolve)
    monkeypatch.setattr(cli, "prepare_item", prepare)
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: True)

    current = cli.start_preparation(Source(), media(), args(), None)

    following = replace(media(), key="def", title="The next one")
    next_job = cli.start_preparation(
        Source(),
        following,
        args(),
        None,
        after=current,
    )

    # the next item has not started asking: this one has not finished
    assert next_job.done_yet() is False

    current_done.set()

    assert next_job.wait() is PREPARED
    assert order == ["abc", "def"]


def test_a_listing_is_played_item_after_item(monkeypatch):
    """
    The whole loop, because this is where the pieces are joined: both
    items play in turn, and the second one's preparation is already going
    when the first one starts - which a feed or a playlist is for.
    """
    import argparse as argparse_module

    first = replace(media(), key="one", title="The first")
    second = replace(media(), key="two", title="The second")
    order: list[str] = []

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: argparse_module.Namespace(
            url="https://www.youtube.com/@The_RHS",
            list=False,
            limit=2,
            feed="rhs",
            search="",
            feeds=False,
            add_feed=False,
            name="",
            remove_feed="",
            pick=False,
            save=False,
            no_play=False,
            audio_only=False,
            quality=1080,
            subs=False,
            subs_from="auto",
            whisper_model="small.en",
            whisper_device="auto",
            subs_scale="auto",
            subs_style="auto",
            resume=True,
        ),
    )
    monkeypatch.setattr(
        cli,
        "resolve_target",
        lambda args: cli.Target(Source(), "rhs", "rhs"),
    )
    monkeypatch.setattr(cli, "collect", lambda source, url, limit: [first, second])
    monkeypatch.setattr(cli, "resolve_item", lambda source, item: item)
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: True)

    def prepare(media, args, saved):
        order.append(f"prepared {media.key}")
        return PREPARED

    monkeypatch.setattr(cli, "prepare_item", prepare)
    monkeypatch.setattr(cli, "saved_positions", lambda media, args: None)
    monkeypatch.setattr(cli, "chapters_for", lambda media: None)

    def play(source, item, media, args, subtitles):
        assert subtitles.wait() is PREPARED
        order.append(f"played {media.key}")
        return 0

    monkeypatch.setattr(cli, "play_item", play)

    assert cli.main() == 0
    assert order == [
        "prepared one",
        "prepared two",
        "played one",
        "played two",
    ]


def test_a_cached_listing_opens_the_menu_and_refreshes_behind_it(
    monkeypatch,
):
    """
    A channel listing takes tens of seconds; the menu shows what last
    time's fetch returned and asks again while the user is reading.
    """

    cached = [replace(media(), key="old", title="Last time's newest")]
    fetched: list[int] = []

    monkeypatch.setattr(
        cli.listing,
        "read",
        lambda source, url: cli.listing.Cached(
            url=url,
            fetched=time.time(),
            limit=30,
            items=cached,
        ),
    )
    monkeypatch.setattr(
        cli.listing,
        "save",
        lambda source, url, limit, items: fetched.append(limit),
    )

    class Source:
        name = "youtube"

        @staticmethod
        def video_id(url):
            return None

        def episodes(self, url, limit=None):
            fetched.append(limit)
            return [replace(media(), key="new", title="Today's newest")]

    source = Source()
    items, again = cli.menu_entries(
        source,
        "https://youtube.com/@BBCNews",
        args(pick=True),
    )

    assert [item.key for item in items] == ["old"]
    assert again is not None

    job = again()
    job.start()

    assert [item.key for item in job.wait()] == ["new"]
    assert fetched == [30, 30]


def test_playing_a_listing_fetches_it_now(monkeypatch):
    """
    The menu can show what it has; a run that is going to play something
    asks the source, because what is newest is the point of it.
    """

    monkeypatch.setattr(
        cli.listing,
        "read",
        lambda source, url: pytest.fail("read the cache for playback"),
    )
    monkeypatch.setattr(
        cli.listing,
        "save",
        lambda source, url, limit, items: None,
    )

    class Source:
        name = "youtube"

        @staticmethod
        def video_id(url):
            return None

        def episodes(self, url, limit=None):
            return [replace(media(), key="new", title="Today's newest")]

    items, again = cli.menu_entries(
        Source(),
        "https://youtube.com/@BBCNews",
        args(pick=False, limit=1),
    )

    assert [item.key for item in items] == ["new"]
    assert again is None


def test_chapters_come_from_what_a_previous_run_left(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media: tmp_path / media.key,
    )

    assert cli.chapters_for(media()) is None

    chapters = tmp_path / "abc.chapters.txt"
    chapters.write_text(";FFMETADATA1\n")

    assert cli.chapters_for(media()) == chapters


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


def test_a_broadcast_is_only_captioned_when_asked_for_transcription():
    """
    The captions a broadcast publishes are a playlist that grows for as
    long as it airs, which the caption fetch cannot read - so a live item
    has subtitles only when this run asked for them, and
    `--subs-from published` asked for the opposite.
    """

    live_item = replace(
        media(captions=PUBLISHED),
        live=True,
    )

    assert cli.wants_subtitles(live_item, args()) is False
    assert cli.wants_subtitles(live_item, args(subs=True)) is True
    assert cli.wants_subtitles(live_item, args(subs_from="asr")) is True
    assert cli.wants_subtitles(live_item, args(subs=True, subs_from="published")) is False


def test_a_broadcast_is_prepared_as_a_job_rather_than_a_file(
    tmp_path: Path,
    monkeypatch,
):
    """
    There is no transcript to write for a broadcast: what the run gets
    back is the job that keeps making captions while it plays, writing
    them where a finished video's transcript could never be mistaken for
    them.
    """

    from subcast import config
    from subcast.live import LiveCaptions

    monkeypatch.setattr(cli, "load_model", lambda name, device: None)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")

    live_item = replace(
        media(captions=()),
        live=True,
    )

    job = cli.prepare_item(live_item, args(subs=True), None)

    assert isinstance(job, LiveCaptions)
    assert job.srt_path.name == "abc.live.srt"
    assert job.srt_path.parent == tmp_path / "cache" / "youtube"


@pytest.mark.parametrize("flag", ["save", "no_play"])
def test_a_broadcast_is_neither_saved_nor_prepared_without_playback(
    flag: str,
    monkeypatch,
    capsys,
):
    """
    Saving would record until the broadcast ends, and captions come from
    playing it - so both are refused with a line rather than started.
    """

    import argparse as argparse_module

    live_item = replace(media(), live=True)

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: argparse_module.Namespace(
            url="https://www.youtube.com/watch?v=abc",
            list=False,
            limit=None,
            feed="",
            search="",
            feeds=False,
            add_feed=False,
            name="",
            remove_feed="",
            pick=False,
            save=flag == "save",
            no_play=flag == "no_play",
            audio_only=False,
            quality=1080,
            subs=True,
            subs_from="auto",
            whisper_model="small.en",
            whisper_device="auto",
            subs_scale="auto",
            subs_style="auto",
            resume=True,
        ),
    )
    monkeypatch.setattr(
        cli,
        "resolve_target",
        lambda args: cli.Target(Source(), "abc", "abc"),
    )
    monkeypatch.setattr(cli, "collect", lambda source, url, limit: [live_item])
    monkeypatch.setattr(cli, "resolve_item", lambda source, item: item)
    monkeypatch.setattr(
        cli,
        "prepare_item",
        lambda media, args, saved: pytest.fail("prepared a broadcast anyway"),
    )
    monkeypatch.setattr(
        cli,
        "play_item",
        lambda *args: pytest.fail("played a broadcast anyway"),
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    if flag == "save":

        assert "cannot be saved while it airs" in output

    else:

        assert "--no-play leaves nothing to do" in output


def test_a_stop_signal_ends_the_run_the_way_ctrl_c_does(monkeypatch):
    """
    A run owns a broadcast's capture, and the capture is its own process
    group: dying on a signal would leave yt-dlp and ffmpeg reading a
    broadcast that nothing is watching. SIGTERM and SIGHUP are turned into
    what Ctrl-C raises, so the run's own teardown happens - which is what
    stops the capture and removes its chunks.
    """

    installed: dict[int, object] = {}

    monkeypatch.setattr(
        cli.signal,
        "signal",
        lambda number, handler: installed.__setitem__(number, handler),
    )

    cli.stop_signals()

    assert set(installed) == {
        cli.signal.SIGTERM,
        cli.signal.SIGHUP,
    }

    with pytest.raises(KeyboardInterrupt):

        installed[cli.signal.SIGTERM](cli.signal.SIGTERM, None)
