"""Apple Podcasts: the page a link is, read as the feed it is published as.

Every page of the podcast site is rendered from one payload - the document
embedded in it - and a page that is a show states the feed the show is
published as, which is the URL a podcast client is served. A page that is
one episode of a show states the guid the feed gives that episode as well,
so a link to an episode is that item of the feed rather than the newest one
the show published: the guid is the feed's own name for it, and nothing has
to be matched by title.

What comes back is a podcast feed, and everything after that - the
episodes, their audio, how long they run - is what `sources.podcast` reads
for any feed.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from . import Media, fetch_text
from .podcast import FeedSource

NAME = "apple"

HOSTS = frozenset(
    {
        "podcasts.apple.com",
        "itunes.apple.com",
    }
)

# What a link to the podcast site is: a show, which is the link a listener
# subscribes with, or a channel, which is a group of shows. The storefront
# and the slug are parts of the path a link may or may not carry, so the id
# is what such a page is recognised by. `itunes.apple.com/us/podcast/id123`
# is the form those links had before the site had a name of its own, and it
# is still served.
PAGE_RE = re.compile(
    r"^/(?:[a-z]{2}/)?(?P<kind>podcast|channel)/"
    r"(?:[^/]+/)*?id(?P<id>\d+)/?$",
    re.IGNORECASE,
)

# The payload a page is rendered from, which is where the feed is.
PAYLOAD_RE = re.compile(
    r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# What a channel page is, which is the one kind of page on the site that is
# not something to play: a channel is a group of shows.
CHANNEL_KIND = "ChannelPageIntent"


def page_feed(
    page_html: str,
) -> tuple[str, str]:
    """
    The feed a page's show is published as, and the guid of the episode the
    page names - "" for a page that names only a show.

    The feed is read off the page's own item rather than off the page: a
    page carries other shows beside the one it is about, each with a feed of
    its own, and the item the payload says the page is about is the one
    whose feed is the show's.
    """

    root = _root(page_html)
    intent = root.get("intent") or {}
    kind = str(intent.get("$kind") or "")

    if kind == CHANNEL_KIND:

        raise RuntimeError(
            "that Apple Podcasts link is a channel, which is a group of "
            "shows rather than one of them: play the show you want"
        )

    item = _own_item(
        root,
        str(intent.get("adamId") or ""),
    )

    if item is None:

        raise RuntimeError(
            "that Apple Podcasts page named no show to read"
        )

    context = item.get("contextAction") or {}

    # An episode page's item offers the episode it is about; a show page's
    # offers the show, and the episode it would play first is an action
    # beside it rather than the subject of the page.
    episode = (
        context.get("episodeOffer")
        if kind == "EpisodePageIntent"
        else None
    )

    offer = (
        (episode or {}).get("showOffer")
        or context.get("podcastOffer")
        or {}
    )

    feed = str(offer.get("feedUrl") or "").strip()

    if not feed:

        raise RuntimeError(
            "that Apple Podcasts page names no feed to read"
        )

    return (
        feed,
        str((episode or {}).get("guid") or "").strip(),
    )


def _root(
    page_html: str,
) -> dict:
    """
    The page's own part of the payload it was rendered from.
    """

    match = PAYLOAD_RE.search(page_html)

    if match is None:

        raise RuntimeError(
            "that Apple Podcasts page carried no show to read"
        )

    try:

        data = json.loads(match.group(1))

    except ValueError as error:

        raise RuntimeError(
            "that Apple Podcasts page carried a show this cannot read: "
            f"{error}"
        ) from error

    pages = data.get("data")

    if (
        not isinstance(pages, list)
        or not pages
        or not isinstance(pages[0], dict)
    ):

        raise RuntimeError(
            "that Apple Podcasts page carried no show to read"
        )

    return pages[0]


def _own_item(
    root: dict,
    page_id: str,
):
    """
    The item of the payload that is the page's own subject.

    Every card of a page states its feed, so the one that is this page's is
    the one that answers to the id the page was asked for - the show's, or
    the episode's.
    """

    if not page_id:

        return None

    for shelf in (root.get("data") or {}).get("shelves") or []:

        if not isinstance(shelf, dict):

            continue

        for item in shelf.get("items") or []:

            if not isinstance(item, dict):

                continue

            if page_id in {
                str(item.get("id") or ""),
                str(item.get("adamId") or ""),
                str(item.get("showId") or ""),
            }:

                return item

    return None


class Apple(FeedSource):
    """
    An Apple Podcasts show, or one episode of it.
    """

    name = NAME

    def matches(
        self,
        url: str,
    ) -> bool:
        """
        Whether a URL is a page of the podcast site.

        A channel is one: it has no feed to play, and is matched so that a
        link to one is refused by what it is rather than as a URL nothing
        knows how to handle.
        """

        parts = urlsplit(url)

        if parts.scheme not in ("http", "https") or not parts.netloc:

            return False

        if parts.netloc.lower() not in HOSTS:

            return False

        return PAGE_RE.search(parts.path) is not None

    def page(
        self,
        url: str,
    ) -> tuple[str, str]:
        """
        The feed a page names and the episode it names: one fetch, because
        the payload the page is rendered from holds both.
        """

        return page_feed(fetch_text(url))

    def feed_url(
        self,
        url: str,
    ) -> str:

        return self.page(url)[0]

    def episodes(
        self,
        url: str,
        limit: int | None = None,
    ) -> list[Media]:
        """
        What a page is: the feed's own listing, or the one episode the page
        names.

        An episode link names one item of the feed by the guid the feed
        gives it, which is neither the newest item nor the count a menu
        asked for.
        """

        feed, guid = self.page(url)

        _title, items = self.reading(
            fetch_text(feed)
        )

        if not guid:

            return items[:limit] if limit else items

        named = [
            item
            for item in items
            if item.key == guid
        ]

        if not named:

            raise RuntimeError(
                f"{url} names an episode the feed does not carry"
            )

        return named


SOURCE = Apple()
