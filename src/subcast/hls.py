"""A live playlist: the pieces a broadcast has published, and where they sit.

A broadcast is not a file. There is no length to probe and nothing to range
over, so the way at its audio is the way a player takes it: read the playlist
naming the last few seconds of it, and fetch the pieces one at a time. That
is what a bounded request buys - a piece can be retried, skipped or renewed
on its own, where a pipe reading the broadcast has to survive the whole of
it.

What the playlist carries is what a piece is and how long it is. Where a
piece belongs is not read from here: a live manifest also states the clock
its first piece aired at (`#EXT-X-PROGRAM-DATE-TIME`), but a piece's own
timestamps carry the same clock - measured, the two agree to the millisecond
- and those come with the audio, so they are what `live.timestamp_of` reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import requests

# What one request may take. A piece is five seconds of the cheapest
# rendition carrying sound (measured: 90KB), so this is a hang rather than a
# slow network.
TIMEOUT = 20.0

# The statuses that mean the session is over rather than the piece missing: a
# googlevideo URL carries its own expiry, and a broadcast outlives it.
EXPIRED = frozenset({401, 403, 410})


@dataclass(frozen=True)
class Segment:
    """
    One piece of a broadcast, as the playlist names it.
    """

    sequence: int
    uri: str
    duration: float


@dataclass(frozen=True)
class Playlist:
    """
    What a broadcast offered when it was read, oldest piece first.
    """

    segments: tuple[Segment, ...]
    init: str | None
    ended: bool


class Expired(Exception):
    """
    The session is over: the URL is past the expiry it carries.
    """


class Unavailable(Exception):
    """
    The request did not come back, for a reason that is not the expiry.
    """


def read(
    url: str,
) -> Playlist:
    """
    The playlist a broadcast is publishing now.
    """

    return parse(
        _get(url).decode("utf-8", "replace"),
        url,
    )


def fetch(
    uri: str,
) -> bytes:
    """
    One piece of a broadcast, whole.
    """

    return _get(uri)


def parse(
    text: str,
    url: str,
) -> Playlist:
    """
    A media playlist read into the pieces it names.

    `#EXTINF` states a piece's length and `#EXT-X-MEDIA-SEQUENCE` the number
    of the first one, so a piece is identified by the broadcast's own
    counting rather than by where it sits in a listing; relative URIs are
    resolved against the playlist they came from. `#EXT-X-ENDLIST` is the
    broadcast having ended.
    """

    segments: list[Segment] = []
    init: str | None = None
    ended = False
    sequence = 0
    duration: float | None = None

    for raw in text.splitlines():

        line = raw.strip()

        if not line:

            continue

        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):

            sequence = _count(line.split(":", 1)[1])

        elif line.startswith("#EXT-X-MAP:"):

            init = urljoin(url, _attribute(line, "URI"))

        elif line.startswith("#EXTINF:"):

            duration = _number(line.split(":", 1)[1].split(",")[0])

        elif line.startswith("#EXT-X-ENDLIST"):

            ended = True

        elif not line.startswith("#") and duration is not None:

            segments.append(
                Segment(
                    sequence=sequence + len(segments),
                    uri=urljoin(url, line),
                    duration=duration,
                )
            )

            duration = None

    return Playlist(
        segments=tuple(segments),
        init=init,
        ended=ended,
    )


def _get(
    url: str,
) -> bytes:
    """
    What a URL answers with, as one of three outcomes: the body, a session
    that is over (`Expired`), or a request that did not come back.
    """

    try:

        response = requests.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

    except requests.RequestException as error:

        raise Unavailable(str(error)) from error

    if response.status_code in EXPIRED:

        raise Expired(f"it answered {response.status_code}")

    if response.status_code != 200:

        raise Unavailable(f"it answered {response.status_code}")

    return response.content


def _number(
    value: str,
) -> float:

    try:

        return float(value.strip())

    except ValueError as error:

        raise Unavailable(f"it does not say what {value!r} means") from error


def _count(
    value: str,
) -> int:
    """
    A piece number, which is a whole one.
    """

    number = _number(value)

    if number != int(number):

        raise Unavailable(f"it does not say what {value!r} means")

    return int(number)


def _attribute(
    line: str,
    name: str,
) -> str:
    """
    An attribute of a tag, as `#EXT-X-MAP:URI="seg.mp4"` means one.
    """

    for part in line.split(":", 1)[1].split(","):

        key, _sep, value = part.partition("=")

        if key.strip().upper() == name:

            return value.strip().strip('"')

    return ""
