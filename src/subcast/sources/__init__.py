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
    segments: tuple[Segment, ...] = ()

    @property
    def is_audio(self) -> bool:
        return self.kind == "audio"


class Source(Protocol):
    """
    A place episodes come from.
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

    from . import rte, youtube

    for source in (youtube.SOURCE, rte.SOURCE):

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

    from . import rte, youtube

    for source in (youtube.SOURCE, rte.SOURCE):

        if source.name == name:
            return source

    return None


def default() -> Source:
    """
    The source used when no URL is given.
    """

    from . import rte

    return rte.SOURCE
