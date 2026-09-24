"""Filesystem locations and defaults."""

from __future__ import annotations

import os
from pathlib import Path

SAVE_DIR = Path(
    "~/Videos"
).expanduser()

# Audio and subtitles kept for replay: a --subs run has to download the
# episode anyway, and transcribing it twice would be wasteful.
CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME")
    or "~/.cache"
).expanduser() / "subcast"

# How long a run keeps what it cached. The audio, the transcript heard from
# it and the files written beside it are the tool's own copy of an item, so
# the next run drops the whole of it once it has gone untouched for longer
# than this (`retention.sweep`).
RETENTION_DAYS = 7

# What the user chose rather than what the tool remembers: the feeds list.
CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME")
    or "~/.config"
).expanduser() / "subcast"

# Whisper model used by --subs when none is given.
DEFAULT_WHISPER_MODEL = "small.en"

# How much of a listing a menu shows when --limit is not given: enough to
# choose from, and little enough that opening a channel that has thousands
# of videos is not a wait. --limit 0 asks for the whole listing, and
# SUBSCAST_LIMIT changes what the default is.
DEFAULT_LIST_LIMIT = 30

LIST_LIMIT_ENVIRONMENT = "SUBSCAST_LIMIT"


def feeds_path() -> Path:
    """
    Where the saved feeds live.

    Outside the checkout on purpose: the feeds are the one thing here that
    is the user's rather than the tool's.
    """

    return CONFIG_DIR / "feeds.json"


def list_limit() -> int:
    """
    How much of a listing a menu shows: DEFAULT_LIST_LIMIT, or whatever
    SUBSCAST_LIMIT says. A setting that cannot be read is the default
    rather than an error - it is not worth refusing to play over.
    """

    try:

        return max(
            int(
                os.environ.get(
                    LIST_LIMIT_ENVIRONMENT,
                    "",
                )
            ),
            0,
        )

    except ValueError:
        return DEFAULT_LIST_LIMIT


def cache_dir(
    source: str,
) -> Path:
    """
    Where a source keeps cached audio, transcripts and subtitles.
    """

    return CACHE_DIR / source


def save_dir(
    source: str,
) -> Path:
    """
    Where --save puts finished episodes, one directory per source.
    """

    return SAVE_DIR / source
