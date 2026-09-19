"""The caption block we draw ourselves at the bottom of the terminal."""

from __future__ import annotations

from subcast import captionbar


def test_frame_shows_the_segment_title_above_the_dialogue():
    cues = [
        (10.0, 14.0, "Good morning and welcome to the programme."),
    ]
    segments = [
        (0.0, 12.0, "Weather Forecast"),
        (12.0, 20.0, "8am News Bulletin"),
    ]

    title, history, current = captionbar.frame(
        cues, segments, 11.0, width=30
    )

    assert title == "Weather Forecast"
    assert history == []
    assert current == [
        "Good morning and welcome to",
        "the programme.",
    ]


def test_frame_is_empty_while_nothing_is_playing():
    assert captionbar.frame([], [], 5.0, width=42) == ("", [], [])


def test_frame_caps_the_dialogue_at_two_lines():
    rambling = " ".join(["word"] * 40)

    _, _, current = captionbar.frame(
        [(0.0, 9.0, rambling)],
        [],
        1.0,
        width=42,
    )

    assert len(current) == captionbar.CURRENT_LINES


def test_draw_paints_the_bottom_rows_without_scrolling():
    screen = captionbar.draw(
        "8am News Bulletin",
        [],
        ["Good morning again, this is Morning Ireland"],
        rows=30,
        columns=100,
    )

    first_row = 30 - captionbar.BLOCK_ROWS + 1

    assert f"\x1b[{first_row};1H" in screen
    assert "8am News Bulletin" in screen
    assert "Good morning again, this is Morning Ireland" in screen

    # A newline on the last row would scroll the screen out from under
    # the playback, and the cursor has to come back where it was.
    assert "\n" not in screen
    assert screen.count(captionbar.SAVE_CURSOR) == 1
    assert screen.endswith(captionbar.RESTORE_CURSOR)


def test_draw_marks_muted_playback():
    screen = captionbar.draw(
        "8am News Bulletin",
        [],
        [],
        rows=30,
        columns=100,
        muted=True,
    )

    assert captionbar.MUTED_MARK in screen


def test_draw_keeps_lines_inside_the_terminal():
    screen = captionbar.draw(
        "t" * 120,
        [],
        [],
        rows=30,
        columns=40,
    )

    assert "t" * 39 in screen
    assert "t" * 40 not in screen


def test_scaled_lines_are_sent_through_the_sizing_protocol():
    screen = captionbar.draw(
        "8am News Bulletin",
        [],
        ["Good morning again"],
        rows=30,
        columns=100,
        scale=2,
    )

    assert captionbar.scaled_text("abc", 2) == "\x1b]66;s=2;abc\x07"
    assert captionbar.scaled_text("abc", 1) == "abc"
    assert "\x1b]66;s=2;8am News Bulletin\x07" in screen


def test_scaled_lines_occupy_and_clear_both_of_their_rows():
    screen = captionbar.draw(
        "Title",
        [],
        ["caption"],
        rows=30,
        columns=100,
        scale=2,
    )

    first_row = 30 - captionbar.BLOCK_ROWS * 2 + 1

    # every row of every line is cleared before it is written
    for offset in range(captionbar.BLOCK_ROWS * 2):
        assert f"\x1b[{first_row + offset};1H\x1b[2K" in screen

    # the title row, then the caption two rows below it
    assert f"\x1b[{first_row};1H" in screen
    assert f"\x1b[{first_row + 2};1H" in screen


def test_scaled_lines_hold_half_as_many_characters():
    screen = captionbar.draw(
        "t" * 100,
        [],
        [],
        rows=30,
        columns=80,
        scale=2,
    )

    assert "t" * 39 in screen
    assert "t" * 40 not in screen


def test_scale_is_capped_by_the_space_available():
    # the block needs BLOCK_ROWS rows for every step up in size
    assert captionbar.effective_scale(
        3, rows=captionbar.BLOCK_ROWS * 2, columns=200
    ) == 2
    assert captionbar.effective_scale(
        3, rows=captionbar.BLOCK_ROWS, columns=200
    ) == 1
    # and a line still has to be worth reading
    assert captionbar.effective_scale(3, rows=40, columns=40) == 2
    assert captionbar.effective_scale(3, rows=40, columns=20) == 1
    assert captionbar.effective_scale(1, rows=40, columns=200) == 1


def test_captions_fill_the_window():
    # one cell of margin, so a line cannot wrap into the next row
    assert captionbar.caption_width(80, scale=1) == 79
    assert captionbar.caption_width(160, scale=1) == 159
    assert captionbar.caption_width(400, scale=1) == 399


def test_caption_width_accounts_for_scaled_text():
    # at 2x each character takes two cells, so half as many fit
    assert captionbar.caption_width(160, scale=2) == 79
    assert captionbar.caption_width(120, scale=2) == 59


def test_caption_width_never_goes_below_a_readable_line():
    assert captionbar.caption_width(10, scale=1) == captionbar.MIN_COLUMNS


def test_terminal_size_asks_the_terminal_not_the_environment(
    monkeypatch,
):
    """A resized window must win over stale COLUMNS/LINES."""

    monkeypatch.setenv("COLUMNS", "40")
    monkeypatch.setenv("LINES", "10")
    monkeypatch.setattr(
        captionbar.os,
        "get_terminal_size",
        lambda fd: captionbar.os.terminal_size((163, 47)),
    )

    assert captionbar.terminal_size() == (163, 47)


def test_terminal_size_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("COLUMNS", "132")
    monkeypatch.setenv("LINES", "43")

    def no_terminal(fd):
        raise OSError("not a terminal")

    monkeypatch.setattr(
        captionbar.os,
        "get_terminal_size",
        no_terminal,
    )

    assert captionbar.terminal_size() == (132, 43)


def test_the_block_still_spans_the_window_when_text_is_scaled():
    """At 2x each character takes two cells, but the line still reaches the edge."""

    for columns in (60, 105, 160, 400):
        scale = captionbar.effective_scale(
            captionbar.DEFAULT_SCALE,
            rows=60,
            columns=columns,
        )
        width = captionbar.caption_width(columns, scale)

        assert scale >= 1
        assert width == max(columns // scale - 1, captionbar.MIN_COLUMNS)


def test_resizing_erases_the_previous_block():
    """The block moves with the window; where it was must be wiped."""

    old = captionbar.clear_block(rows=24, columns=80, scale=1)
    first_old_row = 24 - captionbar.BLOCK_ROWS + 1

    for offset in range(captionbar.BLOCK_ROWS):
        assert f"\x1b[{first_old_row + offset};1H\x1b[2K" in old

    # a scaled block occupies more rows and clears all of them
    scaled = captionbar.clear_block(rows=40, columns=200, scale=3)
    first_scaled_row = 40 - captionbar.BLOCK_ROWS * 3 + 1

    for offset in range(captionbar.BLOCK_ROWS * 3):
        assert f"\x1b[{first_scaled_row + offset};1H\x1b[2K" in scaled


def test_the_previous_line_lingers_until_the_next_one_replaces_it():
    cues = [
        (0.0, 2.0, "Good morning and welcome to the programme."),
        (2.0, 5.0, "More news after this."),
    ]
    segments: list[tuple[float, float, str]] = []

    _, history, current = captionbar.frame(cues, segments, 3.0, width=42)

    assert history == ["Good morning and welcome to the programme."]
    assert current == ["More news after this."]


def test_a_long_current_line_keeps_only_the_tail_of_the_previous_one():
    cues = [
        (0.0, 2.0, "The Taoiseach is in Manchester this morning."),
        (2.0, 6.0, "And the rest of the front pages are about the budget."),
    ]

    _, history, current = captionbar.frame(cues, [], 3.0, width=30)

    assert len(current) == captionbar.CURRENT_LINES
    assert len(history) == captionbar.CAPTION_LINES - len(current)
    assert history == ["this morning."]


def test_the_block_is_the_same_height_whatever_is_showing():
    cues = [
        (0.0, 2.0, "Short."),
        (2.0, 6.0, "A much longer line of dialogue that has to wrap twice over."),
    ]

    for position in (1.0, 3.0):
        _, history, current = captionbar.frame(cues, [], position, width=28)
        assert len(history) + len(current) <= captionbar.CAPTION_LINES


def test_history_is_drawn_dimmer_than_what_is_being_said():
    screen = captionbar.draw(
        "8am News Bulletin",
        ["the previous line"],
        ["the current line"],
        rows=30,
        columns=100,
    )

    assert (
        f"{captionbar.HISTORY_COLOUR}the previous line"
    ) in screen

    assert (
        f"{captionbar.CAPTION_COLOUR}the current line"
    ) in screen
