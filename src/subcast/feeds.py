"""Feeds: the listings worth coming back to, saved under a name.

A feed here is a URL - today a YouTube playlist or channel - kept in the
user's config directory so it can be played by name instead of pasted
again. It is not a podcast feed: the point is a short list of the listings
you follow, played through exactly the same pipeline as any other URL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Feed:
    """
    A listing the user saved, under the name they will ask for it by.
    """

    name: str
    url: str


def load() -> list[Feed]:
    """
    The saved feeds, in the order they were added.

    A feeds file that is missing, unreadable or not a list of names and
    URLs means no feeds rather than an error: the tool is still usable
    without the file, and a half-written one should not stop playback.
    """

    try:

        raw = json.loads(
            config.feeds_path().read_text(
                encoding="utf-8"
            )
        )

    except (OSError, ValueError):
        return []

    if not isinstance(raw, list):

        return []

    feeds: list[Feed] = []

    for entry in raw:

        if not isinstance(entry, dict):
            continue

        name = entry.get("name")
        url = entry.get("url")

        if (
            isinstance(name, str)
            and name.strip()
            and isinstance(url, str)
            and url.strip()
        ):

            feeds.append(
                Feed(
                    name=name.strip(),
                    url=url.strip(),
                )
            )

    return feeds


def save(
    feeds: list[Feed],
) -> None:
    """
    Write the list back, creating the directory it lives in.
    """

    path = config.feeds_path()

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            [
                {
                    "name": feed.name,
                    "url": feed.url,
                }
                for feed in feeds
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def add(
    name: str,
    url: str,
) -> list[Feed]:
    """
    Remember a URL under `name`, replacing whatever that name held.
    """

    feeds = [
        feed
        for feed in load()
        if feed.name.lower() != name.lower()
    ]

    feeds.append(
        Feed(
            name=name,
            url=url,
        )
    )

    save(feeds)

    return feeds


def remove(
    name: str,
) -> list[Feed]:
    """
    Forget the feed called `name`.
    """

    feeds = load()

    kept = [
        feed
        for feed in feeds
        if feed.name.lower() != name.lower()
    ]

    if len(kept) == len(feeds):

        raise RuntimeError(_no_such(name))

    save(kept)

    return kept


def find(
    name: str,
) -> Feed:
    """
    The feed called `name`, by name or by the number --feeds prints.
    """

    feeds = load()

    for number, feed in enumerate(feeds, start=1):

        if (
            feed.name.lower() == name.lower()
            or name == str(number)
        ):

            return feed

    raise RuntimeError(_no_such(name))


def title_for(
    url: str,
) -> str:
    """
    What a listing calls itself, for a feed saved without a name.

    The source is asked, through the hook it publishes - YouTube asks the
    playlist, RTÉ reads the programme's page.
    """

    from .sources import detect

    source = detect(url)

    naming = getattr(
        source,
        "listing_title",
        None,
    )

    if naming is None:

        raise RuntimeError(
            "--add-feed names a feed after the listing it saves, which "
            "not every source can be asked for; give --name for this one"
        )

    return naming(url)


def _no_such(
    name: str,
) -> str:
    return f"no feed called {name!r}; --feeds lists the saved ones"
