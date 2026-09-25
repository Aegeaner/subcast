"""The items a run keeps, worked through one after another."""

from __future__ import annotations

import threading
import time

from subcast import background, caching


def asked(
    queue: caching.Caching,
    key: str,
    work,
    title: str = "An episode",
) -> None:
    """
    One ask, with the title most of these do not care about.
    """

    queue.ask(key, title, work)


def settled(
    queue: caching.Caching,
    timeout: float = 5.0,
) -> list[str]:
    """
    What the work said, once it has all been said.
    """

    queue.wait(timeout)

    return queue.take_notes()


def test_nothing_asked_for_is_nothing_to_wait_for():
    """
    An idle queue is not something a run has to wait on, so a run that was
    only playing never waits at all.
    """

    queue = caching.Caching()

    assert queue.done_yet()

    queue.wait(0.0)

    assert queue.take_notes() == []


def test_the_queue_is_the_processs_rather_than_a_runs():
    """
    A shell is one process with several commands in it, and a `d` in one of
    them has to outlive the command: every ask goes to the same queue.
    """

    assert caching.shared() is caching.shared()


def test_the_items_are_kept_in_the_order_they_were_asked_for():
    queue = caching.Caching()
    order: list[str] = []

    def work(key):
        order.append(key)

    for key in ("one", "two", "three"):

        asked(queue, key, lambda key=key: work(key))

    assert settled(queue) == []
    assert order == ["one", "two", "three"]


def test_one_item_is_kept_at_a_time():
    """
    Two hearings at once would be two Whisper models in memory at once, so
    the queue is what keeps a `3d 4d` run to one of them: the second item
    does not start until the first has finished.
    """

    queue = caching.Caching()

    release = threading.Event()
    started = threading.Event()
    order: list[str] = []

    def slow():
        started.set()
        release.wait(timeout=5)
        order.append("first")

    def next_one():
        order.append("second")

    asked(queue, "one", slow)
    asked(queue, "two", next_one)

    assert started.wait(timeout=5)

    # the second is queued, and nothing of it has happened yet
    time.sleep(0.05)

    assert order == []
    assert not queue.done_yet()

    release.set()

    assert settled(queue) == []
    assert order == ["first", "second"]


def test_asking_twice_for_one_item_is_one_job(capsys):
    """
    Two jobs for one item would be two writers of the same cache files, and
    the loser's half-written file is what a later run would read. The second
    ask is answered from the item's own state instead.
    """

    queue = caching.Caching()

    release = threading.Event()
    started = threading.Event()
    runs: list[int] = []

    def work():
        runs.append(1)
        started.set()
        release.wait(timeout=5)

    asked(queue, "one", work, title="An episode")

    assert started.wait(timeout=5)

    asked(queue, "one", work, title="An episode")

    assert caching.GOING in capsys.readouterr().out

    release.set()

    assert settled(queue) == []
    assert runs == [1]

    # and once the cache holds it, the ask is not queued at all
    asked(queue, "one", work, title="An episode")

    assert caching.CACHED in capsys.readouterr().out
    assert runs == [1]
    assert queue.done_yet()


def test_an_item_whose_work_failed_can_be_asked_for_again(capsys):
    """
    A download that would not come down is worth another go, so the failure
    is not what the item is remembered by.
    """

    queue = caching.Caching()
    runs: list[int] = []

    def fails_once():
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("no link to the audio")

    asked(queue, "one", fails_once)

    assert settled(queue) == [
        caching.FAILED.format(reason="no link to the audio"),
    ]

    asked(queue, "one", fails_once)

    assert settled(queue) == []
    assert runs == [1, 1]

    assert (
        caching.ASKED.format(title="An episode")
        in capsys.readouterr().out
    )


def test_a_failure_does_not_hold_up_the_item_behind_it():
    queue = caching.Caching()
    order: list[str] = []

    def explodes():
        order.append("first")
        raise RuntimeError("no link to the audio")

    def runs():
        order.append("second")

    asked(queue, "one", explodes)
    asked(queue, "two", runs)

    assert settled(queue) == [
        caching.FAILED.format(reason="no link to the audio"),
    ]

    assert order == ["first", "second"]


def test_a_worker_that_dies_does_not_leave_the_run_waiting():
    """
    The queue's done signal is what a run's own end waits on, so a job that
    could not even be reported must not leave it set false: a run that waits
    forever is the one failure this must not have.
    """

    queue = caching.Caching()

    def fatal():
        raise KeyboardInterrupt

    asked(queue, "one", fatal)

    assert settled(queue) == [
        caching.FAILED.format(reason=""),
    ]

    assert queue.done_yet()


def test_a_jobs_own_output_is_said_as_a_line_of_the_queue():
    """
    A job says what it has to say through `background.say`, and the queue is
    listening: the worker never prints for itself, so its lines can be said
    by whoever owns the screen - a player drawing the caption block, a
    prompt waiting for the next command, or the run that is waiting for the
    work itself.
    """

    queue = caching.Caching()

    def work():
        background.say("    File: /tmp/one.mp3")

    asked(queue, "one", work)

    assert settled(queue) == ["    File: /tmp/one.mp3"]


def test_a_percentage_is_not_a_line_to_be_said():
    """
    A progress line replaces the one before it, so it belongs to a terminal
    that is watching one thing: behind a screen it is dropped rather than
    collected, and nothing says it.
    """

    queue = caching.Caching()

    def work():
        background.say("    Downloaded: 1.0 MB (1.0%)", progress=True)
        background.say("    Downloaded: 2.0 MB (2.0%)", progress=True)
        background.say("")
        background.say("    Saved successfully: /tmp/one.mp3")

    asked(queue, "one", work)

    assert settled(queue) == ["    Saved successfully: /tmp/one.mp3"]


def test_a_line_is_said_once():
    """
    Whoever drains the lines takes them: the screen says each of them once,
    however often it looks.
    """

    queue = caching.Caching()

    def work():
        background.say("    Cached: /tmp/one.mp3")
        background.say("    Subtitles ready: /tmp/one.srt")

    asked(queue, "one", work)

    assert settled(queue) == [
        "    Cached: /tmp/one.mp3",
        "    Subtitles ready: /tmp/one.srt",
    ]

    assert queue.take_notes() == []
