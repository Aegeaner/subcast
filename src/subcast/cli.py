"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from . import captionbar, config, feeds, listing, meta, picker
from .background import Background
from .config import DEFAULT_WHISPER_MODEL, cache_dir, save_dir
from .media import acquire, download_audio, sanitize_filename
from .player import Positions, play_window, play_with_mpv
from .sources import Media, Source, default, detect
from .subtitles import (
    PendingSubtitles,
    Prepared,
    cache_stem,
    has_transcript,
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


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Play or save an episode with subtitles: generated locally "
            "when the source publishes none, and shown as they play. "
            "Give it a URL (YouTube video, playlist or channel, or an "
            "RTÉ Morning Ireland episode or show page) or nothing at all "
            "for the latest Morning Ireland."
        )
    )

    parser.add_argument(
        "url",
        nargs="?",
        default="",
        help=(
            "YouTube video, playlist or channel URL, or an RTÉ "
            "Morning Ireland show or episode URL. Omit for the latest "
            "Morning Ireland."
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
        help="List the saved feeds and exit.",
    )

    parser.add_argument(
        "--add-feed",
        action="store_true",
        help=(
            "Save the URL (a YouTube playlist or channel) as a feed, "
            "named by --name or after the listing itself."
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
            "cache; --subs transcribes where the source has none)."
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
            "written."
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
            "transcribing the audio locally. Captions the source already "
            "has are used either way, so this is only needed for items "
            "without published captions."
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

    return parser.parse_args()


def source_for(
    url: str,
) -> Source:
    """
    The source that handles a URL, or the default one.
    """

    if not url:
        return default()

    return detect(url)


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

    if args.feed:

        feed = feeds.find(args.feed)

        return Target(
            detect(feed.url),
            feed.url,
            f"{feed.name}: {feed.url}",
        )

    return Target(
        source_for(args.url),
        args.url,
        args.url or "latest",
    )


def show_feeds() -> int:
    """
    The saved feeds, in the order they were added.
    """

    saved = feeds.load()

    if not saved:

        print(
            "    No feeds saved; add one with: "
            "subcast <url> --add-feed"
        )

        return 0

    for number, feed in enumerate(saved, start=1):

        print(
            f"  {number:>3}. {feed.name}  {feed.url}"
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
        f"    Feed: {name}\n"
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
    """

    return bool(
        args.subs
        or media.captions
        or args.subs_from == "asr"
        or has_transcript(media)
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

    media = source.resolve(item)

    meta.save(media)

    return media


def prepare_item(
    media: Media,
    args: argparse.Namespace,
    saved_path: Path | None,
) -> Prepared | None:
    """
    Subtitles for one item, fetching audio only when they are generated
    locally.
    """

    if not wants_subtitles(media, args):
        return None

    audio_path = saved_path

    if (
        audio_path is None
        and needs_audio(media, args.subs_from)
        and not has_transcript(media)
    ):

        print(
            "    Downloading audio for transcription:",
            flush=True,
        )

        audio_path = acquire(
            media,
            cache_dir(media.source) / media.key,
        )

    return prepare(
        media,
        audio_path,
        args.whisper_model,
        args.whisper_device,
        args.subs_from,
    )


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
) -> PendingSubtitles:
    """
    Resolve and prepare an item beside the playback that is already going.

    This is what makes a YouTube run start in seconds: the resolve (2-5s)
    and the transcript are the only things subcast needs, and neither is
    needed to play - mpv is handed the page URL and asks yt-dlp itself.

    `after` is the preparation this one waits for before starting, which is
    how the item after the one playing is worked out without two of them
    asking YouTube at once.
    """

    def work() -> Prepared | None:

        if after is not None:

            after.wait()

        media = resolve_item(
            source,
            item,
        )

        if not wants_subtitles(media, args):

            return None

        return prepare_item(
            media,
            args,
            saved_path,
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


def play_item(
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

    if media.is_audio or args.audio_only:

        if subtitles is not None and caption_style(args) == "bar":

            return captionbar.play(
                media.url,
                subtitles,
                chapters,
                caption_scale(args),
                warn_about_scale=args.subs_scale != "auto",
                stream=media.stream,
                positions=positions,
            )

        return play_with_mpv(
            media.url,
            None,
            chapters,
            stream=media.stream,
            positions=positions,
            subtitles=subtitles,
        )

    return play_window(
        media.url,
        None,
        chapters,
        quality=args.quality,
        stream=media.stream,
        positions=positions,
        subtitles=subtitles,
    )


def main() -> int:

    args = parse_args()

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

            status = play_item(
                media,
                args,
                subtitles,
            )

            if status != 0:

                print(
                    f"    mpv exited with {status}",
                    flush=True,
                )

        return 0

    except KeyboardInterrupt:

        print(
            "\nInterrupted.",
            flush=True,
        )

        return 130

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
