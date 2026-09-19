"""The entries a listing URL points at, and keeping them between runs.

A channel is fetched with one yt-dlp call, and for a busy one that call
takes tens of seconds - too long to sit in front of before a menu appears.
What was fetched is written down, so the menu can be shown at once and the
listing refreshed behind it: what is on screen is what the source said last
time, until the fresh answer arrives and takes its place.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import config
from .background import Background
from .sources import Media

# Kept longer than this and it is only a starting point: the refresh
# replaces it as soon as the source answers anyway.
KEEP_FOR = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class Cached:
    """
    Entries a previous run fetched, and how deep that fetch went.

    `limit` is what the fetch asked for, None meaning as many as the source
    offered: a listing of the newest 5 entries cannot answer a question
    about the newest 30.
    """

    url: str
    fetched: float
    limit: int | None
    items: list[Media]

    def covers(
        self,
        wanted: int | None,
    ) -> bool:
        """
        Whether these entries answer a request for `wanted` of them, None
        meaning all of them.
        """

        if wanted is None:

            return self.limit is None

        return self.limit is None or self.limit >= wanted

    def taking(
        self,
        wanted: int | None,
    ) -> list[Media]:
        """
        As many of them as the request wants.
        """

        if wanted is None:

            return self.items

        return self.items[:wanted]


def path(
    source: str,
    url: str,
) -> Path:
    """
    Where a listing is kept: one file per URL, named after it.
    """

    digest = hashlib.sha256(
        url.encode()
    ).hexdigest()[:16]

    return (
        config.cache_dir(source)
        / "listings"
        / f"{digest}.json"
    )


def read(
    source: str,
    url: str,
) -> Cached | None:
    """
    What a previous run fetched, or None when nothing usable was.
    """

    try:

        raw = json.loads(
            path(source, url).read_text(
                encoding="utf-8"
            )
        )

    except (OSError, ValueError):
        return None

    if not isinstance(raw, dict) or raw.get("url") != url:

        return None

    fetched = raw.get("fetched")
    limit = raw.get("limit")

    if not isinstance(fetched, (int, float)):

        return None

    if time.time() - float(fetched) > KEEP_FOR:

        return None

    items: list[Media] = []

    for entry in raw.get("items") or []:

        if not isinstance(entry, dict):
            continue

        key = entry.get("key")
        title = entry.get("title")
        item_url = entry.get("url")

        if not (isinstance(key, str) and isinstance(title, str) and isinstance(item_url, str)):

            continue

        duration = entry.get("duration")

        items.append(
            Media(
                source=source,
                key=key,
                title=title,
                url=item_url,
                duration=(
                    float(duration)
                    if isinstance(duration, (int, float))
                    else None
                ),
                stream=bool(entry.get("stream", True)),
            )
        )

    if not items:

        return None

    return Cached(
        url=url,
        fetched=float(fetched),
        limit=(
            int(limit)
            if isinstance(limit, (int, float))
            else None
        ),
        items=items,
    )


def save(
    source: str,
    url: str,
    limit: int | None,
    items: list[Media],
) -> None:
    """
    Write down what a fetch returned.
    """

    target = path(source, url)

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        json.dumps(
            {
                "url": url,
                "fetched": time.time(),
                "limit": limit,
                "items": [
                    {
                        "key": item.key,
                        "title": item.title,
                        "url": item.url,
                        "duration": item.duration,
                        "stream": item.stream,
                    }
                    for item in items
                ],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


class Refresh(Background[list[Media]]):
    """
    A listing being fetched again behind the menu.

    Only the menu uses this: it is the one place the entries are there to be
    looked at, so showing what last time returned while the source is asked
    again costs nothing, and what the answer holds is written down for next
    time either way.
    """

    def __init__(
        self,
        work,
    ) -> None:

        super().__init__(
            work,
            "Refreshing the listing",
            "the menu keeps what it had",
        )
