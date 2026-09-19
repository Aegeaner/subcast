"""Command line interface."""

from __future__ import annotations

import argparse
import sys

import requests

from . import captionbar
from .config import (
    CACHE_DIR,
    DEFAULT_WHISPER_MODEL,
    SAVE_DIR,
)
from .media import (
    download_audio,
    find_cached_audio,
    sanitize_filename,
)
from .player import play_with_mpv
from .rte import (
    HEADERS,
    SHOW_URL,
    episode_key,
    extract_episode_title,
    find_dustin_iframe,
    find_episode_clips,
    find_latest_episode,
    http_get,
    media_headers,
    resolve_audio,
    verify_audio,
)
from .subtitles import prepare_subtitles

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


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Find the latest RTÉ Morning Ireland episode "
            "and play or save its audio."
        )
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            "Save the episode to "
            "~/Videos/MorningIreland/ "
            "instead of playing it."
        ),
    )

    parser.add_argument(
        "--subs",
        "--subtitles",
        dest="subs",
        action="store_true",
        help=(
            "Transcribe the episode with Whisper and show the "
            "subtitles, with the published segment titles, in the "
            "terminal."
        ),
    )

    parser.add_argument(
        "--whisper-model",
        default=DEFAULT_WHISPER_MODEL,
        metavar="MODEL",
        help=(
            "faster-whisper model used by --subs "
            f"(default: {DEFAULT_WHISPER_MODEL})."
        ),
    )

    parser.add_argument(
        "--whisper-device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help=(
            "Device used by --subs to run Whisper "
            "(default: auto)."
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

def main() -> int:

    args = parse_args()

    # --subs adds a preparation step in front of playback.
    steps = (
        6
        if args.subs and not args.save
        else 5
    )

    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    try:

        # ============================================================
        # Show page
        # ============================================================

        print(
            f"[1/{steps}] Fetching show page:",
            flush=True,
        )

        show_response = http_get(
            session,
            SHOW_URL,
        )

        print(
            f"    {SHOW_URL}",
            flush=True,
        )

        # ============================================================
        # Find latest episode
        # ============================================================

        print(
            f"\n[2/{steps}] Finding latest episode:",
            flush=True,
        )

        episode_url, listing_title = (
            find_latest_episode(
                show_response.text
            )
        )

        print(
            f"    List title: {listing_title}",
            flush=True,
        )

        print(
            f"    URL: {episode_url}",
            flush=True,
        )

        # ============================================================
        # Fetch episode page
        # ============================================================

        print(
            f"\n[3/{steps}] Fetching episode page:",
            flush=True,
        )

        episode_response = http_get(
            session,
            episode_url,
            referer=SHOW_URL,
        )

        # IMPORTANT:
        # Get the real title from the concrete episode page.
        title = extract_episode_title(
            episode_response.text,
            listing_title,
        )

        print(
            f"    Episode title: {title}",
            flush=True,
        )

        iframe_url = find_dustin_iframe(
            episode_response.text,
            episode_url,
        )

        print(
            f"    Player: {iframe_url}",
            flush=True,
        )

        # ============================================================
        # Resolve actual media URL
        # ============================================================

        print(
            f"\n[4/{steps}] Resolving actual media URL:",
            flush=True,
        )

        media_url = resolve_audio(
            iframe_url,
        )

        print()
        print(
            "    Captured media URL:"
        )
        print(
            f"    {media_url}",
            flush=True,
        )

        print(
            "\n    Verifying media endpoint:",
            flush=True,
        )

        media_url = verify_audio(
            media_url,
            episode_url,
        )

        print(
            "    Final media URL:"
        )
        print(
            f"    {media_url}",
            flush=True,
        )

        # ============================================================
        # Save OR play
        # ============================================================

        if args.save:

            print(
                f"\n[5/{steps}] Saving audio:",
                flush=True,
            )

            print()
            print(
                f"    Save directory: {SAVE_DIR}",
                flush=True,
            )

            saved_path = download_audio(
                media_url,
                SAVE_DIR
                / sanitize_filename(title),
                media_headers(episode_url),
            )

            print()
            print(
                "Download complete.",
                flush=True,
            )

            print(
                f"    {saved_path}",
                flush=True,
            )

            if args.subs:

                print(
                    "\n    Generating subtitles:",
                    flush=True,
                )

                prepared = prepare_subtitles(
                    saved_path,
                    find_episode_clips(
                        episode_response.text
                    ),
                    title,
                    args.whisper_model,
                    args.whisper_device,
                )

                print(
                    f"    {prepared.srt_path}",
                    flush=True,
                )

                if prepared.chapters_path is not None:
                    print(
                        f"    {prepared.chapters_path}",
                        flush=True,
                    )

            # --save = download only.
            # Do NOT start mpv.
            return 0

        if args.subs:

            print(
                f"\n[5/{steps}] Preparing subtitles:",
                flush=True,
            )

            audio_path = find_cached_audio(
                CACHE_DIR,
                episode_key(
                    episode_url,
                    title,
                ),
            )

            if audio_path is None:

                print(
                    f"    Cache directory: {CACHE_DIR}",
                    flush=True,
                )

                audio_path = download_audio(
                    media_url,
                    CACHE_DIR
                    / episode_key(
                        episode_url,
                        title,
                    ),
                    media_headers(episode_url),
                )

            clips = find_episode_clips(
                episode_response.text
            )

            if clips:

                print(
                    f"    Published segments: "
                    f"{len(clips)}",
                    flush=True,
                )

            else:

                print(
                    "    No published segment list; "
                    "subtitles only.",
                    flush=True,
                )

            prepared = prepare_subtitles(
                audio_path,
                clips,
                title,
                args.whisper_model,
                args.whisper_device,
            )

            print(
                f"\n[6/{steps}] Starting mpv...",
                flush=True,
            )

            if caption_style(args) == "bar":

                return captionbar.play(
                    audio_path,
                    prepared.cues,
                    prepared.segments,
                    prepared.chapters_path,
                    caption_scale(args),
                    warn_about_scale=args.subs_scale != "auto",
                )

            return play_with_mpv(
                audio_path,
                prepared.srt_path,
                prepared.chapters_path,
            )

        print(
            f"\n[5/{steps}] Starting mpv...",
            flush=True,
        )

        return play_with_mpv(
            media_url,
        )

    except KeyboardInterrupt:

        print(
            "\nInterrupted.",
            flush=True,
        )

        return 130

    except Exception as exc:

        print(
            f"\nError: {exc}",
            file=sys.stderr,
        )

        return 1
