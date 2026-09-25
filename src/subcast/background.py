"""Work that runs in a thread, for what playback should not wait on."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Generic, TypeVar

T = TypeVar("T")

# Where this thread's lines go while something else owns the screen. Thread
# local because the worker is the one that must not print: the player drawing
# the caption block, or the prompt waiting for the next command, is what says
# the lines the worker produces.
_SINK = threading.local()


def say(
    line: str,
    progress: bool = False,
) -> None:
    """
    One line of a job's output, said where it belongs.

    A line goes to the terminal in one write: two threads say things while a
    run goes on - the one that owns the screen, and the worker behind it -
    and `print` writes the text and its newline separately, so one line can
    land inside another. Measured on the picker's own `Caching:` line, which
    came out with the worker's `Resolving:` line through the middle of it.

    `progress` is a line that replaces the one before it - a percentage, say
    - so it is written without a newline. While something else owns the
    screen it is dropped instead of collected: a percentage belongs to a
    terminal that is watching one thing, and a prompt with a command being
    typed on it is not that terminal. A line with nothing on it is not a
    line either: it is what ends a progress line, and there is none to end.
    """

    collect = getattr(_SINK, "collect", None)

    if collect is not None:

        if line and not progress:

            collect(line)

        return

    if progress:

        sys.stdout.write("\r" + line)

    else:

        sys.stdout.write(line + "\n")

    sys.stdout.flush()


@contextmanager
def listening(
    collect: Callable[[str], None],
):
    """
    Hand this thread's lines to `collect` instead of the terminal.

    Installed by whatever is running a job behind a screen - the run's cache
    queue - and taken down when the job ends, so the thread that owns the
    screen says them when it can (`player.CacheKey.wait`, `cli.cache_notes`,
    `shell.Keeper`).
    """

    _SINK.collect = collect

    try:

        yield

    finally:

        _SINK.collect = None


class Background(Generic[T]):
    """
    Work started in a thread and asked after rather than waited on.

    A failure is carried, not raised: by the time it is noticed, whatever
    it belonged to is already under way, so it is worth a line printed and
    not the end of the run. `label` and `aside` are what that line says.
    """

    def __init__(
        self,
        work: Callable[[], T],
        label: str,
        aside: str,
    ) -> None:

        self.label = label
        self.aside = aside

        self._work = work
        self._done = threading.Event()
        self._value: T | None = None
        self._failure: str | None = None
        self._thread: threading.Thread | None = None

    @classmethod
    def finished(
        cls,
        value: T,
        label: str,
        aside: str,
    ) -> Background[T]:
        """
        Work that ran to completion before anything asked for it, for the
        callers that cannot start without it.
        """

        background = cls(
            lambda: value,
            label,
            aside,
        )

        background._value = value
        background._done.set()

        return background

    def start(self) -> None:
        """
        Set the work going. Starting twice does nothing.
        """

        if self._thread is not None:

            return

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

        self._thread.start()

    def _run(self) -> None:

        try:

            self._value = self._work()

        # Reported by whoever asked, not raised at them.
        except Exception as error:  # noqa: BLE001

            self._failure = str(error)

        finally:

            self._done.set()

    def done_yet(self) -> bool:

        return self._done.is_set()

    def value(self) -> T | None:

        return self._value

    def failure_message(self) -> str | None:
        """
        What went wrong, as a line to print, or None when nothing did.
        """

        if self._failure is None:

            return None

        return (
            f"    {self.label} failed: {self._failure}; "
            f"{self.aside}."
        )

    def wait(self) -> T | None:
        """
        The result, once the work is done. A failure comes back as None.
        """

        self._done.wait()

        return self._value
