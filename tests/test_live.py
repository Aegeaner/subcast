"""Captions for a broadcast, made while it airs."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from subcast import hls, live
from subcast.live import Piece

# The clock a faked broadcast publishes against, and the first piece number
# it counts from.
AIRED = datetime.fromisoformat("2026-09-20T17:00:00+00:00")
FIRST = 1000

MANIFEST = "https://manifest.test/api/manifest/hls_playlist/pl.m3u8"

PAGE = "https://www.youtube.com/watch?v=abc"

# What the faked ffprobe says the first piece begins at.
FIRST_STAMP = 5000.0


def a_playlist(
    sequences: list[int],
    duration: float = 5.0,
    ended: bool = False,
    init: bool = False,
) -> str:
    """
    A media playlist as a live broadcast writes one: a window of pieces,
    each with its length, starting at the clock the first one aired at.
    """

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:5",
        f"#EXT-X-MEDIA-SEQUENCE:{sequences[0]}",
        "#EXT-X-PROGRAM-DATE-TIME:"
        + (
            AIRED + timedelta(seconds=(sequences[0] - FIRST) * duration)
        ).isoformat(),
    ]

    if init:

        lines.append('#EXT-X-MAP:URI="init.mp4"')

    for sequence in sequences:

        lines += [
            f"#EXTINF:{duration},",
            f"seg{sequence}.ts",
        ]

    if ended:

        lines.append("#EXT-X-ENDLIST")

    return "\n".join(lines) + "\n"


class Broadcast:
    """
    A broadcast publishing pieces, faked: the window it is offering, and the
    bytes each piece comes down as.

    `publish` is the only thing that moves it, the way airing does.
    """

    def __init__(
        self,
        window: int = 6,
        duration: float = 5.0,
    ) -> None:

        self.duration = duration
        self.pieces = list(range(FIRST, FIRST + window))
        self.ended = False
        self.init = False
        self.expired = 0
        self.expiring = 0
        self.broken: set[int] = set()
        self.fetched: list[str] = []

    def publish(
        self,
        count: int = 1,
    ) -> None:

        for _ in range(count):

            self.pieces.append(self.pieces[-1] + 1)
            self.pieces.pop(0)

    def read(
        self,
        url: str,
    ) -> hls.Playlist:

        if self.expired:

            self.expired -= 1

            raise hls.Expired("it answered 403")

        return hls.parse(
            a_playlist(
                self.pieces,
                self.duration,
                ended=self.ended,
                init=self.init,
            ),
            url,
        )

    def fetch(
        self,
        uri: str,
    ) -> bytes:

        self.fetched.append(uri)

        if uri.endswith("init.mp4"):

            return b"init"

        if self.expiring:

            self.expiring -= 1

            raise hls.Expired("it answered 403")

        if number(uri) in self.broken:

            raise hls.Unavailable("it answered 404")

        return b"ts"


def number(
    uri: str,
) -> int:

    return int(
        uri.rsplit("seg", 1)[-1].split(".")[0]
    )


class Clock:
    """
    This run's own clock, in a test: it moves only when the test says the
    broadcast has gone on.
    """

    def __init__(self) -> None:

        self.now = 100.0

    def __call__(self) -> float:

        return self.now

    def passes(
        self,
        seconds: float = 2.0,
    ) -> None:

        self.now += seconds


class Programs:
    """
    The outside programs a capture runs, faked: ffprobe says when the audio
    it was asked about begins, ffmpeg writes the audio it was asked for, and
    what each was asked is kept for the test to read.

    The clock ffprobe answers with starts at `FIRST_STAMP` and moves a piece
    at a time, the way a broadcast's audio does.
    """

    def __init__(self) -> None:

        self.commands: list[list[str]] = []
        self.written: list[Path] = []
        self.read: list[bytes] = []
        self.stamps: list[float] = []
        self.broken = False
        self.silent = False

    def run(self, command, **kwargs):

        self.commands.append(list(command))

        if command[0] == "ffprobe":

            if self.silent:

                return subprocess.CompletedProcess(command, 0, "", "")

            stamp = FIRST_STAMP + 5.0 * len(self.stamps)

            self.stamps.append(stamp)

            return subprocess.CompletedProcess(command, 0, f"{stamp}\n", "")

        if self.broken:

            return subprocess.CompletedProcess(command, 1, b"", b"no codec")

        dest = Path(command[-1])
        source = Path(command[command.index("-i") + 1])

        self.read.append(source.read_bytes())

        dest.write_bytes(b"RIFF")

        self.written.append(dest)

        return subprocess.CompletedProcess(command, 0, b"", b"")


class Studio:
    """
    A faked broadcast being captured: what it is publishing, the programs
    the capture runs, and the clock its playlist is timed against.
    """

    def __init__(
        self,
        monkeypatch,
        broadcast: Broadcast,
    ) -> None:

        self.broadcast = broadcast
        self.programs = Programs()
        self.clock = Clock()

        monkeypatch.setattr(live, "manifest_url", lambda url: MANIFEST)
        monkeypatch.setattr(live.hls, "read", broadcast.read)
        monkeypatch.setattr(live.hls, "fetch", broadcast.fetch)
        monkeypatch.setattr(live.subprocess, "run", self.programs.run)

        # The playlist states when its pieces aired on the wall clock, and
        # the captions are placed on this run's own: both are the one clock
        # in a test, so a piece's air time is exactly what the playlist said.
        monkeypatch.setattr(live.time, "time", self.clock)

        self.capture = live.Capture(
            PAGE,
            clock=self.clock,
        )

        self.capture.start()

    def airs(
        self,
        count: int = 1,
    ) -> None:
        """
        More of the broadcast published, and the time for it to have aired.
        """

        self.broadcast.publish(count)
        self.clock.passes()

    def look(
        self,
        after: int = -1,
    ) -> list[Piece]:
        """
        One look at the playlist, a second after the last.
        """

        self.clock.passes()

        return self.capture.chunks(after=after)


class FakeCapture:
    """A capture that hands over whatever the test says it has closed."""

    def __init__(
        self,
        pieces: list[Piece] | None = None,
        finished: bool = True,
        reason: str | None = None,
    ) -> None:

        self.started = 0
        self.stopped = 0
        self.notes: list[str] = []
        self._pieces = list(pieces or [])
        self._finished = finished
        self._reason = reason

    def start(self) -> None:

        self.started += 1

    def chunks(self, after: int = -1) -> list[Piece]:

        return [
            piece
            for piece in self._pieces
            if piece.sequence > after
        ]

    def finished(self) -> bool:

        return self._finished

    def reason(self) -> str | None:

        return self._reason

    def take_notes(self) -> list[str]:

        notes = self.notes
        self.notes = []

        return notes

    def stop(self) -> None:

        self.stopped += 1


class TricklingCapture(FakeCapture):
    """
    A capture that closes one piece per look, the way a broadcast does.
    """

    def __init__(
        self,
        pieces: list[Piece],
    ) -> None:

        super().__init__(pieces, finished=False)

    def chunks(self, after: int = -1) -> list[Piece]:

        if not self._pieces:

            return []

        return [self._pieces.pop(0)]

    def finished(self) -> bool:

        return not self._pieces


def captions(
    tmp_path: Path,
    capture: FakeCapture | None = None,
) -> live.LiveCaptions:
    return live.LiveCaptions(
        tmp_path / "abc",
        model=None,
        capture=capture or FakeCapture(),
    )


def pieces_in(
    tmp_path: Path,
    *sequences: int,
    duration: float = 5.0,
    at: float = 5000.0,
) -> list[Piece]:
    """
    Pieces of the broadcast on disk, as a capture hands them over: each one
    beginning a piece-length after the one before it.
    """

    written = []

    for index, sequence in enumerate(sequences):

        path = tmp_path / f"chunk_{sequence:05d}.wav"
        path.write_bytes(b"")

        written.append(
            Piece(
                sequence=sequence,
                path=path,
                at=at + index * duration,
                duration=duration,
            )
        )

    return written


def hearing(
    monkeypatch,
    *answers: list[tuple[float, float, str]],
) -> None:
    """
    What the model hears, one answer per pass.
    """

    remaining = [list(answer) for answer in answers]

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: (
            remaining.pop(0)
            if remaining
            else []
        ),
    )


def test_the_playlist_is_asked_for_with_the_selector_the_player_uses(monkeypatch):
    """
    The capture asks yt-dlp for the playlist of the same rendition mpv is
    told to play. The copy is what matters: captions heard from one
    rendition of a broadcast are not in pace with another.
    """

    asked: list[list[str]] = []

    def run(command, **kwargs):

        asked.append(list(command))

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{MANIFEST}\n",
            stderr="",
        )

    monkeypatch.setattr(live.subprocess, "run", run)

    assert live.manifest_url(PAGE) == MANIFEST

    command = asked[0]

    assert command[0] == "yt-dlp"
    assert command[command.index("-f") + 1] == "worstaudio/worst"
    assert command[command.index("-g") + 1] == PAGE


def test_a_broadcast_that_cannot_be_resolved_is_reported(monkeypatch):
    """
    yt-dlp saying no is a line to print, not a traceback: the run plays
    without captions.
    """

    monkeypatch.setattr(
        live.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="ERROR: Video unavailable\n",
        ),
    )

    with pytest.raises(RuntimeError) as raised:

        live.manifest_url(PAGE)

    assert "Video unavailable" in str(raised.value)


def test_a_piece_is_decoded_on_its_own(tmp_path: Path):
    """
    A piece is a bounded file rather than a pipe, so ffmpeg is handed it and
    writes the audio to hear: one channel at 16 kHz, which is what the
    caption model was trained on.
    """

    command = live.decode_command(
        tmp_path / "segment_00042",
        tmp_path / "chunk_00042.part",
    )

    assert command[0] == "ffmpeg"
    assert command[command.index("-i") + 1] == str(tmp_path / "segment_00042")
    assert command[command.index("-ar") + 1] == str(live.SAMPLE_RATE)
    assert command[command.index("-ac") + 1] == "1"
    assert "-vn" in command
    assert command[-1] == str(tmp_path / "chunk_00042.part")


def test_a_piece_is_asked_when_it_began(monkeypatch, tmp_path: Path):
    """
    A piece's own clock is what a caption is placed by, so the capture asks
    the audio itself: ffprobe reads the stream's first timestamp, and a piece
    that will not say is not placed at a guess.
    """

    asked: list[list[str]] = []

    def run(command, **kwargs):

        asked.append(list(command))

        return subprocess.CompletedProcess(command, 0, "9812.345011\n", "")

    monkeypatch.setattr(live.subprocess, "run", run)

    assert live.timestamp_of(tmp_path / "chunk_00042.wav") == 9812.345011

    command = asked[0]

    assert command[0] == "ffprobe"
    assert command[command.index("-select_streams") + 1] == "a:0"
    assert command[-1] == str(tmp_path / "chunk_00042.wav")

    monkeypatch.setattr(
        live.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    assert live.timestamp_of(tmp_path / "chunk_00042.wav") is None


def test_a_piece_is_placed_by_its_own_clock(monkeypatch):
    """
    What the capture hands over is already placed: each piece of a broadcast
    says at what moment of it the audio begins, and that is where its words
    go. Nothing is read off the player, which is what put captions on screen
    before the words.
    """

    studio = Studio(monkeypatch, Broadcast())

    pieces = studio.look()

    assert [piece.at for piece in pieces] == [FIRST_STAMP, FIRST_STAMP + 5.0]
    assert [piece.duration for piece in pieces] == [5.0, 5.0]


def test_a_piece_that_will_not_say_when_it_began_is_placed_after_the_one_before(
    monkeypatch,
):
    """
    A piece whose clock cannot be read is placed where the piece before it
    ends - which is where the pieces of a playlist tile - rather than left
    with no place on the timeline.
    """

    studio = Studio(monkeypatch, Broadcast())

    first = studio.look()

    studio.programs.silent = True

    studio.airs(1)

    (later,) = studio.look(after=first[-1].sequence)

    assert later.at == first[-1].at + first[-1].duration

    assert "would not say when it aired" in " ".join(studio.capture.take_notes())


def test_a_broadcast_whose_audio_will_not_say_when_it_aired_is_refused(
    monkeypatch,
):
    """
    Nothing read so far and no clock to start from is a caption with nowhere
    to go, which is worse than no captions: the capture says so instead.
    """

    studio = Studio(monkeypatch, Broadcast())

    studio.programs.silent = True

    assert studio.look() == []

    assert studio.capture.finished() is True
    assert "would not say when it aired" in studio.capture.reason()


def test_the_window_opens_on_the_pieces_being_broadcast_now(tmp_path, monkeypatch):
    """
    A playlist holds the last few seconds of the broadcast, most of which
    aired before the run began. What is taken is the piece airing now and the
    one before it - the audio playback is heading towards - and the number
    each is kept under is the playlist's own.
    """

    studio = Studio(monkeypatch, Broadcast())

    pieces = studio.look()

    assert [piece.sequence for piece in pieces] == [1004, 1005]
    assert [piece.duration for piece in pieces] == [5.0, 5.0]
    assert [piece.path.name for piece in pieces] == [
        "chunk_01004.wav",
        "chunk_01005.wav",
    ]

    # Each piece is decoded into a file that is not a chunk's until it is
    # whole, so a chunk that is there is a chunk that can be heard.
    assert [path.name for path in studio.programs.written] == [
        "chunk_01004.part",
        "chunk_01005.part",
    ]

    assert [number(uri) for uri in studio.broadcast.fetched] == [1004, 1005]


def test_a_piece_that_has_been_taken_is_never_taken_again(monkeypatch):
    """
    A piece is what the playlist numbered it; a look that finds the same
    window again, or a window that has slid, takes only what is new.
    """

    studio = Studio(monkeypatch, Broadcast())

    first = studio.look()

    assert [piece.sequence for piece in first] == [1004, 1005]

    studio.airs(2)

    later = studio.look(after=first[-1].sequence)

    assert [piece.sequence for piece in later] == [1006, 1007]


def test_a_playlist_that_has_expired_is_resolved_again(monkeypatch):
    """
    A googlevideo URL carries its own expiry and a broadcast outlives it, so
    the run asks for a fresh playlist rather than losing the rest of its
    captions to an expired one.
    """

    broadcast = Broadcast()
    broadcast.expired = 1

    studio = Studio(monkeypatch, broadcast)

    asked: list[str] = []

    monkeypatch.setattr(
        live,
        "manifest_url",
        lambda url: asked.append(url) or MANIFEST,
    )

    assert studio.look() == []

    pieces = studio.look()

    assert len(asked) == 2
    assert [piece.sequence for piece in pieces] == [1004, 1005]
    assert studio.capture.reason() is None
    assert "renewed" in " ".join(studio.capture.take_notes())


def test_a_piece_whose_session_expired_is_taken_again(monkeypatch):
    """
    Every piece of a playlist is named by URLs carrying the same expiry, so
    one piece answered 403 is the whole session being over - not the piece
    being lost. The playlist is resolved again once, and the piece is taken
    from the fresh one rather than counted as a miss.
    """

    broadcast = Broadcast()
    broadcast.expiring = 1

    studio = Studio(monkeypatch, broadcast)

    asked: list[str] = []

    monkeypatch.setattr(
        live,
        "manifest_url",
        lambda url: asked.append(url) or MANIFEST,
    )

    assert studio.look() == []

    # The session is over, so the playlist is a resolution away: this look
    # ends with it cleared, and the next one asks for a fresh playlist.
    assert len(asked) == 1

    pieces = studio.look()

    assert len(asked) == 2
    assert [piece.sequence for piece in pieces] == [1004, 1005]
    assert studio.capture.reason() is None
    assert "renewed" in " ".join(studio.capture.take_notes())


def test_a_playlist_that_cannot_be_renewed_ends_the_capture(monkeypatch):
    studio = Studio(monkeypatch, Broadcast())

    monkeypatch.setattr(
        live.hls,
        "read",
        lambda url: (_ for _ in ()).throw(hls.Expired("it answered 403")),
    )

    for _ in range(live.RENEW_LIMIT + 1):

        studio.clock.passes()

        studio.capture.chunks()

    assert studio.capture.finished() is True
    assert "could not be renewed" in studio.capture.reason()


def test_a_playlist_that_stops_being_readable_ends_the_capture(monkeypatch):
    """
    A few looks in a row that come back with nothing is the capture being
    over rather than the network having a bad moment, and it says so.
    """

    studio = Studio(monkeypatch, Broadcast())

    monkeypatch.setattr(
        live.hls,
        "read",
        lambda url: (_ for _ in ()).throw(hls.Unavailable("it answered 503")),
    )

    for _ in range(live.UNREAD_LIMIT - 1):

        studio.clock.passes()

        assert studio.capture.finished() is False

        studio.capture.chunks()

    studio.clock.passes()

    studio.capture.chunks()

    assert studio.capture.finished() is True
    assert "stopped being readable" in studio.capture.reason()


def test_a_piece_that_will_not_come_down_is_skipped(monkeypatch):
    """
    One piece lost is not the capture ending: it is asked for a few times,
    said once, and the broadcast carries on without it.
    """

    broadcast = Broadcast()
    broadcast.broken = {1004}

    studio = Studio(monkeypatch, broadcast)

    pieces = studio.look()

    assert [piece.sequence for piece in pieces] == [1005]

    assert [number(uri) for uri in broadcast.fetched].count(1004) == live.SEGMENT_TRIES

    assert "could not be fetched" in " ".join(studio.capture.take_notes())


def test_a_broadcast_that_has_ended_is_not_a_failure(monkeypatch):
    """
    `#EXT-X-ENDLIST` is the broadcast saying it is over, which the playlist
    knows and ffmpeg's exit code only ever implied. The pieces it published
    last are still taken.
    """

    broadcast = Broadcast()
    broadcast.ended = True

    studio = Studio(monkeypatch, broadcast)

    assert [piece.sequence for piece in studio.look()] == [1004, 1005]
    assert studio.capture.finished() is True
    assert studio.capture.reason() is None


def test_a_fragmented_playlist_is_read_with_its_init_segment(monkeypatch):
    """
    A fragment of a fragmented stream is not decodable on its own, so a
    playlist that names an init segment has it fetched once and decoded in
    front of every piece.
    """

    broadcast = Broadcast()
    broadcast.init = True

    studio = Studio(monkeypatch, broadcast)

    pieces = studio.look()

    assert [piece.sequence for piece in pieces] == [1004, 1005]

    # what ffmpeg was handed: the init segment, then the piece
    assert studio.programs.read == [b"initts", b"initts"]

    assert "init.mp4" in " ".join(broadcast.fetched)


def test_the_join_begins_where_the_captions_stopped(tmp_path: Path):
    """
    A word arriving across a piece boundary must not be handed to the model
    in halves: ffmpeg joins the tail of the previous piece to this one, cut
    behind where the captions stopped and over a little of what was said.
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


def test_every_closed_piece_is_heard_as_they_are_deleted(tmp_path, monkeypatch):
    """
    The regression this pipeline was rewritten for: pieces used to be walked
    by their position in a listing, and hearing one deleted it, so the
    listing shifted under the cursor and every second piece of dialogue was
    dropped - captions in bursts, with a piece-length of nothing between
    them.
    """

    heard: list[str] = []

    def hear(model, path, **settings):
        heard.append(Path(path).name)
        return []

    monkeypatch.setattr(live, "transcribe_cues", hear)
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    job = captions(
        tmp_path,
        capture=TricklingCapture(pieces_in(tmp_path, 0, 1, 2, 3)),
    )

    job._work()

    assert heard == [
        "chunk_00000.wav",
        "chunk_00001.wav",
        "chunk_00002.wav",
        "chunk_00003.wav",
    ]


def test_a_backlog_is_placed_by_when_each_piece_closed(tmp_path, monkeypatch):
    """
    One look can find several pieces closed at once - a slow poll or a missed
    one - and they did not all close at that moment. Each is placed by the
    clock the playlist gave it, so nothing drifts with the size of the
    backlog.
    """

    hearing(
        monkeypatch,
        [(1.0, 2.0, "first")],
        [(6.0, 7.0, "second")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: True)

    first, second = pieces_in(tmp_path, 4, 5, at=5000.0)

    job = captions(tmp_path)

    # What the capture hands over is already placed: a piece says where it is.
    assert [piece.at for piece in (first, second)] == [5000.0, 5005.0]

    for piece in (first, second):

        job.transcribe(piece)

    assert job.cues() == [
        (5001.0, 5002.0, "first"),
        (5006.0, 5007.0, "second"),
    ]


def test_the_pass_hears_the_words_in_front_of_the_piece(tmp_path, monkeypatch):
    """
    A piece is heard with the tail of the one before it, back over a fixed
    length of what has already been said: the model is given the sentence
    this piece opens in the middle of rather than five seconds of cold audio.
    """

    hearing(
        monkeypatch,
        [(1.0, 3.0, "Good morning.")],
        [(5.5, 6.5, "And this is new.")],
    )

    joins: list[float] = []

    def stitch(self, previous, chunk, dest, start):

        joins.append(start)

        return True

    monkeypatch.setattr(live.LiveCaptions, "_stitch", stitch)

    first, second = pieces_in(tmp_path, 0, 1)

    job = captions(tmp_path)

    job.transcribe(Piece(0, first.path, 5000.0, 5.0))

    assert job.cues() == [(5001.0, 5003.0, "Good morning.")]

    job.transcribe(Piece(1, second.path, 5005.0, 5.0))

    # The captions stopped at 5003 and the model is given from 5000.5: the
    # piece before, less all but the last 2.5 seconds of what was said.
    assert joins == [0.5]

    assert job.cues() == [
        (5001.0, 5003.0, "Good morning."),
        (5006.0, 5007.0, "And this is new."),
    ]


def test_the_end_of_a_piece_waits_for_the_pass_that_hears_its_ending(
    tmp_path,
    monkeypatch,
):
    """
    The audio runs out where the piece ends, so the last seconds of a piece
    may be a sentence cut in half: they wait for the next pass, which hears
    them again with what follows.
    """

    hearing(
        monkeypatch,
        [(1.0, 2.0, "early"), (3.0, 5.0, "to the very end")],
        [(2.0, 4.0, "to the very end"), (5.0, 6.0, "next")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: True)

    first, second = pieces_in(tmp_path, 0, 1)

    job = captions(tmp_path)

    job.transcribe(Piece(0, first.path, 5000.0, 5.0))

    # "to the very end" ends inside the last second and a half of the piece,
    # so only the cue before it is said
    assert [text for _, _, text in job.cues()] == ["early"]

    job.transcribe(Piece(1, second.path, 5005.0, 5.0))

    # the next pass hears it again with the words after it
    assert [text for _, _, text in job.cues()] == [
        "early",
        "to the very end",
        "next",
    ]

    # the piece that was joined in front is heard once and then gone
    assert not first.path.exists()


def test_a_line_the_model_heard_from_the_words_before_is_dropped(
    tmp_path,
    monkeypatch,
):
    """
    The join reaches back over words the last pass already said, so a line
    the model makes of those words alone is not said twice. Where a line
    straddles the join it is cut rather than dropped (`_heard`), which is
    what the model's word timings are for.
    """

    hearing(
        monkeypatch,
        [(1.0, 3.0, "already said")],
        [(-3.0, -0.5, "already said")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: True)

    first, second = pieces_in(tmp_path, 0, 1)

    job = captions(tmp_path)

    job.transcribe(Piece(0, first.path, 5000.0, 5.0))
    job.transcribe(Piece(1, second.path, 5005.0, 5.0))

    assert [text for _, _, text in job.cues()] == [
        "already said",
    ]


def test_what_waits_too_long_is_dropped_and_said_once(tmp_path, monkeypatch):
    """
    A machine slower than realtime must lose detail, not the live edge: the
    queue is short, and what it drops is said out loud once rather than
    looking like captions that stopped.
    """

    monkeypatch.setattr(live, "transcribe_cues", lambda model, path, **settings: [])

    pieces = pieces_in(tmp_path, 0, 1, 2, 3, 4)

    job = captions(tmp_path)

    job._queued.extend(pieces)

    job._drop_what_cannot_be_heard()

    # three may wait, so the two oldest of five are dropped
    assert [piece.sequence for piece in job._queued] == [2, 3, 4]

    assert not pieces[0].path.exists()
    assert not pieces[1].path.exists()
    assert pieces[2].path.exists()

    notes = job.take_notes()

    assert len(notes) == 1
    assert "cannot keep up" in notes[0]

    # said once, not once per piece
    job._queued.extend(pieces_in(tmp_path, 5, at=5025.0))

    job._drop_what_cannot_be_heard()

    assert job.take_notes() == []

    assert job.summary() is not None
    assert "skipped" in job.summary()


def test_the_summary_counts_what_the_captions_came_to(tmp_path, monkeypatch):
    hearing(
        monkeypatch,
        [],
        [(1.0, 2.0, "Hello.")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    job = captions(tmp_path, FakeCapture(pieces_in(tmp_path, 0, 1)))

    job._work()

    assert job.summary() == (
        "    Live captions: 2 chunk(s) heard, 1 with no speech."
    )


def test_a_chunk_that_cannot_be_heard_is_said_once(tmp_path, monkeypatch):
    """
    Whisper falling over is a line to print while the video plays, not the
    end of the run - the same way a caption download that failed is.
    """

    def exploded(model, path, **settings):
        raise RuntimeError("no such file")

    monkeypatch.setattr(live, "transcribe_cues", exploded)

    job = captions(tmp_path)

    job.transcribe(Piece(0, tmp_path / "chunk_00000.wav", 5000.0, 5.0))

    assert job.failure_message() == (
        "    Live captions failed: a chunk could not be transcribed "
        "(no such file); playing without them."
    )

    # nothing was heard and nothing was skipped, so there is nothing to
    # report: the failure has already said its line.
    assert job.summary() is None


def test_a_capture_that_could_not_start_is_reported(tmp_path):
    """
    A working directory that cannot be made is worth saying out loud rather
    than failing silently: the run plays on either way.
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


def test_cues_are_moved_onto_the_timeline_of_the_broadcast():
    assert live.placed(
        [(1.0, 2.0, "spoken")],
        offset=5000.0,
    ) == [(5001.0, 5002.0, "spoken")]


def test_a_sentence_the_model_loops_is_said_once():
    """
    Left on music, the model invents - measured, the same line cue after cue,
    ten and twenty-five times inside one pass. Nobody says the same words
    twice in five seconds of broadcast.
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


def test_a_line_the_pass_before_said_is_not_said_again():
    """
    A limit inside one pass cannot see a line the model invents again in the
    pass after it, which is what a model left on music does: what has just
    been said is what the next pass may not say.
    """

    assert live.drop_loops(
        [
            (0.0, 1.0, "Bye!"),
            (2.0, 3.0, "Come on!"),
        ],
        said=[
            (5000.0, 5001.0, "Bye!"),
            (5001.0, 5002.0, "Let's play."),
        ],
    ) == [
        (2.0, 3.0, "Come on!"),
    ]
