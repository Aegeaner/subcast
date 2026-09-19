"""Playback through mpv."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

def mpv_path() -> str:
    """
    Absolute path to mpv, or a RuntimeError explaining it is missing.
    """

    mpv = shutil.which(
        "mpv"
    )

    if not mpv:

        raise RuntimeError(
            "mpv was not found in PATH."
        )

    return mpv


def play_with_mpv(
    url: str,
    subtitle_path: Path | None = None,
    chapters_path: Path | None = None,
) -> int:

    mpv = mpv_path()

    print()
    print(
        "Starting mpv..."
    )
    print(
        f"    {url}"
    )

    if subtitle_path is not None:
        print(
            f"    {subtitle_path}"
        )

    print()

    command = [
        mpv,
        "--no-video",
        "--force-window=no",
        "--cache=yes",
    ]

    if subtitle_path is not None:

        command.extend(
            [
                f"--sub-file={subtitle_path}",

                # Print the subtitles in the terminal, and keep the
                # status line quiet so it does not redraw them.
                "--term-osd=force",
                "--term-status-msg=",
            ]
        )

    if chapters_path is not None:

        command.append(
            f"--chapters-file={chapters_path}"
        )

    command.append(
        str(url)
    )

    return subprocess.run(
        command,
        check=False,
    ).returncode
