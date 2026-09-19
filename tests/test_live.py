"""Captions for a broadcast, made while it airs."""

from __future__ import annotations

import time
from pathlib import Path

from subcast import live
from subcast.live import Chunk


class FakeCapture:
    """A capture that hands over whatever the test says it has closed."""

    def __init__(
        self,
        directory: Path | None = None,
        finished: bool = True,
        reason: str | None = None,
    ) -> None:

        self.started = 0
        self.stopped = 0
        self.directory = directory
        self._finished = finished
        self._reason = reason

    def start(self) -> None:

        self.started += 1

    def chunks(self, after: int = -1) -> list[tuple[int, Path]]:

        if self.directory is None:

            return []

        return [
            (sequence, path)
            for sequence, path in live.closed_chunks(
                self.directory,
                finished=self._finished,
            )
            if sequence > after
        ]

    def finished(self) -> bool:

        return self._finished

    def reason(self) -> str | None:

        return self._reason

    def stop(self) -> None:

        self.stopped += 1


def captions(
    tmp_path: Path,
    capture: FakeCapture | None = None,
    clock=None,
) -> live.LiveCaptions:
    return live.LiveCaptions(
        tmp_path / "abc",
        model=None,
        capture=capture or FakeCapture(),
        clock=clock or time.monotonic,
    )


def chunks_in(tmp_path: Path, *sequences: int) -> list[Path]:
    written = []

    for sequence in sequences:

        path = tmp_path / f"chunk_{sequence:05d}.wav"
        path.write_bytes(b"")
        written.append(path)

    return written


def test_the_capture_asks_for_the_cheapest_format_with_sound(tmp_path: Path):
    """
    A live YouTube item offers no audio-only format at all - its formats
    are muxed - so the cheapest one carrying sound is the cheapest way at
    the audio, and ffmpeg drops the picture.
    """

    reader, cutter = live.capture_command(
        "https://www.youtube.com/watch?v=abc",
        tmp_path,
    )

    assert reader[0] == "yt-dlp"
    assert reader[-1] == "https://www.youtube.com/watch?v=abc"
    assert reader[reader.index("-f") + 1] == "worstaudio/worst"
    assert reader[reader.index("-o") + 1] == "-"

    # Whisper hears 16 kHz mono, cut into chunks that a caption can be
    # made from before the broadcast has ended.
    assert cutter[0] == "ffmpeg"
    assert cutter[cutter.index("-ar") + 1] == str(live.SAMPLE_RATE)
    assert cutter[cutter.index("-ac") + 1] == "1"
    assert (
        cutter[cutter.index("-segment_time") + 1]
        == str(int(live.CHUNK_SECONDS))
    )
    assert cutter[-1] == str(tmp_path / "chunk_%05d.wav")


def test_the_join_begins_where_the_captions_stopped(tmp_path: Path):
    """
    A word arriving across a chunk boundary must not be handed to the model
    in halves: ffmpeg joins what is left unheard of the previous chunk to
    this one, cut where the captions stopped.
    """

    command = live.stitch_command(
        tmp_path / "chunk_00000.wav",
        tmp_path / "chunk_00001.wav",
        tmp_path / "stitch.wav",
        3.5,
    )

    assert command[0] == "ffmpeg"
    assert command[command.index("-i") + 1] == str(tmp_path / "chunk_00000.wav")
    assert str(tmp_path / "chunk_00001.wav") in command
    assert command[-1] == str(tmp_path / "stitch.wav")
    assert "atrim=start=3.500" in " ".join(command)


def test_a_chunk_is_named_by_its_number_not_by_where_it_sits(tmp_path: Path):
    """
    A chunk is what ffmpeg called it. The files are deleted as they are
    heard and the last one is kept for the join, so a position in a
    listing says nothing about which piece of the broadcast it holds -
    which is what once made every second chunk go unheard.
    """

    chunks_in(tmp_path, 3, 0, 1)

    (tmp_path / "capture.log").write_text("noise")

    assert live.sequence_of(tmp_path / "chunk_00007.wav") == 7
    assert live.sequence_of(tmp_path / "capture.log") is None

    assert live.closed_chunks(tmp_path, finished=True) == [
        (0, tmp_path / "chunk_00000.wav"),
        (1, tmp_path / "chunk_00001.wav"),
        (3, tmp_path / "chunk_00003.wav"),
    ]

    # the newest one is still being written into, so it is not closed yet
    assert live.closed_chunks(tmp_path) == [
        (0, tmp_path / "chunk_00000.wav"),
        (1, tmp_path / "chunk_00001.wav"),
    ]


class TricklingCapture(FakeCapture):
    """
    A capture that closes one chunk per look, the way a broadcast does.
    """

    def __init__(self, paths: list[Path]) -> None:

        super().__init__(finished=False)
        self._paths = list(paths)

    def chunks(self, after: int = -1) -> list[tuple[int, Path]]:

        if not self._paths:

            return []

        path = self._paths.pop(0)

        return [(live.sequence_of(path), path)]

    def finished(self) -> bool:

        return not self._paths


def test_every_closed_chunk_is_heard_as_they_are_deleted(tmp_path: Path, monkeypatch):
    """
    The regression this pipeline was rewritten for: chunks used to be
    walked by their position in the listing, and hearing one deleted it,
    so the listing shifted under the cursor and every second chunk of
    dialogue was dropped - captions in bursts, with a chunk-length of
    nothing between them.
    """

    heard: list[str] = []

    def hear(model, path, **settings):
        heard.append(Path(path).name)
        return []

    monkeypatch.setattr(live, "transcribe_cues", hear)
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    job = captions(
        tmp_path,
        capture=TricklingCapture(chunks_in(tmp_path, 0, 1, 2, 3)),
        clock=lambda: 100.0 + live.CHUNK_SECONDS,
    )
    job.sample(100.0, 5000.0)

    job._work()

    assert heard == [
        "chunk_00000.wav",
        "chunk_00001.wav",
        "chunk_00002.wav",
        "chunk_00003.wav",
    ]


def test_a_chunk_lands_where_the_broadcast_was_when_it_closed(
    tmp_path: Path,
    monkeypatch,
):
    """
    A chunk that closed just now began recording a chunk-length ago, so
    its words belong at the live edge of that moment.
    """

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: [(1.0, 3.0, "Good morning.")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    chunks_in(tmp_path, 0)

    job = captions(tmp_path, capture=FakeCapture(tmp_path), clock=lambda: 100.0 + live.CHUNK_SECONDS)
    job.sample(100.0, 5000.0)

    job._work()

    # 5000 is where mpv had read up to at wall 100, which is a chunk-length
    # before the clock the chunk closed on.
    assert job.cues() == [(5001.0, 5003.0, "Good morning.")]
    assert job.revision() == 1


def test_a_backlog_is_placed_by_when_each_chunk_closed(
    tmp_path: Path,
    monkeypatch,
):
    """
    One look can find several chunks closed at once - a slow poll or a
    missed one - and they did not all close at that moment: the newest
    ended here, the one before it a chunk-length earlier. The second of
    them is heard from where the first left off, so its words land a second
    after that, not a chunk after it.
    """

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: [(1.0, 2.0, "heard")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: True)

    chunks_in(tmp_path, 0, 1)

    job = captions(tmp_path, capture=FakeCapture(tmp_path), clock=lambda: 100.0 + live.CHUNK_SECONDS)
    job.sample(100.0, 5000.0)

    job._work()

    first = 5000.0 - live.CHUNK_SECONDS

    assert job.cues() == [
        (first + 1.0, first + 2.0, "heard"),
        (first + 3.0, first + 4.0, "heard"),
    ]


def test_a_slow_transcriber_does_not_move_the_captions(
    tmp_path: Path,
    monkeypatch,
):
    """
    Where a chunk belongs is settled when it closes, not when Whisper gets
    to it: a machine that takes a minute over a chunk must lose captions
    to the queue, never put them at a moment the broadcast has gone past.
    """

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: [(1.0, 3.0, "Good morning.")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    now = [100.0 + live.CHUNK_SECONDS]

    chunks_in(tmp_path, 0)

    job = captions(
        tmp_path,
        capture=FakeCapture(tmp_path),
        clock=lambda: now[0],
    )
    job.sample(100.0, 5000.0)

    job._place(job._capture.chunks(after=-1))

    now[0] += 60.0

    job.transcribe(job._queued.popleft())

    assert job.cues() == [(5001.0, 5003.0, "Good morning.")]


def test_the_end_of_a_chunk_waits_for_the_pass_that_hears_its_ending(
    tmp_path: Path,
    monkeypatch,
):
    """
    The audio runs out where the chunk ends, so the last seconds of a chunk
    may be a sentence cut in half: they wait for the next pass, which hears
    them again with what follows.
    """

    answers: list[list[tuple[float, float, str]]] = [
        [(1.0, 2.0, "early"), (3.0, 5.0, "to the very end")],
        [(0.5, 1.0, "to the very end"), (2.0, 3.0, "next")],
    ]

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: answers.pop(0),
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: True)

    first, second = chunks_in(tmp_path, 0, 1)

    job = captions(tmp_path, capture=FakeCapture(tmp_path))

    job.transcribe(Chunk(0, first, 5000.0))

    # "to the very end" ends inside the last second and a half of the
    # chunk, so only the cue before it is said
    assert [text for _, _, text in job.cues()] == ["early"]

    job.transcribe(Chunk(1, second, 5005.0))

    # the next pass hears it again with the words after it
    assert [text for _, _, text in job.cues()] == [
        "early",
        "to the very end",
        "next",
    ]

    # the chunk that was joined in front is heard twice and then gone
    assert not first.exists()


def test_a_cue_that_starts_in_what_was_already_said_is_dropped(
    tmp_path: Path,
    monkeypatch,
):
    """
    The join is cut where the captions stopped, which can be in the middle
    of a word: the half the model hears from there is dropped rather than
    said, because the last pass said the word.
    """

    answers: list[list[tuple[float, float, str]]] = [
        [(1.0, 3.0, "already said")],
        [(-0.8, -0.3, "already said"), (2.0, 3.0, "and this is new")],
    ]

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: answers.pop(0),
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: True)

    first, second = chunks_in(tmp_path, 0, 1)

    job = captions(tmp_path, capture=FakeCapture(tmp_path))

    job.transcribe(Chunk(0, first, 5000.0))
    job.transcribe(Chunk(1, second, 5005.0))

    assert [text for _, _, text in job.cues()] == [
        "already said",
        "and this is new",
    ]


def test_what_waits_too_long_is_dropped_and_said_once(
    tmp_path: Path,
    monkeypatch,
):
    """
    A machine slower than realtime must lose detail, not the live edge:
    the queue is short, and what it drops is said out loud once rather
    than looking like captions that stopped.
    """

    monkeypatch.setattr(live, "transcribe_cues", lambda model, path, **settings: [])

    paths = chunks_in(tmp_path, 0, 1, 2, 3, 4)

    job = captions(tmp_path, clock=lambda: 100.0 + live.CHUNK_SECONDS)
    job.sample(100.0, 5000.0)

    job._place([(index, path) for index, path in enumerate(paths)])
    job._drop_what_cannot_be_heard()

    # three may wait, so the two oldest of five are dropped
    assert [chunk.sequence for chunk in job._queued] == [2, 3, 4]

    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[2].exists()

    notes = job.take_notes()

    assert len(notes) == 1
    assert "cannot keep up" in notes[0]

    # said once, not once per chunk
    job._place([(5, chunks_in(tmp_path, 5)[0])])
    job._drop_what_cannot_be_heard()

    assert job.take_notes() == []

    assert job.summary() is not None
    assert "skipped" in job.summary()


def test_the_summary_counts_what_the_captions_came_to(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: (
            [] if Path(path).name == "chunk_00001.wav" else [(1.0, 2.0, "Hello.")]
        ),
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    chunks_in(tmp_path, 0, 1)

    job = captions(tmp_path, capture=FakeCapture(tmp_path), clock=lambda: 100.0 + live.CHUNK_SECONDS)
    job.sample(100.0, 5000.0)

    job._work()

    assert job.summary() == (
        "    Live captions: 2 chunk(s) heard, 1 with no speech."
    )


def test_nothing_is_written_before_mpv_has_said_where_it_is(
    tmp_path: Path,
    monkeypatch,
):
    """
    A chunk heard before the first reading of the live edge cannot be
    placed, and a caption on the wrong second is worse than none.
    """

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: [(1.0, 3.0, "Good morning.")],
    )

    chunks_in(tmp_path, 0)

    job = captions(tmp_path, capture=FakeCapture(tmp_path))

    job._work()

    assert job.cues() == []
    assert job.revision() == 0
    assert not job.srt_path.exists()
    assert job.failure_message() is None


def test_a_chunk_that_cannot_be_heard_is_said_once(
    tmp_path: Path,
    monkeypatch,
):
    """
    Whisper falling over is a line to print while the video plays, not the
    end of the run - the same way a caption download that failed is.
    """

    def exploded(model, path, **settings):
        raise RuntimeError("no such file")

    monkeypatch.setattr(live, "transcribe_cues", exploded)

    job = captions(tmp_path)

    job.transcribe(Chunk(0, tmp_path / "chunk_00000.wav", 5000.0))

    assert job.failure_message() == (
        "    Live captions failed: a chunk could not be transcribed "
        "(no such file); playing without them."
    )

    # nothing was heard and nothing was skipped, so there is nothing to
    # report: the failure has already said its line.
    assert job.summary() is None


def test_a_capture_that_could_not_start_is_reported(
    tmp_path: Path,
    monkeypatch,
):
    """
    A missing yt-dlp or ffmpeg is worth saying out loud rather than
    failing silently: the run plays on either way.
    """

    class Broken(FakeCapture):
        """A capture that will not start."""

        def start(self) -> None:

            raise RuntimeError("the live audio could not be captured (nope)")

    job = captions(tmp_path, capture=Broken())

    job.start()

    assert job.failure_message() == (
        "    Live captions failed: the live audio could not be captured "
        "(nope); playing without them."
    )


def test_a_capture_is_started_once_and_ended_once(tmp_path: Path):
    """
    Both player paths call `start`, and a job prepared for later is started
    by whoever plays it - so starting twice has to do nothing, and stopping
    has to be what ends the capture.
    """

    capture = FakeCapture(finished=False)
    job = captions(tmp_path, capture=capture)

    job.start()
    job.start()

    assert capture.started == 1
    assert job.failure_message() is None

    job.stop()

    assert capture.stopped == 1


def test_a_broadcast_that_ends_is_not_a_failure():
    """
    Running out of broadcast is how this is meant to go, and the cutter is
    what says so: it has seen every byte the reader passed on, so ffmpeg
    exiting cleanly is an end of input whatever the reader made of it.
    """

    assert live.capture_failure(0, "no message") is None
    assert live.capture_failure(None, "no message") is None

    assert live.capture_failure(
        1,
        "ERROR: Video unavailable",
    ) == "the live audio stopped (ERROR: Video unavailable)"


def test_the_live_edge_moves_with_the_wall_clock():
    """
    One reading of what mpv has read up to places a moment before it:
    between reads the edge advances with the clock.
    """

    assert live.edge_at([(100.0, 5000.0)], 85.0) == 4985.0
    assert live.edge_at([(100.0, 5000.0)], 112.0) == 5012.0
    assert live.edge_at([(100.0, 5000.0), (110.0, 5010.0)], 105.0) == 5005.0
    assert live.edge_at([], 100.0) is None


def test_readings_that_outrun_the_clock_are_not_a_timeline():
    """
    At the start of a run mpv reads faster than the broadcast is published
    while it fills its buffer - 27 seconds of stream in 16 seconds of clock
    on one run - and the oldest of those readings is far behind where the
    broadcast really is. Placing a chunk from it put the first chunk
    thirteen seconds early, where mpv had already played past it, so its
    captions were never seen.
    """

    filling = [(100.0, 5000.0), (116.0, 5027.0)]

    # the moment wanted is 15 seconds back, and the broadcast was at 5012
    # then: not the 5001 the oldest reading would have claimed
    assert live.edge_at(filling, 101.0) == 5012.0

    # once the readings keep time with the clock, they are a timeline again
    steady = [(100.0, 5000.0), (116.0, 5016.0)]

    assert live.edge_at(steady, 101.0) == 5001.0


def test_cues_are_moved_onto_the_timeline_of_the_broadcast():
    assert live.placed(
        [(1.0, 2.0, "spoken")],
        offset=5000.0,
    ) == [(5001.0, 5002.0, "spoken")]


def test_a_sentence_the_model_loops_is_said_once():
    """
    Left on music, the model invents - measured, the same line cue after
    cue, ten and twenty-five times inside one pass. Nobody says the same
    words twice in five seconds of broadcast.
    """

    assert live.drop_loops(
        [
            (0.0, 1.0, "Bye!"),
            (1.0, 2.0, "Bye!"),
            (2.0, 3.0, "Alice."),
            (3.0, 4.0, "Alice."),
            (4.0, 4.5, "  alice. "),
        ]
    ) == [
        (0.0, 1.0, "Bye!"),
        (2.0, 3.0, "Alice."),
    ]
