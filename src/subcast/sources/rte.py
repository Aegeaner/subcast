"""RTÉ Morning Ireland: show and episode lookup, media resolution."""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .media import sanitize_filename
from .segments import clip_start_from_title


SHOW_URL = (
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

EPISODE_RE = re.compile(
    r"/radio/radio1/morning-ireland/episodes/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.I,
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

def find_latest_episode(
    show_html: str,
) -> tuple[str, str]:
    soup = BeautifulSoup(
        show_html,
        "html.parser",
    )

    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = a["href"].strip()

        absolute = urljoin(
            SHOW_URL,
            href,
        )

        if EPISODE_RE.search(
            absolute.rstrip("/")
        ):
            title = a.get_text(
                " ",
                strip=True,
            )

            return (
                absolute.rstrip("/") + "/",
                title,
            )

    raise RuntimeError(
        "Could not find a concrete Morning Ireland episode URL."
    )

def extract_episode_title(
    episode_html: str,
    fallback: str,
) -> str:
    """
    Get the actual title from the concrete episode page.

    The show listing may expose only:
        Morning Ireland

    while the episode page contains:
        Morning Ireland - 4 September 2026
    """

    soup = BeautifulSoup(
        episode_html,
        "html.parser",
    )

    # ------------------------------------------------------------
    # Prefer H1
    # ------------------------------------------------------------

    for h1 in soup.find_all("h1"):
        text = h1.get_text(
            " ",
            strip=True,
        )

        if not text:
            continue

        # Usually the wanted form is:
        # Morning Ireland - 4 September 2026
        if "Morning Ireland" in text:
            return text

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
                content = content.strip()

                if content:
                    return content

    # ------------------------------------------------------------
    # HTML title
    # ------------------------------------------------------------

    if soup.title:
        text = soup.title.get_text(
            " ",
            strip=True,
        )

        if text:
            # Remove common site suffixes.
            text = re.sub(
                r"\s*\|\s*Morning Ireland.*$",
                "",
                text,
                flags=re.I,
            ).strip()

            text = re.sub(
                r"\s+-\s+RTÉ Radio 1.*$",
                "",
                text,
                flags=re.I,
            ).strip()

            if text:
                return text

    return fallback

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
        clip_start_from_title(title)
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

        except Exception as exc:
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

                except Exception:
                    pass

        except Exception as exc:

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

                    except Exception:
                        continue

                if clicked:
                    break

            except Exception:
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

            except Exception:
                pass

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

            except Exception:
                pass

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

        except Exception as exc:

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

        except Exception:
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
        key = match.group(1).lower()

    else:
        key = sanitize_filename(
            title
        ).replace(" ", "_")

    return key
