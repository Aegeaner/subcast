"""Bloomberg podcasts, read where Bloomberg publishes them.

A Bloomberg series page is served by a bot filter that answers a plain
fetch with 403 - with a browser user agent, and with the whole set of
headers a browser sends - so this source reads the same show from the
platform its podcasts are hosted on: the show page names the programme
and links the feed it is syndicated as. The slug is the same on both,
`/podcasts/series/<name>` being `omny.fm/shows/<name>`.

What comes back is a podcast feed, and everything after that - the
episodes, their audio, the transcripts published beside them - is what
`sources.podcast` reads for any feed.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from . import fetch_text
from .podcast import FeedSource, feed_link

NAME = "bloomberg"

HOSTS = frozenset(
    {
        "bloomberg.com",
        "www.bloomberg.com",
    }
)

SERIES_RE = re.compile(
    r"^/podcasts/series/(?P<slug>[a-z0-9-]+)/?$",
    re.IGNORECASE,
)

SHOW_URL = "https://omny.fm/shows/{slug}"

# How many items one request for the feed asks for: the feed states it,
# so a run that needs one episode does not download a thousand.
PAGE_SIZE_PARAMETER = "pageSize"


def series_slug(
    url: str,
) -> str:
    """
    The show a series URL names.
    """

    match = SERIES_RE.search(
        urlsplit(url).path
    )

    if match is None:

        raise RuntimeError(
            f"{url} is not a Bloomberg podcast; a series page is "
            "/podcasts/series/<name>"
        )

    return match.group("slug").lower()


def sized(
    url: str,
    limit: int | None,
) -> str:
    """
    A feed URL asked for `limit` items - the whole feed when there is no
    limit, which is what a menu of everything wants.
    """

    if not limit:

        return url

    joiner = "&" if "?" in url else "?"

    return f"{url}{joiner}{PAGE_SIZE_PARAMETER}={limit}"


class Bloomberg(FeedSource):
    """
    A Bloomberg podcast series, as the feed it is published as.
    """

    name = NAME

    def matches(
        self,
        url: str,
    ) -> bool:

        parts = urlsplit(url)

        return (
            parts.netloc.lower() in HOSTS
            and SERIES_RE.search(parts.path) is not None
        )

    def feed_url(
        self,
        url: str,
    ) -> str:
        """
        A series page's feed: the show page names it, and the show page
        is the one thing about the show that answers.
        """

        slug = series_slug(url)

        return feed_link(
            fetch_text(
                SHOW_URL.format(slug=slug)
            )
        )

    def feed_text(
        self,
        url: str,
        limit: int | None,
    ) -> str:

        return fetch_text(
            sized(
                self.feed_url(url),
                limit,
            )
        )


SOURCE = Bloomberg()
