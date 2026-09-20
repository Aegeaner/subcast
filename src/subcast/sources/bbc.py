"""BBC Audio: what a page lists, and the audio an episode plays from.

Every page of the audio site is rendered from one document - the payload
embedded in it - so a brand or series page lists its episodes, a
category page lists the programmes it is a directory of, and a schedule
lists the programmes a station puts out over a day. Reading that is one
fetch for a whole listing, however many items it holds: nothing has to
be asked about each episode.

A page names an episode and its length but not the version of it the
audio belongs to, which is what the syndication URL every podcast client
uses is built from. That comes from the programme's own JSON - a few
kilobytes, asked for when the item is played - and the audio behind it
is an mp3 on a redirect, which mpv follows like any other URL.

A category page is a directory of programmes rather than episodes, so an
item that is a programme plays that programme's newest episode, which is
what its own page leads with.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from . import Media, fetch_text

NAME = "bbc"

HOSTS = frozenset(
    {
        "bbc.com",
        "www.bbc.com",
        "bbc.co.uk",
        "www.bbc.co.uk",
    }
)

# What a page of the audio site can be: a programme (a brand), a series,
# a category to browse, one episode to play, or a station's schedule.
# A schedule's id is a service, whose names carry an underscore.
AUDIO_RE = re.compile(
    r"^/audio/(?P<kind>brand|series|category|play|schedules)/"
    r"(?P<id>[a-z0-9_]+)/?$",
    re.IGNORECASE,
)

# The payload a page is rendered from, which is where its listing is.
PAYLOAD_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# The card type that is an episode: a page also carries its own card, and
# the programme to play next.
EPISODE_TYPE = "audio-episode"

# The programme's own JSON, where the version lives and where an episode
# is really named.
PROGRAMME_API = "https://www.bbc.co.uk/programmes/{pid}.json"

# The mp3 podcast clients are served, built from the version id. It is a
# redirect to a signed URL, so it is built when an item is played rather
# than written down in a listing that outlives it.
STREAM_URL = (
    "https://open.live.bbc.co.uk/mediaselector/6/redir/version/2.0/"
    "mediaset/audio-nondrm-download-rss/proto/https/vpid/{vpid}.mp3"
)

# The version BBC publishes for download. A programme that has aired
# lists the version it aired as, and a podcast version beside it where the
# episode is published on demand; the syndication URL every client is
# served carries the latter, and answers 404 for the former.
PODCAST_TYPE = "podcast version"

# How much of a programme one page carries: a listing deeper than this
# asks for the pages it needs.
PAGE_SIZE = 10

# The card types that are the page's own subject rather than an episode
# under it.
OWN_CARD_TYPES = (
    "audio-brand",
    "audio-series",
)


def payload(
    html: str,
) -> dict:
    """
    What a page was rendered from, as the props its payload carries.
    """

    match = PAYLOAD_RE.search(html)

    if match is None:

        raise RuntimeError(
            "that BBC page carried no listing"
        )

    try:

        data = json.loads(match.group(1))

    except ValueError as error:

        raise RuntimeError(
            "that BBC page carried a listing this cannot read: "
            f"{error}"
        ) from error

    props = (data.get("props") or {}).get("pageProps")

    if isinstance(props, dict):

        return props

    raise RuntimeError(
        "that BBC page carried no listing"
    )


def node_of(
    props: dict,
) -> dict:
    """
    The part of a payload that is the page's own contents.
    """

    node = (
        props.get("page") or {}
    ).get(
        props.get("pageKey") or ""
    )

    return node if isinstance(node, dict) else {}


def page_items(
    html: str,
    base: str,
) -> list[Media]:
    """
    What a page lists, in the order it lists it.

    A programme or series page lists episodes under its own card; a
    category page lists the programmes its sections are about; a single
    episode page lists that one episode; a station's schedule lists the
    programme each part of its day is.
    """

    node = node_of(
        payload(html)
    )

    found: list[Media] = []

    contents = node.get("contents")

    if isinstance(contents, list):

        for card in contents:

            if not isinstance(card, dict):

                continue

            item = episode_media(
                str(card.get("type") or ""),
                card.get("model") or {},
                base,
            )

            if item is not None:

                found.append(item)

    sections = node.get("sections")

    if isinstance(sections, list):

        for section in sections:

            if not isinstance(section, dict):

                continue

            for card in section.get("content") or []:

                if not isinstance(card, dict):

                    continue

                item = directory_media(
                    card,
                    base,
                )

                if item is not None:

                    found.append(item)

    for entry in schedule_entries(node):

        item = schedule_media(
            entry,
            base,
        )

        if item is not None:

            found.append(item)

    return dedupe(found)


def episode_media(
    kind: str,
    model: dict,
    base: str,
) -> Media | None:
    """
    One episode a page lists, or None when a card is not an episode.
    """

    if kind != EPISODE_TYPE:

        return None

    pid = str(model.get("id") or "").strip()
    path = str(model.get("path") or "").strip()

    if not pid or not path:

        return None

    return Media(
        source=NAME,
        key=pid,
        title=str(model.get("title") or "").strip() or pid,
        url=urljoin(base, path),
        kind="audio",
        duration=card_duration(model),
        stream=False,
    )


def directory_media(
    card: dict,
    base: str,
) -> Media | None:
    """
    One entry of a category page: an episode, which plays, or a
    programme, which plays its newest episode.
    """

    pid = str(card.get("id") or "").strip()
    href = str(card.get("href") or "").strip()

    if not pid or not href:

        return None

    metadata = card.get("metadata")

    duration = (
        float(metadata["duration"])
        if isinstance(metadata, dict)
        and isinstance(metadata.get("duration"), (int, float))
        else None
    )

    return Media(
        source=NAME,
        key=pid,
        title=str(card.get("title") or "").strip() or pid,
        url=urljoin(base, href),
        kind="audio",
        duration=duration,
        stream=False,
    )


def section_cards(
    node: dict,
) -> list[dict]:
    """
    The cards a page's sections hold.

    Everything a section renders is one card, whatever the section is
    for: a category's directory, or the station a schedule runs under.
    """

    cards: list[dict] = []

    for section in node.get("sections") or []:

        if not isinstance(section, dict):

            continue

        for card in (section.get("model") or {}).get("blocks") or []:

            if isinstance(card, dict):

                cards.append(card)

    return cards


def schedule_entries(
    node: dict,
) -> list[dict]:
    """
    A station's day, in the order the day runs.

    The day is not the page's contents but the entries under the card a
    section draws for the station.
    """

    entries: list[dict] = []

    for card in section_cards(node):

        for entry in (card.get("model") or {}).get("blocks") or []:

            if (
                isinstance(entry, dict)
                and isinstance(entry.get("episode"), dict)
            ):

                entries.append(entry)

    return entries


def schedule_media(
    entry: dict,
    base: str,
) -> Media | None:
    """
    One programme a station puts out, as an item to play.

    A schedule entry also carries the version it airs as, which is not
    what an item plays - the version a listener is served comes out of
    the programme's own JSON, the way it does for any episode of this
    source.
    """

    episode = entry.get("episode") or {}

    pid = str(episode.get("id") or "").strip()
    path = str(episode.get("path") or "").strip()

    if not pid or not path:

        return None

    return Media(
        source=NAME,
        key=pid,
        title=schedule_title(entry) or pid,
        url=urljoin(base, path),
        kind="audio",
        duration=iso_seconds(
            str(episode.get("duration") or "")
        ),
        stream=False,
    )


def schedule_title(
    entry: dict,
) -> str:
    """
    What a schedule entry is, as the entry names it.

    The entry's own title is the date it airs on when the station is
    relaying something, so the programme it is a slot of - its brand -
    is the useful name.
    """

    brand = entry.get("brand")

    if isinstance(brand, dict):

        title = str(brand.get("title") or "").strip()

        if title:

            return title

    return str(entry.get("title") or "").strip()


def card_duration(
    model: dict,
) -> float | None:
    """
    The length a card states, off the version it plays.
    """

    for block in model.get("blocks") or []:

        if not isinstance(block, dict):

            continue

        versions = (
            block.get("model") or {}
        ).get("versions")

        if (
            isinstance(versions, list)
            and versions
            and isinstance(versions[0], dict)
        ):

            return iso_seconds(
                str(versions[0].get("duration") or "")
            )

    return None


def iso_seconds(
    text: str,
) -> float | None:
    """
    A length stated as a clock: "00:26:29.000".
    """

    parts = text.strip().split(":")

    if len(parts) != 3:

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


def page_title(
    html: str,
) -> str:
    """
    What a page calls what it lists.

    A programme or series page names itself with its own card; an
    episode page names the programme the episode belongs to, and falls
    back to the episode when the card does not carry one; a category
    page carries its own title, and a schedule the station it runs.
    """

    node = node_of(
        payload(html)
    )

    contents = node.get("contents")

    if (
        isinstance(contents, list)
        and contents
        and isinstance(contents[0], dict)
    ):

        card = contents[0]
        model = card.get("model") or {}

        if str(card.get("type") or "") in OWN_CARD_TYPES:

            return str(model.get("title") or "").strip()

        brand = model.get("brand")

        if isinstance(brand, dict) and brand.get("title"):

            return str(brand["title"]).strip()

        return str(model.get("title") or "").strip()

    title = str(node.get("title") or "").strip()

    if title:

        return title

    # A schedules page names itself on the card the day runs under, which
    # is the station rather than the page.
    for card in section_cards(node):

        name = str(card.get("title") or "").strip()

        if name:

            return name

    return ""


def episode_id(
    url: str,
) -> str | None:
    """
    The episode a URL names, if it names one rather than a page that
    lists them.
    """

    match = AUDIO_RE.search(
        urlsplit(url).path
    )

    if match is None or match.group("kind").lower() != "play":

        return None

    return match.group("id")


def stream_url(
    vpid: str,
) -> str:
    """
    The mp3 a version of an episode is served as.
    """

    return STREAM_URL.format(
        vpid=vpid
    )


def version_types(
    version: dict,
) -> list[str]:
    """
    What a version says it is, so a type can be matched on.
    """

    return [
        str(one).strip().lower()
        for one in version.get("types") or []
    ]


def playable_version(
    programme: dict,
) -> tuple[str, float | None] | None:
    """
    The version of a programme that can be played, and how long it runs.

    A programme that has aired lists the version it aired as first, and
    the syndication URL every client is served does not carry that one:
    where the episode is published on demand a podcast version is listed
    beside it, and that is the one to play. A programme with one version -
    or none the site types - plays the first it lists.
    """

    versions = [
        version
        for version in programme.get("versions") or []
        if isinstance(version, dict)
    ]

    if not versions:

        return None

    chosen = next(
        (
            version
            for version in versions
            if PODCAST_TYPE in version_types(version)
        ),
        versions[0],
    )

    vpid = str(chosen.get("pid") or "").strip()

    if not vpid:

        return None

    duration = chosen.get("duration")

    return (
        vpid,
        float(duration)
        if isinstance(duration, (int, float))
        else None,
    )


def dedupe(
    items: list[Media],
) -> list[Media]:
    """
    The items, with a repeat of one the page links twice dropped: a
    category's sections overlap, and a programme has its own page.
    """

    seen: set[str] = set()
    kept: list[Media] = []

    for item in items:

        if item.key in seen:

            continue

        seen.add(item.key)
        kept.append(item)

    return kept


def take(
    items: list[Media],
    limit: int | None,
) -> list[Media]:

    return items[:limit] if limit else items


def page_url(
    url: str,
    page: int,
) -> str:

    return f"{url.rstrip('/')}?page={page}"


class Bbc:
    """
    BBC Audio: a programme's episodes, a category's programmes, one
    episode.
    """

    name = NAME

    def matches(
        self,
        url: str,
    ) -> bool:

        parts = urlsplit(url)

        return (
            parts.netloc.lower() in HOSTS
            and AUDIO_RE.search(parts.path) is not None
        )

    def episodes(
        self,
        url: str,
        limit: int | None = None,
    ) -> list[Media]:

        match = AUDIO_RE.search(
            urlsplit(url).path
        )

        kind = (
            match.group("kind").lower()
            if match
            else ""
        )

        if kind not in ("brand", "series"):

            # A category carries its whole directory and one episode is
            # one item: neither is paged.
            return take(
                page_items(
                    fetch_text(url),
                    url,
                ),
                limit,
            )

        return take(
            self.paged(
                url,
                limit,
            ),
            limit,
        )

    def paged(
        self,
        url: str,
        limit: int | None,
    ) -> list[Media]:
        """
        A programme's episodes, one page of the site at a time.

        A page states ten of them, so a deeper listing asks for the pages
        it needs; a page that adds nothing new ends it, which is what
        keeps a listing that has run out from asking for more.
        """

        items: list[Media] = []
        page = 0

        while True:

            html = fetch_text(
                page_url(url, page)
                if page
                else url
            )

            found = page_items(
                html,
                url,
            )

            merged = dedupe(items + found)

            if len(merged) == len(items):

                return items

            items = merged

            if (
                limit
                and len(items) >= limit
            ) or len(found) < PAGE_SIZE:

                return items

            page += 1

    def resolve(
        self,
        media: Media,
    ) -> Media:
        """
        An episode as the thing to play: the mp3 its version is served
        as.

        A page lists episodes without saying which version of one the
        audio belongs to, so the programme's own JSON is asked - one
        small request - and the syndication URL is built from what it
        says. An item that is a programme rather than an episode plays
        that programme's newest episode.
        """

        page = media.url

        pid = episode_id(page)

        if pid is None:

            pid = self.newest_episode(page)

        programme = self.programme(pid)

        version = playable_version(programme)

        if version is None:

            raise RuntimeError(
                f"BBC lists no playable version of {pid} ({page}); "
                "an episode it no longer offers audio for plays nothing"
            )

        vpid, duration = version

        return Media(
            source=NAME,
            key=pid,
            title=str(programme.get("title") or media.title),
            url=stream_url(vpid),
            kind="audio",
            duration=duration or media.duration,
            referer=page,
            stream=False,
        )

    def programme(
        self,
        pid: str,
    ) -> dict:
        """
        What BBC says about an episode, off its own JSON.
        """

        try:

            document = json.loads(
                fetch_text(
                    PROGRAMME_API.format(pid=pid)
                )
            )

        except ValueError as error:

            raise RuntimeError(
                f"BBC returned nothing readable for {pid}"
            ) from error

        programme = document.get("programme")

        if isinstance(programme, dict):

            return programme

        raise RuntimeError(
            f"BBC has no episode {pid}"
        )

    def newest_episode(
        self,
        url: str,
    ) -> str:
        """
        The first episode a page lists, for a programme that was asked
        for rather than an episode.
        """

        for item in page_items(
            fetch_text(url),
            url,
        ):

            pid = episode_id(item.url)

            if pid:

                return pid

        raise RuntimeError(
            f"{url} lists no episode to play"
        )

    def listing_title(
        self,
        url: str,
    ) -> str:
        """
        What a page calls what it lists, for a feed saved under its name.
        """

        title = page_title(
            fetch_text(url)
        )

        if not title:

            raise RuntimeError(
                f"{url} does not name what it lists"
            )

        return title


SOURCE = Bbc()
