"""Choosing what to play out of a long listing."""

from __future__ import annotations

import pytest

from subcast import picker
from subcast.sources import Media


def media(
    title: str,
    duration: float | None = None,
) -> Media:
    return Media(
        source="youtube",
        key=title,
        title=title,
        url="https://youtu.be/x",
        duration=duration,
    )


def listing(
    *titles: str,
) -> list[Media]:
    return [media(title) for title in titles]


def test_a_listing_line_carries_the_duration_when_there_is_one():
    assert (
        picker.listing_line(3, media("A talk", 812.5))
        == "    3. A talk  [13:32]"
    )

    assert (
        picker.listing_line(12, media("A talk"))
        == "   12. A talk"
    )


def test_a_selection_names_entries_by_number_range_or_all():
    assert picker.parse_selection("3", 5) == [2]
    assert picker.parse_selection("2, 5-7", 10) == [1, 4, 5, 6]
    assert picker.parse_selection("3,3", 5) == [2]
    assert picker.parse_selection("all", 3) == [0, 1, 2]
    assert picker.parse_selection("", 3) == []


@pytest.mark.parametrize(
    "selection",
    ["x", "0", "9", "7-2", "2-", "1,,x", "-3"],
)
def test_a_selection_that_cannot_be_read_is_asked_about_again(
    selection: str,
):
    """
    None means "not a selection", so the picker repeats the question
    rather than guessing at what was meant.
    """

    assert picker.parse_selection(selection, 5) is None


def test_the_picker_shows_the_listing_and_plays_what_was_chosen():
    told: list[str] = []
    answers = iter(["1"])

    chosen = picker.choose(
        listing("First", "Second"),
        ask=lambda prompt: next(answers),
        tell=told.append,
    )

    assert [item.title for item in chosen] == ["First"]
    assert told == [
        "    1. First",
        "    2. Second",
    ]


def test_an_unreadable_answer_is_asked_again():
    told: list[str] = []
    answers = iter(["nope", "2"])

    chosen = picker.choose(
        listing("First", "Second"),
        ask=lambda prompt: next(answers),
        tell=told.append,
    )

    assert [item.title for item in chosen] == ["Second"]
    assert told[-1] == picker.COMPLAINT


def test_stopping_chooses_nothing():
    assert (
        picker.choose(
            listing("First"),
            ask=lambda prompt: "",
            tell=lambda line: None,
        )
        == []
    )


def test_a_listing_with_nothing_in_it_asks_nothing():
    asked: list[str] = []

    assert (
        picker.choose(
            [],
            ask=lambda prompt: asked.append(prompt) or "",
            tell=lambda line: None,
        )
        == []
    )

    assert asked == []


def test_end_of_input_chooses_nothing():
    def no_more(prompt: str) -> str:
        raise EOFError

    assert (
        picker.choose(
            listing("First"),
            ask=no_more,
            tell=lambda line: None,
        )
        == []
    )
