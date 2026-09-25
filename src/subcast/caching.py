"""Keeping items, and their subtitles, while the run goes on.

A `d` - a marked entry in a listing, or the key pressed while an item plays -
is a download and a hearing: minutes of work, none of which the run waits for.
What is asked for goes into one queue, and a thread of its own works through
it while the run plays.

**One at a time, because the hearing is where the model is.** A download is
the quick part; a hearing loads a Whisper model of its own (`subtitles.
load_model` builds a fresh one per job rather than sharing an instance between
threads), so `3d 4d 5d` through a thread each would hold three models at once
and slow the machine to a crawl. The queue is what keeps it to one, and the
order asked for is the order kept.

**Asking twice is one job.** Two jobs for one item would be two writers of
`<id>.mp3` and `<id>.cues.json`, and the loser's half-written file is what a
later run would read. A second ask is answered from the item's own state -
queued, running or cached - instead of being queued again.

**The item being played is not in the queue.** Its captions are what the user
is watching, and a broadcast's have to be heard as they air, so nothing here
is allowed to hold them up: the run hands the player the queue's lines rather
than the queue itself.

**The lines are collected, not printed.** A player draws the caption block on
the same terminal a line from the worker would land on, so whoever owns the
screen drains them (`take_notes`) between redraws - and a run with nothing
playing drains what is left itself, so a message about an item that finished
after playback ended is still said.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from .background import listening, say

# What the queue says, here because the queue is what knows the difference
# between the answers to an ask. The ask itself is printed where it is asked
# - the asker owns the screen at that moment - and the rest are collected for
# whoever owns the screen when the work gets to them.
ASKED = "    Caching: {title}"

GOING = "    This item is being cached already."

CACHED = "    This item is cached already."

FAILED = "    Caching failed: {reason}"

# One item's work: it downloads and hears however it likes, saying what it
# has to say through `background.say`, which is what lands in this queue's
# lines.
Work = Callable[[], None]


_SHARED: Caching | None = None
_SHARED_LOCK = threading.Lock()


def shared() -> Caching:
    """
    The queue this process keeps items in.

    A shell is one process with several commands in it, and a `d` in one of
    them has to outlive the command: the user is back at the prompt while
    the item is downloaded and heard. So the queue is the process's rather
    than the run's - every command asks the same one, and whatever owns the
    screen says its lines.
    """

    global _SHARED

    with _SHARED_LOCK:

        if _SHARED is None:

            _SHARED = Caching()

        return _SHARED


class Caching:
    """
    The items this run is keeping, worked through one after another.

    `ask` is what a `3d` choice and the `d` key both call. Nothing waits for
    the queue: `ask` returns as soon as the item is queued, and `done_yet` /
    `wait` are for the run's own end, where the last line has to be said
    before the process leaves.
    """

    def __init__(self) -> None:

        self._lock = threading.Lock()
        self._lines: list[str] = []
        self._wanted: list[tuple[str, Work]] = []
        self._asked: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._done = threading.Event()

        # Nothing asked for is nothing to wait for.
        self._done.set()

    def ask(
        self,
        key: str,
        title: str,
        work: Work,
    ) -> None:
        """
        Ask for an item to be kept, saying what became of the ask.

        An item already being kept is not queued twice, and one the cache
        holds is not queued at all. An item whose work failed is queued
        again: a download that would not come down is worth another go.
        """

        with self._lock:

            state = self._asked.get(key)

            if state is None or state == "failed":

                self._wanted.append(
                    (key, work)
                )

                self._asked[key] = "queued"

                self._done.clear()

                if self._thread is None:

                    self._thread = threading.Thread(
                        target=self._work_through,
                        daemon=True,
                    )

                    self._thread.start()

                line = ASKED.format(
                    title=title
                )

            else:

                line = (
                    CACHED
                    if state == "cached"
                    else GOING
                )

        # Said now rather than collected: the asker is whoever owns the
        # screen - the run before it plays, or the player on the key - and
        # an ask that got no answer would read as a key that did nothing.
        # One write for the line, because the worker may already be printing
        # its own.
        say(line)

    def take_notes(self) -> list[str]:
        """
        What the work has to say, each line once.
        """

        with self._lock:

            taken, self._lines = self._lines, []

        return taken

    def done_yet(self) -> bool:
        """
        Whether everything asked for has been dealt with.
        """

        return self._done.is_set()

    def wait(
        self,
        timeout: float | None = None,
    ) -> None:
        """
        Wait for the queue to empty, or for `timeout` seconds.
        """

        self._done.wait(timeout)

    def _work_through(self) -> None:
        """
        One item after another, for as long as there are any left.

        The thread is left behind when the queue empties, and the next ask
        starts another: an idle queue is a thread doing nothing, and the
        work is minutes away from being asked for again.

        Whatever ends the thread marks the queue done, because a worker that
        dies quietly is a run that waits for it forever - the one failure
        this must not have, since the run's own end is where its lines are
        said (`cli.cache_notes`).
        """

        try:

            while True:

                with self._lock:

                    if not self._wanted:

                        return

                    key, work = self._wanted.pop(0)

                    self._asked[key] = "running"

                try:

                    # The job's own output belongs to whoever owns the
                    # screen: the player drawing the block, the prompt
                    # waiting for the next command, or the run that is
                    # waiting for the work itself.
                    with listening(self._say):

                        work()

                # Said, and the queue goes on: an item that will not come
                # down is one item, and the next one is waiting behind it.
                # Anything at all, not just an Exception: this thread has no
                # signals of its own to pass on, so whatever ended a piece
                # of work is that item's failure.
                except BaseException as error:  # noqa: BLE001

                    with self._lock:

                        self._asked[key] = "failed"

                    self._say(
                        FAILED.format(reason=error)
                    )

                else:

                    with self._lock:

                        self._asked[key] = "cached"

        finally:

            with self._lock:

                self._thread = None
                self._done.set()

    def _say(
        self,
        line: str,
    ) -> None:

        with self._lock:

            self._lines.append(line)
