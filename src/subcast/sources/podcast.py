"""Podcast feeds: the episodes an RSS feed publishes.

A feed is a listing and an episode list in one document, so one reading
serves a feed URL typed by hand and the feed a broadcaster's own show
page points at. Every item says where its audio is (the enclosure) and
how long it runs.

RSS is what podcast feeds are published as, and it is also where the
length lives (`itunes:duration`); Atom is not read. A transcript a feed
publishes (`podcast:transcript`) is not read either: it is timed against
the file the publisher made, and the file a client fetches is not always
that one - Bloomberg's arrives with ads stitched round the content, and
its transcript ran a sentence ahead of what plays - so the captions come
from hearing the audio, which is in pace with it by construction.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlsplit
from xml.etree import ElementTree

from . import Media, fetch_text

NAME = "podcast"

# The feed a page links, for a source whose show page is read to find one.
FEED_LINK_RE = re.compile(
    r'<link[^>]*type="application/rss\+xml"[^>]*>',
    re.IGNORECASE,
)

HREF_RE = re.compile(
    r'href="([^"]+)"',
    re.IGNORECASE,
)

# A URL that ends in one of these is a feed, and that is all most need:
# the format is in the name.
FEED_SUFFIXES = (
    ".rss",
    ".xml",
    ".atom",
)

# Hosts that serve a feed at a path that does not name the format
# ("feeds.megaphone.fm/BLM4711"), so a URL on one is taken at its word.
FEED_HOSTS = (
    "megaphone.fm",
    "simplecast.com",
    "acast.com",
    "omnycontent.com",
)

# Paths that end in one of these name a feed without naming a format.
FEED_TAILS = (
    "feed",
    "rss",
)


def parse_feed(
    text: str,
    source: str = NAME,
) -> tuple[str, list[Media]]:
    """
    What a feed calls itself, and the items it publishes, in its order.

    An item with no audio is not an episode - feeds carry text posts,
    trailers and videos - and neither is one whose audio cannot be
    found: an entry that plays nothing is worse than no entry.
    """

    try:

        root = ElementTree.fromstring(text)

    except ElementTree.ParseError as error:

        raise RuntimeError(
            f"that URL did not answer with a feed: {error}"
        ) from error

    if _local(root.tag) != "rss":

        raise RuntimeError(
            "that URL is a feed of a kind subcast does not read; "
            "RSS is what podcast feeds are published as"
        )

    channel = _first(root, "channel")

    if channel is None:

        raise RuntimeError(
            "that feed has no channel to read"
        )

    items = [
        item
        for item in (
            feed_item(entry, source)
            for entry in _children(channel, "item")
        )
        if item is not None
    ]

    return _text(channel, "title"), items


def feed_link(
    page_html: str,
) -> str:
    """
    The feed a page links.

    A show page of a host that syndicates its shows states the feed it is
    published as, which is the one thing about the show a page has to say
    about its episodes.
    """

    for tag in FEED_LINK_RE.findall(page_html):

        match = HREF_RE.search(tag)

        if match:

            return unescape(match.group(1))

    raise RuntimeError(
        "that show page links no feed to read"
    )


def feed_item(
    entry,
    source: str,
) -> Media | None:
    """
    One feed item as an item to play, or None when it holds no audio.

    The feed states everything a resolve would otherwise go and find, so
    the enclosure is the item's URL and there is nothing slow left in a
    run of this source.
    """

    audio = audio_url(entry)

    if not audio:

        return None

    return Media(
        source=source,
        key=_text(entry, "guid") or audio,
        title=_text(entry, "title") or "Untitled",
        url=audio,
        kind="audio",
        duration=duration_seconds(_text(entry, "duration")),
        stream=False,
    )


def audio_url(
    entry,
) -> str:
    """
    Where an item's audio lives.

    The enclosure is taken at its word when it states no type, because
    that is what the element means; a `media:content` has to say it is
    audio, because the same element also carries the item's image.
    """

    for child in entry:

        if _local(child.tag) != "enclosure":

            continue

        url = (child.get("url") or "").strip()
        kind = (child.get("type") or "").strip().lower()

        if url and (not kind or kind.startswith("audio/")):

            return url

    for child in entry:

        if _local(child.tag) != "content":

            continue

        url = (child.get("url") or "").strip()

        if url and (child.get("type") or "").lower().startswith("audio/"):

            return url

    return ""


def duration_seconds(
    text: str,
) -> float | None:
    """
    The length a feed states: seconds, or "MM:SS", or "HH:MM:SS".

    `itunes:duration` permits all three and feeds use all three, so they
    are read as parts of a base-sixty number rather than one at a time.
    """

    if not text.strip():

        return None

    parts = text.strip().split(":")

    if len(parts) > 3:

        return None

    seconds = 0.0

    for part in parts:

        try:

            seconds = seconds * 60 + float(
                part.replace(",", ".")
            )

        except ValueError:

            return None

    return seconds if seconds > 0 else None


def _local(
    tag: str,
) -> str:
    """
    A tag's name without the namespace it arrived in.

    Feeds spell the same element with whatever prefix they declare, so
    matching on the name is what lets one reading serve all of them.
    """

    return tag.rsplit("}", 1)[-1].lower()


def _children(
    element,
    name: str,
) -> list:
    return [
        child
        for child in element
        if _local(child.tag) == name
    ]


def _first(
    element,
    name: str,
):
    found = _children(
        element,
        name,
    )

    return found[0] if found else None


def _text(
    element,
    name: str,
) -> str:
    child = _first(
        element,
        name,
    )

    if child is None:

        return ""

    return (child.text or "").strip()


class FeedSource:
    """
    A source whose listing is a feed.

    The audio of an item and how long it runs are what the feed states,
    and that is all playing it needs: a resolve has nothing to find, and
    playback streams the enclosure directly, the way it streams any direct
    URL. Captions come from hearing the audio the run plays, like any item
    a site does not caption.
    """

    name = NAME

    def feed_url(
        self,
        url: str,
    ) -> str:
        """
        The feed a URL points at, which for a feed URL is itself.
        """

        raise NotImplementedError

    def feed_text(
        self,
        url: str,
        limit: int | None,
    ) -> str:
        """
        The feed's own text, asked for as much of it as this run needs.
        """

        return fetch_text(
            self.feed_url(url)
        )

    def episodes(
        self,
        url: str,
        limit: int | None = None,
    ) -> list[Media]:

        _title, items = parse_feed(
            self.feed_text(
                url,
                limit,
            ),
            self.name,
        )

        return items[:limit] if limit else items

    def resolve(
        self,
        media: Media,
    ) -> Media:
        """
        Nothing: the feed already said what playing this needs.
        """

        return media

    def listing_title(
        self,
        url: str,
    ) -> str:
        """
        What the feed calls itself, for a feed saved under its name.
        """

        title, _items = parse_feed(
            self.feed_text(
                url,
                None,
            ),
            self.name,
        )

        if not title:

            raise RuntimeError(
                f"{url} does not name the feed it carries"
            )

        return title


class Podcast(FeedSource):
    """
    Any RSS feed whose items enclose audio.
    """

    name = NAME

    def feed_url(
        self,
        url: str,
    ) -> str:

        return url

    def matches(
        self,
        url: str,
    ) -> bool:
        """
        Whether a URL is one to read as a feed.

        A URL cannot be asked what it is before it is fetched, so this is
        what feeds look like: the format in the name, a known feed host,
        or a path that ends in "feed" or "rss".
        """

        parts = urlsplit(url)

        if parts.scheme not in ("http", "https") or not parts.netloc:

            return False

        path = parts.path.rstrip("/").lower()

        if path.endswith(FEED_SUFFIXES):

            return True

        host = parts.netloc.lower()

        if any(
            host == known or host.endswith(f".{known}")
            for known in FEED_HOSTS
        ):

            return True

        return path.rsplit("/", 1)[-1] in FEED_TAILS


SOURCE = Podcast()
