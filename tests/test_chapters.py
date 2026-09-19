"""Chapter output: mpv has to be able to read the segment list back."""

from __future__ import annotations

from pathlib import Path

from subcast.chapters import write_chapters_file


def unescape(value: str) -> str:
    out = []
    index = 0

    while index < len(value):

        if (
            value[index] == "\\"
            and index + 1 < len(value)
        ):
            out.append(value[index + 1])
            index += 2

        else:
            out.append(value[index])
            index += 1

    return "".join(out)


def read_chapters(text: str) -> list[tuple[int, int, str]]:
    """Minimal ffmetadata reader: (start ms, end ms, title)."""

    chapters = []

    for block in text.split("[CHAPTER]")[1:]:

        fields = {}

        for line in block.strip().splitlines():
            key, _, value = line.partition("=")
            fields[key] = value

        chapters.append(
            (
                int(fields["START"]),
                int(fields["END"]),
                unescape(fields["title"]),
            )
        )

    return chapters


def test_chapters_survive_a_read_back(tmp_path: Path):
    segments = [
        (600.0, 783.0, "7.10am Headlines"),
        (
            783.0,
            1093.0,
            "Ferry terminal opens in Kilbride; No. 10 = Harbour",
        ),
    ]

    path = write_chapters_file(
        segments,
        "Example Show - 18 September 2026",
        tmp_path / "episode.chapters.txt",
    )
    text = path.read_text(encoding="utf-8")

    assert text.startswith(";FFMETADATA1\n")

    assert read_chapters(text) == [
        (600000, 783000, "7.10am Headlines"),
        (
            783000,
            1093000,
            "Ferry terminal opens in Kilbride; No. 10 = Harbour",
        ),
    ]

    # Metadata is separated by blank lines, as ffmpeg writes it.
    assert "\n\n[CHAPTER]\n" in text


def test_episode_title_is_carried_with_the_chapters(tmp_path: Path):
    path = write_chapters_file(
        [(0.0, 1.0, "Weather Forecast")],
        "Example Show - 18 September 2026",
        tmp_path / "episode.chapters.txt",
    )

    assert "title=Example Show - 18 September 2026" in path.read_text(
        encoding="utf-8"
    )
