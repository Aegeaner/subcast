"""Choosing what to play out of a long listing."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from subcast import picker
from subcast.background import Background
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


def scripted(
    *answers: str | None,
) -> Callable[[str], str | None]:
    """
    A terminal that answers with each of these in turn, then EOF.
    """

    replies = iter(answers)

    def ask(prompt: str) -> str | None:

        return next(replies, "")

    return ask


def refresh_to(
    found: list[Media],
) -> Callable[[], Background[list[Media]]]:
    """
    A refresh that has already answered, so the menu sees it at once.
    """

    return lambda: Background.finished(
        found,
        "Refreshing the listing",
        "the menu keeps what it had",
    )


def failing_refresh(
    error: str,
    started: list[int],
) -> Callable[[], Background[list[Media]]]:
    """
    A refresh that fails, once its failure is there to be found.
    """

    def again() -> Background[list[Media]]:

        def work() -> list[Media]:
            raise RuntimeError(error)

        job = Background(
            work,
            "Refreshing the listing",
            "the menu keeps what it had",
        )

        started.append(1)
        job.start()
        job.wait()

        return job

    return again


def test_a_refreshed_listing_replaces_the_one_that_was_shown():
    """
    The menu opens on what the cache had and is redrawn with what the
    source says now, so a stale list is never what is left on screen.
    """

    told: list[str] = []
    cached = listing("An entry from last time")
    found = listing("An entry from today", "Another from today")

    chosen = picker.choose(
        cached,
        again=refresh_to(found),
        ask=scripted(None, "1"),
        tell=told.append,
    )

    assert [item.title for item in chosen] == ["An entry from today"]
    assert told == [
        picker.REFRESHING,
        "    1. An entry from last time",
        "    Refreshed: 2 item(s)",
        "    1. An entry from today",
        "    2. Another from today",
    ]


def test_a_refresh_still_running_cannot_renumber_the_menu():
    """
    An answer names what was on screen when it was typed: the menu only
    changes at a redraw, which happens between reads, never between reading
    an answer and acting on it.
    """

    release = threading.Event()

    def work() -> list[Media]:
        release.wait(timeout=5)
        return listing("New first")

    def again() -> Background[list[Media]]:

        job = Background(
            work,
            "Refreshing the listing",
            "the menu keeps what it had",
        )

        job.start()

        return job

    chosen = picker.choose(
        listing("Old first", "Old second"),
        again=again,
        ask=scripted("2"),
        tell=lambda line: None,
    )

    release.set()

    assert [item.title for item in chosen] == ["Old second"]


def test_the_refresh_key_starts_another_fetch():
    told: list[str] = []
    cached = listing("An entry from last time")
    started: list[int] = []

    def again() -> Background[list[Media]]:
        started.append(1)
        return Background.finished(
            listing("An entry from today"),
            "Refreshing the listing",
            "the menu keeps what it had",
        )

    chosen = picker.choose(
        cached,
        again=again,
        ask=scripted(None, "R", None, "1"),
        tell=told.append,
    )

    assert len(started) == 2
    assert [item.title for item in chosen] == ["An entry from today"]
    assert told.count(picker.REFRESHING) == 2


def test_a_listing_that_was_just_fetched_says_there_is_nothing_to_refresh():
    told: list[str] = []

    picker.choose(
        listing("First"),
        again=None,
        ask=scripted("r", "1"),
        tell=told.append,
    )

    assert picker.TOO_SOON in told


def test_a_failed_refresh_is_said_once_and_the_menu_goes_on():
    told: list[str] = []
    started: list[int] = []

    chosen = picker.choose(
        listing("An entry from last time"),
        again=failing_refresh("yt-dlp failed for the channel", started),
        ask=scripted(None, "1"),
        tell=told.append,
    )

    assert [item.title for item in chosen] == ["An entry from last time"]
    assert started == [1]
    assert (
        told.count(
            "    Refreshing the listing failed: yt-dlp failed for the "
            "channel; the menu keeps what it had."
        )
        == 1
    )

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
