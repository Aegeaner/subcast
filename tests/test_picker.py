"""Choosing what to play out of a long listing."""

from __future__ import annotations

import re
import sys
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
    assert picker.parse_selection("3", 5) == [(2, False)]
    assert picker.parse_selection("2, 5-7", 10) == [
        (1, False),
        (4, False),
        (5, False),
        (6, False),
    ]
    assert picker.parse_selection("3,3", 5) == [(2, False)]
    assert picker.parse_selection("all", 3) == [
        (0, False),
        (1, False),
        (2, False),
    ]
    assert picker.parse_selection("", 3) == []


def test_a_selection_may_mark_entries_for_the_cache():
    """
    A `d` after an entry is the same selection asking for that entry to be
    downloaded into the cache with its subtitles rather than played, and a
    mark on any mention of an entry is a mark on the entry.
    """

    assert picker.parse_selection("3d", 5) == [(2, True)]
    assert picker.parse_selection("2d,5", 10) == [(1, True), (4, False)]
    assert picker.parse_selection("5-7d", 8) == [
        (4, True),
        (5, True),
        (6, True),
    ]
    assert picker.parse_selection("3d,3", 5) == [(2, True)]
    assert picker.parse_selection("alld", 3) == [
        (0, True),
        (1, True),
        (2, True),
    ]


def test_a_mark_that_names_nothing_is_asked_about_again():
    """
    The `d` is a suffix on a selection and not a selection of its own, so
    one with nothing in front of it is read the way any other nonsense is.
    """

    assert picker.parse_selection("d", 5) is None
    assert picker.parse_selection("3d-5", 5) is None


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

    assert [item.title for item, _download in chosen] == ["First"]
    assert told == [
        "    1. First",
        "    2. Second",
    ]


def test_the_picker_says_which_entries_were_marked_for_download():
    """
    A marked entry and a played one both come back, and the mark is what
    tells them apart: the caller caches one and plays the other, in the
    order the selection named them.
    """

    answers = iter(["2d,1"])

    chosen = picker.choose(
        listing("First", "Second"),
        ask=lambda prompt: next(answers),
        tell=lambda line: None,
    )

    assert [
        (item.title, download)
        for item, download in chosen
    ] == [
        ("First", False),
        ("Second", True),
    ]


def test_an_unreadable_answer_is_asked_again():
    told: list[str] = []
    answers = iter(["nope", "2"])

    chosen = picker.choose(
        listing("First", "Second"),
        ask=lambda prompt: next(answers),
        tell=told.append,
    )

    assert [item.title for item, _download in chosen] == ["Second"]
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


UP = re.compile(r"\x1b\[(\d+)A")
CLEAR = "\x1b[J"


class Terminal:
    """
    A terminal that keeps what is left on it.

    The menu redraws itself by walking the cursor up and clearing from
    there, so the rows, the cursor and those two sequences are what has to
    be modelled to say what a user is left looking at.
    """

    def __init__(self) -> None:

        self.rows: list[list[str]] = [[]]
        self.row = 0
        self.column = 0

    def isatty(self) -> bool:

        return True

    def flush(self) -> None:

        pass

    def write(self, text: str) -> None:

        while text:

            up = UP.match(text)

            if up is not None:

                self.row = max(0, self.row - int(up.group(1)))
                text = text[up.end():]

                continue

            if text.startswith(CLEAR):

                del self.rows[self.row][self.column:]
                del self.rows[self.row + 1:]
                text = text[len(CLEAR):]

                continue

            self._character(text[0])
            text = text[1:]

    def _character(self, character: str) -> None:

        if character == "\r":

            self.column = 0

            return

        if character == "\n":

            self.row += 1
            self.column = 0

            if self.row == len(self.rows):

                self.rows.append([])

            return

        line = self.rows[self.row]

        while len(line) < self.column:

            line.append(" ")

        if self.column < len(line):

            line[self.column] = character

        else:

            line.append(character)

        self.column += 1

    def screen(self) -> list[str]:
        """
        What is on it, with the empty rows the cursor sits below left off.
        """

        rows = ["".join(line) for line in self.rows]

        while rows and not rows[-1]:

            rows.pop()

        return rows


def typed(
    terminal: Terminal,
    *keys: str | None,
) -> Callable[[str], str | None]:
    """
    A keyboard: one key for each read, None meaning nothing was typed, the
    terminal echoing back what it is given the way a tty does.
    """

    replies = iter(keys)

    def ask(prompt: str) -> str | None:

        if prompt:

            terminal.write(prompt)

        key = next(replies, None)

        if key is None:

            return None

        terminal.write(key + "\r\n")

        return key

    return ask


class Fetching(Background[list[Media]]):
    """
    A listing fetch that takes its time: it answers on the `after`th ask,
    which is a source still working while the menu is up.
    """

    def __init__(
        self,
        found: list[Media],
        after: int,
    ) -> None:

        super().__init__(
            lambda: found,
            "Refreshing the listing",
            "the menu keeps what it had",
        )

        self._found = found
        self._left = after

    def start(self) -> None:
        """
        Already under way, which is what this models.
        """

    def done_yet(self) -> bool:

        self._left -= 1

        return self._left < 0

    def value(self) -> list[Media] | None:

        return self._found


def fetching(
    found: list[Media],
    after: int = 1,
) -> Callable[[], Background[list[Media]]]:
    """
    A source that keeps working across asks.
    """

    return lambda: Fetching(found, after)


def test_a_refreshed_listing_replaces_the_one_that_was_shown(monkeypatch):
    """
    The menu opens on what the cache had and is redrawn with what the
    source says now, so a stale list is never what is left on screen.
    """

    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)

    chosen = picker.choose(
        listing("An entry from last time"),
        again=refresh_to(
            listing("An entry from today", "Another from today")
        ),
        ask=typed(terminal, None, "1"),
        tell=print,
    )

    assert [item.title for item, _download in chosen] == ["An entry from today"]
    assert terminal.screen() == [
        "    Refreshed: 2 item(s)",
        "    1. An entry from today",
        "    2. Another from today",
        (
            "Play which? [3, 5-7, 3d to download, all, r to refresh, "
            "Enter to stop] 1"
        ),
    ]


def test_a_refresh_takes_back_every_row_the_menu_wrote(monkeypatch):
    """
    The entries, the line a refresh writes and the echo of an answer all
    pushed the cursor down, so all of them are rows to take back: erasing
    fewer leaves the head of the old menu above the redrawn one, and the
    numbering a user reads then names entries the menu no longer holds.
    """

    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)

    chosen = picker.choose(
        listing("An entry from last time", "Another from last time"),
        again=fetching(
            listing("An entry from today", "Another from today")
        ),
        ask=typed(terminal, None, "nonsense", None, "r", None, None, "1"),
        tell=print,
    )

    assert [item.title for item, _download in chosen] == ["An entry from today"]
    assert terminal.screen() == [
        "    Refreshed: 2 item(s)",
        "    1. An entry from today",
        "    2. Another from today",
        (
            "Play which? [3, 5-7, 3d to download, all, r to refresh, "
            "Enter to stop] 1"
        ),
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

    assert [item.title for item, _download in chosen] == ["Old second"]


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
    assert [item.title for item, _download in chosen] == ["An entry from today"]
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

    assert [item.title for item, _download in chosen] == ["An entry from last time"]
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
