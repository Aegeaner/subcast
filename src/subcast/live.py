"""Captions for a broadcast, made while it airs.

A live item is not a file: there is nothing to download and transcribe in
one go, and usually no captions published to fall back on. What it has is a
playlist naming the last few seconds of it, so `Capture` fetches those pieces
one at a time - each a bounded request that can be retried, skipped or
resolved again on its own, where a pipe reading the broadcast has to survive
the whole of it - and `LiveCaptions` hears each piece as it closes, into a
subtitle file mpv reads again as it grows (`sub-reload`). That is what makes
captions possible at all for a stream with no end in sight.

Three things are kept apart on purpose, because doing them together is what
made captions come and go:

*   A piece is identified by the number the playlist gave it, never by where
    it sits in a listing: the files are deleted as they are heard, and a
    listing is not an identity.
*   Where a cue belongs is read off the piece itself: a piece of a broadcast
    says at what moment of the broadcast it starts, and that is where its
    words are. Nothing is inferred from where the player has read up to -
    measured, mpv's reading edge is a whole piece behind the broadcast for as
    long as it takes it to look at the playlist again, and captions placed
    from it were on screen seconds before the words.
*   What waits to be heard is a short queue: a machine slower than realtime
    drops the oldest pieces and says so, because for a broadcast being
    incomplete is better than falling behind for good.

The audio in front of a piece is the tail of the one before it, so a word
arriving across the cut is not handed to the model in halves and a sentence
is not heard from its middle; what it says there was said by the pass before,
and is dropped.
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

from . import hls
from .player import LIVE_AUDIO_FORMAT
from .srt import split_cues, write_srt
from .subtitles import GrowingCaptions, transcribe_cues

# What reads a piece's own clock: how many seconds into the broadcast its
# audio begins. ffprobe answers in one process - measured at 40ms for a piece
# - and the answer is the whole of where a cue belongs, so a piece whose
# timestamp cannot be read is placed after the one before it rather than
# guessed at.
TIMESTAMP_TRIES = 2
TIMESTAMP_SECONDS = 20.0

# How often the playlist is read. A piece is five seconds of broadcast, so
# this is how long after it closed the run can know about it - and reading
# it more often than the broadcast is published would be asking the same
# question twice.
PLAYLIST_SECONDS = 1.0

# How much of the window a run opens on: the piece airing now and the one
# before it, which is the audio mpv is playing its way towards. The rest of
# the window aired before the run began, and has nothing to be shown on.
START_BEHIND = 2

# How many times a piece is asked for before it is given up on, how many
# times the broadcast is resolved before the capture is taken for unable to
# start, and how long a decode may take before it is taken for stuck. A piece
# that has scrolled out of the window is answered 404, which is one piece
# lost rather than the capture ending.
SEGMENT_TRIES = 3
MANIFEST_TRIES = 3
DECODE_SECONDS = 60.0

# How many looks at the playlist in a row may come back with nothing before
# the capture is taken for broken, and how many times its URL may be
# resolved again. A googlevideo URL carries its own expiry, and a broadcast
# outlives it, so a run asks for a fresh playlist rather than losing the
# rest of its captions.
UNREAD_LIMIT = 15
RENEW_LIMIT = 3

# Seconds of the piece before this one that are heard again in front of it,
# on top of what has not been said yet, so the model is not left to make out
# a sentence from its middle. It costs no delay: what a caption waits for is
# the piece closing, not the audio in front of it.
CONTEXT_SECONDS = 2.5

# What Whisper hears: one channel at 16 kHz, which is what the caption
# model was trained on and a fraction of what the stream carries.
SAMPLE_RATE = 16000

# How a live chunk is heard, on top of what every transcript gets (`_stream`
# runs without the voice filter for every path). Greedy decoding costs a
# little accuracy and buys the headroom a chunk that is still being followed
# does not have.
#
# Measured on a live chunk: the voice filter hears 104 words where the same
# audio without it hears 211, and where the two disagree the filter is
# usually the one that is wrong - it drops whole sentences (one pass lost "I
# know. Let's play Wedding Wives, Traffic Home and Ballerina." outright) and
# cuts the fronts off words ("The ants on the slide" heard as "Hands on the
# slide").
#
# What it was there for is `drop_loops`: over music the model invents text,
# as the same sentence cue after cue.
#
# The timing of the words comes back with them, because a pass hears the
# words before it and what the model makes of those was said by the pass
# before: with the word times the half of a line that is new is kept and the
# half already said is dropped, where dropping the whole line loses the words
# it ends with.
LIVE_HEARING = {
    "beam_size": 1,
    "best_of": 1,
    "vad_filter": False,
    "word_timestamps": True,
}

# How many cues of one pass may say the same thing before the rest of that
# run is taken for the model looping, and how far back a line the pass before
# said counts as the same line. Nobody says the same words twice inside five
# seconds of broadcast; a model left on music does, and what it invents is
# worse than what it misses.
LOOP_LIMIT = 1
LOOP_SECONDS = 15.0

# How often to look for a piece that has been closed.
POLL_SECONDS = 0.5

# How long a capture process is given to go away before it is killed.
STOP_SECONDS = 5.0

# How much of the end of a piece waits for the pass that hears its ending,
# and how many pieces may wait to be heard before the oldest are dropped: a
# slow machine should lose detail, not the live edge.
OVERLAP_SECONDS = 1.5
MAX_QUEUED_CHUNKS = 3


@dataclass(frozen=True)
class Piece:
    """
    A piece of the broadcast on disk, and where in the broadcast it begins.

    `at` is the moment the piece's own audio says it starts: the broadcast's
    timeline, which is the timeline a cue is written on and the one mpv reads
    a subtitle file against.
    """

    sequence: int
    path: Path
    at: float
    duration: float


def manifest_url(
    page_url: str,
) -> str:
    """
    The playlist of the rendition this run hears.

    The same selector the player hands mpv, because the copy is what matters:
    the audio the model hears has to be the audio being played, or the
    captions are in pace with another rendition of the broadcast.
    """

    completed = subprocess.run(
        [
            "yt-dlp",
            "--no-warnings",
            "--socket-timeout",
            "15",
            "-f",
            LIVE_AUDIO_FORMAT,
            "-g",
            page_url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]

    if completed.returncode != 0 or not lines:

        raise RuntimeError(
            "the broadcast could not be resolved "
            f"({last_line(completed.stderr)})"
        )

    return lines[0]


def decode_command(
    segment: Path,
    dest: Path,
) -> list[str]:
    """
    What turns one piece of the broadcast into audio to hear.

    ffmpeg is handed a file rather than a pipe: a piece that came down whole
    is decoded on its own, so a slow decode costs a moment of the queue
    rather than the capture, and the model hears the same 16 kHz mono a chunk
    of a broadcast always was.
    """

    return [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(segment),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "wav",
        str(dest),
    ]


def timestamp_of(
    piece: Path,
) -> float | None:
    """
    When in the broadcast a piece of audio begins, or None if it will not say.

    A live stream's pieces carry the broadcast's own timeline, which is the
    one a caption is written on and the one a player reads a subtitle file
    against: reading it here is what makes a cue land on the words rather
    than on where the player happened to have read up to.

    What is asked is the piece as it came down, not the audio decoded out of
    it: a wav is written under a timestamp of its own and answers `N/A`.
    """

    for _attempt in range(TIMESTAMP_TRIES):

        try:

            completed = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=start_time",
                    "-of",
                    "csv=p=0",
                    str(piece),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=TIMESTAMP_SECONDS,
            )

        except (OSError, subprocess.TimeoutExpired):

            continue

        if completed.returncode != 0:

            continue

        stamps = completed.stdout.split()

        if not stamps:

            continue

        try:

            return float(stamps[0])

        except ValueError:

            continue

    return None


def stitch_command(
    previous: Path,
    chunk: Path,
    dest: Path,
    start: float,
) -> list[str]:
    """
    What joins the tail of one piece to the next.

    `start` is the second of the previous piece to begin at - behind where
    the captions stopped, so the model hears the words a sentence opens with
    - and what falls before this piece's own start is dropped afterwards.
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


def last_line(
    text: str,
) -> str:
    """
    The last thing a program said, for an error message.
    """

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    return (
        lines[-1]
        if lines
        else "no message"
    )


def drop_loops(
    cues: list[tuple[float, float, str]],
    said: Sequence[tuple[float, float, str]] = (),
) -> list[tuple[float, float, str]]:
    """
    At most `LOOP_LIMIT` cue a pass for each thing it says, and nothing the
    pass before it has just said.

    A model with music and nobody talking invents: measured, it said "Bye!"
    ten times over and "Alice." twenty-five times, both inside one pass. A
    line invented once is invented again in the pass after it, which is what
    `said` is for - nobody says the same words twice inside a few seconds of
    broadcast - and the first of a run is kept, the rest of it is not.
    """

    already = {
        " ".join(text.split()).casefold()
        for _start, _end, text in said
    }

    kept: list[tuple[float, float, str]] = []
    counted: dict[str, int] = {}

    for start, end, text in cues:

        key = " ".join(text.split()).casefold()

        counted[key] = counted.get(key, 0) + 1

        if counted[key] <= LOOP_LIMIT and key not in already:

            kept.append((start, end, text))

    return kept


def placed(
    cues: list[tuple[float, float, str]],
    offset: float,
) -> list[tuple[float, float, str]]:
    """
    What a piece said, on the timeline of the broadcast.

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
    End a process and whatever it was writing through.
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
    A broadcast's audio, read from its playlist a piece at a time.

    Every request is bounded and belongs to one piece, so what fails is one
    piece: a segment that will not come down is asked for again and then
    skipped, and a playlist past the expiry its URL carries is resolved
    again, because a broadcast outlives the URL that named it.

    The pieces are temporary: they exist to be heard and deleted, and the
    whole directory goes when the capture stops. Errors are kept out of the
    terminal - a run drawing its own caption block owns those rows - and read
    back as the reason the capture ended, if it ended badly.
    """

    def __init__(
        self,
        url: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:

        self._url = url
        self._clock = clock
        self._directory: Path | None = None
        self._log: BinaryIO | None = None

        self._manifest = ""
        self._init: bytes | None = None
        self._pieces: deque[Piece] = deque()
        self._taken = -1
        self._opening = True
        self._clocked = False
        self._last = 0.0
        self._read_at = 0.0
        self._misses = 0
        self._renewals = 0
        self._ended = False
        self._failure: str | None = None
        self._notes: list[str] = []
        self._said: set[str] = set()

    def start(self) -> None:
        """
        Set the capture going. Starting twice does nothing.

        Raises RuntimeError when its own working directory cannot be made.
        Nothing else is fatal here: the resolve, the playlist and every
        piece are retried, and a capture that cannot go on says so through
        `reason` rather than failing the run it belongs to.
        """

        if self._directory is not None:

            return

        try:

            self._directory = Path(
                tempfile.mkdtemp(
                    prefix="subcast-live-",
                )
            )

        except OSError as error:

            raise RuntimeError(
                f"the live audio could not be captured ({error})"
            ) from error

        self._log = (self._directory / "capture.log").open("ab")

    def chunks(
        self,
        after: int = -1,
    ) -> list[Piece]:
        """
        Read the playlist, and answer the pieces closed since a given
        number, oldest first.

        Called from the caption worker, so what it costs is a moment of the
        queue: the playlist is read no more often than `PLAYLIST_SECONDS`,
        and a piece is fetched and decoded once, when it is first seen.
        """

        self._forget(after)

        if self._directory is None or self.finished():

            return []

        now = self._clock()

        if now - self._read_at >= PLAYLIST_SECONDS:

            self._read_at = now

            self._read(now)

        return [
            piece
            for piece in self._pieces
            if piece.sequence > after
        ]

    def finished(self) -> bool:
        """
        Whether the broadcast ended, or the capture gave up on it.
        """

        return self._ended or self._failure is not None

    def reason(self) -> str | None:
        """
        Why the capture stopped, when it stopped badly, or None.
        """

        return self._failure

    def take_notes(self) -> list[str]:
        """
        What is worth saying, each line once, and nothing twice.
        """

        notes = self._notes
        self._notes = []

        return notes

    def stop(self) -> None:
        """
        End the capture and take the pieces with it.
        """

        self._ended = True

        if self._log is not None:

            self._log.close()

        if self._directory is not None:

            shutil.rmtree(
                self._directory,
                ignore_errors=True,
            )

    def _read(
        self,
        now: float,
    ) -> None:
        """
        One look at the playlist: resolve it if it is not known, take every
        piece that has appeared since the last look, and let what it says
        about the broadcast having ended do the rest.
        """

        if not self._manifest:

            self._manifest = self._resolve()

            if not self._manifest:

                return

        try:

            playlist = hls.read(self._manifest)

        except hls.Expired as error:

            self._renew(str(error))

            return

        except hls.Unavailable as error:

            self._miss(str(error))

            return

        if not playlist.segments and not playlist.ended:

            self._miss("it named no pieces")

            return

        self._misses = 0

        if playlist.ended:

            self._ended = True

        try:

            self._take_new(playlist, now)

        except hls.Expired as error:

            # One session ended, not one piece: the ones behind it are named
            # by the same URLs, and the playlist is resolved again before any
            # of them is asked for.
            self._renew(str(error))

    def _take_new(
        self,
        playlist: hls.Playlist,
        now: float,
    ) -> None:
        """
        Every piece this look found that has not been taken, oldest first.
        """

        if playlist.init is not None and self._init is None:

            self._init = self._download(
                playlist.init,
                "the broadcast's init segment could not be fetched",
            )

        if self._opening:

            self._opening = False

            self._taken = min(
                segment.sequence
                for segment in playlist.segments[-START_BEHIND:]
            ) - 1

        for segment in playlist.segments:

            if segment.sequence > self._taken:

                self._take(segment)

    def _take(
        self,
        segment: hls.Segment,
    ) -> None:
        """
        Fetch one piece of the broadcast, decode it, and make it a chunk
        under the number the playlist gave it.

        A piece is written under a name that is not a chunk's and renamed
        only once it is whole, so a chunk that is there is a chunk that can
        be heard: a poll never sees half of one, and no chunk has to be left
        alone just in case.
        """

        if self._directory is None:

            return

        chunk = self._directory / f"chunk_{segment.sequence:05d}.wav"
        partial = chunk.with_suffix(".part")
        source = self._directory / f"segment_{segment.sequence:05d}"

        body = self._download(
            segment.uri,
            "a piece of the broadcast could not be fetched",
        )

        # Taken once, whatever became of this request - except by a session
        # that had expired, which is raised before this and leaves the piece
        # to be taken again from the playlist resolved in its place.
        self._taken = max(self._taken, segment.sequence)

        if body is None:

            return

        # A fragment of a fragmented playlist is not decodable on its own;
        # the init segment is what every piece of it is read with.
        source.write_bytes((self._init or b"") + body)

        # The piece's clock is read from the piece: the audio that is decoded
        # out of it is written under a timestamp of its own, and it is the
        # container that carries the broadcast's.
        at = self._begins_at(source, segment.duration)

        if self._failure is not None:

            source.unlink(missing_ok=True)

            return

        try:

            completed = subprocess.run(
                decode_command(source, partial),
                stdout=subprocess.DEVNULL,
                stderr=self._log,
                check=False,
                timeout=DECODE_SECONDS,
            )

        except (OSError, subprocess.TimeoutExpired) as error:

            self._note(
                "a piece of the broadcast could not be decoded "
                f"({error})"
            )

            partial.unlink(missing_ok=True)

            return

        finally:

            source.unlink(missing_ok=True)

        if completed.returncode != 0 or not partial.is_file():

            self._note(
                "a piece of the broadcast could not be decoded "
                f"({self._log_tail()})"
            )

            partial.unlink(missing_ok=True)

            return

        partial.replace(chunk)

        self._pieces.append(
            Piece(
                sequence=segment.sequence,
                path=chunk,
                at=at,
                duration=segment.duration,
            )
        )

    def _begins_at(
        self,
        piece: Path,
        duration: float,
    ) -> float:
        """
        Where in the broadcast a piece begins, as its own audio says.

        A piece of a live stream carries the broadcast's timeline in its
        timestamps, and that is the timeline a caption is written on: where
        the player has read up to is a different thing, measured a whole
        piece behind the broadcast while the player is between one look at
        the playlist and the next.

        A piece whose clock cannot be read is placed after the one before it,
        which is where the pieces of a playlist tile anyway.
        """

        stamp = timestamp_of(piece)

        if stamp is not None:

            self._clocked = True
            self._last = stamp + duration

            return stamp

        if not self._clocked:

            # Nothing read so far and no clock to start from: a caption with
            # no place on the timeline is worse than no captions, and the run
            # is better told why.
            self._failure = "the broadcast's audio would not say when it aired"

            return self._last

        self._note("a piece of the broadcast would not say when it aired")

        return self._last

    def _download(
        self,
        uri: str,
        missing: str,
    ) -> bytes | None:
        """
        Bytes of one request, asked for a few times before it is given up on.

        A piece that has scrolled out of the window is answered 404, which is
        one piece lost rather than the capture ending. A session that is over
        is raised instead: every piece behind that one is named by the same
        expired URLs, so nothing else can be fetched until the playlist has
        been resolved again.
        """

        for _attempt in range(SEGMENT_TRIES):

            try:

                return hls.fetch(uri)

            except hls.Expired:

                raise

            except hls.Unavailable:

                continue

        self._note(missing)

        return None

    def _resolve(self) -> str:
        """
        The playlist of the rendition this run hears, or "" after saying why
        it could not be found.
        """

        last = "no message"

        for _attempt in range(MANIFEST_TRIES):

            try:

                return manifest_url(self._url)

            except RuntimeError as error:

                last = str(error)

        self._failure = f"the live playlist could not be found ({last})"

        return ""

    def _renew(
        self,
        reason: str,
    ) -> None:
        """
        A session that is over: the playlist is resolved again on the next
        look, so a broadcast longer than the URL that names it keeps its
        captions.
        """

        self._renewals += 1

        if self._renewals > RENEW_LIMIT:

            self._failure = f"the live playlist could not be renewed ({reason})"

            return

        self._manifest = ""

        self._note("the broadcast's playlist was renewed")

    def _miss(
        self,
        reason: str,
    ) -> None:
        """
        A look at the playlist that came back with nothing: a few of those
        in a row is the capture being over rather than the network having a
        bad moment.
        """

        self._misses += 1

        if self._misses >= UNREAD_LIMIT:

            self._failure = f"the live playlist stopped being readable ({reason})"

    def _forget(
        self,
        after: int,
    ) -> None:
        """
        Pieces that have been handed over are dropped from the record: what
        is held is what has not been heard yet.
        """

        while self._pieces and self._pieces[0].sequence <= after:

            self._pieces.popleft()

    def _note(
        self,
        line: str,
    ) -> None:

        text = f"    Live captions: {line}."

        if text in self._said:

            return

        self._said.add(text)

        self._notes.append(text)

    def _log_tail(self) -> str:
        """
        The last thing the capture said, for an error message.
        """

        if self._log is None or self._directory is None:

            return "no message"

        try:

            self._log.flush()

            return last_line(
                (self._directory / "capture.log").read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

        except OSError:

            return "no message"


class LiveCaptions(GrowingCaptions):
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
    ) -> None:

        self.srt_path = stem.with_suffix(".live.srt")

        self._model = model
        self._capture = capture

        self._lock = threading.Lock()
        self._cues: list[tuple[float, float, str]] = []
        self._revision = 0
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

        # Pieces waiting to be heard, and the piece whose tail belongs in
        # front of the next one.
        self._queued: deque[Piece] = deque()
        self._previous: Path | None = None
        self._previous_at = 0.0
        self._previous_duration = 0.0

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
        piece: Piece,
    ) -> None:
        """
        One closed piece: hear it, place it, and write what it said.

        The tail of the piece before is heard again in front of this one -
        back over a little of what has already been said, so the model hears
        the sentence this piece opens in the middle of rather than five
        seconds of cold audio - and what it says in the part already said
        was said by the pass before, and is dropped.

        The last of a piece is left for the next pass on purpose: the audio
        runs out where the piece ends, and a sentence cut off there is a
        sentence the next pass can finish.
        """

        with self._lock:

            said_until = self._said_until

        audio = piece.path
        start = piece.at

        if self._previous is not None and self._previous.exists():

            tail = self._tail_from(said_until)
            stitched = piece.path.with_name("stitch.wav")

            if tail is not None and self._stitch(
                self._previous,
                piece.path,
                stitched,
                tail,
            ):

                audio = stitched
                start = self._previous_at + tail

        try:

            cues = transcribe_cues(
                self._model,
                audio,
                after=max(0.0, said_until - start),
                **LIVE_HEARING,
            )

        except Exception as error:  # noqa: BLE001 - reported, not raised

            self._fail(
                f"a chunk could not be transcribed ({error})"
            )

            return

        finally:

            if audio != piece.path:

                audio.unlink(
                    missing_ok=True
                )

            if self._previous is not None:

                self._previous.unlink(
                    missing_ok=True
                )

            self._previous = piece.path
            self._previous_at = piece.at
            self._previous_duration = piece.duration

        heard = split_cues(
            drop_loops(
                placed(
                    cues,
                    start,
                ),
                said=self._recent(said_until),
            )
        )

        with self._lock:

            self._heard += 1

            if not cues:

                self._silent += 1

        # Nothing heard before what has already been said - the join is
        # there to give the model the words in front of the piece, not to
        # say them twice - and nothing from the seconds the audio runs out
        # in, which the next pass hears again with what follows them.
        said = [
            cue
            for cue in heard
            if cue[0] >= said_until
            and cue[1] <= piece.at + piece.duration - OVERLAP_SECONDS
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

    def _tail_from(
        self,
        said_until: float,
    ) -> float | None:
        """
        Where in the piece before this one the audio to hear again begins.

        The captions stop somewhere inside that piece, and the model is
        given the rest of it back over a fixed length of what has already
        been said. None when there is nothing of it to give - it was dropped
        for want of a reading, or the captions have already run past it.
        """

        if self._previous_duration <= 0.0:

            return None

        tail = max(
            0.0,
            min(
                said_until - self._previous_at - CONTEXT_SECONDS,
                self._previous_duration,
            ),
        )

        if tail >= self._previous_duration:

            return None

        return tail

    def _recent(
        self,
        said_until: float,
    ) -> list[tuple[float, float, str]]:
        """
        What has just been said, which the next pass may not say again: a
        line the model invents over music is invented again in the pass
        after it.
        """

        return [
            cue
            for cue in self._cues
            if cue[0] >= said_until - LOOP_SECONDS
        ]

    def _stitch(
        self,
        previous: Path,
        chunk: Path,
        dest: Path,
        start: float,
    ) -> bool:
        """
        Join the tail of the piece before to this one, in a temporary file.

        False when the join could not be made, which leaves the piece to be
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
        Notice each piece as the capture closes it, place it, and hear it.

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
        belongs is read off the piece itself, so a transcriber that is behind
        costs delay rather than captions in the wrong place, and what is
        waiting can be dropped when it falls too far behind.
        """

        cursor = -1

        while not self._stopping.is_set():

            closed = self._capture.chunks(after=cursor)

            if closed:

                # The number of the newest piece seen, whatever became of
                # the queue: a piece taken once is never taken again.
                cursor = max(piece.sequence for piece in closed)

                self._queued.extend(closed)

            self._note(
                self._capture.take_notes()
            )

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

    def _drop_what_cannot_be_heard(self) -> None:
        """
        Keep the queue short, and the captions with the broadcast.

        A machine slower than realtime would otherwise queue pieces until
        each one's cues are written after mpv has already played past them,
        which looks like captions that stopped: dropping the oldest keeps
        what is said next, and it is said once.
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

            # What was dropped sat between them, and the tail of one piece
            # joined to a piece from another part of the broadcast is a
            # sentence nobody said.
            self._previous.unlink(
                missing_ok=True
            )

            self._previous = None
            self._previous_at = 0.0
            self._previous_duration = 0.0

        with self._lock:

            self._skipped += dropped

            if self._skipped == dropped:

                self._notes.append(
                    "    Live captions cannot keep up with this "
                    "broadcast; skipping ahead to the live edge."
                )

    def _note(
        self,
        lines: list[str],
    ) -> None:

        if not lines:

            return

        with self._lock:

            self._notes.extend(lines)

    def _fail(
        self,
        message: str,
    ) -> None:

        with self._lock:

            if self._failure is None:

                self._failure = message
