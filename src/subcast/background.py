"""Work that runs in a thread, for what playback should not wait on."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


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
