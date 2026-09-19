"""What a resolve learned about an item, so a replay need not ask again.

A resolve is a round trip to the source - the slowest thing in the run - and
what it yields for an item whose transcript is already cached is metadata we
can write down once: its title, its length, and when we were told. The
stream URL is deliberately not stored: it is signed, short-lived, and
pointed at by the page URL mpv is given anyway.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from . import config

# How long a resolve is trusted. Long enough that replays cost nothing,
# short enough that a video whose captions or length changed is asked about
# again within the month.
RESOLVE_TTL = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class Known:
    """
    What a previous resolve wrote down about an item.
    """

    title: str
    duration: float | None
    resolved: float

    @property
    def stale(self) -> bool:
        """
        Whether it is old enough that we would rather ask again.
        """

        return (
            time.time() - self.resolved
            > RESOLVE_TTL
        )


def read(
    source: str,
    key: str,
) -> Known | None:
    """
    What was written down for an item, or None when nothing usable was.
    """

    target = (
        config.cache_dir(source)
        / f"{key}.meta.json"
    )

    try:

        raw = json.loads(
            target.read_text(
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
    )


def save(
    media,
) -> None:
    """
    Write down what a resolve just told us.
    """

    target = (
        config.cache_dir(media.source)
        / f"{media.key}.meta.json"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        json.dumps(
            {
                "title": media.title,
                "duration": media.duration,
                "resolved": time.time(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
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
