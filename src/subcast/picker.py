"""Choosing what to play out of a long listing."""

from __future__ import annotations

from collections.abc import Callable

from .captionbar import clock
from .sources import Media

PROMPT = "Play which? [3, 5-7, all, Enter to stop] "
COMPLAINT = "    ?"


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


def choose(
    items: list[Media],
    ask: Callable[[str], str] = input,
    tell: Callable[[str], None] = print,
) -> list[Media]:
    """
    Print a listing and ask which entries to play.

    An empty answer, Ctrl-D or a listing with nothing in it plays nothing,
    so browsing a long channel costs no more than the listing itself.
    """

    for index, media in enumerate(items, start=1):

        tell(
            listing_line(index, media)
        )

    if not items:

        return []

    while True:

        try:

            answer = ask(PROMPT)

        except EOFError:

            return []

        picked = parse_selection(
            answer,
            len(items),
        )

        if picked is not None:

            return [
                items[index]
                for index in picked
            ]

        tell(COMPLAINT)
