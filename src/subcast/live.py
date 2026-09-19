"""Captions for a broadcast, made while it airs.

A live item is not a file: there is nothing to download and transcribe in
one go, and usually no captions published to fall back on. So `Capture`
reads the broadcast as it is being read - yt-dlp hands the cheapest format
that carries sound to ffmpeg, which cuts it into fixed chunks - and
`LiveCaptions` hears each chunk as it closes, into a subtitle file mpv
reads again as it grows (`sub-reload`). That is what makes captions
possible at all for a stream with no end in sight.

Three things are kept apart on purpose, because doing them together is
what made captions come and go:

*   A chunk is identified by the number ffmpeg put in its name, never by
    where it sits in a listing: the files are deleted as they are heard,
    and a listing is not an identity.
*   Where a cue belongs is decided when its chunk closes, from mpv's own
    reading edge, and carried with the chunk until it is heard. A
    transcriber that is a few seconds behind therefore costs a few seconds
    of delay, not captions placed at the wrong moment.
*   What waits to be heard is a short queue: a machine slower than
    realtime drops the oldest chunks and says so, because for a broadcast
    being incomplete is better than falling behind for good.

The audio in front of a chunk is the last of the one before it, so a word
arriving across the cut is not handed to the model in halves; what falls
before the chunk's own start is dropped afterwards.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .srt import split_cues, write_srt
from .subtitles import transcribe_cues

# How much faster than the clock mpv's reading edge may move before it is
# taken for what it is: mpv filling its buffer rather than the broadcast's
# own timeline. Measured at the start of a run: 27 seconds of stream in 16
# seconds of wall clock, and extrapolating from that reading placed the
# first chunk thirteen seconds early, where nothing would show it.
STEADY_RATIO = 1.2

# Seconds of broadcast per chunk. This is now only how often the audio is
# cut: what a caption waits for is decided when the chunk is heard, so the
# delay between the words being aired and the cue being written is this
# plus the hearing (measured at 0.3s a chunk), against mpv's own buffer of
# ten to sixteen seconds - which is what it has to fit inside, and did not
# when a chunk was fifteen seconds long: the first five seconds of every
# one of those was written after the picture had gone past it.
CHUNK_SECONDS = 5.0

# What Whisper hears: one channel at 16 kHz, which is what the caption
# model was trained on and a fraction of what the stream carries.
SAMPLE_RATE = 16000

# How a live chunk is heard, on top of what every transcript gets. Greedy
# decoding costs a little accuracy and buys the headroom a chunk that is
# still being followed does not have.
#
# The voice filter goes, which is the opposite of the episode path. Its
# purpose there is to keep a two-hour episode quick; a chunk is five
# seconds. Measured through this pipeline on the same audio: 104 words
# against 211 without it, and where the two disagree the filter is usually
# the one that is wrong - it drops whole sentences (one pass lost "I know.
# Let's play Wedding Wives, Traffic Home and Ballerina." outright) and cuts
# the fronts off words ("The ants on the slide" heard as "Hands on the
# slide"). It costs 0.3s a chunk against 0.27s.
#
# What it was there for is `drop_loops`: without a filter the model invents
# text over music, as the same sentence cue after cue.
LIVE_HEARING = {
    "beam_size": 1,
    "best_of": 1,
    "vad_filter": False,
}

# How many cues of one pass may say the same thing before the rest of that
# run is taken for the model looping. Nobody says the same words twice
# inside five seconds of broadcast; a model left on music does, and what it
# invents is worse than what it misses.
LOOP_LIMIT = 1

# How often to look for a chunk that has been closed, and how far back the
# samples of mpv's live edge are kept (a few chunk lengths, so the chunk
# that just closed can be placed).
POLL_SECONDS = 0.5
SAMPLES_KEPT = 300

# How long a capture process is given to go away before it is killed.
STOP_SECONDS = 5.0

# How much of the previous chunk is heard again in front of this one, and
# how many chunks may wait to be heard before the oldest are dropped: a
# slow machine should lose detail, not the live edge.
OVERLAP_SECONDS = 1.5
MAX_QUEUED_CHUNKS = 3


@dataclass(frozen=True)
class Chunk:
    """
    A closed piece of the broadcast, and where its first sample belongs.
    """

    sequence: int
    path: Path
    at: float


def capture_command(
    url: str,
    directory: Path,
) -> tuple[list[str], list[str]]:
    """
    The two halves of the capture: yt-dlp reads the broadcast, ffmpeg cuts
    it into chunks.

    `worstaudio/worst` because a live YouTube item offers no audio-only
    format at all - its formats are muxed - so the cheapest one carrying
    sound is the cheapest way at the audio, and ffmpeg drops the picture.
    """

    reader = [
        "yt-dlp",
        "--no-warnings",
        "--socket-timeout",
        "15",
        "-f",
        "worstaudio/worst",
        "-o",
        "-",
        url,
    ]

    cutter = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "segment",
        "-segment_time",
        str(int(CHUNK_SECONDS)),
        "-reset_timestamps",
        "1",
        str(directory / "chunk_%05d.wav"),
    ]

    return reader, cutter


def stitch_command(
    previous: Path,
    chunk: Path,
    dest: Path,
    start: float,
) -> list[str]:
    """
    What joins what is left unheard of one chunk to the next.

    `start` is the second of the previous chunk to begin at - where the
    captions stopped - so the join is as long as what has not been said
    yet, and never a sentence cut in half.
    """

    return [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(previous),
        "-i",
        str(chunk),
        "-filter_complex",
        (
            f"[0:a]atrim=start={start:.3f},asetpts=PTS-STARTPTS[tail];"
            f"[tail][1:a]concat=n=2:v=0:a=1[out]"
        ),
        "-map",
        "[out]",
        "-f",
        "wav",
        str(dest),
    ]


def sequence_of(
    path: Path,
) -> int | None:
    """
    The number ffmpeg put in a chunk's name, which is what a chunk is.

    The files come and go as they are heard, so a position in a listing
    says nothing about which piece of the broadcast it holds.
    """

    try:

        return int(
            path.stem.rsplit("_", 1)[-1]
        )

    except ValueError:

        return None


def closed_chunks(
    directory: Path,
    finished: bool = False,
) -> list[tuple[int, Path]]:
    """
    The chunks written in full, oldest first, as (sequence, path).

    ffmpeg is still filling the newest one, so it is not one of them -
    unless the capture has stopped, when what is there is all there will
    be.
    """

    written = sorted(
        directory.glob("chunk_*.wav")
    )

    if not finished:

        written = written[:-1]

    return [
        (sequence, path)
        for path in written
        if (sequence := sequence_of(path)) is not None
    ]


def capture_failure(
    cutter_code: int | None,
    tail: str,
) -> str | None:
    """
    Why a capture stopped, or None when it simply ran out of broadcast.

    The cutter is what says so: it has seen every byte the reader passed
    on, so ffmpeg exiting cleanly is an end of input, whatever the reader
    made of its own exit code.
    """

    if cutter_code in (0, None):

        return None

    return f"the live audio stopped ({tail})"


def edge_at(
    samples: Sequence[tuple[float, float]],
    when: float,
) -> float | None:
    """
    Where mpv had read up to at a given moment.

    The live edge is sampled with the playback clock, so between samples it
    moves with the wall clock: one reading is enough to place a moment
    before it.

    Readings moving faster than the clock are not the broadcast's timeline
    at all - they are mpv filling its buffer at the start of a run, and the
    oldest of them is seconds behind where the broadcast actually is.
    Placing from one puts a chunk before the run began, where nothing shows
    it; the newest reading, carried back by the clock, is what those are
    good for.
    """

    if not samples:

        return None

    oldest_wall, oldest = samples[0]
    newest_wall, newest = samples[-1]

    if newest - oldest > (newest_wall - oldest_wall) * STEADY_RATIO:

        return newest - (newest_wall - when)

    chosen = samples[0]

    for sample in samples:

        if sample[0] <= when:
            chosen = sample
        else:
            break

    return chosen[1] + (when - chosen[0])


def drop_loops(
    cues: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    """
    At most `LOOP_LIMIT` cue of a pass for each thing it says.

    A model with music and nobody talking invents: measured, it said "Bye!"
    ten times over and "Alice." twenty-five times, both inside one pass.
    The first of a run is kept, the rest of it is not.
    """

    kept: list[tuple[float, float, str]] = []
    said: dict[str, int] = {}

    for start, end, text in cues:

        key = " ".join(text.split()).casefold()

        said[key] = said.get(key, 0) + 1

        if said[key] <= LOOP_LIMIT:

            kept.append((start, end, text))

    return kept


def placed(
    cues: list[tuple[float, float, str]],
    offset: float,
) -> list[tuple[float, float, str]]:
    """
    What a chunk said, on the timeline of the broadcast.

    `offset` is where the first sample of what was heard belongs.
    """

    return [
        (start + offset, end + offset, text)
        for start, end, text in cues
    ]


def stop_process(
    process: subprocess.Popen,
) -> None:
    """
    End a capture process and whatever it was writing through.

    Both halves are their own process group - killing the reader alone
    would leave ffmpeg waiting on a pipe that will never fill again.
    """

    if process.poll() is not None:

        return

    try:

        os.killpg(
            os.getpgid(process.pid),
            signal.SIGTERM,
        )

    except OSError:

        process.terminate()

    try:

        process.wait(
            timeout=STOP_SECONDS
        )

    except subprocess.TimeoutExpired:

        process.kill()


class Capture:
    """
    A broadcast's audio, read from the stream and cut into chunks.

    The chunks are temporary: they exist to be heard and deleted, and the
    whole directory goes when the capture stops. Errors are kept out of the
    terminal - a run drawing its own caption block owns those rows - and
    read back as the reason the capture ended, if it ended badly.
    """

    def __init__(
        self,
        url: str,
    ) -> None:

        self._url = url
        self._reader: subprocess.Popen | None = None
        self._cutter: subprocess.Popen | None = None
        self._directory: Path | None = None
        self._log: BinaryIO | None = None

    def start(self) -> None:
        """
        Set the capture going. Starting twice does nothing.

        Raises RuntimeError when a half of it cannot be started - a missing
        yt-dlp or ffmpeg - which is the one failure worth saying out loud.
        """

        if self._reader is not None:

            return

        directory = Path(
            tempfile.mkdtemp(
                prefix="subcast-live-"
            )
        )

        self._directory = directory

        reader_command, cutter_command = capture_command(
            self._url,
            directory,
        )

        self._log = (
            directory / "capture.log"
        ).open("wb")

        try:

            reader = subprocess.Popen(
                reader_command,
                stdout=subprocess.PIPE,
                stderr=self._log,
                # Its own group: a broadcast has no end to wait for, so
                # stopping is a signal to the reader and the cutter
                # together, never to this run's own process group.
                start_new_session=True,
            )

        except OSError as error:

            raise RuntimeError(
                f"the live audio could not be captured ({error})"
            ) from error

        try:

            cutter = subprocess.Popen(
                cutter_command,
                stdin=reader.stdout,
                stderr=self._log,
                start_new_session=True,
            )

        except OSError as error:

            stop_process(reader)

            raise RuntimeError(
                f"the live audio could not be cut up ({error})"
            ) from error

        finally:

            # Our own copy of the pipe goes: the reader must see it break
            # when the cutter stops, and never wait on a writer that is
            # this run.
            reader.stdout.close()

        self._reader = reader
        self._cutter = cutter

    def chunks(
        self,
        after: int = -1,
    ) -> list[tuple[int, Path]]:
        """
        The chunks closed since a given sequence, oldest first.
        """

        if self._directory is None:

            return []

        return [
            (sequence, path)
            for sequence, path in closed_chunks(
                self._directory,
                finished=self.finished(),
            )
            if sequence > after
        ]

    def finished(self) -> bool:
        """
        Whether either half has stopped: the broadcast ended, or broke.
        """

        return any(
            process is not None and process.poll() is not None
            for process in (self._reader, self._cutter)
        )

    def reason(self) -> str | None:
        """
        Why the capture stopped, when it stopped badly, or None.
        """

        if self._cutter is None:

            return None

        return capture_failure(
            self._cutter.returncode,
            self._log_tail(),
        )

    def stop(self) -> None:
        """
        End the capture and take the chunks with it.
        """

        for process in (self._reader, self._cutter):

            if process is not None:

                stop_process(process)

        if self._log is not None:

            self._log.close()

        if self._directory is not None:

            shutil.rmtree(
                self._directory,
                ignore_errors=True,
            )

    def _log_tail(self) -> str:
        """
        The last thing the capture said, for an error message.
        """

        if self._log is None or self._directory is None:

            return "no message"

        try:

            self._log.flush()

            lines = [
                line.strip()
                for line in (
                    self._directory / "capture.log"
                ).read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
                if line.strip()
            ]

        except OSError:

            return "no message"

        return (
            lines[-1]
            if lines
            else "no message"
        )


class LiveCaptions:
    """
    A broadcast's captions, transcribed as it airs.

    The model is loaded by whoever makes this, before playback starts,
    because loading it is what prints - and printing is what a run's own
    caption block cannot have happening underneath it.
    """

    def __init__(
        self,
        stem: Path,
        model,
        capture: Capture,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:

        self.srt_path = stem.with_suffix(".live.srt")

        self._model = model
        self._capture = capture
        self._clock = clock

        self._lock = threading.Lock()
        self._cues: list[tuple[float, float, str]] = []
        self._revision = 0
        self._samples: deque[tuple[float, float]] = deque(
            maxlen=SAMPLES_KEPT
        )
        self._failure: str | None = None
        self._notes: list[str] = []

        # The broadcast time the captions have been written up to. The
        # first pass has nothing behind it, and stream time never goes
        # below zero.
        self._said_until = 0.0
        self._heard = 0
        self._skipped = 0
        self._silent = 0

        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

        # Chunks that have been placed but not yet heard, and the chunk
        # whose tail belongs in front of the next one.
        self._queued: deque[Chunk] = deque()
        self._previous: Path | None = None
        self._previous_at = 0.0

    def start(self) -> None:
        """
        Set the capture and the transcription going. Starting twice does
        nothing.
        """

        if self._thread is not None:

            return

        try:

            self._capture.start()

        except RuntimeError as error:

            self._fail(str(error))

            return

        self._thread = threading.Thread(
            target=self._work,
            daemon=True,
        )

        self._thread.start()

    def sample(
        self,
        wall: float,
        edge: float,
    ) -> None:
        """
        Where mpv has read up to, and when it said so.
        """

        with self._lock:

            self._samples.append(
                (wall, edge)
            )

    def cues(self) -> list[tuple[float, float, str]]:
        """
        What has been said so far, on the broadcast's timeline.
        """

        with self._lock:

            return list(self._cues)

    def revision(self) -> int:
        """
        A number that changes when the subtitles on disk do.
        """

        with self._lock:

            return self._revision

    def failure_message(self) -> str | None:
        """
        What went wrong, as a line to print, or None when nothing did.
        """

        with self._lock:

            failure = self._failure

        if failure is None:

            return None

        return (
            f"    Live captions failed: {failure}; "
            f"playing without them."
        )

    def take_notes(self) -> list[str]:
        """
        What is worth saying, each line once, and nothing twice.

        Carried rather than printed: the worker runs while a caption block
        is drawing, and only the run that owns the terminal may write to
        it.
        """

        with self._lock:

            notes = self._notes
            self._notes = []

        return notes

    def summary(self) -> str | None:
        """
        What the captions came to, for the end of the run.
        """

        with self._lock:

            heard, skipped, silent = (
                self._heard,
                self._skipped,
                self._silent,
            )

        if not heard and not skipped:

            return None

        parts = [f"{heard} chunk(s) heard"]

        if silent:

            parts.append(f"{silent} with no speech")

        if skipped:

            parts.append(f"{skipped} skipped")

        return "    Live captions: " + ", ".join(parts) + "."

    def stop(self) -> None:
        """
        End the capture, keeping the subtitles it wrote.
        """

        self._stopping.set()

        self._capture.stop()

        if self._thread is not None:

            self._thread.join(
                timeout=STOP_SECONDS
            )

    def transcribe(
        self,
        chunk: Chunk,
    ) -> None:
        """
        One closed chunk: hear it, place it, and write what it said.

        What is left unheard of the chunk before is heard again in front of
        this one - from the moment the captions stopped, so a sentence
        arriving across the join is not handed to the model in halves - and
        what it says there was said by the pass before.

        The last of a chunk is left for the next pass on purpose: the audio
        runs out where the chunk ends, and a sentence cut off there is a
        sentence the next pass can finish.
        """

        with self._lock:

            said_until = self._said_until

        audio = chunk.path

        # From the last thing said to the end of the chunk before it, when
        # that is inside the chunk we still have.
        start = chunk.at

        if (
            self._previous is not None
            and self._previous.exists()
            and 0.0 <= said_until - self._previous_at < CHUNK_SECONDS
        ):

            stitched = chunk.path.with_name("stitch.wav")

            if self._stitch(
                self._previous,
                chunk.path,
                stitched,
                said_until - self._previous_at,
            ):

                audio = stitched
                start = said_until

        try:

            cues = transcribe_cues(
                self._model,
                audio,
                **LIVE_HEARING,
            )

        except Exception as error:  # noqa: BLE001 - reported, not raised

            self._fail(
                f"a chunk could not be transcribed ({error})"
            )

            return

        finally:

            if audio != chunk.path:

                audio.unlink(
                    missing_ok=True
                )

            if self._previous is not None:

                self._previous.unlink(
                    missing_ok=True
                )

            self._previous = chunk.path
            self._previous_at = chunk.at

        heard = split_cues(
            drop_loops(
                placed(
                    cues,
                    start,
                )
            )
        )

        with self._lock:

            self._heard += 1

            if not cues:

                self._silent += 1

        # Nothing heard before what has already been said - the join is
        # there to give the model the words in front of the chunk, not to
        # say them twice - and nothing from the seconds the audio runs out
        # in, which the next pass hears again with what follows them.
        said = [
            cue
            for cue in heard
            if cue[0] >= said_until
            and cue[1] <= chunk.at + CHUNK_SECONDS - OVERLAP_SECONDS
        ]

        if not said:

            return

        # The file first: the revision is what tells a running player the
        # new cues are there to be read.
        try:

            write_srt(
                self._cues + said,
                self.srt_path,
            )

        except OSError as error:

            self._fail(
                f"the subtitles could not be written ({error})"
            )

            return

        with self._lock:

            self._cues.extend(
                said
            )

            self._said_until = max(
                self._said_until,
                max(end for _start, end, _text in said),
            )

            self._revision += 1

    def _stitch(
        self,
        previous: Path,
        chunk: Path,
        dest: Path,
        start: float,
    ) -> bool:
        """
        Join the tail of the chunk before to this one, in a temporary file.

        False when the join could not be made, which leaves the chunk to be
        heard on its own rather than not at all.
        """

        try:

            completed = subprocess.run(
                stitch_command(previous, chunk, dest, start),
                capture_output=True,
                check=False,
            )

        except OSError:

            return False

        return (
            completed.returncode == 0
            and dest.is_file()
        )

    def _work(self) -> None:
        """
        Notice each chunk as the capture closes it, place it, and hear it.

        Nothing may end this loop without a word: a worker that died
        quietly is a broadcast that stopped being captioned with nothing
        said about it, which is the hardest kind of problem to see.
        """

        try:

            self._hear_as_it_airs()

        except Exception as error:  # noqa: BLE001 - reported, not raised

            self._fail(
                f"the captions stopped ({error})"
            )

    def _hear_as_it_airs(self) -> None:
        """
        The loop itself.

        Noticing and hearing are separate on purpose: where a caption
        belongs is settled when its chunk closes, so a transcriber that is
        behind costs delay rather than captions in the wrong place, and
        what is waiting can be dropped when it falls too far behind.
        """

        cursor = -1

        while not self._stopping.is_set():

            closed = self._capture.chunks(after=cursor)

            if closed:

                self._place(closed)

                # The number of the newest one seen, whatever became of
                # the queue: a chunk taken once is never taken again.
                cursor = closed[-1][0]

            self._drop_what_cannot_be_heard()

            while self._queued and not self._stopping.is_set():

                self.transcribe(
                    self._queued.popleft()
                )

            if self._capture.finished():

                reason = self._capture.reason()

                if reason is not None:

                    self._fail(reason)

                break

            self._stopping.wait(
                POLL_SECONDS
            )

    def _place(
        self,
        closed: list[tuple[int, Path]],
    ) -> None:
        """
        Give newly closed chunks the broadcast time they start at.

        The newest of them closed just now and each one before it a
        chunk-length earlier - the poll cannot see them any sooner, and a
        backlog must not be placed at one moment - so a batch is walked
        backwards from the reading edge mpv reported.
        """

        now = self._clock()

        for index, (sequence, path) in enumerate(closed):

            behind = len(closed) - 1 - index

            at = edge_at(
                list(self._samples),
                now - behind * CHUNK_SECONDS - CHUNK_SECONDS,
            )

            if at is None:

                # Nothing has said where the broadcast is yet, and a
                # caption on the wrong second is worse than none.
                path.unlink(
                    missing_ok=True
                )

                continue

            self._queued.append(
                Chunk(
                    sequence=sequence,
                    path=path,
                    at=at,
                )
            )

    def _drop_what_cannot_be_heard(self) -> None:
        """
        Keep the queue short, and the captions with the broadcast.

        A machine slower than realtime would otherwise queue chunks until
        each one's cues are written after mpv has already played past
        them, which looks like captions that stopped: dropping the oldest
        keeps what is said next, and it is said once.
        """

        dropped = 0

        while len(self._queued) > MAX_QUEUED_CHUNKS:

            self._queued.popleft().path.unlink(
                missing_ok=True
            )

            dropped += 1

        if not dropped:

            return

        if self._previous is not None:

            # What was dropped sat between them, and the tail of one chunk
            # joined to a chunk from another part of the broadcast is a
            # sentence nobody said.
            self._previous.unlink(
                missing_ok=True
            )

            self._previous = None
            self._previous_at = 0.0

        with self._lock:

            self._skipped += dropped

            if self._skipped == dropped:

                self._notes.append(
                    "    Live captions cannot keep up with this "
                    "broadcast; skipping ahead to the live edge."
                )

    def _fail(
        self,
        message: str,
    ) -> None:

        with self._lock:

            if self._failure is None:

                self._failure = message
