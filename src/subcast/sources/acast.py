"""Acast: the shows it hosts, and the pages of the publishers it serves.

Acast publishes a feed for every show it hosts, and a page states which
one in one of two ways. Its own show page - `shows.acast.com/<show>` -
links the feed it is published as, and the path is not that feed's name:
a show's slug there says `inside-politics` where its feed says
`inside-politics-2`, so the page is read rather than the URL rewritten.
A publisher's own page links no feed at all; every card of one show
there plays from the same stream, and that stream's id is the show's, so
the feed is built from the audio the page itself plays.

What comes back is a podcast feed either way, and everything after it -
the episodes, their audio, how long they run - is what `sources.podcast`
reads for any feed. An episode reached through a publisher's page and one
reached through the show's own feed are the same item, under the same id.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from . import fetch_text
from .podcast import FeedSource, feed_link

NAME = "acast"

# Acast's own pages: one show, by its slug or by its id.
SHOW_HOSTS = frozenset(
    {
        "shows.acast.com",
    }
)

SHOW_RE = re.compile(
    r"^/(?P<show>[^/]+)/?$",
    re.IGNORECASE,
)

# Publisher pages whose own episodes are published on Acast. A page
# cannot be asked what it is before it is fetched, so this is what such a
# page looks like: the site, and the shape of its show listing.
PUBLISHER_HOSTS = frozenset(
    {
        "irishtimes.com",
        "www.irishtimes.com",
    }
)

PUBLISHER_RE = re.compile(
    r"^/podcasts/(?P<show>[a-z0-9-]+)/?$",
    re.IGNORECASE,
)

# The feed of a show, named by the id its episodes are served from.
FEED_URL = "https://feeds.acast.com/public/shows/{show}"

# Where a page's own episodes are served from, which names the show they
# are published as.
STREAM_RE = re.compile(
    r"https://feeds\.acast\.com/public/streams/"
    r"(?P<show>[0-9a-f-]+)/episodes/",
    re.IGNORECASE,
)


def page_feed(
    page_html: str,
) -> str:
    """
    The feed the episodes a publisher's page carries are published as.

    A page whose episodes are spread over more than one stream is a page
    about several shows, and there is no one feed to read it as: taking
    one of them would play another show's episodes without saying so, so
    each feed found is offered instead.
    """

    shows = {
        match.group("show").lower()
        for match in STREAM_RE.finditer(page_html)
    }

    if not shows:

        raise RuntimeError(
            "that page carries no podcast audio to read"
        )

    if len(shows) > 1:

        raise RuntimeError(
            "that page carries more than one podcast; play one of them "
            "from its feed: "
            + ", ".join(
                FEED_URL.format(show=show)
                for show in sorted(shows)
            )
        )

    return FEED_URL.format(
        show=shows.pop()
    )


class Acast(FeedSource):
    """
    A show published on Acast: Acast's own page for it, or the page of a
    publisher it serves.
    """

    name = NAME

    def matches(
        self,
        url: str,
    ) -> bool:

        parts = urlsplit(url)

        if parts.scheme not in ("http", "https") or not parts.netloc:

            return False

        host = parts.netloc.lower()

        if host in SHOW_HOSTS:

            return SHOW_RE.search(parts.path) is not None

        if host in PUBLISHER_HOSTS:

            return PUBLISHER_RE.search(parts.path) is not None

        return False

    def feed_url(
        self,
        url: str,
    ) -> str:
        """
        The feed a page's show is published as: the one Acast's own page
        links, or the one a publisher's page names in its own audio.
        """

        page = fetch_text(url)

        if urlsplit(url).netloc.lower() in SHOW_HOSTS:

            return feed_link(page)

        return page_feed(page)


SOURCE = Acast()
