"""Choosing what to play out of a long listing."""

from __future__ import annotations

import select
import sys
from collections.abc import Callable

from .background import Background
from .captionbar import clock
from .sources import Media

PROMPT = "Play which? [3, 5-7, all, r to refresh, Enter to stop] "

COMPLAINT = "    ?"

# The key that asks the source again; the menu is redrawn when it answers.
REFRESH = "r"

REFRESHING = "    Refreshing the listing..."

TOO_SOON = "    Nothing to refresh: this listing was just fetched."

# How long one read of the prompt waits before the caller gets a turn: short
# enough that a refresh landing mid-question is noticed, long enough that
# waiting costs nothing.
POLL_SECONDS = 0.25


def listing_line(
    index: int,
    media: Media,
) -> str:
    """
    One entry of a listing, the way --list and the picker print it.
    """

    duration = (
        clock(media.duration)
        if media.duration
        else ""
    )

    return f"  {index:>3}. {media.title}" + (
        f"  [{duration}]" if duration else ""
    )


def parse_selection(
    selection: str,
    count: int,
) -> list[int] | None:
    """
    The entries a selection names, as indices into the listing.

    `3`, `2,5-7` and `all` are selections; an empty one is nothing at all.
    A selection that cannot be read - a word, a backwards range, a number
    that is not in the listing - comes back as None, so the caller can ask
    again rather than guess.
    """

    text = selection.strip().lower()

    if not text:

        return []

    if text == "all":

        return list(range(count))

    chosen: list[int] = []

    for part in text.split(","):

        part = part.strip()

        if not part:

            continue

        first, dash, last = part.partition("-")

        if not first.strip().isdigit():

            return None

        start = int(first)
        end = start

        if dash:

            if not last.strip().isdigit() or int(last) < start:

                return None

            end = int(last)

        for number in range(start, end + 1):

            if not 1 <= number <= count:

                return None

            if number - 1 not in chosen:

                chosen.append(number - 1)

    return sorted(chosen)


def read_line(
    prompt: str,
    timeout: float = POLL_SECONDS,
) -> str | None:
    """
    A line typed at the prompt, or None when none arrived in time.

    The terminal hands over a line when Enter is pressed, so asking again
    loses nothing; an empty prompt writes nothing, which is how a question
    that is already on screen is left where it is.
    """

    if prompt:

        sys.stdout.write(prompt)
        sys.stdout.flush()

    readable, _, _ = select.select(
        [sys.stdin],
        [],
        [],
        timeout,
    )

    if not readable:

        return None

    line = sys.stdin.readline()

    if not line:

        raise EOFError

    return line.rstrip("\n")


def start_refresh(
    again: Callable[[], Background[list[Media]]] | None,
    tell: Callable[[str], None],
    quiet: bool = False,
) -> Background[list[Media]] | None:
    """
    Begin another fetch of the listing.

    `again` is what makes one: the menu uses it when it opens on a cached
    listing, and again whenever `r` is pressed, so a listing that was
    fetched a moment ago can still be asked about. Opening the menu says
    nothing when there is nothing to fetch; pressing `r` then does.
    """

    if again is None:

        if not quiet:

            tell(TOO_SOON)

        return None

    job = again()
    job.start()

    tell(REFRESHING)

    return job


def answer_at(
    ask: Callable[[str], str | None],
    prompt: str,
) -> str | None:
    """
    One read of the prompt. End of input counts as an empty answer, which
    is the same as walking away.
    """

    try:

        return ask(prompt)

    except EOFError:

        return ""


def erase(
    lines: int,
) -> None:
    """
    Take back the lines the menu occupies, so redrawing it does not push
    everything above out of the window.

    Only where the terminal can be asked to: redirected output keeps its
    plain, append-only shape.
    """

    if lines <= 0 or not sys.stdout.isatty():

        return

    sys.stdout.write(
        f"\x1b[{lines}A\x1b[J"
    )

    sys.stdout.flush()


def show(
    items: list[Media],
    tell: Callable[[str], None],
) -> int:
    """
    Print the menu, and say how many lines it took.
    """

    for index, media in enumerate(items, start=1):

        tell(
            listing_line(index, media)
        )

    return len(items)


def choose(
    items: list[Media],
    again: Callable[[], Background[list[Media]]] | None = None,
    ask: Callable[[str], str | None] = read_line,
    tell: Callable[[str], None] = print,
) -> list[Media]:
    """
    Print a listing and ask which entries to play.

    `again` fetches the listing afresh: one is started as the menu opens,
    and the menu is redrawn with what it found, so a cached list is never
    what the user is left looking at. Pressing `r` starts another. The
    numbering always means what is on screen, so an answer can never land
    on entries that were not there when it was typed.

    An empty answer, Ctrl-D or a listing with nothing in it plays nothing,
    so browsing a long channel costs no more than the listing itself.
    """

    if not items:

        return []

    displayed = items
    current = start_refresh(again, tell, quiet=True)

    shown = show(displayed, tell)

    while True:

        answer = answer_at(ask, PROMPT)

        while answer is None:

            current, found = collect(current, tell)

            if found is not None:

                displayed = found or displayed

                # the menu, and the question sitting under it
                erase(shown + 1)

                shown = show(displayed, tell)

                break

            answer = answer_at(ask, "")

        if answer is None:

            continue

        if answer.strip().lower() == REFRESH:

            current = start_refresh(again, tell)

            continue

        picked = parse_selection(
            answer,
            len(displayed),
        )

        if picked is not None:

            return [
                displayed[index]
                for index in picked
            ]

        tell(COMPLAINT)


def collect(
    current: Background[list[Media]] | None,
    tell: Callable[[str], None],
) -> tuple[Background[list[Media]] | None, list[Media] | None]:
    """
    What a running refresh has to say: the entries it found, anything the
    menu should show for them, and nothing left to wait for.

    Either half being None means keep waiting; a failure is said once and
    then dropped, so the menu goes on with what it has and `r` is still
    there to try again.
    """

    if current is None:

        return None, None

    failure = current.failure_message()

    if failure is not None:

        tell(failure)

        return None, None

    if not current.done_yet():

        return current, None

    found = current.value() or []

    tell(
        f"    Refreshed: {len(found)} item(s)"
    )

    return None, found
