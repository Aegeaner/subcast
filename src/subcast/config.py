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

# Whisper model used by --subs when none is given.
DEFAULT_WHISPER_MODEL = "small.en"


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
