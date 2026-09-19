"""Chapter files (ffmetadata) for mpv."""

from __future__ import annotations

from pathlib import Path


def escape_ffmetadata(
    text: str,
) -> str:
    """
    Escape the characters that carry meaning in an ffmetadata header.
    """

    for character in ("\\", "=", ";", "#"):
        text = text.replace(
            character,
            "\\" + character,
        )

    return text

def write_chapters_file(
    segments: list[tuple[float, float, str]],
    title: str,
    path: Path,
) -> Path:
    """
    mpv chapters file, so the published segments can be jumped through.
    """

    lines = [
        ";FFMETADATA1",
        f"title={escape_ffmetadata(title)}",
        "",
    ]

    for start, end, segment_title in segments:

        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={int(start * 1000)}",
                f"END={int(end * 1000)}",
                f"title={escape_ffmetadata(segment_title)}",
                "",
            ]
        )

    temp_path = path.with_name(
        path.name + ".part"
    )

    temp_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    temp_path.replace(path)

    return path
