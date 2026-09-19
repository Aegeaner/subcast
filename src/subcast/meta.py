"""What a resolve learned about an item, and how long it can be trusted.

A resolve is the slowest thing in a run, and a replay of an item should not
need it: its title and length, and the stream URLs its formats came with,
are written down once. They have different lifetimes - the title is good for
a month, a signed stream URL for hours - so each is trusted on its own terms
and everything else is asked for again.

The stream URLs are why this exists at all: mpv is handed a page URL and
runs yt-dlp for itself, which is the same extraction subcast has just done,
twice, before the first frame.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import config

# How long a resolve is trusted for what it learned about the item itself.
RESOLVE_TTL = 30 * 24 * 60 * 60

# Signed URLs are good for hours; a margin keeps a run from starting on one
# that is about to be refused.
EXPIRY_MARGIN = 10 * 60

# What is kept per format: what picking and playing need, and nothing else.
KEPT_FIELDS = (
    "format_id",
    "url",
    "protocol",
    "vcodec",
    "acodec",
    "height",
    "tbr",
    "abr",
    "vbr",
)


@dataclass(frozen=True)
class Known:
    """
    What a previous resolve wrote down about an item.
    """

    title: str
    duration: float | None
    resolved: float
    formats: list[dict]
    expires: float

    @property
    def stale(self) -> bool:
        """
        Whether what it learned about the item is old enough to ask again.
        """

        return (
            time.time() - self.resolved
            > RESOLVE_TTL
        )

    @property
    def streams_live(self) -> bool:
        """
        Whether the stream URLs it wrote down are still worth playing.

        A live stream has none - its formats are manifests - so this is also
        what tells playback to leave the extraction to mpv.
        """

        return bool(self.formats) and (
            time.time()
            < self.expires - EXPIRY_MARGIN
        )


@dataclass(frozen=True)
class Streams:
    """
    What mpv is given instead of a page URL: the streams to play.

    `video` alone when the source's sound is inside it, `audio` alone when
    there is no picture to play, both when they arrive separately.
    """

    video: str | None
    audio: str | None

    @property
    def first(self) -> str:
        """
        The URL mpv is pointed at.
        """

        return self.video or self.audio or ""


def path(
    source: str,
    key: str,
) -> Path:
    """
    Where an item's metadata is kept, beside its transcript.
    """

    return (
        config.cache_dir(source)
        / f"{key}.meta.json"
    )


def save(
    media,
    formats: list | None = None,
) -> None:
    """
    Write down what a resolve just told us.

    Called by the sources, because they are the ones holding the payload the
    formats came out of.
    """

    target = path(
        media.source,
        media.key,
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    playable = [
        _kept(entry)
        for entry in formats or []
        if _playable(entry)
    ]

    target.write_text(
        json.dumps(
            {
                "title": media.title,
                "duration": media.duration,
                "resolved": time.time(),
                "expires": _expiry(formats or []),
                "formats": playable,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


def read(
    source: str,
    key: str,
) -> Known | None:
    """
    What was written down, or None when nothing usable was.
    """

    try:

        raw = json.loads(
            path(source, key).read_text(
                encoding="utf-8"
            )
        )

    except (OSError, ValueError):
        return None

    if not isinstance(raw, dict):
        return None

    title = raw.get("title")
    resolved = raw.get("resolved")
    duration = raw.get("duration")
    expires = raw.get("expires")
    formats = raw.get("formats")
    if not isinstance(title, str) or not isinstance(resolved, (int, float)):

        return None

    return Known(
        title=title,
        duration=(
            float(duration)
            if isinstance(duration, (int, float))
            else None
        ),
        resolved=float(resolved),
        formats=(
            [entry for entry in formats if isinstance(entry, dict)]
            if isinstance(formats, list)
            else []
        ),
        expires=(
            float(expires)
            if isinstance(expires, (int, float))
            else 0.0
        ),
    )


def fresh(
    media,
) -> bool:
    """
    Whether `media` - an item as a listing gave it - is already known well
    enough to play without asking the source again.

    The title has to agree: it is the one thing we have to check the video
    against, and it is what a re-upload or an edit changes.
    """

    known = read(
        media.source,
        media.key,
    )

    if known is None or known.stale:

        return False

    return (
        known.title.strip().casefold()
        == media.title.strip().casefold()
    )


def streams(
    media,
    quality: int | None = None,
) -> Streams | None:
    """
    The streams mpv should be given for an item, out of what a resolve wrote
    down, or None to leave mpv to extract for itself.

    `quality` is the picture to cap at, and None asks for sound only - the
    same choice the format argument mpv would have been given makes
    (`bestvideo[height<=quality]+bestaudio`, falling back to the best single
    stream), so that handing mpv URLs does not change what is played. What
    a format charges decides the rest: at one height a codec that gets the
    same picture out of fewer bytes is what a slow link feels least.
    """

    known = read(
        media.source,
        media.key,
    )

    if known is None or not known.streams_live:

        return None

    if quality is None:

        audio = _best(known.formats, "audio")

        if audio is not None:

            return Streams(
                video=None,
                audio=audio["url"],
                )

        muxed = _best(known.formats, "muxed")

        if muxed is None:

            return None

        return Streams(
            video=muxed["url"],
            audio=None,
        )

    video = _best(known.formats, "video", quality)
    audio = _best(known.formats, "audio")

    if video is not None and audio is not None:

        return Streams(
            video=video["url"],
            audio=audio["url"],
        )

    muxed = _best(known.formats, "muxed", quality)

    if muxed is None:

        return None

    return Streams(
        video=muxed["url"],
        audio=None,
    )


def _kind(
    entry: dict,
) -> str:
    """
    What a format carries: picture, sound, both, or neither.
    """

    picture = entry.get("vcodec") not in (None, "none")
    sound = entry.get("acodec") not in (None, "none")

    if picture and sound:
        return "muxed"

    if picture:
        return "video"

    if sound:
        return "audio"

    return "nothing"


def _playable(
    entry: object,
) -> bool:
    """
    Whether mpv can be pointed straight at this format.

    A plain URL it can open is what is wanted; a manifest - a live stream, or
    a DASH or HLS adaptation set - is mpv's own extraction's business.
    """

    if not isinstance(entry, dict) or not entry.get("url"):

        return False

    if entry.get("protocol") not in (None, "http", "https"):

        return False

    return _kind(entry) != "nothing"


def _best(
    formats: list[dict],
    kind: str,
    quality: int | None = None,
) -> dict | None:
    """
    The best format of a kind, within a picture height when one is given.
    """

    candidates = [
        entry
        for entry in formats
        if _kind(entry) == kind
        and (
            quality is None
            or kind == "audio"
            or (entry.get("height") or 0) <= quality
        )
    ]

    if not candidates:

        return None

    return max(
        candidates,
        key=_standing,
    )


# Codecs scored by the picture they get out of a byte: at one height AV1
# costs 1417k where VP9 costs 2130k, so a bitrate says what a format charges
# rather than what it shows - which leaves the codec to decide between
# formats of the same height, and the bitrate to break ties within one.
CODEC_SCORES = {
    "av01": 2,
    "vp9": 1,
    "vp09": 1,
}


def _standing(
    entry: dict,
) -> tuple[float, float, float]:
    """
    How good a format is: its picture, then its codec, then its bitrate.
    """

    codec = str(
        entry.get("vcodec")
        or ""
    ).split(".")[0]

    return (
        float(entry.get("height") or 0),
        float(CODEC_SCORES.get(codec, 0)),
        float(
            entry.get("tbr")
            or entry.get("abr")
            or entry.get("vbr")
            or 0
        ),
    )


def _kept(
    entry: dict,
) -> dict:
    """
    A format, with only the fields that are used here kept.
    """

    return {
        field: entry[field]
        for field in KEPT_FIELDS
        if field in entry
    }


def _expiry(
    formats: list,
) -> float:
    """
    When the signed URLs run out: the soonest `expire` among them, since the
    earliest to go is the one that decides.

    No expiry at all means now, so nothing is trusted that says nothing.
    """

    soonest: float | None = None

    for entry in formats:

        if not isinstance(entry, dict):
            continue

        query = parse_qs(
            urlsplit(
                str(entry.get("url") or "")
            ).query
        )

        found = query.get("expire") or []

        if not found or not found[0].isdigit():
            continue

        expires = float(found[0])

        if soonest is None or expires < soonest:

            soonest = expires

    return soonest or time.time()
