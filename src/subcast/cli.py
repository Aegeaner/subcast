"""Command line interface."""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from . import captionbar, config, feeds, listing, meta, picker, shell
from .background import Background
from .config import DEFAULT_WHISPER_MODEL, cache_dir, save_dir
from .live import Capture, LiveCaptions
from .media import (
    acquire,
    download_audio,
    find_cached_audio,
    range_probe,
    request_headers,
    sanitize_filename,
)
from .player import Positions, play_window, play_with_mpv
from .sources import Media, Source, detect
from .subtitles import (
    GrowingCaptions,
    HeardWhilePlaying,
    PendingSubtitles,
    Prepared,
    StreamedWhilePlaying,
    cache_stem,
    has_transcript,
    load_model,
    prepare,
)


def caption_style(
    args: argparse.Namespace,
) -> str:
    """
    Where the captions are drawn: mpv's plain OSD, or a block we draw
    ourselves (which needs a terminal to draw on).
    """

    if args.subs_style != "auto":
        return args.subs_style

    return "bar" if sys.stdout.isatty() else "osd"


def caption_scale(
    args: argparse.Namespace,
) -> int | None:
    """
    Requested caption size multiplier, or None to size captions to the
    window.
    """

    if args.subs_scale == "auto":
        return None

    return int(args.subs_scale)


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Play or save an episode with subtitles: generated locally "
            "when the source publishes none, and shown as they play. "
            "Give it a URL (YouTube video, playlist or channel, a BBC "
            "Audio page, a Bloomberg podcast, a podcast feed, or an "
            "RTÉ Radio 1 programme or episode page), or give it no "
            "arguments at all and it waits for commands (/help lists "
            "them)."
        )
    )

    parser.add_argument(
        "url",
        nargs="?",
        default="",
        help=(
            "YouTube video, playlist or channel URL, a BBC Audio page, "
            "a Bloomberg podcast series, a podcast feed, or an RTÉ "
            "Radio 1 programme or episode URL. Omit for the feed called "
            f"{feeds.DEFAULT_NAME!r}; no arguments at all opens the shell."
        ),
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List what the URL points at and exit.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help=(
            "How many entries of a playlist or show listing to play, "
            "newest first (default: 1, 0 means all). A menu (--list, "
            "--pick, --feed) shows the newest "
            f"{config.list_limit()} unless N says otherwise."
        ),
    )

    sources = parser.add_mutually_exclusive_group()

    sources.add_argument(
        "--feed",
        metavar="NAME",
        default="",
        help=(
            "Open a saved feed by name (or by its number in --feeds): "
            "its entries are listed and you choose what to play."
        ),
    )

    sources.add_argument(
        "--search",
        metavar="QUERY",
        default="",
        help=(
            "Search YouTube, and play or pick from the results instead "
            "of a URL."
        ),
    )

    parser.add_argument(
        "--feeds",
        action="store_true",
        help=(
            "List the saved feeds with the source each one is read by, "
            "then exit."
        ),
    )

    parser.add_argument(
        "--add-feed",
        action="store_true",
        help=(
            "Save the URL as a feed: a YouTube playlist or channel, an "
            "RTÉ programme, a BBC Audio programme or category, a "
            "Bloomberg podcast series, or any podcast feed. Named by "
            "--name or after the listing itself; a name that already "
            "means another URL is refused rather than replaced."
        ),
    )

    parser.add_argument(
        "--name",
        metavar="NAME",
        default="",
        help="The name --add-feed saves the feed under.",
    )

    parser.add_argument(
        "--remove-feed",
        metavar="NAME",
        default="",
        help="Forget the feed called NAME.",
    )

    choosing = parser.add_mutually_exclusive_group()

    choosing.add_argument(
        "--pick",
        dest="pick",
        action="store_true",
        default=None,
        help=(
            "Print the listing and choose what to play from it - by "
            "number, a range such as 5-7, 'all', or 'r' to fetch the "
            "listing again. A saved --feed is opened this way whether or "
            "not this is given."
        ),
    )

    choosing.add_argument(
        "--no-pick",
        dest="pick",
        action="store_false",
        default=None,
        help=(
            "Play without asking: the newest entry, or --limit of them."
        ),
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            "Download into ~/Videos/<source>/ instead of streaming, "
            "then stop (published captions and chapters are kept in the "
            "cache; --subs transcribes where the source has none). A live "
            "broadcast is refused: it has no end to download up to."
        ),
    )

    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help=(
            "Start from the beginning instead of where the item was left "
            "last time; playback is remembered as it goes either way."
        ),
    )

    parser.add_argument(
        "--no-play",
        action="store_true",
        help=(
            "Prepare everything but do not start mpv; prints what was "
            "written. A live broadcast is refused: its captions only "
            "exist while it plays."
        ),
    )

    parser.add_argument(
        "--audio-only",
        action="store_true",
        help=(
            "Play the audio with captions in the terminal, instead of "
            "video in an mpv window."
        ),
    )

    parser.add_argument(
        "--quality",
        type=int,
        default=1080,
        metavar="HEIGHT",
        help=(
            "Maximum video height for streaming and --save "
            "(default: 1080)."
        ),
    )

    parser.add_argument(
        "--subs",
        "--subtitles",
        dest="subs",
        action="store_true",
        help=(
            "Produce subtitles where the source publishes none, by "
            "transcribing the audio locally - on a live broadcast, as it "
            "airs. Captions the source already has are used either way, "
            "so this is only needed for items without published captions."
        ),
    )

    parser.add_argument(
        "--subs-from",
        choices=("auto", "published", "asr"),
        default="auto",
        help=(
            "Where subtitles come from: the source's own captions, "
            "local speech recognition, or whichever is available "
            "(default: auto)."
        ),
    )

    parser.add_argument(
        "--whisper-model",
        default=DEFAULT_WHISPER_MODEL,
        metavar="MODEL",
        help=(
            "faster-whisper model used for transcription "
            f"(default: {DEFAULT_WHISPER_MODEL})."
        ),
    )

    parser.add_argument(
        "--whisper-device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help=(
            "Device used to run Whisper (default: auto)."
        ),
    )

    parser.add_argument(
        "--subs-scale",
        choices=("auto", "1", "2", "3"),
        default="auto",
        help=(
            "Caption size for --subs-style=bar, as a multiple of the "
            "terminal font. Needs a terminal that renders scaled text "
            "(kitty 0.40+) and falls back to 1 elsewhere; 'auto' sizes "
            "the captions to the window — 1x when narrow, up to 3x "
            "maximised (default: auto)."
        ),
    )

    parser.add_argument(
        "--subs-style",
        choices=("auto", "bar", "osd"),
        default="auto",
        help=(
            "How --subs shows captions. 'bar' draws a coloured block "
            "at the bottom of the terminal (segment title, up to two "
            "lines of dialogue, and the playback clock with elapsed "
            "and total time); 'osd' lets mpv print plain "
            "captions; 'auto' uses the bar when stdout is a terminal "
            "(default: auto)."
        ),
    )

    return parser


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    """
    The arguments of a command line: this run's, or a shell command's.

    The shell translates a command into the arguments it means and parses
    them with this, so a command cannot grow a second set of options.
    """

    return build_parser().parse_args(argv)


def play_limit(
    args: argparse.Namespace,
) -> int:
    """
    How many entries of a listing playback walks through: one, unless
    --limit says otherwise (0 meaning all of them).
    """

    return 1 if args.limit is None else args.limit


def browsing(
    args: argparse.Namespace,
) -> bool:
    """
    Whether the listing is shown rather than played straight through.

    --list prints it and stops, --pick prints it and plays what is chosen,
    and a saved feed is opened that way: a feed is the listing you keep in
    order to come back to it, so opening one shows what is in it. --no-pick
    plays a feed's newest entry without being asked, and a URL plays what
    it points at, as it always did.
    """

    if args.list:

        return True

    if args.pick is None:

        return bool(args.feed)

    return bool(args.pick)


def fetch_limit(
    args: argparse.Namespace,
) -> int:
    """
    How many entries to fetch from the source.

    Browsing wants the listing itself - the picker chooses from what was
    fetched, and --list prints what was fetched - so it asks for
    config.list_limit() entries, or for as many as --limit names (0 for
    all of them). Playing asks for what it will play and no more.
    """

    if browsing(args):

        return (
            config.list_limit()
            if args.limit is None
            else args.limit
        )

    return play_limit(args)


class Target(NamedTuple):
    """
    What a run works on, and the line that says which it is.
    """

    source: Source
    url: str
    description: str


def resolve_target(
    args: argparse.Namespace,
) -> Target:
    """
    What to work on: a URL, a saved feed or a YouTube search.

    With no URL at all it is the feed called `feeds.DEFAULT_NAME`, and it
    goes through the same path a feed named on the command line does: which
    programme opens by default is a fact about the feeds file, not about the
    source that reads it.
    """

    if args.search:

        from .sources import youtube

        # As much of the results as this run will use: the top hit when
        # playback is the only thing asked for, a menu's page when it is
        # going to be browsed.
        count = fetch_limit(args) or config.list_limit()

        return Target(
            youtube.SOURCE,
            youtube.search_url(args.search, count),
            f'search "{args.search}"',
        )

    if args.feed or not args.url:

        feed = feeds.find(
            args.feed or feeds.DEFAULT_NAME
        )

        return Target(
            detect(feed.url),
            feed.url,
            f"{feed.name}: {feed.url}",
        )

    return Target(
        detect(args.url),
        args.url,
        args.url,
    )


def feed_source(
    url: str,
) -> str:
    """
    The source a feed's URL is read by, or "?" when nothing reads it.
    """

    return feeds.source_of(url) or "?"


def show_feeds() -> int:
    """
    The saved feeds in the order they were added.

    The source is not part of what was saved - the URL decides it - but a
    list that mixes a channel with an audio programme says which pipeline
    each one goes through, because what they have in common is only that
    they are listings.
    """

    saved = feeds.load()

    if not saved:

        print(
            "    No feeds saved; add one with: "
            "subcast <url> --add-feed"
        )

    for number, feed in enumerate(saved, start=1):

        print(
            f"  {number:>3}. {feed.name}  "
            f"{feed_source(feed.url)}  {feed.url}"
        )

    return 0


def remember_feed(
    args: argparse.Namespace,
) -> int:
    """
    Save the URL as a feed, named by --name or after the listing.
    """

    if not args.url:

        raise RuntimeError(
            "--add-feed needs a URL: subcast <url> --add-feed"
        )

    name = args.name or feeds.title_for(args.url)

    feeds.add(name, args.url)

    print(
        f"    Feed: {name} ({feed_source(args.url)})\n"
        f"    {args.url}",
        flush=True,
    )

    return 0


def forget_feed(
    name: str,
) -> int:
    """
    Drop a saved feed.
    """

    feeds.remove(name)

    print(
        f"    Forgot: {name}",
        flush=True,
    )

    return 0


def cached_item(
    source: Source,
    url: str,
) -> Media | None:
    """
    A single video whose transcript is already cached, as the item the
    source would have listed it as.

    Asking what a URL points at is the last round trip a replay makes, and
    it is not needed at all when the answer is on disk: the source's own id
    says which video it is, and what a previous resolve wrote down says
    what to call it and how long it is.
    """

    find = getattr(
        source,
        "video_id",
        None,
    )

    if find is None:

        return None

    key = find(url)

    if not key:

        return None

    known = meta.read(
        source.name,
        key,
    )

    if known is None or known.stale:

        return None

    item = Media(
        source=source.name,
        key=key,
        title=known.title,
        url=url,
        duration=known.duration,
        stream=True,
    )

    if not has_transcript(item):

        return None

    return item


def cached_menu(
    source: Source,
    url: str,
    limit: int,
) -> list[Media] | None:
    """
    A listing a previous run fetched, when it can answer this one.

    Only the menu reads this: it is the one place the entries are there to
    be looked at, and a channel's listing takes long enough that sitting in
    front of a blank terminal is the worst part of browsing.
    """

    find = getattr(
        source,
        "video_id",
        None,
    )

    if find is not None and find(url):

        # One video is not a listing: the cache knows it better than a
        # list of one does.
        return None

    known = listing.read(
        source.name,
        url,
    )

    if known is None or not known.covers(limit or None):

        return None

    return known.taking(limit or None)


def refresher(
    source: Source,
    url: str,
    limit: int,
) -> Callable[[], Background[list[Media]]]:
    """
    What fetches a listing again, for a menu to call when it wants one.

    Whatever the source says is written down for the next run, whether or
    not the menu is still waiting for it.
    """

    def again() -> Background[list[Media]]:

        def work() -> list[Media]:

            items = source.episodes(
                url,
                limit=limit or None,
            )

            listing.save(
                source.name,
                url,
                limit or None,
                items,
            )

            return items

        return Background(
            work,
            "Refreshing the listing",
            "the menu keeps what it had",
        )

    return again


def menu_entries(
    source: Source,
    url: str,
    args: argparse.Namespace,
) -> tuple[list[Media], Callable[[], Background[list[Media]]] | None]:
    """
    What the menu shows, and how to ask the source for it again.

    A listing the user asked for by name - `--list`, or entries to play -
    is fetched fresh, because being current is what was asked for. The menu
    is the case that can show what it has: the cached entries go up at once
    and the fetch happens behind them.
    """

    limit = fetch_limit(args)

    if args.list or not browsing(args):

        return collect(source, url, limit), None

    known = cached_menu(source, url, limit)

    if known is None:

        items = collect(source, url, limit)

        listing.save(
            source.name,
            url,
            limit or None,
            items,
        )

        return items, None

    return known, refresher(source, url, limit)


def collect(
    source: Source,
    url: str,
    limit: int,
) -> list[Media]:
    """
    What the URL points at, asked for now: one item, or many for a playlist
    or listing.
    """

    known = cached_item(
        source,
        url,
    )

    if known is not None:

        return [known]

    items = source.episodes(
        url,
        limit=limit or None,
    )

    if not items:

        raise RuntimeError(
            f"{source.name} returned nothing for "
            f"{url or 'the default listing'}"
        )

    return items


def format_duration(
    seconds: float | None,
) -> str:
    """
    A duration the way a listener reads it: 0:19, 4:07, 2:00:35.

    Same clock the caption block shows during playback, so a duration
    and a position always read alike; nothing to show means nothing.
    """

    if not seconds:
        return ""

    return captionbar.clock(
        seconds
    )


def show_listing(
    source: Source,
    items: list[Media],
) -> None:

    print(
        f"{source.name}: {len(items)} item(s)"
    )

    for index, item in enumerate(items, start=1):

        print(
            picker.listing_line(index, item)
        )


def save_media(
    media: Media,
    quality: int,
) -> Path:
    """
    Download a media item into its source's directory.
    """

    stem = save_dir(
        media.source
    ) / sanitize_filename(media.title)

    if media.stream:

        from .sources import youtube

        return youtube.media_download(
            media.url,
            stem,
            quality=quality,
        )

    return download_audio(
        media.url,
        stem,
        dict(media.headers),
    )


def wants_subtitles(
    media: Media,
    args: argparse.Namespace,
) -> bool:
    """
    Whether an item gets subtitles.

    Always when asked, and whenever the source already publishes them -
    those cost a download where transcribing costs minutes of GPU. Asking
    for local transcription (`--subs-from asr`) is asking for subtitles
    too, and so is a transcript a previous run already left in the cache.

    A broadcast is the exception: the captions it may publish are a
    playlist that grows for as long as it airs, so they are not captions
    this run can fetch - which leaves local transcription, and only when
    this run asked for it. Nothing a previous run wrote down is right for
    a stream that has not finished being made.
    """

    if media.live:

        return making_live_captions(args)

    return bool(
        args.subs
        or media.captions
        or args.subs_from == "asr"
        or has_transcript(media)
    )


def making_live_captions(
    args: argparse.Namespace,
) -> bool:
    """
    Whether this run transcribes a broadcast as it airs.
    """

    if args.subs_from == "published":

        return False

    return bool(
        args.subs
        or args.subs_from == "asr"
    )


def resolve_item(
    source: Source,
    item: Media,
) -> Media:
    """
    What to play: the item resolved, or the item as the listing gave it
    when a previous run already learned what this run needs.

    A resolve is the slowest part of a YouTube run, and on that source it
    buys only metadata: mpv is handed the page URL and asks yt-dlp for the
    stream itself, and the captions, chapters and length are on disk from
    last time. Sources whose stream URL has to be found first - RTÉ - are
    always resolved, since there is nothing to play without it.
    """

    if item.stream and has_transcript(item) and meta.fresh(item):

        print(
            "    Using the cached transcript; not asking YouTube again.",
            flush=True,
        )

        return item

    print(
        f"    Resolving: {item.url}",
        flush=True,
    )

    return source.resolve(item)


def prepare_item(
    media: Media,
    args: argparse.Namespace,
    saved_path: Path | None,
    playing: bool = False,
) -> Prepared | GrowingCaptions | None:
    """
    Subtitles for one item, fetching audio only when they are generated
    locally: a broadcast is transcribed as it plays instead, which is a job
    rather than a file.

    `playing` says the run is about to show them, which is what lets a file
    be heard while it is watched (`HeardWhilePlaying`): the cues are written
    as the model produces them and the player reloads them, where a run that
    plays nothing waits for the whole transcript.
    """

    if not wants_subtitles(media, args):
        return None

    if media.live:

        return live_captions(
            media,
            args,
        )

    audio = captions_audio(
        media,
        args,
        saved_path,
    )

    if playing and audio is not None and hears_the_audio(media, args):

        return HeardWhilePlaying(
            media,
            audio,
            args.whisper_model,
            args.whisper_device,
        )

    return prepare(
        media,
        audio,
        args.whisper_model,
        args.whisper_device,
        args.subs_from,
    )


def hears_the_audio(
    media: Media,
    args: argparse.Namespace,
) -> bool:
    """
    Whether this run hears the audio rather than using captions a site
    publishes, or a transcript the cache already holds.

    It is the one case whose captions can be written while it plays: there
    is no track to fetch and nothing on disk to read, so the model is all
    that stands between the run and its subtitles. A page mpv resolves for
    itself is excluded - there the audio is still being fetched while the
    picture plays, so there is nothing to hear ahead of it.
    """

    return (
        not media.stream
        and wants_subtitles(media, args)
        and needs_audio(
            media,
            args.subs_from,
        )
        and not has_transcript(media)
    )


def captions_audio(
    media: Media,
    args: argparse.Namespace,
    saved_path: Path | None,
) -> Path | None:
    """
    The audio a transcript for this item is made from, fetched if it is not
    here yet: the file --save wrote, the one a previous run left in the
    cache, or a download now.

    Only what a transcript needs is asked for. An item whose captions the
    source already publishes is transcribed from nothing, and one whose
    transcript is cached is not heard again, so neither fetches anything.

    This is the download a captioned play waits for when the item cannot be
    heard from the stream instead (`streamed_captions`): the copies have to be
    the same one, and a site that answers a second request with different
    bytes - Bloomberg's host serves an enclosure with a pre-roll now and then -
    leaves downloading first as the only way to be sure (`playback_url`).
    """

    if saved_path is not None:

        return saved_path

    if not needs_audio(media, args.subs_from) or has_transcript(media):

        return None

    cached = find_cached_audio(
        cache_dir(media.source),
        media.key,
    )

    if cached is not None:

        return cached

    length = (
        f" {format_duration(media.duration)}"
        if media.duration
        else ""
    )

    print(
        f"    Fetching the audio to transcribe:{length}.",
        flush=True,
    )

    return acquire(
        media,
        cache_dir(media.source) / media.key,
    )


def streamed_captions(
    media: Media,
    args: argparse.Namespace,
    saved_path: Path | None,
) -> GrowingCaptions | None:
    """
    Captions for an item the player will read from its own URL, or None
    when it has to be downloaded and heard from the file.

    Two probes have to agree - the same length and the same opening bytes -
    before anything is streamed: that is what says the copy the model hears
    is the copy the player reads, which is the whole of what keeps cues in
    pace with the picture (`media.range_probe`). A site that stitches ads
    into a request answers a different length the second time, and an item
    that is already on disk is not fetched again at all.
    """

    if saved_path is not None or not hears_the_audio(media, args):

        return None

    headers = request_headers(media)

    ranged = range_probe(media.url, headers)

    if ranged is None or ranged != range_probe(media.url, headers):

        return None

    print(
        "    Captions are heard from the stream while it plays.",
        flush=True,
    )

    return StreamedWhilePlaying(
        media,
        media.url,
        ranged,
        headers,
        cache_dir(media.source) / media.key,
        args.whisper_model,
        args.whisper_device,
    )


def live_captions(
    media: Media,
    args: argparse.Namespace,
) -> LiveCaptions:
    """
    Captions for a broadcast, made while it plays.

    A broadcast has no file to transcribe and no captions to fetch, so the
    audio is taken from the stream itself, chunk by chunk, for as long as
    the item is watched - which the player starts, because an item that is
    prepared but never played has no broadcast to listen to.

    The model is loaded here rather than by the job: loading it is what
    prints, and a run drawing its own caption block cannot have that
    happening underneath it.
    """

    return LiveCaptions(
        cache_stem(media),
        load_model(
            args.whisper_model,
            args.whisper_device,
        ),
        Capture(media.url),
    )


def stop_captions(
    subtitles: PendingSubtitles | None,
) -> None:
    """
    End the capture a broadcast's captions were coming from.

    Playback is the only thing a live job exists for, so the run is what
    says when it is over; the subtitles it wrote stay behind it.
    """

    if subtitles is None:

        return

    settled = (
        subtitles.value()
        if subtitles.done_yet()
        else subtitles.wait()
    )

    if isinstance(settled, GrowingCaptions):

        settled.stop()

        summary = settled.summary()

        if summary is not None:

            print(summary, flush=True)


def needs_audio(
    media: Media,
    subs_from: str,
) -> bool:
    """
    Whether subtitles will need the audio locally.
    """

    if subs_from == "published":
        return False

    if subs_from == "asr":
        return True

    return not media.captions


def saved_positions(
    media: Media,
    args: argparse.Namespace,
) -> Positions | None:
    """
    Where this item is remembered from run to run, or None when there is
    nothing to remember: a stream of unknown length (a live feed) has no
    "where you were", and --no-resume is the way back to the beginning.
    """

    if not media.duration:

        return None

    return Positions(
        cache_stem(media),
        resume=args.resume,
    )


def plays_while_preparing(
    item: Media,
    playing: bool,
) -> bool:
    """
    Whether playback can start before this item is resolved and captioned.

    Only where mpv resolves the URL itself (a page URL it hands to yt-dlp)
    and only when something is actually being watched: RTÉ's stream URL
    comes out of the resolve, and --no-play and --save are not waiting to
    watch anything.
    """

    return playing and item.stream


def start_preparation(
    source: Source,
    item: Media,
    args: argparse.Namespace,
    saved_path: Path | None,
    after: PendingSubtitles | None = None,
    media: Media | None = None,
) -> PendingSubtitles:
    """
    Resolve and prepare an item beside the playback that is already going.

    This is what makes a YouTube run start in seconds: the resolve (2-5s)
    and the transcript are the only things subcast needs, and neither is
    needed to play - mpv is handed the page URL and asks yt-dlp itself.

    `after` is the preparation this one waits for before starting, which is
    how the item after the one playing is worked out without two of them
    asking YouTube at once.

    `media` is an item the run has already resolved, and whose audio it has
    already fetched (`captions_audio`), because that audio is what plays.
    The resolve is not asked for again: only the transcript is left to
    happen beside the playback.
    """

    def work() -> Prepared | LiveCaptions | None:

        if after is not None:

            after.wait()

        resolved = (
            media
            if media is not None
            else resolve_item(
                source,
                item,
            )
        )

        if not wants_subtitles(resolved, args):

            return None

        return prepare_item(
            resolved,
            args,
            saved_path,
            playing=True,
        )

    job = PendingSubtitles(
        work
    )

    job.start()

    return job


def ready_subtitles(
    media: Media,
    args: argparse.Namespace,
    saved_path: Path | None,
) -> PendingSubtitles | None:
    """
    The subtitles for an item, worked out before playback starts.

    None means none are wanted at all, which is also what a run with no
    --subs gets from a source that publishes no captions.
    """

    if not wants_subtitles(media, args):

        return None

    return PendingSubtitles.finished(
        prepare_item(
            media,
            args,
            saved_path,
        )
    )


def chapters_for(
    media: Media,
) -> Path | None:
    """
    The chapter file a previous run left, if it did.

    Chapters cannot be added to mpv once it is playing, so a run that
    starts before its subtitles are ready uses the ones already on disk and
    leaves this run's for next time.
    """

    path = cache_stem(media).with_suffix(
        ".chapters.txt"
    )

    return path if path.is_file() else None


def playback_url(
    media: Media,
    subtitles: PendingSubtitles | None,
) -> str:
    """
    What to play: the audio the captions were timed against when there is
    one, the stream URL otherwise.

    RTÉ stitches ads into an episode per request, measured: the same URL
    answered with two different files a second apart, 57,154,080 bytes and
    56,829,745, with different audio at the start. So the file that was
    transcribed and the file mpv would stream are not the same audio, and
    captions timed against one cannot be in pace with the other. The file
    a run already downloaded is the one the cues belong to, so that is what
    plays.

    Nothing else changes: a run that is not captioned downloads nothing and
    streams (`subtitles` is None), a source whose URL is a page is mpv's to
    resolve either way, and captions heard from the stream itself
    (`StreamedWhilePlaying`) belong to the stream.
    """

    if subtitles is None or media.stream:

        return media.url

    settled = (
        subtitles.value()
        if subtitles.done_yet()
        else None
    )

    if isinstance(settled, StreamedWhilePlaying):

        return media.url

    cached = find_cached_audio(
        cache_dir(media.source),
        media.key,
    )

    if cached is None:

        return media.url

    return str(cached)


def play_item(
    source: Source,
    item: Media,
    media: Media,
    args: argparse.Namespace,
    subtitles: PendingSubtitles | None,
) -> int:
    """
    Audio in the terminal with our captions, video in an mpv window.
    """

    positions = saved_positions(
        media,
        args,
    )

    if positions is not None and positions.start > 0:

        print(
            f"    Resuming at "
            f"{format_duration(positions.start)}",
            flush=True,
        )

    chapters = chapters_for(
        media
    )

    audio = media.is_audio or args.audio_only

    # Captions made while the item plays are handed over as they land, and
    # mpv logs its whole track list every time it reads the file again.
    reloading = hears_the_audio(media, args)

    streams = meta.streams(
        media,
        None if audio else args.quality,
    )

    target = playback_url(
        media,
        subtitles,
    )

    if audio:

        if subtitles is not None and caption_style(args) == "bar":

            return captionbar.play(
                target,
                subtitles,
                chapters,
                caption_scale(args),
                warn_about_scale=args.subs_scale != "auto",
                stream=media.stream,
                positions=positions,
                live=media.live,
            )

        return play_with_mpv(
            target,
            None,
            chapters,
            stream=media.stream,
            positions=positions,
            subtitles=subtitles,
            streams=streams,
            live=media.live,
            reloading=reloading,
        )

    return play_window(
        target,
        None,
        chapters,
        quality=args.quality,
        stream=media.stream,
        positions=positions,
        subtitles=subtitles,
        streams=streams,
        live=media.live,
        reloading=reloading,
    )


class Stopped(BaseException):
    """
    A signal asked the run to end.

    Not a KeyboardInterrupt, because the two mean different things to a
    shell: Ctrl-C stops the command that is running and the shell reads the
    next one, where a SIGTERM is the process being told to go away.
    """


def stop_signals() -> None:
    """
    Stop the way Ctrl-C does when the run is asked to end.

    A run owns a broadcast's capture, and the two are separate process
    groups: dying on a signal would leave yt-dlp and ffmpeg reading a
    broadcast that nothing is watching. Raising on the way to the same
    teardown means the same paths end it as any other stop.
    """

    for name in ("SIGTERM", "SIGHUP"):

        number = getattr(signal, name, None)

        if number is not None:

            signal.signal(number, _stop_requested)


def _stop_requested(signum, frame) -> None:

    raise Stopped


def main(
    argv: list[str] | None = None,
) -> int:
    """
    The command line, or the shell when there is no command line at all.

    The arguments are an input rather than the process's own argv so that
    what a run does can be said out loud, by a test or by anything else
    that starts one.
    """

    arguments = sys.argv[1:] if argv is None else argv

    args = parse_args(arguments)

    try:

        stop_signals()

        try:

            feeds.seed()

        except OSError:

            # A machine whose config cannot be written still plays URLs: the
            # feed a run with no URL opens is then one the user adds.
            pass

        if opens_shell(arguments):

            return shell.run(
                parse_args,
                run_once,
            )

        return run_once(args)

    except (KeyboardInterrupt, Stopped):

        print(
            "\nInterrupted.",
            flush=True,
        )

        return 130


def opens_shell(
    arguments: list[str],
) -> bool:
    """
    Whether a command line asks for nothing at all, which is the shell.

    Every argument is a run: `subcast --subs` plays the feed a run with no
    URL opens, and so does anything else the command line can be told,
    because a flag is a request for something.
    """

    return not arguments


def run_once(
    args: argparse.Namespace,
) -> int:
    """
    One command line's worth of work, from finding items to playing them.

    The shell runs this per command, which is why a command that goes wrong
    is reported rather than ending the shell: a URL that does not work is
    one command that did not work. KeyboardInterrupt is left alone here -
    it passes through, so a shell stops the command it is running and a
    command line ends, which is what each of them means by it - and so is
    the signal that asks the whole run to end.
    """

    try:

        if args.feeds:

            return show_feeds()

        if args.remove_feed:

            return forget_feed(args.remove_feed)

        if args.add_feed:

            return remember_feed(args)

        target = resolve_target(args)

        print(
            f"[1/3] Finding items ({target.source.name}):",
            flush=True,
        )

        items, again = menu_entries(
            target.source,
            target.url,
            args,
        )

        print(
            f"    {target.description}"
        )

        print(
            f"    {len(items)} item(s)",
            flush=True,
        )

        if args.list:

            show_listing(target.source, items)

            return 0

        if browsing(args):

            print()

            items = picker.choose(
                items,
                again,
            )

            if not items:

                print(
                    "    Nothing chosen.",
                    flush=True,
                )

                return 0

            print()

        ahead: dict[str, PendingSubtitles] = {}

        for index, item in enumerate(items, start=1):

            position = (
                f" ({index}/{len(items)})"
                if len(items) > 1
                else ""
            )

            print(
                f"\n[2/3] Preparing{position}:",
                flush=True,
            )

            watching = not (args.no_play or args.save)
            beside = plays_while_preparing(item, watching)

            media = item
            subtitles: PendingSubtitles | None = None

            if beside:

                # The listing's own title and length are all playback
                # needs; the resolve and the subtitles happen beside it -
                # or already did, for the item after the last one.
                subtitles = ahead.pop(item.key, None)

                if subtitles is None:

                    subtitles = start_preparation(
                        target.source,
                        item,
                        args,
                        saved_path=None,
                    )

            else:

                media = resolve_item(
                    target.source,
                    item,
                )

            print(
                f"    {media.title}"
            )

            if media.duration:

                print(
                    f"    Duration: "
                    f"{format_duration(media.duration)}"
                )

            if media.captions:

                print(
                    f"    Published captions: "
                    f"{media.captions[0].language}"
                )

            if media.segments:

                print(
                    f"    Published segments: "
                    f"{len(media.segments)}"
                )

            if media.live:

                print(
                    "    Live broadcast: captions made as it plays"
                    if making_live_captions(args)
                    else "    Live broadcast: playing without captions"
                )

            if media.live and (args.save or args.no_play):

                if args.save:

                    # A broadcast has no end to download up to; it is an
                    # ordinary video once it has one.
                    print(
                        "    A live broadcast cannot be saved while it "
                        "airs; wait for the video of it.",
                        flush=True,
                    )

                else:

                    print(
                        "    A broadcast is prepared by playing it; "
                        "--no-play leaves nothing to do.",
                        flush=True,
                    )

                continue

            saved_path = None

            if args.save:

                print(
                    f"    Save directory: "
                    f"{save_dir(media.source)}",
                    flush=True,
                )

                saved_path = save_media(
                    media,
                    args.quality,
                )

                print(
                    f"    Saved: {saved_path}",
                    flush=True,
                )

            if not beside:

                if watching and wants_subtitles(media, args):

                    # Captions for something about to play are heard from
                    # the bytes the player is reading whenever the site
                    # serves the same ones to every request: the first frame
                    # is seconds away and the model follows the stream a
                    # span at a time. An item that cannot be heard that way
                    # is downloaded whole first, because its captions have
                    # to belong to the copy that plays.
                    streamed = streamed_captions(
                        media,
                        args,
                        saved_path,
                    )

                    if streamed is not None:

                        subtitles = PendingSubtitles.finished(
                            streamed
                        )

                    else:

                        captions_audio(
                            media,
                            args,
                            saved_path,
                        )

                        subtitles = start_preparation(
                            target.source,
                            item,
                            args,
                            saved_path=saved_path,
                            media=media,
                        )

                else:

                    subtitles = ready_subtitles(
                        media,
                        args,
                        saved_path,
                    )

            if not watching:

                if subtitles is not None:

                    subtitles.wait()

                continue

            print(
                f"\n[3/3] Playing{position}:",
                flush=True,
            )

            following = (
                items[index]
                if index < len(items)
                else None
            )

            if following is not None and plays_while_preparing(
                following,
                watching,
            ):

                # Watched next, so it is worked out now: by the time this
                # item ends, the next one is ready to start.
                ahead[following.key] = start_preparation(
                    target.source,
                    following,
                    args,
                    saved_path=None,
                    after=subtitles,
                )

            try:

                status = play_item(
                    target.source,
                    item,
                    media,
                    args,
                    subtitles,
                )

            finally:

                # A broadcast's capture is playback's to keep alive, and
                # nothing else knows when mpv has stopped playing it.
                stop_captions(subtitles)

            if status != 0:

                print(
                    f"    mpv exited with {status}",
                    flush=True,
                )

        return 0

    except Exception as exc:  # noqa: BLE001 - the command reports it below

        print(
            f"\nError: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
