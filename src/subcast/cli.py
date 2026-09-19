"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import captionbar
from .config import DEFAULT_WHISPER_MODEL, cache_dir, save_dir
from .media import acquire, download_audio, sanitize_filename
from .player import play_window, play_with_mpv
from .sources import Media, Source, default, detect
from .subtitles import (
    Prepared,
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
        default=1,
        metavar="N",
        help=(
            "How many entries of a playlist or show listing to play, "
            "newest first (default: 1, 0 means all)."
        ),
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            "Download into ~/Videos/<source>/ instead of streaming, "
            "then stop (add --subs to keep subtitles alongside)."
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
            "Produce subtitles: published captions where the source has "
            "them, otherwise a local Whisper transcription."
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
            "at the bottom of the terminal (segment title, then up to "
            "two lines of dialogue); 'osd' lets mpv print plain "
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
    """

    if not seconds:
        return ""

    total = int(seconds)

    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


def show_listing(
    source: Source,
    items: list[Media],
) -> None:

    print(
        f"{source.name}: {len(items)} item(s)"
    )

    for index, item in enumerate(items, start=1):

        duration = format_duration(
            item.duration
        )

        print(
            f"  {index:>3}. {item.title}"
            + (f"  [{duration}]" if duration else "")
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


def prepare_item(
    media: Media,
    args: argparse.Namespace,
    saved_path: Path | None,
) -> Prepared | None:
    """
    Subtitles for one item, fetching audio only when they are generated
    locally.
    """

    if not args.subs:
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


def play_item(
    media: Media,
    prepared: Prepared | None,
    args: argparse.Namespace,
) -> int:
    """
    Audio in the terminal with our captions, video in an mpv window.
    """

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
            )

        return play_with_mpv(
            media.url,
            prepared.srt_path if prepared else None,
            prepared.chapters_path if prepared else None,
            stream=media.stream,
        )

    return play_window(
        media.url,
        prepared.srt_path if prepared else None,
        prepared.chapters_path if prepared else None,
        quality=args.quality,
        stream=media.stream,
    )


def main() -> int:

    args = parse_args()

    try:

        source = source_for(args.url)

        print(
            f"[1/3] Finding items ({source.name}):",
            flush=True,
        )

        items = collect(
            source,
            args.url,
            args.limit,
        )

        print(
            f"    {args.url or 'latest'}"
        )

        print(
            f"    {len(items)} item(s)",
            flush=True,
        )

        if args.list:

            show_listing(source, items)

            return 0

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

            media = source.resolve(item)

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
