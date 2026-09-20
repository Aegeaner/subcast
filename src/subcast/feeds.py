"""Feeds: the listings worth coming back to, saved under a name.

A feed here is a URL kept in the user's config directory so it plays by
name instead of being pasted again: a YouTube channel or playlist, an RTÉ
programme, a BBC Audio page, a Bloomberg series, or a podcast feed's own
URL. What a feed is *not* is the source that reads it - the URL decides
that, and the same source lists many programmes (Morning Ireland and This
Week are both RTÉ) - so each one worth coming back to is a feed of its
own, under a name of its own.

`DEFAULT` is the one feed that is built in: the listing a run with no URL
opens. It is a feed like any other rather than a property of its source,
because which programme opens by default is a fact about the user's
habits, not about RTÉ.

An RSS document is a feed in the other sense of the word. `sources.podcast`
reads it, and saving one here saves a listing like any other.
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


# The listing a run with no URL opens: Morning Ireland, the programme
# subcast is built around. It lives here rather than on the RTÉ source
# because a source is a pipeline, not a programme - and neither Morning
# Ireland nor This Week belongs to it.
DEFAULT = Feed(
    name="Morning Ireland",
    url="https://www.rte.ie/radio/radio1/morning-ireland/",
)


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
    Remember a URL under `name`.

    A name that already means another URL is refused rather than quietly
    replaced: a name is how a feed is asked for, the same show is often
    published twice (a channel and the programme's own page), and a name
    that starts meaning something else is how a run plays the wrong
    thing. Removing the feed is how a name is made to mean this URL.
    """

    feeds = load()

    for feed in feeds:

        if feed.name.lower() != name.lower():

            continue

        if feed.url == url:

            return feeds

        raise RuntimeError(
            f"the feed {feed.name!r} already points at {feed.url}; "
            "give this one another --name, or --remove-feed it first"
        )

    if name.strip().lower() == DEFAULT.name.lower():

        raise RuntimeError(
            f"{DEFAULT.name!r} is the built-in feed - the one a run with "
            "no URL opens - so it is not a name to save this URL under; "
            "give this one another --name"
        )

    feeds = feeds + [
        Feed(
            name=name,
            url=url,
        )
    ]

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

        if name.strip().lower() == DEFAULT.name.lower():

            raise RuntimeError(
                f"{DEFAULT.name!r} is the built-in feed, not one of the "
                "saved ones: it is what a run with no URL opens, and "
                "there is nothing to forget"
            )

        raise RuntimeError(_no_such(name))

    save(kept)

    return kept


def find(
    name: str,
) -> Feed:
    """
    The feed called `name`, by name or by the number --feeds prints.

    A name is tried before a number, so a feed that is itself called "2"
    is still findable by it. The built-in feed answers to its own name
    like any other, which is why it can be opened on purpose and not only
    by giving no URL at all.
    """

    feeds = load()

    wanted = name.strip().lower()

    for feed in feeds:

        if feed.name.lower() == wanted:

            return feed

    if DEFAULT.name.lower() == wanted:

        return DEFAULT

    if wanted.isdigit() and 1 <= int(wanted) <= len(feeds):

        return feeds[int(wanted) - 1]

    raise RuntimeError(_no_such(name))


def source_of(
    url: str,
) -> str:
    """
    The name of the source that reads a URL, or "" when nothing does.

    A feed outlives the source that serves it: a site can stop being
    supported and a URL can be saved ahead of the source that will read
    it, and neither is a reason for listing the feeds to fail.
    """

    from .sources import detect

    try:

        return detect(url).name

    except RuntimeError:
        return ""


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
    return f"no feed called {name!r}; --feeds lists the ones there are"
