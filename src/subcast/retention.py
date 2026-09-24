"""Dropping what a run cached long enough ago that it is not wanted back.

The cache is the tool's own copy of an item: the audio a run downloaded to
hear, the transcript it heard from that audio, the subtitles, the segments
and the position written beside them. It grows with every captioned item
and nothing here ever removed any of it, so a run sweeps what has gone
untouched for `config.RETENTION_DAYS` before it reads any of it.

An item goes whole or not at all. A transcript is only in pace with the
audio it was heard from - a site that stitches ads into a request answers a
different length the second time, which is why a captioned run plays the
copy its cues belong to - so a transcript whose audio has been dropped
would time a later run's captions against audio nobody heard.

The sweep is one pass over one directory per source, and it happens before
the run has looked at anything, so it cannot take a file out from under the
run doing it. It reads no file's bytes - one `scandir` and one `stat` per
file is the whole of the work - which is why it is a step of the run itself
rather than a thread or a scheduled job: a thread would race the run that
started it, and a sweeper outside the tool would have to find the cache
(`XDG_CACHE_HOME` is not in cron's environment) and to know which files
belong to an item.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import config

SECONDS_PER_DAY = 24 * 60 * 60


def sweep(
    days: float = config.RETENTION_DAYS,
) -> int:
    """
    Drop every cached item left untouched for more than `days`, and answer
    how many items went.
    """

    cutoff = time.time() - days * SECONDS_PER_DAY

    dropped = 0

    for directory in config.CACHE_DIR.glob("*"):

        if not directory.is_dir():

            continue

        for _key, files, touched in _items(directory):

            if touched >= cutoff:

                continue

            try:

                for path in files:

                    path.unlink(
                        missing_ok=True
                    )

            # A file that will not go - a cache on a read-only mount, a
            # directory somebody else owns - is left for the next run
            # rather than reported: nothing a run does depends on it.
            except OSError:

                continue

            dropped += 1

    return dropped


def _items(
    directory: Path,
) -> list[tuple[str, list[Path], float]]:
    """
    The cached items in one source's directory: the files each one left,
    and when the last of them was written.

    An item's files all begin with its own key and a dot - `<id>.mp3`,
    `<id>.cues.json`, `<id>.position` - so the key is what stands in front
    of the first dot. The newest file is when the item was last used, which
    is what its age is measured by: a run that resumes an old episode, or
    renders its subtitles again, keeps the whole of it.

    A directory is not an item's: `listings/` is a menu, kept for what it
    says rather than for how new it is (`listing.KEEP_FOR`), and a menu is
    read again anyway.
    """

    files: dict[str, list[Path]] = {}
    touched: dict[str, float] = {}

    try:

        entries = list(
            os.scandir(directory)
        )

    except OSError:

        return []

    for entry in entries:

        if not entry.is_file():

            continue

        try:

            written = entry.stat().st_mtime

        except OSError:

            continue

        key = entry.name.partition(".")[0]

        files.setdefault(
            key,
            [],
        ).append(
            Path(entry.path)
        )

        touched[key] = max(
            touched.get(key, 0.0),
            written,
        )

    return [
        (key, found, touched[key])
        for key, found in files.items()
    ]
