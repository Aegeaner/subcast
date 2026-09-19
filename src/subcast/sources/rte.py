"""RTÉ Radio 1: programme and episode lookup, media resolution.

A programme is a listing URL. Its page lists the episodes RTÉ published,
and an episode page carries the clip list and the player embed; what a
programme knows about itself - its name, when it airs - is read from its
own page, so nothing here belongs to one programme.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    sync_playwright,
)

from ..media import sanitize_filename
from ..segments import clip_clock_seconds
from . import Media, Segment

# The programme subcast plays when no URL is given.
DEFAULT_SHOW_URL = (
    "https://www.rte.ie/radio/radio1/morning-ireland/"
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-IE,en;q=0.9",
}

# Every programme is served by the same pages: /radio/<station>/<show>/
# lists the episodes RTÉ published, and one episode lives under
# /episodes/<uuid>. Those pages are what this source handles - nothing
# else on rte.ie is a programme.
EPISODE_RE = re.compile(
    r"(?P<show_path>/radio/(?P<station>[a-z0-9-]+)/"
    r"(?P<show>[a-z0-9-]+))/episodes/"
    r"(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)

SHOW_RE = re.compile(
    r"/radio/[a-z0-9-]+/[a-z0-9-]+/?$",
    re.IGNORECASE,
)

# A programme's own schedule line, in the hero card of its page: "Mon -
# Fri • 07:00 - 09:00". Only the start of it is wanted - it is what a
# clock-titled clip ("8am News Bulletin") is measured against.
SCHEDULE_RE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*"
    r"(?:\s*-\s*[A-Z][a-z]{2,8})?"
    r"\s*•\s*(\d{1,2}):(\d{2})",
    re.IGNORECASE,
)

# An episode card leads with the title and then repeats the date and
# states the length: "Morning Ireland - 18 September 2026 Fri 18 Sep  •
# 2 Hr 0 Mins • Morning Ireland".
CARD_DAY_RE = re.compile(
    r"\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$"
)

CARD_HOURS_RE = re.compile(
    r"(\d+)\s*Hrs?\b",
    re.IGNORECASE,
)

CARD_MINUTES_RE = re.compile(
    r"(\d+)\s*Mins?\b",
    re.IGNORECASE,
)

# The hero card's own words are a call to action rather than a name: the
# dated card below it is what names the episode.
CARD_CALL_RE = re.compile(
    r"^Listen\b",
    re.IGNORECASE,
)

# What every page of the site adds to a title it names itself.
SITE_SUFFIX_RE = re.compile(
    r"\s*(?:\||-)\s*RTÉ Radio 1\s*$",
    re.IGNORECASE,
)

def http_get(
    session: requests.Session,
    url: str,
    referer: str | None = None,
):
    headers = dict(HEADERS)

    if referer:
        headers["Referer"] = referer

    response = session.get(
        url,
        headers=headers,
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response

def extract_episode_title(
    episode_html: str,
    fallback: str,
) -> str:
    """
    What a page names itself.

    A programme page carries only the programme; an episode page carries
    the programme and the date:

        This Week - 13th September 2026

    so the caller passes what it already knows as the fallback.
    """

    soup = BeautifulSoup(
        episode_html,
        "html.parser",
    )

    # ------------------------------------------------------------
    # OpenGraph title
    # ------------------------------------------------------------

    for attrs in (
        {"property": "og:title"},
        {"name": "twitter:title"},
    ):
        tag = soup.find(
            "meta",
            attrs=attrs,
        )

        if tag:
            content = tag.get("content")

            if content:
                content = SITE_SUFFIX_RE.sub(
                    "",
                    content.strip(),
                ).strip()

                if content:
                    return content

    # ------------------------------------------------------------
    # Then a heading
    # ------------------------------------------------------------

    for h1 in soup.find_all("h1"):
        text = h1.get_text(
            " ",
            strip=True,
        )

        if not text:
            continue

        text = SITE_SUFFIX_RE.sub(
            "",
            text,
        ).strip()

        if text:
            return text

    # ------------------------------------------------------------
    # HTML title
    # ------------------------------------------------------------

    if soup.title:
        text = soup.title.get_text(
            " ",
            strip=True,
        )

        if text:
            text = SITE_SUFFIX_RE.sub(
                "",
                text,
            ).strip()

            if text:
                return text

    return fallback

def show_url(
    url: str,
) -> str:
    """
    The programme page an episode belongs to; a programme page itself
    comes back with its own trailing slash.
    """

    trimmed = url.rstrip("/")

    match = EPISODE_RE.search(trimmed)

    if match is None:
        return trimmed + "/"

    return trimmed[: match.end("show_path")] + "/"

def programme_name(
    url: str,
) -> str:
    """
    What to call a programme before its episode page has been read: its
    slug, spelled out ("another-show" -> "Another Show"). The resolve
    replaces it with what the episode calls itself.
    """

    slug = show_url(url).rstrip("/").rsplit(
        "/",
        1,
    )[-1]

    return slug.replace(
        "-",
        " ",
    ).title()

def scheduled_start(
    html: str,
) -> float | None:
    """
    The time of day a programme's audio begins, from its own schedule
    line: what a clock-titled clip is measured against.

    A page that states no schedule leaves the clip times unusable rather
    than guessed at, which is what every programme but Morning Ireland
    publishes anyway - their clip titles carry no clock time.
    """

    match = SCHEDULE_RE.search(html)

    if match is None:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if hour > 23 or minute > 59:
        return None

    return float(
        hour * 3600
        + minute * 60
    )

def card_title(
    text: str,
) -> str:
    """
    The title an episode card leads with: everything before the date it
    repeats and the length it states. The hero card's call to action is
    no title at all.
    """

    head = text.split(
        "•"
    )[0].strip()

    if CARD_CALL_RE.match(head):
        return ""

    return CARD_DAY_RE.sub(
        "",
        head,
    ).strip()

def card_duration(
    text: str,
) -> float | None:
    """
    The length an episode card states: "1 Hr 5 Mins", "59 Mins".
    """

    hours = CARD_HOURS_RE.search(text)
    minutes = CARD_MINUTES_RE.search(text)

    if hours is None and minutes is None:
        return None

    total = 0

    if hours is not None:
        total += int(hours.group(1)) * 3600

    if minutes is not None:
        total += int(minutes.group(1)) * 60

    return float(total)

def fetched_title(
    session: requests.Session,
    episode_url: str,
    referer: str,
) -> str:
    """
    What an episode calls itself, for a hero card that names nothing.

    One extra request, and only where the programme's page does not give
    the newest episode a dated card of its own, so a menu's first line
    reads like every other line of it.
    """

    page = http_get(
        session,
        episode_url,
        referer=referer,
    )

    return extract_episode_title(
        page.text,
        programme_name(episode_url),
    )

def find_episode_clips(
    episode_html: str,
) -> list[tuple[str, float]]:
    """
    Read the segment list RTÉ publishes with every episode.

    The page embeds it as:

        var clips = [{"title": "8am News Bulletin",
                      "duration": 367000, ...}, ...];
        var title = "Episode Clips";

    Titles and durations only - RTÉ publishes no in-show offsets, so
    positions have to be derived (see build_segments).

    Returns (title, duration in seconds) in broadcast order, or an
    empty list when the episode page carries no clip list.
    """

    marker = episode_html.find(
        'var title = "Episode Clips"'
    )

    if marker < 0:
        return []

    blocks = list(
        re.finditer(
            r"var\s+\w+\s*=\s*\[",
            episode_html[:marker],
        )
    )

    if not blocks:
        return []

    start = blocks[-1].end() - 1
    end = episode_html.find("];", start)

    if end < 0:
        return []

    try:
        raw = json.loads(
            episode_html[start:end + 1]
        )

    except ValueError:
        return []

    clips: list[tuple[str, float]] = []

    for clip in raw:

        if not isinstance(clip, dict):
            continue

        title = str(
            clip.get("title") or ""
        ).strip()

        duration = clip.get("duration")

        if (
            not title
            or not isinstance(
                duration,
                (int, float),
            )
            or duration <= 0
        ):
            continue

        clips.append(
            (
                title,
                duration / 1000.0,
            )
        )

    # RTÉ publishes some clip lists newest-first; the clock times in the
    # titles tell which way round this one is.
    clock_times = [
        clip_clock_seconds(title)
        for title, _ in clips
    ]

    known = [
        seconds
        for seconds in clock_times
        if seconds is not None
    ]

    if (
        len(known) > 1
        and known == sorted(
            known,
            reverse=True,
        )
    ):
        clips.reverse()

    return clips

def find_dustin_iframe(
    episode_html: str,
    episode_url: str,
) -> str:
    soup = BeautifulSoup(
        episode_html,
        "html.parser",
    )

    for iframe in soup.find_all(
        "iframe",
        src=True,
    ):
        src = urljoin(
            episode_url,
            iframe["src"],
        )

        if "/media-embed/dustin/" in src:
            return src

    for iframe in soup.find_all(
        "iframe",
        src=True,
    ):
        src = urljoin(
            episode_url,
            iframe["src"],
        )

        if "/media-embed/" in src:
            return src

    raise RuntimeError(
        "RTÉ Dustin media iframe was not found."
    )

def resolve_audio(
    iframe_url: str,
) -> str:

    found_urls: list[str] = []

    def remember(
        url: str,
        source: str,
    ) -> None:

        if not url:
            return

        if url in found_urls:
            return

        low = url.lower()

        markers = (
            ".mp3",
            ".m4a",
            ".aac",
            ".m3u8",
            "/audio/direct/",
            "tritondigital.com",
            "omny.fm",
            "media-session",
        )

        if not any(
            x in low
            for x in markers
        ):
            return

        found_urls.append(url)

        print(
            f"    [{source}] {url}",
            flush=True,
        )

    def is_final_audio(
        url: str,
    ) -> bool:

        low = url.lower()

        return (
            ".mp3" in low
            or "/audio/direct/" in low
        )

    with sync_playwright() as p:

        print(
            "    Launching Chromium...",
            flush=True,
        )

        try:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies",
                ],
            )

        except Exception as exc:

            # The most common cause by far is that the browsers were never
            # installed for this interpreter, or were installed by a
            # different Playwright version (the cache is per revision).
            raise RuntimeError(
                "Could not launch Chromium for Playwright. If the "
                "browser is missing, or was installed by another "
                "Playwright version, run:\n"
                f"    {sys.executable} -m playwright install chromium"
            ) from exc

        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="en-IE",
            extra_http_headers={
                "Accept-Language": "en-IE,en;q=0.9",
            },
        )

        page = context.new_page()

        # ------------------------------------------------------------
        # Network
        # ------------------------------------------------------------

        page.on(
            "request",
            lambda request: remember(
                request.url,
                "request",
            ),
        )

        page.on(
            "response",
            lambda response: remember(
                response.url,
                f"response {response.status}",
            ),
        )

        page.on(
            "requestfailed",
            lambda request: print(
                f"    [requestfailed] "
                f"{request.url} -> {request.failure}",
                flush=True,
            ),
        )

        page.on(
            "console",
            lambda msg: print(
                f"    [console {msg.type}] "
                f"{msg.text}",
                flush=True,
            ),
        )

        page.on(
            "pageerror",
            lambda exc: print(
                f"    [pageerror] {exc}",
                flush=True,
            ),
        )

        # ------------------------------------------------------------
        # Open player
        # ------------------------------------------------------------

        print(
            "    Opening player...",
            flush=True,
        )

        try:
            page.goto(
                iframe_url,
                wait_until="commit",
                timeout=20_000,
            )

        except PlaywrightError as exc:
            print(
                f"    Navigation notice: {exc}",
                flush=True,
            )

        # ------------------------------------------------------------
        # Wait briefly for Angular/player UI to render.
        # ------------------------------------------------------------

        page.wait_for_timeout(
            3_000
        )

        # ------------------------------------------------------------
        # Dump buttons so we know what Dustin rendered.
        # ------------------------------------------------------------

        print(
            "    Inspecting player controls...",
            flush=True,
        )

        try:

            controls = page.locator(
                "button, [role='button'], "
                "[aria-label], [title]"
            )

            count = controls.count()

            print(
                f"    Found {count} possible controls",
                flush=True,
            )

            for i in range(
                min(count, 30)
            ):

                try:

                    el = controls.nth(i)

                    text = el.inner_text(
                        timeout=500
                    ).strip()

                    aria = el.get_attribute(
                        "aria-label"
                    )

                    title = el.get_attribute(
                        "title"
                    )

                    print(
                        f"      #{i}: "
                        f"text={text!r} "
                        f"aria={aria!r} "
                        f"title={title!r}",
                        flush=True,
                    )

                except (PlaywrightError, AttributeError, RuntimeError):
                    # Not every control can be inspected; skip it.
                    pass

        except PlaywrightError as exc:

            print(
                f"    Control inspection failed: {exc}",
                flush=True,
            )

        # ------------------------------------------------------------
        # Try to activate Play.
        # ------------------------------------------------------------

        print(
            "    Attempting to start playback...",
            flush=True,
        )

        play_selectors = [
            "button[aria-label*='Play' i]",
            "[role='button'][aria-label*='Play' i]",
            "[aria-label='Play']",
            "[title*='Play' i]",

            "button.play",
            ".play-button",
            ".playButton",
            ".player-play",
            ".player__play",
            ".controls-play",
            ".control-play",

            "button:has(.play)",
            "button:has(.fa-play)",
            "button:has(.icon-play)",
            "button:has(svg)",
        ]

        clicked = False

        for selector in play_selectors:

            try:

                locator = page.locator(
                    selector
                )

                n = locator.count()

                if n == 0:
                    continue

                for i in range(n):

                    try:

                        element = locator.nth(i)

                        if not element.is_visible():
                            continue

                        print(
                            f"    Clicking: "
                            f"{selector} [{i}]",
                            flush=True,
                        )

                        element.click(
                            timeout=2_000,
                            force=True,
                        )

                        clicked = True
                        break

                    except (PlaywrightError, AttributeError, RuntimeError):
                        # Not clickable; try the next control.
                        continue

                if clicked:
                    break

            except (PlaywrightError, AttributeError, RuntimeError):
                # The selector could not be used; try the next one.
                continue

        # ------------------------------------------------------------
        # Fallback: press Space after focusing player.
        # ------------------------------------------------------------

        if not clicked:

            print(
                "    No Play button matched; "
                "trying keyboard activation...",
                flush=True,
            )

            try:

                page.keyboard.press(
                    "Tab"
                )

                page.keyboard.press(
                    "Space"
                )

                clicked = True

            except PlaywrightError as exc:

                print(
                    f"    Keyboard activation failed: {exc}",
                    flush=True,
                )

        # ------------------------------------------------------------
        # Final fallback: center click.
        # ------------------------------------------------------------

        if not clicked:

            print(
                "    Trying center click...",
                flush=True,
            )

            try:

                page.mouse.click(
                    150,
                    80,
                )

                clicked = True

            except PlaywrightError as exc:

                print(
                    f"    Center click failed: {exc}",
                    flush=True,
                )

        if clicked:

            print(
                "    Playback activation attempted.",
                flush=True,
            )

        else:

            print(
                "    Could not activate playback.",
                flush=True,
            )

        # ------------------------------------------------------------
        # Wait for actual network request.
        # ------------------------------------------------------------

        print(
            "    Monitoring audio network traffic...",
            flush=True,
        )

        for second in range(45):

            # Direct MP3 -> immediately return.
            for url in found_urls:

                if is_final_audio(url):

                    print(
                        "    Direct audio URL found.",
                        flush=True,
                    )

                    browser.close()

                    return url

            if (
                second == 0
                or second % 5 == 0
            ):

                print(
                    f"    Waiting... {second}s "
                    f"(interesting URLs: "
                    f"{len(found_urls)})",
                    flush=True,
                )

            page.wait_for_timeout(
                1_000
            )

        # ------------------------------------------------------------
        # Performance API
        # ------------------------------------------------------------

        print(
            "    Checking browser resource entries...",
            flush=True,
        )

        try:

            resources = page.evaluate(
                """
                () => performance
                    .getEntriesByType("resource")
                    .map(x => x.name)
                """
            )

            for url in resources:

                if isinstance(
                    url,
                    str,
                ):

                    remember(
                        url,
                        "performance",
                    )

        except PlaywrightError as exc:

            print(
                f"    Performance inspection failed: {exc}",
                flush=True,
            )

        # ------------------------------------------------------------
        # DOM audio
        # ------------------------------------------------------------

        try:

            dom_urls = page.locator(
                "audio, source"
            ).evaluate_all(
                """
                els => els
                    .map(e => e.currentSrc || e.src)
                    .filter(Boolean)
                """
            )

            for url in dom_urls:

                if isinstance(
                    url,
                    str,
                ):

                    remember(
                        url,
                        "dom",
                    )

        except (
            PlaywrightError,
            AttributeError,
            TypeError,
        ):
            # A frame without media is not an error; try the next one.
            pass

        # ------------------------------------------------------------
        # Prefer MP3.
        # ------------------------------------------------------------

        for url in found_urls:

            if is_final_audio(url):

                browser.close()

                return url

        # ------------------------------------------------------------
        # Show what was actually captured.
        # ------------------------------------------------------------

        print(
            "\n    Interesting URLs captured:",
            file=sys.stderr,
        )

        if found_urls:

            for url in found_urls:

                print(
                    f"      {url}",
                    file=sys.stderr,
                )

        else:

            print(
                "      (none)",
                file=sys.stderr,
            )

        browser.close()

    raise RuntimeError(
        "The RTÉ player was loaded and activated, "
        "but no direct audio URL was captured."
    )

def verify_audio(
    url: str,
    referer: str,
) -> str:

    session = requests.Session()

    response = session.get(
        url,
        headers={
            **HEADERS,
            "Referer": referer,
            "Range": "bytes=0-1023",
        },
        stream=True,
        timeout=30,
        allow_redirects=True,
    )

    try:

        content_type = (
            response.headers
            .get("Content-Type", "")
            .lower()
        )

        print(
            f"    HTTP {response.status_code}"
            f" Content-Type={content_type}",
            flush=True,
        )

        if response.status_code not in (
            200,
            206,
        ):

            raise RuntimeError(
                f"Media URL returned HTTP "
                f"{response.status_code}"
            )

        return response.url

    finally:
        response.close()

def media_headers(
    referer: str,
) -> dict[str, str]:
    """
    Request headers the RTÉ media endpoints expect.
    """

    return {
        **HEADERS,
        "Referer": referer,
    }

def episode_key(
    episode_url: str,
    title: str,
) -> str:
    """
    Cache name for an episode: its UUID when the URL carries one.
    """

    match = EPISODE_RE.search(
        episode_url.rstrip("/")
    )

    if match:
        key = match.group("uuid").lower()

    else:
        key = sanitize_filename(
            title
        ).replace(" ", "_")

    return key


def find_episodes(
    show_html: str,
    base_url: str,
    limit: int | None = None,
) -> list[tuple[str, str, float | None]]:
    """
    The episodes a programme page links, newest first, as (URL, title,
    duration).

    The newest episode is linked from its hero card - which says no more
    than "Listen LATEST episode" - and again from the dated list under it,
    so entries are keyed by episode id and the one that names the episode
    best is kept. A hero with no dated card of its own comes back
    untitled, which is what the caller reads the episode page for.
    """

    soup = BeautifulSoup(
        show_html,
        "html.parser",
    )

    episodes: dict[str, tuple[str, str, float | None]] = {}

    for anchor in soup.find_all(
        "a",
        href=True,
    ):

        absolute = (
            urljoin(
                base_url,
                anchor["href"].strip(),
            ).rstrip("/")
            + "/"
        )

        match = EPISODE_RE.search(
            absolute.rstrip("/")
        )

        if match is None:
            continue

        text = anchor.get_text(
            " ",
            strip=True,
        )

        title = card_title(text)

        key = match.group("uuid").lower()

        known = episodes.get(key)

        if known is not None and len(known[1]) >= len(title):
            continue

        episodes[key] = (
            absolute,
            title,
            card_duration(text),
        )

    listed = list(
        episodes.values()
    )

    return listed[:limit] if limit else listed


def episode_duration(
    episode_html: str,
) -> float | None:
    """
    The duration RTÉ states for an episode, in seconds.
    """

    match = re.search(
        r'<meta\s+name="duration"\s+content="(\d+)"',
        episode_html,
    )

    if not match:
        return None

    return int(match.group(1)) / 1000.0


class Rte:
    """
    RTÉ Radio 1.

    Any programme page is a listing, and an episode URL is one item.
    Listing is one request; resolving an episode means reading its page
    and then driving the RTÉ player in a headless browser to find the
    audio the player itself would stream - which is why an item of this
    source is never streamed from its page URL (`Media.stream` is False
    here and in `resolve`), the way a YouTube page can be.
    """

    name = "rte"

    def matches(
        self,
        url: str,
    ) -> bool:

        parts = urlsplit(url)

        host = parts.netloc.lower()

        if not (host == "rte.ie" or host.endswith(".rte.ie")):
            return False

        return (
            EPISODE_RE.search(parts.path.rstrip("/")) is not None
            or SHOW_RE.search(parts.path) is not None
        )

    def episodes(
        self,
        url: str,
        limit: int | None = None,
    ) -> list[Media]:

        target = url or DEFAULT_SHOW_URL

        if EPISODE_RE.search(target.rstrip("/")):

            return [
                Media(
                    source=self.name,
                    key=episode_key(target, ""),
                    title=programme_name(target),
                    url=target,
                    kind="audio",
                    stream=False,
                )
            ]

        session = requests.Session()

        listing = http_get(
            session,
            target,
        )

        clock_start = scheduled_start(
            listing.text
        )

        items: list[Media] = []

        for episode_url, title, duration in find_episodes(
            listing.text,
            target,
            limit,
        ):

            items.append(
                Media(
                    source=self.name,
                    key=episode_key(episode_url, title),
                    title=(
                        title
                        or fetched_title(
                            session,
                            episode_url,
                            target,
                        )
                    ),
                    url=episode_url,
                    kind="audio",
                    duration=duration,
                    stream=False,
                    clock_start=clock_start,
                )
            )

        return items

    def listing_title(
        self,
        url: str,
    ) -> str:
        """
        What a programme calls itself, for a feed saved under its name.
        """

        page = http_get(
            requests.Session(),
            show_url(url),
        )

        return extract_episode_title(
            page.text,
            programme_name(url),
        )

    def resolve(
        self,
        media: Media,
    ) -> Media:

        session = requests.Session()

        show = show_url(media.url)

        episode = http_get(
            session,
            media.url,
            referer=show,
        )

        title = extract_episode_title(
            episode.text,
            media.title or programme_name(media.url),
        )

        clips = find_episode_clips(
            episode.text
        )

        # Only a clip list with clock times in it needs the programme's
        # schedule, and only when the listing this item came from did not
        # already read it off the programme's page.
        clock_start = media.clock_start

        if clock_start is None and any(
            clip_clock_seconds(clip_title) is not None
            for clip_title, _ in clips
        ):

            clock_start = scheduled_start(
                http_get(
                    session,
                    show,
                ).text
            )

        iframe_url = find_dustin_iframe(
            episode.text,
            media.url,
        )

        stream_url = verify_audio(
            resolve_audio(iframe_url),
            media.url,
        )

        return Media(
            source=self.name,
            key=media.key,
            title=title,
            url=stream_url,
            kind="audio",
            duration=episode_duration(episode.text),
            referer=media.url,
            headers=tuple(
                media_headers(media.url).items()
            ),
            stream=False,
            captions=(),
            segments=tuple(
                Segment(
                    title=clip_title,
                    duration=clip_duration,
                )
                for clip_title, clip_duration in find_episode_clips(
                    episode.text
                )
            ),
        )


SOURCE = Rte()
