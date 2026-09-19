"""YouTube videos and playlists, listed and resolved with yt-dlp.

yt-dlp is not a Python dependency: it is the same external binary the
shell script used, so YouTube support costs nothing until it is asked
for. Listings are flat and cheap; resolving a video is the slow step,
and it is the one that brings back the captions YouTube already
publishes and the chapters it already has.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import Captions, Media, Segment

NAME = "youtube"

HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
)

# A channel URL that already names one of these is already a listing.
LISTING_TAILS = (
    "videos",
    "streams",
    "playlists",
    "shorts",
)

# Channels are reached through /channel/<id>, /user/<name> or /@handle.
LISTING_ROOTS = (
    "channel",
    "user",
)

WATCH_URL = "https://www.youtube.com/watch?v="

# What yt-dlp is asked for a search: "ytsearch20:morning ireland".
SEARCH_URL = "ytsearch{count}:{query}"

MISSING_MESSAGE = (
    "yt-dlp is required for YouTube support; "
    "install it (e.g. pipx install yt-dlp) or use --source rte"
)


class Youtube:
    """
    A place episodes come from: someone's videos, or one video.
    """

    name = NAME

    def matches(
        self,
        url: str,
    ) -> bool:
        """
        Whether this source handles the URL.
        """

        return urlsplit(url).hostname in HOSTS

    def episodes(
        self,
        url: str,
        limit: int | None = None,
    ) -> list[Media]:
        """
        The videos a URL points at: one for a video, many for a playlist
        or a channel listing. Flat - yt-dlp does not visit each video.
        """

        payload = yt_dlp_json(
            flatten_url(url),
            limit=limit,
            flat=True,
        )

        return parse_entries(payload, limit)

    def resolve(
        self,
        media: Media,
    ) -> Media:
        """
        Fill in what playing an item needs: duration, chapters, and the
        captions YouTube already has.
        """

        return parse_media(
            yt_dlp_json(media.url)
        )

    def caption_file(
        self,
        url: str,
        language: str,
        dest_stem: Path,
    ) -> Path | None:
        """
        Save a published caption track next to the episode, through
        yt-dlp.

        The URLs in the player JSON are often HLS playlists rather than
        WebVTT, so the download is left to yt-dlp, which knows how to get
        the text out. Returns the file it wrote, or None when the video
        has no captions in that language.
        """

        if not yt_dlp_available():

            raise RuntimeError(MISSING_MESSAGE)

        dest_stem.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        completed = _run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                language,
                "--sub-format",
                "vtt",
                "-o",
                f"{dest_stem}.%(ext)s",
                "--no-playlist",
                url,
            ]
        )

        written = sorted(
            dest_stem.parent.glob(
                f"{dest_stem.name}*.vtt"
            )
        )

        if written:

            return written[0]

        # Nothing written is either "this video has no track in that
        # language" - the caller has its own message for that - or
        # yt-dlp failing, which it should say out loud.
        if completed.returncode != 0:

            raise RuntimeError(
                f"yt-dlp could not fetch the captions for {url}: "
                f"{_stderr_tail(completed)}"
            )

        return None


SOURCE = Youtube()


def search_url(
    query: str,
    count: int,
) -> str:
    """
    A search, as the URL yt-dlp understands it.
    """

    return SEARCH_URL.format(
        count=max(count, 1),
        query=query,
    )


def listing_title(
    url: str,
) -> str:
    """
    What a listing calls itself: the playlist or channel name.

    A channel listing says what it lists ("BBC News - Videos"), which is
    noise in a feed's name, so that tail comes off.
    """

    payload = yt_dlp_json(
        flatten_url(url),
        limit=1,
        flat=True,
    )

    title = payload.get("title")

    if not isinstance(title, str) or not title.strip():

        raise RuntimeError(
            f"{url} does not name a playlist or channel"
        )

    named = title.strip()

    for tail in LISTING_TAILS:

        suffix = f" - {tail.title()}"

        if named.lower().endswith(suffix.lower()):

            return named[: -len(suffix)].strip() or named

    return named


def yt_dlp_available() -> bool:
    """
    Whether the yt-dlp binary is on PATH.
    """

    return shutil.which("yt-dlp") is not None


def yt_dlp_json(
    url: str,
    limit: int | None = None,
    flat: bool = False,
) -> dict:
    """
    Run yt-dlp and return the JSON it prints for `url`.

    `flat` lists a playlist without visiting each entry; a truthy `limit`
    stops yt-dlp at that many entries.
    """

    if not yt_dlp_available():

        raise RuntimeError(MISSING_MESSAGE)

    command = [
        "yt-dlp",
        "-J",
        "--no-warnings",
        "--socket-timeout",
        "15",
        "--retries",
        "2",
    ]

    if flat:

        command.append("--flat-playlist")

    if limit:

        command.extend(
            [
                "--playlist-end",
                str(limit),
            ]
        )

    command.append(url)

    completed = _run(command)

    if completed.returncode != 0:

        raise RuntimeError(
            f"yt-dlp failed for {url}: {_stderr_tail(completed)}"
        )

    try:

        payload = json.loads(completed.stdout)

    except ValueError as error:

        raise RuntimeError(
            f"yt-dlp returned no JSON for {url}: "
            f"{_stderr_tail(completed)}"
        ) from error

    if not isinstance(payload, dict):

        raise TypeError(
            f"yt-dlp returned no video for {url}"
        )

    return payload


def flatten_url(
    url: str,
) -> str:
    """
    Point a channel URL at its videos listing.

    `@handle`, /channel/<id> and /user/<name> URLs gain a /videos, unless
    they already name a listing. Watch and playlist URLs are left alone:
    they already point at what should be played.
    """

    split = urlsplit(url)

    parts = [
        part
        for part in split.path.split("/")
        if part
    ]

    if not parts:

        return url

    if parts[-1].lower() in LISTING_TAILS:

        return url

    root = parts[0].lower()

    if not (
        root.startswith("@")
        or root in LISTING_ROOTS
    ):

        return url

    if root in LISTING_ROOTS and len(parts) < 2:

        return url

    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            "/" + "/".join(parts) + "/videos",
            split.query,
            split.fragment,
        )
    )


def parse_entries(
    payload: dict,
    limit: int | None = None,
) -> list[Media]:
    """
    The videos in a playlist payload, or in a single-video payload.

    Entries that are not videos - gaps, nested playlists, entries with no
    id - are skipped, and a truthy `limit` stops the list early.
    """

    entries = payload.get("entries")

    if not isinstance(entries, list):

        entries = [payload]

    found: list[Media] = []

    for entry in entries:

        if not isinstance(entry, dict):

            continue

        media = _entry_media(entry)

        if media is None:

            continue

        found.append(media)

        if limit and len(found) >= limit:

            break

    return found


def parse_media(
    payload: dict,
) -> Media:
    """
    A resolved video: title, duration, chapters and captions.
    """

    video_id = payload.get("id") or ""

    return Media(
        source=NAME,
        key=str(video_id),
        title=payload.get("title") or "Untitled",
        url=payload.get("webpage_url") or f"{WATCH_URL}{video_id}",
        kind="video",
        duration=(
            None
            if payload.get("is_live")
            else _seconds(payload.get("duration"))
        ),
        stream=True,
        captions=_choose_captions(payload),
        segments=_chapters(payload),
    )


def _entry_media(
    entry: dict,
) -> Media | None:
    """
    One listing entry as a Media, or None when it is not a video.
    """

    video_id = entry.get("id")

    if not video_id:

        return None

    if entry.get("_type") not in (
        None,
        "video",
        "url",
    ):

        return None

    return Media(
        source=NAME,
        key=str(video_id),
        title=entry.get("title") or "Untitled",
        url=(
            entry.get("webpage_url")
            or f"{WATCH_URL}{video_id}"
        ),
        kind="video",
        duration=_seconds(entry.get("duration")),
        stream=True,
    )


def _chapters(
    payload: dict,
) -> tuple[Segment, ...]:
    """
    The video's chapters, in the order it publishes them.
    """

    published = payload.get("chapters")

    if not isinstance(published, list):

        return ()

    found: list[Segment] = []

    for chapter in published:

        if not isinstance(chapter, dict):

            continue

        title = chapter.get("title")

        if not title:

            continue

        found.append(
            Segment(
                title=title,
                start=_seconds(chapter.get("start_time")),
            )
        )

    return tuple(found)


def _choose_captions(
    payload: dict,
) -> tuple[Captions, ...]:
    """
    The caption track to play: a published one before an automatic one,
    `en` before other English variants, the first of anything otherwise.
    """

    for field in (
        "subtitles",
        "automatic_captions",
    ):

        tracks = payload.get(field)

        if not isinstance(tracks, dict):

            continue

        language = _choose_language(tracks)

        if language is None:

            continue

        caption = _choose_format(
            language,
            tracks[language],
        )

        if caption is not None:

            return (caption,)

    return ()


def _choose_language(
    tracks: dict,
) -> str | None:
    """
    `en` if it is there, then any other English, then whatever is first.
    """

    if not tracks:

        return None

    if "en" in tracks:

        return "en"

    for language in tracks:

        if language.lower().startswith("en"):

            return language

    return next(iter(tracks))


def _choose_format(
    language: str,
    formats: object,
) -> Captions | None:
    """
    A track's `vtt` format, or its first usable one.
    """

    if not isinstance(formats, list):

        return None

    chosen: dict | None = None

    for entry in formats:

        if not isinstance(entry, dict):

            continue

        if not entry.get("url"):

            continue

        if chosen is None or entry.get("ext") == "vtt":

            chosen = entry

        if entry.get("ext") == "vtt":

            break

    if chosen is None:

        return None

    return Captions(
        language=language,
        url=chosen["url"],
        ext="vtt",
    )


def _seconds(
    value: object,
) -> float | None:
    """
    A duration yt-dlp may or may not have supplied.
    """

    if isinstance(
        value,
        (int, float),
    ):

        return float(value)

    return None


def audio_download(
    url: str,
    dest_stem: Path,
) -> Path:
    """
    Download a video's best audio into "<dest_stem>.<ext>" and return the
    file yt-dlp wrote.
    """

    if not yt_dlp_available():

        raise RuntimeError(MISSING_MESSAGE)

    dest_stem.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    completed = _run(
        [
            "yt-dlp",
            "-f",
            "bestaudio",
            "-o",
            f"{dest_stem}.%(ext)s",
            "--no-playlist",
            url,
        ]
    )

    written = [
        path
        for path in sorted(
            dest_stem.parent.glob(
                f"{dest_stem.name}.*"
            )
        )
        if path.suffix != ".part"
    ]

    if completed.returncode != 0 or not written:

        raise RuntimeError(
            f"yt-dlp could not download {url}: "
            f"{_stderr_tail(completed)}"
        )

    return written[0]


def media_download(
    url: str,
    dest_stem: Path,
    quality: int = 1080,
) -> Path:
    """
    Download a video, up to `quality` lines tall, for --save.
    """

    if not yt_dlp_available():

        raise RuntimeError(MISSING_MESSAGE)

    dest_stem.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    completed = _run(
        [
            "yt-dlp",
            "-f",
            (
                f"bestvideo[height<={quality}]+bestaudio/"
                f"bestvideo[height<={quality}]+bestaudio/best"
            ),
            "--merge-output-format",
            "mp4",
            "-o",
            f"{dest_stem}.%(ext)s",
            "--no-playlist",
            url,
        ]
    )

    written = [
        path
        for path in sorted(
            dest_stem.parent.glob(
                f"{dest_stem.name}.*"
            )
        )
        if path.suffix not in (".part", ".vtt", ".srt")
    ]

    if completed.returncode != 0 or not written:

        raise RuntimeError(
            f"yt-dlp could not download {url}: "
            f"{_stderr_tail(completed)}"
        )

    return written[0]


def _run(
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    """
    Run a yt-dlp command, reporting a missing binary the way the rest of
    the pipeline expects.
    """

    try:

        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

    except FileNotFoundError as error:

        raise RuntimeError(MISSING_MESSAGE) from error


def _stderr_tail(
    completed: subprocess.CompletedProcess[str],
) -> str:
    """
    The last thing yt-dlp said, for an error message.
    """

    lines = [
        line.strip()
        for line in (completed.stderr or "").splitlines()
        if line.strip()
    ]

    if lines:

        return lines[-1]

    return f"exit code {completed.returncode}"
