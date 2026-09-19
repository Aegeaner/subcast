"""WebVTT captions: published subtitles, and YouTube's rolling ones."""

from __future__ import annotations

from pathlib import Path

from subcast.vtt import (
    parse_vtt,
    read_vtt,
)


def vtt(
    *blocks: str,
) -> str:
    """A WebVTT file whose cue blocks follow the header."""

    return "\n\n".join(
        (
            "WEBVTT",
            *blocks,
        )
    ) + "\n"


# One sentence revealed word by word the way YouTube redraws it: every
# step resends the line so far, one step revises the line shorter, and
# two steps are the same line twice.
ROLLING = vtt(
    "00:00:01.000 --> 00:00:03.000\nhello",
    "00:00:02.000 --> 00:00:04.000\nhello world",
    "00:00:02.500 --> 00:00:04.500\nhello",
    "00:00:03.000 --> 00:00:05.000\nhello world <c>again</c>",
    "00:00:03.500 --> 00:00:05.500\nhello world again",
    "00:00:04.000 --> 00:00:06.000\ngood morning",
    "00:00:04.500 --> 00:00:06.500\ngood morning everyone",
)


def test_a_plain_file_reads_back():
    text = vtt(
        "00:00:01.000 --> 00:00:03.000\nGood morning.",
        "00:00:03.000 --> 00:00:05.500\nWelcome to the programme.",
    )

    assert parse_vtt(text) == [
        (1.0, 3.0, "Good morning."),
        (3.0, 5.5, "Welcome to the programme."),
    ]


def test_minute_second_timings_are_read():
    text = vtt(
        "01:02.500 --> 01:05.000\nHello.",
        "1:02:03.400 --> 01:02:05.000\nLater.",
    )

    assert parse_vtt(text) == [
        (62.5, 65.0, "Hello."),
        (3723.4, 3725.0, "Later."),
    ]


def test_cue_identifiers_and_settings_are_ignored():
    text = vtt(
        "intro\n"
        "00:00:01.000 --> 00:00:02.500 align:start position:0%\n"
        "Hello.",
        "00:00:02.500 --> 00:00:04.000 line:90% position:20%\n"
        "Goodbye.",
    )

    assert parse_vtt(text) == [
        (1.0, 2.5, "Hello."),
        (2.5, 4.0, "Goodbye."),
    ]


def test_markup_and_entities_are_stripped():
    text = vtt(
        "00:00:01.000 --> 00:00:02.000\n"
        "<00:00:01.000><v Speaker>Fish &amp; chips "
        "&lt;today&gt;&#39;s&nbsp;special</v>",
    )

    assert parse_vtt(text) == [
        (1.0, 2.0, "Fish & chips <today>'s special"),
    ]


def test_headers_notes_styles_and_regions_carry_no_speech():
    text = (
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: en\n"
        "X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n"
        "\n"
        "NOTE a note here\n"
        "which runs on for two lines\n"
        "\n"
        "STYLE\n"
        "::cue { color: white }\n"
        "\n"
        "REGION\n"
        "id:speaker\n"
        "width:40%\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "Hello there.\n"
    )

    assert parse_vtt(text) == [(2.0, 4.0, "Hello there.")]


def test_a_file_with_only_a_header_and_a_note_is_empty():
    assert parse_vtt(vtt("NOTE nothing was said here\nnor here")) == []
    assert parse_vtt("") == []


def test_cues_without_text_are_dropped():
    text = vtt(
        "00:00:01.000 --> 00:00:02.000\n",
        "00:00:03.000 --> 00:00:04.000\n   ",
        "00:00:05.000 --> 00:00:06.000\nreal speech",
    )

    assert parse_vtt(text) == [(5.0, 6.0, "real speech")]


def test_a_cue_that_does_not_advance_the_clock_is_skipped():
    text = vtt(
        "00:00:05.000 --> 00:00:05.000\nno time to read this",
        "00:00:06.000 --> 00:00:05.000\nnor this",
        "00:00:07.000 --> 00:00:08.000\nthis one stays",
    )

    assert parse_vtt(text) == [(7.0, 8.0, "this one stays")]


def test_repeated_words_inside_a_cue_are_collapsed():
    text = vtt("00:00:01.000 --> 00:00:02.000\nthe the the cat sat")

    assert parse_vtt(text) == [(1.0, 2.0, "the cat sat")]


def test_rolling_captions_reveal_each_word_once():
    cues = parse_vtt(ROLLING)

    starts = [start for start, _, _ in cues]

    # Every word of both sentences, once, in the order it was spoken.
    assert " ".join(text for _, _, text in cues).split() == [
        "hello",
        "world",
        "again",
        "good",
        "morning",
        "everyone",
    ]
    assert starts == sorted(starts)


def test_a_line_redrawn_shorter_is_skipped():
    text = vtt(
        "00:00:01.000 --> 00:00:02.000\nwe are live",
        "00:00:01.500 --> 00:00:02.500\nwe are",
        "00:00:02.000 --> 00:00:03.000\nwe are live from Dublin",
    )

    assert parse_vtt(text) == [
        (1.0, 2.0, "we are live"),
        (2.0, 3.0, "from Dublin"),
    ]


def test_read_vtt_reads_a_file(tmp_path: Path):
    path = tmp_path / "captions.vtt"
    path.write_text(
        vtt("00:00:01.000 --> 00:00:03.000\nGood morning."),
        encoding="utf-8",
    )

    assert read_vtt(path) == [(1.0, 3.0, "Good morning.")]


def test_read_vtt_survives_a_missing_or_mangled_file(tmp_path: Path):
    assert read_vtt(tmp_path / "missing.vtt") == []

    mangled = tmp_path / "mangled.vtt"
    mangled.write_bytes(
        b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\ncaf\xe9 break\n"
    )

    assert read_vtt(mangled) == [(1.0, 3.0, "caf\ufffd break")]
