"""Episode audio: naming, downloading, caching, probing."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

AUDIO_SUFFIXES = (
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
)

# How much of an audio URL a range probe asks for: enough to recognise the
# opening of the file, and small enough to cost nothing.
PROBE_BYTES = 64 * 1024

# What a ranged request is allowed to take. A span of audio is a few
# minutes, so this is a hang rather than a slow network.
RANGE_TIMEOUT = 60.0


@dataclass(frozen=True)
class Ranged:
    """
    What a server said about an audio URL: how long it is, how it opens, and
    what kind of audio it is. Two of these agreeing is what says the URL can
    be heard a span at a time (`subtitles.StreamedWhilePlaying`).
    """

    length: int
    opening: bytes
    extension: str


def range_probe(
    url: str,
    headers: dict[str, str],
) -> Ranged | None:
    """
    How long an audio URL is, how it opens and what it is, or None when the
    server will not serve a range.

    Two probes agreeing - the same length and the same opening bytes - are
    what says an item can be heard a span at a time while a player reads the
    same URL (`subtitles.StreamedWhilePlaying`). A site that stitches ads
    into a request answers a different length the second time, and such an
    item is downloaded whole instead: the captions have to belong to the
    copy that plays.
    """

    with requests.get(
        url,
        headers=_range_headers(
            headers,
            0,
            PROBE_BYTES - 1,
        ),
        timeout=RANGE_TIMEOUT,
        stream=True,
        allow_redirects=True,
    ) as response:

        if response.status_code != 206:

            return None

        length = _length_of(response)
        opening = response.raw.read(PROBE_BYTES)
        extension = guess_audio_extension(
            response.headers.get("Content-Type", ""),
            url,
        )

    if length is None or len(opening) < PROBE_BYTES:

        return None

    return Ranged(
        length=length,
        opening=opening,
        extension=extension,
    )


def fetch_range(
    url: str,
    headers: dict[str, str],
    first: int,
    last: int,
) -> bytes:
    """
    Bytes `first` to `last` of an audio URL, both inclusive, as a range
    means them.

    Only what has been probed is fetched, so a server that will not serve a
    range is refused rather than answered with the whole file.
    """

    with requests.get(
        url,
        headers=_range_headers(
            headers,
            first,
            last,
        ),
        timeout=RANGE_TIMEOUT,
        allow_redirects=True,
    ) as response:

        if response.status_code != 206:

            raise RuntimeError(
                f"{url} answered {response.status_code} to a range "
                "request, so it cannot be heard a span at a time"
            )

        return response.content


def _range_headers(
    headers: dict[str, str],
    first: int,
    last: int,
) -> dict[str, str]:

    return {
        **headers,
        "Range": f"bytes={first}-{last}",
    }


def _length_of(
    response,
) -> int | None:
    """
    The whole length a Content-Range states: "bytes 0-65535/116464259".
    """

    _range, _, total = response.headers.get(
        "Content-Range",
        "",
    ).partition("/")

    return int(total) if total.isdigit() else None


# What subcast says it is when it fetches audio: the browser the sites
# serve, and nothing else unless the source says so.
BROWSER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0 Safari/537.36"
)


def request_headers(
    media,
) -> dict[str, str]:
    """
    The headers an item's audio is fetched with, whoever is fetching it: a
    span heard while it plays, or the whole file.
    """

    return {
        "User-Agent": BROWSER_AGENT,
        **dict(media.headers),
    }


def sanitize_filename(
    name: str,
) -> str:

    name = name.strip()

    # Illegal/control characters.
    name = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        name,
    )

    # Normalize whitespace.
    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    # Normalize repeated underscores.
    name = re.sub(
        r"_+",
        "_",
        name,
    )

    # Remove trailing spaces/dots/underscores.
    name = name.rstrip(
        " ._"
    )

    if not name:
        name = "episode"

    # Keep the filename reasonably short.
    return name[:180]

def guess_audio_extension(
    content_type: str,
    final_url: str,
) -> str:

    content_type = content_type.lower()
    url = final_url.lower()

    if (
        "mpeg" in content_type
        or ".mp3" in url
    ):
        return ".mp3"

    if (
        "mp4" in content_type
        or ".m4a" in url
    ):
        return ".m4a"

    if (
        "aac" in content_type
        or ".aac" in url
    ):
        return ".aac"

    if (
        "ogg" in content_type
        or ".ogg" in url
    ):
        return ".ogg"

    # RTÉ direct audio endpoint normally returns MP3.
    return ".mp3"

def download_audio(
    url: str,
    stem: Path,
    headers: dict[str, str],
) -> Path:
    """
    Stream url into "<stem><extension>" and return the final path.

    The extension depends on the served content type, so the caller
    passes a stem without one.
    """

    stem.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = requests.Session()

    temp_path: Path | None = None

    try:

        with session.get(
            url,
            headers=headers,
            stream=True,
            timeout=60,
            allow_redirects=True,
        ) as response:

            response.raise_for_status()

            content_type = (
                response.headers
                .get("Content-Type", "")
                .lower()
            )

            extension = guess_audio_extension(
                content_type,
                response.url,
            )

            output_path = stem.with_name(
                stem.name + extension
            )

            temp_path = output_path.with_name(
                output_path.name
                + ".part"
            )

            total = response.headers.get(
                "Content-Length"
            )

            total_bytes = (
                int(total)
                if total
                and total.isdigit()
                else None
            )

            downloaded = 0
            last_reported_mb = -1

            print(
                f"    File: {output_path}",
                flush=True,
            )

            with open(
                temp_path,
                "wb",
            ) as file:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if not chunk:
                        continue

                    file.write(
                        chunk
                    )

                    downloaded += len(
                        chunk
                    )

                    current_mb = (
                        downloaded
                        // (
                            1024 * 1024
                        )
                    )

                    if (
                        current_mb
                        != last_reported_mb
                    ):

                        last_reported_mb = (
                            current_mb
                        )

                        if total_bytes:

                            percent = (
                                downloaded
                                / total_bytes
                                * 100
                            )

                            print(
                                f"\r    Downloaded: "
                                f"{downloaded / 1024 / 1024:.1f} MB "
                                f"({percent:.1f}%)",
                                end="",
                                flush=True,
                            )

                        else:

                            print(
                                f"\r    Downloaded: "
                                f"{downloaded / 1024 / 1024:.1f} MB",
                                end="",
                                flush=True,
                            )

            print()

        # Only expose the final filename after
        # the download completed successfully.
        temp_path.replace(
            output_path
        )

        print(
            f"    Saved successfully: "
            f"{output_path}",
            flush=True,
        )

        return output_path

    except BaseException:

        # A download that is interrupted is a download nobody wants the
        # remains of, so the partial file goes for Ctrl-C as much as for a
        # failure - and what ended the download is raised on unchanged.
        if temp_path is not None:

            try:
                temp_path.unlink(
                    missing_ok=True
                )
            # The temporary file is being discarded anyway.
            except OSError:
                pass

        raise

def find_cached_audio(
    directory: Path,
    key: str,
) -> Path | None:
    """
    Audio already downloaded for this episode, if any.
    """

    if not directory.is_dir():
        return None

    for path in sorted(
        directory.iterdir()
    ):

        if (
            path.stem == key
            and path.suffix.lower()
            in AUDIO_SUFFIXES
            and path.is_file()
        ):
            return path

    return None

def media_duration(
    path: Path,
) -> float:
    """
    Duration in seconds, straight from the downloaded file.
    """

    try:

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        return float(
            result.stdout.strip()
        )

    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def acquire(
    media,
    stem: Path,
) -> Path:
    """
    Local audio for a media item, downloaded once and reused.

    Sources that only expose a page (YouTube) go through their own
    downloader; sources that hand out a direct stream are fetched
    straight.
    """

    cached = find_cached_audio(
        stem.parent,
        stem.name,
    )

    if cached is not None:
        return cached

    if media.stream:

        from .sources import youtube

        return youtube.audio_download(
            media.url,
            stem,
        )

    return download_audio(
        media.url,
        stem,
        request_headers(media),
    )
