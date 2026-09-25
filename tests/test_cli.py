"""What the command line decides before anything is played."""

from __future__ import annotations

import argparse
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from subcast import background, cli, config, player
from subcast.media import Ranged
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
    osc: str = "always",
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
        osc=osc,
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


def in_config_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """
    Feeds live in the user's config directory, and a first run writes one:
    keep every run in the tests out of it.
    """

    monkeypatch.setattr(
        cli.config,
        "CONFIG_DIR",
        tmp_path,
    )


def in_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """
    A run sweeps the cache before it reads any of it: a test that runs one
    must not sweep the developer's own cache.
    """

    monkeypatch.setattr(
        config,
        "CACHE_DIR",
        tmp_path / "cache",
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

    def prepare(media, args, saved, playing=False):
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
        lambda media, args, saved, playing=False: pytest.fail("prepared anyway"),
    )

    assert cli.start_preparation(Source(), media(), args(), None).wait() is None
    assert cli.ready_subtitles(media(), args(), None) is None


def test_an_item_already_resolved_is_only_transcribed_beside_playback(
    monkeypatch,
):
    """
    A stream that comes out of a resolve had to be found before playback,
    but the transcript did not have to: it is made while the item plays and
    attached when it lands. The resolve is not asked for a second time.
    """

    monkeypatch.setattr(
        cli,
        "resolve_item",
        lambda source, item: pytest.fail("resolved twice"),
    )
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: True)
    monkeypatch.setattr(
        cli,
        "prepare_item",
        lambda media, args, saved, playing=False: PREPARED,
    )

    resolved = replace(
        media(),
        url="https://example.test/audio.mp3",
        stream=False,
    )

    job = cli.start_preparation(
        Source(),
        media(),
        args(),
        None,
        media=resolved,
    )

    assert job.wait() is PREPARED


def test_the_audio_a_transcript_is_made_from_is_fetched_once(
    monkeypatch,
    tmp_path,
):
    """
    The audio is what the captions are timed against, so it is here before
    the first frame - and only what a transcript needs is fetched: a site
    that publishes captions is not heard from a download, and a transcript
    already on disk is not heard again.
    """

    fetched: list[str] = []

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cli, "has_transcript", lambda media: False)
    monkeypatch.setattr(
        cli,
        "acquire",
        lambda media, stem: (
            fetched.append(media.key) or Path("/tmp/audio.mp3")
        ),
    )

    item = media()

    assert cli.captions_audio(
        item,
        args(subs=True),
        None,
    ) == Path("/tmp/audio.mp3")

    # a file --save wrote is the audio, and needs no fetching
    assert cli.captions_audio(
        item,
        args(subs=True),
        Path("/tmp/saved.mp3"),
    ) == Path("/tmp/saved.mp3")

    assert cli.captions_audio(
        media(PUBLISHED),
        args(),
        None,
    ) is None

    monkeypatch.setattr(cli, "has_transcript", lambda media: True)

    assert cli.captions_audio(item, args(subs=True), None) is None

    # and audio a previous run left in the cache is not fetched again
    monkeypatch.setattr(cli, "has_transcript", lambda media: False)

    cached = tmp_path / media().source / f"{item.key}.mp3"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"audio")

    assert cli.captions_audio(item, args(subs=True), None) == cached
    assert fetched == ["abc"]


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


def test_the_player_is_given_the_items_own_name(monkeypatch, tmp_path):
    """
    The item mpv is handed is a URL - a page, or the signed stream URL a
    resolve found - so a window titled by mpv alone says the wrong thing.
    What the run plays is named to it.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)

    audio = args()
    audio.audio_only = True

    named: list[str] = []

    monkeypatch.setattr(
        cli,
        "play_window",
        lambda url, *rest, **kwargs: named.append(kwargs["title"]) or 0,
    )
    monkeypatch.setattr(
        cli,
        "play_with_mpv",
        lambda url, *rest, **kwargs: named.append(kwargs["title"]) or 0,
    )

    item = replace(media(), title="The Morning After")

    assert cli.play_item(Source(), item, item, args(), None) == 0
    assert cli.play_item(Source(), item, item, audio, None) == 0

    assert named == [
        "The Morning After",
        "The Morning After",
    ]


def test_the_window_is_told_what_the_controller_does(
    monkeypatch,
    tmp_path,
):
    """
    Whether mpv's on-screen controller stays up is the user's to decide,
    and it is the run that carries the decision to the player. An item
    played in the terminal has no window and no controller to ask about.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)

    asked: list[str] = []

    monkeypatch.setattr(
        cli,
        "play_window",
        lambda url, *rest, **kwargs: asked.append(kwargs["osc"]) or 0,
    )
    monkeypatch.setattr(
        cli,
        "play_with_mpv",
        lambda url, *rest, **kwargs: pytest.fail(
            "the terminal has no controller"
        ),
    )

    item = media()

    assert cli.play_item(Source(), item, item, args(), None) == 0
    assert (
        cli.play_item(
            Source(),
            item,
            item,
            args(osc="never"),
            None,
        )
        == 0
    )

    assert asked == ["always", "never"]


def test_caching_an_item_says_what_landed(monkeypatch, tmp_path, capsys):
    """
    The two lines a caching answers with: the file the cache holds, and the
    subtitles made from it.
    """

    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media_item: tmp_path / media_item.key,
    )
    monkeypatch.setattr(
        cli,
        "acquire",
        lambda media_item, stem: tmp_path / "abc.mp3",
    )
    monkeypatch.setattr(
        cli,
        "prepare",
        lambda media_item, audio, model, device, subs_from: PREPARED,
    )

    cli.cache_item(media(), args())

    printed = capsys.readouterr().out

    assert f"Cached: {tmp_path / 'abc.mp3'}" in printed
    assert f"Subtitles ready: {PREPARED.srt_path}" in printed


def test_a_broadcast_is_not_cached(capsys):
    """
    A broadcast has no finished audio to keep: its captions only exist
    while it plays, and there is nothing else to put in the cache.
    """

    cli.cache_item(replace(media(), live=True), args())

    assert (
        "cannot be cached while it airs"
        in capsys.readouterr().out
    )


def test_the_player_is_given_a_key_that_caches_the_item(
    monkeypatch,
    tmp_path,
):
    """
    Playback carries what the `d` key does - an ask of the run's queue, the
    same one a marked entry goes into - and the queue's lines, for the
    player to say between redraws. A broadcast is the exception: it has
    nothing to cache, so it gets the lines but no key.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)

    asked: list[player.CacheWork | None] = []

    monkeypatch.setattr(
        cli,
        "play_window",
        lambda url, *rest, **kwargs: asked.append(kwargs["cache"]) or 0,
    )

    caching = cli.Caching()
    item = media()

    assert cli.play_item(Source(), item, item, args(), None, caching) == 0
    assert callable(asked[0].press)
    assert callable(asked[0].notes)

    live = replace(media(), live=True)

    assert cli.play_item(Source(), live, live, args(), None, caching) == 0
    assert asked[1].press is None
    assert callable(asked[1].notes)


def test_the_cache_key_queues_the_item_and_says_what_became_of_it(
    monkeypatch,
    capsys,
):
    """
    The key is a request rather than a second copy of the work: pressing it
    queues the item behind whatever is already being kept, and pressing it
    again says where that item stands instead of queueing it twice - two
    jobs for one item would be two writers of the same cache files.
    """

    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    def cache(media_item, args):
        started.set()
        release.wait(timeout=5)
        finished.set()

    monkeypatch.setattr(cli, "cache_item", cache)

    caching = cli.Caching()
    item = media(title="An episode")

    cli.cache_ask(caching, item, args())

    assert started.wait(timeout=5)
    assert not finished.is_set()
    assert "Caching: An episode" in capsys.readouterr().out

    cli.cache_ask(caching, item, args())

    assert (
        "This item is being cached already."
        in capsys.readouterr().out
    )

    release.set()

    assert finished.wait(timeout=5)

    caching.wait(5)
    caching.take_notes()

    cli.cache_ask(caching, item, args())

    assert "This item is cached already." in capsys.readouterr().out


def test_a_caching_that_goes_wrong_is_reported_and_the_queue_goes_on(
    monkeypatch,
):
    """
    One item that will not come down is one item: the failure is a line for
    whoever owns the screen, and the next item is still waiting its turn.
    """

    def explode(media_item, args):
        raise RuntimeError("no link to the audio")

    monkeypatch.setattr(cli, "cache_item", explode)

    caching = cli.Caching()

    first = replace(media(), key="one")
    second = replace(media(), key="two")

    cli.cache_ask(caching, first, args())
    cli.cache_ask(caching, second, args())

    caching.wait(5)

    said = caching.take_notes()

    assert said == [
        "    Caching failed: no link to the audio",
        "    Caching failed: no link to the audio",
    ]

    assert caching.done_yet()


def test_a_marked_entry_is_cached_and_not_played(monkeypatch, tmp_path):
    """
    A listing choice with a `d` after it asks for the entry to be kept
    rather than watched: the run caches it, waits for it to land so its
    lines can be said, and opens no player - which is what downloading an
    episode to listen to later means.
    """

    in_config_dir(monkeypatch, tmp_path)
    in_cache(monkeypatch, tmp_path)

    item = replace(media(), key="one", title="The first")

    monkeypatch.setattr(
        cli,
        "resolve_target",
        lambda args: cli.Target(Source(), "rhs", "rhs"),
    )
    monkeypatch.setattr(
        cli,
        "menu_entries",
        lambda source, url, args: ([item], None),
    )
    monkeypatch.setattr(
        cli.picker,
        "choose",
        lambda items, again: [(item, True)],
    )
    monkeypatch.setattr(
        cli,
        "resolve_item",
        lambda source, chosen: chosen,
    )

    cached: list[str] = []

    monkeypatch.setattr(
        cli,
        "cache_item",
        lambda chosen, args: cached.append(chosen.key),
    )
    monkeypatch.setattr(
        cli,
        "play_item",
        lambda *arguments: pytest.fail("played a download"),
    )

    assert cli.run_once(cli.parse_args(["--feed", "rhs"])) == 0
    assert cached == ["one"]


def test_a_shells_run_leaves_what_it_asked_to_keep_to_the_shell(
    monkeypatch,
    tmp_path,
):
    """
    A shell command's item outlives the command: the run does not wait for
    it, so the prompt comes back while the download is still going, and the
    shell is what says the lines when they land.
    """

    in_config_dir(monkeypatch, tmp_path)
    in_cache(monkeypatch, tmp_path)

    item = replace(media(), key="one", title="The first")

    monkeypatch.setattr(
        cli,
        "resolve_target",
        lambda args: cli.Target(Source(), "rhs", "rhs"),
    )
    monkeypatch.setattr(
        cli,
        "menu_entries",
        lambda source, url, args: ([item], None),
    )
    monkeypatch.setattr(
        cli.picker,
        "choose",
        lambda items, again: [(item, True)],
    )
    monkeypatch.setattr(
        cli,
        "resolve_item",
        lambda source, chosen: chosen,
    )

    release = threading.Event()
    finished = threading.Event()

    def cache(chosen, args):
        release.wait(timeout=5)
        finished.set()
        background.say("    Cached: (test)")

    monkeypatch.setattr(cli, "cache_item", cache)
    monkeypatch.setattr(
        cli,
        "play_item",
        lambda *arguments: pytest.fail("played a download"),
    )

    jobs = cli.Caching()

    assert (
        cli.run_once(
            cli.parse_args(["--feed", "rhs"]),
            jobs,
            wait_for_caching=False,
        )
        == 0
    )

    # the run is over and the item is still being kept
    assert not finished.is_set()
    assert not jobs.done_yet()

    release.set()

    assert finished.wait(timeout=5)
    jobs.wait(5)

    assert jobs.take_notes() == ["    Cached: (test)"]


def test_a_marked_entry_is_kept_beside_what_plays(
    monkeypatch,
    tmp_path,
    capsys,
):
    """
    The mark belongs to the entry, not to the answer, and the keeping
    happens beside the playback: `2d,1` plays the first while the second is
    downloaded, rather than after it. The job is held open until the play
    is over, so a run that waited for the download would never finish, and
    the line it said while the player was running is printed once the
    player has gone.
    """

    in_config_dir(monkeypatch, tmp_path)
    in_cache(monkeypatch, tmp_path)

    first = replace(media(), key="one", title="The first")
    second = replace(media(), key="two", title="The second")

    monkeypatch.setattr(
        cli,
        "resolve_target",
        lambda args: cli.Target(Source(), "rhs", "rhs"),
    )
    monkeypatch.setattr(
        cli,
        "menu_entries",
        lambda source, url, args: ([first, second], None),
    )
    monkeypatch.setattr(
        cli.picker,
        "choose",
        lambda items, again: [(first, False), (second, True)],
    )
    monkeypatch.setattr(
        cli,
        "resolve_item",
        lambda source, chosen: chosen,
    )
    monkeypatch.setattr(
        cli,
        "wants_subtitles",
        lambda media_item, args: False,
    )
    monkeypatch.setattr(cli, "saved_positions", lambda media_item, args: None)
    monkeypatch.setattr(cli, "chapters_for", lambda media_item: None)

    played = threading.Event()
    order: list[str] = []

    def cache(chosen, args):
        # Only a play that went by while this was going lets it finish.
        assert played.wait(timeout=5)
        order.append(f"cached {chosen.key}")
        background.say("    Cached: (test)")

    monkeypatch.setattr(cli, "cache_item", cache)

    def play(source, item, media_item, args, subtitles, caching=None):
        order.append(f"played {media_item.key}")
        played.set()
        return 0

    monkeypatch.setattr(cli, "play_item", play)

    assert cli.run_once(cli.parse_args(["--feed", "rhs"])) == 0
    assert order == ["played one", "cached two"]
    assert "    Cached: (test)" in capsys.readouterr().out


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

    def prepare(media, args, saved, playing=False):
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


def test_a_listing_is_played_item_after_item(monkeypatch, tmp_path: Path):
    """
    The whole loop, because this is where the pieces are joined: both
    items play in turn, and the second one's preparation is already going
    when the first one starts - which a feed or a playlist is for.
    """
    import argparse as argparse_module

    in_config_dir(monkeypatch, tmp_path)
    in_cache(monkeypatch, tmp_path)

    first = replace(media(), key="one", title="The first")
    second = replace(media(), key="two", title="The second")
    order: list[str] = []

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda argv=None: argparse_module.Namespace(
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
            osc="always",
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

    def prepare(media, args, saved, playing=False):
        order.append(f"prepared {media.key}")
        return PREPARED

    monkeypatch.setattr(cli, "prepare_item", prepare)
    monkeypatch.setattr(cli, "saved_positions", lambda media, args: None)
    monkeypatch.setattr(cli, "chapters_for", lambda media: None)

    def play(source, item, media, args, subtitles, caching=None):
        assert subtitles.wait() is PREPARED
        order.append(f"played {media.key}")
        return 0

    monkeypatch.setattr(cli, "play_item", play)

    assert cli.main(["--feed", "rhs"]) == 0
    assert order == [
        "prepared one",
        "prepared two",
        "played one",
        "played two",
    ]


def test_the_fetch_says_what_it_is_fetching(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    """
    The download is the wait a captioned item has, so the run says what it
    is fetching - how long the audio is - before it settles in to wait.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        cli,
        "acquire",
        lambda media_item, stem: tmp_path / "audio.mp3",
    )

    cli.captions_audio(media(), args(subs=True), None)

    assert (
        "Fetching the audio to transcribe: 5:00."
        in capsys.readouterr().out
    )


def test_a_stable_stream_is_heard_while_it_plays(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    """
    Two probes agreeing - the same length, the same opening bytes - are what
    lets the model hear the bytes the player is reading, so the first frame
    does not wait for the whole item to be downloaded.
    """

    in_config_dir(monkeypatch, tmp_path)

    ranged = Ranged(
        length=1000,
        opening=b"x" * 16,
        extension=".mp3",
    )

    monkeypatch.setattr(cli, "range_probe", lambda url, headers: ranged)
    monkeypatch.setattr(
        cli,
        "hears_the_audio",
        lambda media_item, args: True,
    )

    hearing = cli.streamed_captions(media(), args(subs=True), None)

    assert isinstance(hearing, cli.StreamedWhilePlaying)
    assert "heard from the stream" in capsys.readouterr().out


def test_a_url_that_answers_differently_is_downloaded_instead(
    monkeypatch,
    tmp_path: Path,
):
    """
    An ad stitched into one request makes the two copies of an item
    different, and captions timed against one of them cannot be in pace with
    the other: such an item is downloaded whole first, which is what every
    captioned run did before there was a stream to hear.
    """

    in_config_dir(monkeypatch, tmp_path)

    answers = iter(
        [
            Ranged(length=1000, opening=b"x" * 16, extension=".mp3"),
            Ranged(length=2000, opening=b"y" * 16, extension=".mp3"),
        ]
    )

    monkeypatch.setattr(
        cli,
        "range_probe",
        lambda url, headers: next(answers),
    )
    monkeypatch.setattr(
        cli,
        "hears_the_audio",
        lambda media_item, args: True,
    )

    assert cli.streamed_captions(media(), args(subs=True), None) is None


def test_a_server_that_will_not_serve_ranges_is_downloaded(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    monkeypatch.setattr(cli, "range_probe", lambda url, headers: None)
    monkeypatch.setattr(
        cli,
        "hears_the_audio",
        lambda media_item, args: True,
    )

    assert cli.streamed_captions(media(), args(subs=True), None) is None


def test_an_item_already_on_disk_is_not_fetched_again(
    monkeypatch,
    tmp_path: Path,
):
    """
    A run that has just written the audio - `--save` - hears that file: the
    bytes it plays are the bytes it has.
    """

    in_config_dir(monkeypatch, tmp_path)

    monkeypatch.setattr(
        cli,
        "range_probe",
        lambda url, headers: pytest.fail("probed an item already on disk"),
    )

    assert (
        cli.streamed_captions(
            media(),
            args(subs=True),
            tmp_path / "saved.mp3",
        )
        is None
    )


def test_captions_heard_from_the_stream_play_the_stream(
    monkeypatch,
    tmp_path: Path,
):
    """
    The copy that is heard is the copy that plays: an item whose captions
    are coming off the stream plays the stream rather than a file, which is
    what lets the first frame be seconds away.
    """

    in_config_dir(monkeypatch, tmp_path)

    item = replace(
        media(),
        kind="audio",
        stream=False,
        url="https://example.test/one.mp3",
    )

    hearing = cli.StreamedWhilePlaying(
        item,
        item.url,
        Ranged(length=1000, opening=b"x" * 16, extension=".mp3"),
        {},
        tmp_path / "rte" / "one",
        "small.en",
        "auto",
    )

    assert cli.playback_url(
        item,
        cli.PendingSubtitles.finished(hearing),
    ) == "https://example.test/one.mp3"


def test_an_item_must_be_resolved_and_heard_from_the_same_audio(
    monkeypatch,
    tmp_path: Path,
):
    """
    The whole loop for a source mpv cannot play a page of, because this is
    where the pieces join: the resolve and the audio happen in front of the
    first frame, the transcript happens behind it, and the job is handed to
    playback still running rather than finished.
    """
    import argparse as argparse_module

    in_config_dir(monkeypatch, tmp_path)
    in_cache(monkeypatch, tmp_path)

    order: list[str] = []
    release = threading.Event()

    item = replace(
        media(),
        kind="audio",
        stream=False,
        url="https://example.test/page",
    )

    resolved = replace(
        item,
        url="https://example.test/audio.mp3",
    )

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda argv=None: argparse_module.Namespace(
            url="https://example.test/page",
            list=False,
            limit=None,
            feed="",
            search="",
            feeds=False,
            add_feed=False,
            name="",
            remove_feed="",
            pick=None,
            save=False,
            no_play=False,
            audio_only=False,
            quality=1080,
            subs=True,
            subs_from="auto",
            whisper_model="small.en",
            whisper_device="auto",
            subs_scale="auto",
            osc="always",
            subs_style="auto",
            resume=True,
        ),
    )
    monkeypatch.setattr(
        cli,
        "resolve_target",
        lambda args: cli.Target(Source(), "page", "page"),
    )
    monkeypatch.setattr(cli, "collect", lambda source, url, limit: [item])
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: True)
    monkeypatch.setattr(cli, "saved_positions", lambda media, args: None)
    monkeypatch.setattr(cli, "chapters_for", lambda media: None)

    def resolve(source, listed):
        order.append("resolved")
        return resolved

    def fetch_audio(media, args, saved):
        order.append("audio")

    def prepare(media, args, saved, playing=False):
        release.wait(timeout=5)
        order.append("transcribed")
        return PREPARED

    def play(source, listed, media, args, subtitles, caching=None):
        assert media.url == "https://example.test/audio.mp3"
        assert subtitles.done_yet() is False
        order.append("played")
        release.set()
        assert subtitles.wait() is PREPARED
        return 0

    monkeypatch.setattr(
        cli,
        "streamed_captions",
        lambda media, args, saved: None,
    )
    monkeypatch.setattr(cli, "resolve_item", resolve)
    monkeypatch.setattr(cli, "captions_audio", fetch_audio)
    monkeypatch.setattr(cli, "prepare_item", prepare)
    monkeypatch.setattr(cli, "play_item", play)

    assert cli.main(["https://example.test/page"]) == 0

    # the audio is here before the first frame, the transcript after it
    assert order == ["resolved", "audio", "played", "transcribed"]


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


def test_no_url_opens_the_feed_called_morning(monkeypatch, tmp_path: Path):
    """
    Which programme opens by default is a fact about the feeds file, not
    about the source: the source is decided by the URL, the same way it is
    for any other feed.
    """

    in_config_dir(monkeypatch, tmp_path)

    cli.feeds.seed()

    source, url, description = cli.resolve_target(args())

    assert url == cli.feeds.DEFAULT_URL
    assert source.name == "rte"
    assert description.startswith(f"{cli.feeds.DEFAULT_NAME}: ")


def test_two_programmes_of_one_source_are_two_feeds(
    monkeypatch,
    tmp_path: Path,
):
    """
    RTÉ is the source; Morning Ireland and This Week are two feeds of it,
    each with its own URL, and neither stands for the source.
    """

    in_config_dir(monkeypatch, tmp_path)

    cli.feeds.add(
        "morning",
        cli.feeds.DEFAULT_URL,
    )

    cli.feeds.add(
        "this-week",
        "https://www.rte.ie/radio/radio1/this-week/",
    )

    morning = cli.resolve_target(args(feed="morning"))
    week = cli.resolve_target(args(feed="this-week"))

    assert morning.source.name == week.source.name == "rte"
    assert morning.url != week.url


def test_the_feed_list_says_which_source_reads_each_one(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    """
    A channel and an audio programme are saved the same way, so the list
    is where the two pipelines have to be told apart.
    """

    in_config_dir(monkeypatch, tmp_path)

    cli.feeds.add(
        "c4",
        "https://www.youtube.com/@Channel4News",
    )

    cli.feeds.add(
        "this-week",
        "https://www.rte.ie/radio/radio1/this-week/",
    )

    cli.show_feeds()

    printed = capsys.readouterr().out

    assert "1. c4  youtube  https://www.youtube.com/@Channel4News" in printed

    assert (
        "2. this-week  rte  https://www.rte.ie/radio/radio1/this-week/"
        in printed
    )


def test_a_feed_nothing_reads_is_still_listed(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    """
    A feed outlives the source that served it, so listing them cannot be
    listing the ones that still work.
    """

    in_config_dir(monkeypatch, tmp_path)

    cli.feeds.add(
        "old",
        "https://example.test/listings/9",
    )

    cli.show_feeds()

    assert "old  ?  https://example.test/listings/9" in capsys.readouterr().out


def test_saving_a_feed_says_which_source_reads_it(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    in_config_dir(monkeypatch, tmp_path)

    cli.remember_feed(
        argparse.Namespace(
            url="https://www.rte.ie/radio/radio1/this-week/",
            name="this-week",
        )
    )

    assert "Feed: this-week (rte)" in capsys.readouterr().out


def test_no_arguments_at_all_is_the_shell():
    assert cli.opens_shell([])


def test_an_argument_is_a_run():
    """
    A flag is a request for something, so `subcast --subs` plays the
    feed a run with no URL opens - which is what a bare run used to do, and what a script
    that wants it asks for now.
    """

    assert not cli.opens_shell(["--subs"])


def test_a_bare_run_opens_the_shell_with_the_command_line_s_own_parser(
    monkeypatch,
    tmp_path: Path,
):
    """
    A command in the shell is parsed by the parser the command line uses,
    so a command cannot come to mean something the options do not say.
    """

    in_config_dir(monkeypatch, tmp_path)

    entered: list[argparse.Namespace] = []

    def run(parse, once, **rest):

        entered.append(parse(["--feeds"]))

        return 0

    monkeypatch.setattr(cli.shell, "run", run)

    assert cli.main([]) == 0
    assert [namespace.feeds for namespace in entered] == [True]


def test_a_run_told_to_stop_ends_the_process(monkeypatch, capsys, tmp_path: Path):
    in_config_dir(monkeypatch, tmp_path)

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda argv=None: args(url="https://example.test/page"),
    )

    def stopped(args):

        raise cli.Stopped

    monkeypatch.setattr(cli, "run_once", stopped)

    assert cli.main(["https://example.test/page"]) == 130
    assert "Interrupted." in capsys.readouterr().out


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
    tmp_path: Path,
):
    """
    Saving would record until the broadcast ends, and captions come from
    playing it - so both are refused with a line rather than started.
    """

    import argparse as argparse_module

    in_config_dir(monkeypatch, tmp_path)
    in_cache(monkeypatch, tmp_path)

    live_item = replace(media(), live=True)

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda argv=None: argparse_module.Namespace(
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
            osc="always",
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
        lambda media, args, saved, playing=False: pytest.fail("prepared a broadcast anyway"),
    )
    monkeypatch.setattr(
        cli,
        "play_item",
        lambda *args: pytest.fail("played a broadcast anyway"),
    )

    assert cli.main(["https://www.youtube.com/watch?v=abc"]) == 0

    output = capsys.readouterr().out

    if flag == "save":

        assert "cannot be saved while it airs" in output

    else:

        assert "--no-play leaves nothing to do" in output


def test_a_stop_signal_ends_the_run_but_is_not_ctrl_c(monkeypatch):
    """
    A run owns a broadcast's capture, and the capture is its own process
    group: dying on a signal would leave yt-dlp and ffmpeg reading a
    broadcast that nothing is watching. SIGTERM and SIGHUP are turned into
    `cli.Stopped`, so the run's own teardown happens - which is what stops
    the capture and removes its chunks - and it is not the exception Ctrl-C
    raises, because a shell stops one command for Ctrl-C and goes away for
    a signal.
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

    with pytest.raises(cli.Stopped):

        installed[cli.signal.SIGTERM](cli.signal.SIGTERM, None)


def test_a_file_the_run_hears_is_captioned_while_it_plays(monkeypatch, tmp_path):
    """
    A source whose stream came out of a resolve has its audio in hand when
    playback starts, so the captions can be written as the model hears it.
    A run that plays nothing has to wait for the whole transcript instead:
    there is no picture for a caption to arrive behind.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cli, "wants_subtitles", lambda media, args: True)
    monkeypatch.setattr(cli, "has_transcript", lambda media: False)
    monkeypatch.setattr(
        cli,
        "captions_audio",
        lambda media, args, saved: Path("/tmp/audio.mp3"),
    )

    item = replace(media(), kind="audio", stream=False)

    heard = cli.prepare_item(item, args(subs=True), None, playing=True)

    assert isinstance(heard, cli.HeardWhilePlaying)

    prepared: list = []

    monkeypatch.setattr(
        cli,
        "prepare",
        lambda media, audio, model, device, subs_from: (
            prepared.append(audio) or PREPARED
        ),
    )

    assert cli.prepare_item(item, args(subs=True), None) is PREPARED
    assert prepared == [Path("/tmp/audio.mp3")]


@pytest.mark.parametrize(
    ("captions", "stream", "transcript", "subs_from", "expected"),
    [
        # a file the run has to hear: nothing published, nothing cached
        ((), False, False, "auto", True),
        # a track the source publishes costs no hearing
        (PUBLISHED, False, False, "auto", False),
        # nor does a transcript already on disk
        ((), False, True, "auto", False),
        # a page mpv resolves is playing before the audio exists
        ((), True, False, "auto", False),
        # and published captions can be refused
        ((), False, False, "published", False),
    ],
)
def test_a_run_hears_the_audio_only_when_there_is_nothing_to_read(
    monkeypatch,
    captions,
    stream: bool,
    transcript: bool,
    subs_from: str,
    expected: bool,
):
    monkeypatch.setattr(cli, "has_transcript", lambda media: transcript)

    item = replace(
        media(captions),
        stream=stream,
    )

    assert (
        cli.hears_the_audio(
            item,
            args(subs=True, subs_from=subs_from),
        )
        is expected
    )


def test_the_hearing_ends_with_the_playback(monkeypatch, capsys):
    """
    What ends the captions of a file is the run ending, the way a
    broadcast's capture ends: the item is over, so there is nothing left to
    hear it for.
    """

    class Hearing(cli.GrowingCaptions):
        stopped = 0

        def stop(self):
            Hearing.stopped += 1

        def summary(self):
            return "    Captions heard to 1 min of 5 min."

    job = cli.PendingSubtitles.finished(Hearing())

    cli.stop_captions(job)

    assert Hearing.stopped == 1
    assert "Captions heard to 1 min" in capsys.readouterr().out
