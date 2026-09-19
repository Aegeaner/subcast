"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

from . import captionbar, config, feeds, picker
from .config import DEFAULT_WHISPER_MODEL, cache_dir, save_dir
from .media import acquire, download_audio, sanitize_filename
from .player import Positions, play_window, play_with_mpv
from .sources import Media, Source, default, detect
from .subtitles import (
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
            "number, a range such as 5-7, or 'all'. A saved --feed is "
            "opened this way whether or not this is given."
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


def collect(
    source: Source,
    url: str,
    limit: int,
) -> list[Media]:
    """
    What the URL points at: one item, or many for a playlist or listing.
    """

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
    too.
    """

    return bool(
        args.subs
        or media.captions
        or args.subs_from == "asr"
    )


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


def play_item(
    media: Media,
    prepared: Prepared | None,
    args: argparse.Namespace,
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

    if media.is_audio or args.audio_only:

        if prepared is not None and caption_style(args) == "bar":

            return captionbar.play(
                media.url,
                prepared.cues,
                prepared.segments,
                prepared.chapters_path,
                caption_scale(args),
                warn_about_scale=args.subs_scale != "auto",
                stream=media.stream,
                positions=positions,
            )

        return play_with_mpv(
            media.url,
            prepared.srt_path if prepared else None,
            prepared.chapters_path if prepared else None,
            stream=media.stream,
            positions=positions,
        )

    return play_window(
        media.url,
        prepared.srt_path if prepared else None,
        prepared.chapters_path if prepared else None,
        quality=args.quality,
        stream=media.stream,
        positions=positions,
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

        items = collect(
            target.source,
            target.url,
            fetch_limit(args),
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

            items = picker.choose(items)

            if not items:

                print(
                    "    Nothing chosen.",
                    flush=True,
                )

                return 0

            print()

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

            media = target.source.resolve(item)

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

            prepared = prepare_item(
                media,
                args,
                saved_path,
            )

            if (
                prepared is not None
                and prepared.chapters_path is not None
            ):

                print(
                    f"    {prepared.chapters_path}",
                    flush=True,
                )

            if args.no_play or args.save:

                continue

            print(
                f"\n[3/3] Playing{position}:",
                flush=True,
            )

            status = play_item(
                media,
                prepared,
                args,
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
