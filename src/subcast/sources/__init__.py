"""Where media comes from, and what the rest of the pipeline needs.

A source turns a URL (or nothing at all, for the default source) into
`Media` records: what to play, which captions the site already publishes,
and what its segments are. Everything downstream - acquiring, transcribing,
aligning, rendering, playing - works on those records and does not care
which site they came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests

# What a source says it is when it fetches a page. The sites subcast
# reads serve a browser, and some refuse anything else outright, so this
# is one definition rather than a per-site decision.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0 Safari/537.36"
)

FETCH_TIMEOUT = 30.0


def fetch_text(
    url: str,
    session: requests.Session | None = None,
) -> str:
    """
    The body of a page or feed a source reads.

    A refusal is raised as it comes: the caller's message says what it
    was reading, and the status code is the most useful thing to add to
    it. Sources that need headers of their own (RTÉ) fetch for
    themselves.
    """

    session = session or requests.Session()

    response = session.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en;q=0.9",
        },
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response.text


@dataclass(frozen=True)
class Segment:
    """
    A published piece of an episode.

    Sources that know exactly when a segment starts supply `start`;
    sources that only publish lengths supply `duration`, and the start is
    derived and then aligned against the transcript.
    """

    title: str
    start: float | None = None
    duration: float | None = None


@dataclass(frozen=True)
class Captions:
    """
    A subtitle track the site already publishes.
    """

    language: str
    url: str
    ext: str = "vtt"


@dataclass(frozen=True)
class Media:
    """
    One playable item.

    `key` identifies it within its source (an episode UUID, a video id) and
    names its cache files.
    """

    source: str
    key: str
    title: str
    url: str
    kind: str = "video"
    duration: float | None = None
    referer: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    stream: bool = True
    captions: tuple[Captions, ...] = ()

    # A programme whose clip titles carry clock times ("8am News
    # Bulletin"): the time of day its audio begins, in seconds since
    # midnight, which is what those titles are measured against. Sources
    # that publish no clock times leave it None.
    clock_start: float | None = None

    segments: tuple[Segment, ...] = ()

    # A broadcast, not a file: its captions have to be made while it airs,
    # because there is no finished recording to work from.
    live: bool = False

    @property
    def is_audio(self) -> bool:
        return self.kind == "audio"


class Source(Protocol):
    """
    A place episodes come from.

    A source may also offer `caption_file(url, language, stem)`, which the
    subtitle pipeline calls when the caption URL it was handed does not
    itself yield WebVTT: sources whose captions come as playlists need it
    to get the text out their own way (yt-dlp, for YouTube).

    A source that can name a listing may offer `listing_title(url)`, which
    is what a feed saved without `--name` is called.
    """

    name: str

    def matches(
        self,
        url: str,
    ) -> bool:
        """
        Whether this source handles the URL.
        """
        ...

    def episodes(
        self,
        url: str,
        limit: int | None = None,
    ) -> list[Media]:
        """
        The items a URL points at: one for a single video, many for a
        playlist or a show listing. Cheap - metadata only.
        """
        ...

    def resolve(
        self,
        media: Media,
    ) -> Media:
        """
        Fill in what playing an item needs: the stream, its captions, its
        segments. This is the step allowed to be slow.
        """
        ...


def detect(
    url: str,
) -> Source:
    """
    The source that handles a URL.
    """

    from . import acast, apple, bbc, bloomberg, podcast, rte, youtube

    for source in (
        youtube.SOURCE,
        bbc.SOURCE,
        bloomberg.SOURCE,
        # a show page on acast.com is taken for a feed by the host rule
        # below, so the source that reads those pages is asked first
        acast.SOURCE,
        apple.SOURCE,
        podcast.SOURCE,
        rte.SOURCE,
    ):

        if source.matches(url):
            return source

    raise RuntimeError(
        f"No source knows how to handle {url}"
    )


def by_name(
    name: str,
) -> Source | None:
    """
    The source with this name, if it is one we know.
    """

    from . import acast, apple, bbc, bloomberg, podcast, rte, youtube

    for source in (
        youtube.SOURCE,
        bbc.SOURCE,
        bloomberg.SOURCE,
        acast.SOURCE,
        apple.SOURCE,
        podcast.SOURCE,
        rte.SOURCE,
    ):

        if source.name == name:
            return source

    return None
