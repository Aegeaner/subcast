"""Remembering where an item got to, so the next run picks it up."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from subcast import live, player
from subcast.meta import Streams
from subcast.subtitles import PendingSubtitles, Prepared


class FakeClient:
    """An mpv that only remembers what it was told."""

    def __init__(self, problem: str | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.problem = problem

    def command(self, *command: str) -> str | None:
        self.commands.append(command)
        return self.problem


def prepared() -> Prepared:
    return Prepared(
        srt_path=Path("/tmp/example.srt"),
        chapters_path=None,
        cues=[],
        segments=[],
    )


def test_subtitles_that_are_not_ready_are_asked_about_again():
    release = threading.Event()

    def work():
        release.wait(timeout=5)
        return prepared()

    job = PendingSubtitles(work)
    job.start()

    client = FakeClient()

    assert player.attach_subtitles(client, job) is False
    assert client.commands == []

    release.set()
    job.wait()

    assert player.attach_subtitles(client, job) is True
    assert client.commands == [
        ("sub-add", "/tmp/example.srt", "select"),
    ]


def test_subtitles_that_are_ready_are_added_once():
    job = PendingSubtitles.finished(prepared())
    client = FakeClient()

    assert player.attach_subtitles(client, job) is True
    assert player.attach_subtitles(client, job) is True

    # the caller stops asking once this says so, but a second call is
    # harmless: mpv replaces the track it was given
    assert len(client.commands) == 2


def test_a_failed_preparation_is_reported_not_retried(capsys):
    def work():
        raise RuntimeError("the published captions were empty")

    job = PendingSubtitles(work)
    job.start()
    job.wait()

    client = FakeClient()

    assert player.attach_subtitles(client, job) is True
    assert client.commands == []
    assert "playing without them" in capsys.readouterr().out


def test_mpv_refusing_the_file_is_said_out_loud(capsys):
    job = PendingSubtitles.finished(prepared())
    client = FakeClient(problem="invalid parameter")

    assert player.attach_subtitles(client, job) is True
    assert "invalid parameter" in capsys.readouterr().out


def test_streams_are_handed_to_mpv_instead_of_a_page():
    """
    `--ytdl=no` with the URLs is what saves mpv the extraction subcast has
    already done, and the sound is a second URL, so mpv gets it as an
    external track. No headers go with them: sending the ones a resolve
    reported is what made YouTube answer `HTTP error 400` on the stream URL
    while the same URL played when mpv asked for it by itself.
    """

    assert player.stream_arguments(
        Streams(
            video="https://example.test/video",
            audio="https://example.test/audio",
        )
    ) == [
        "--ytdl=no",
        "--audio-file=https://example.test/audio",
    ]


def test_the_run_says_which_of_the_two_things_mpv_gets(monkeypatch, capsys):
    """
    The page URL is printed either way, so it cannot tell a reader whether
    mpv was handed the resolved URLs or the page to extract - which is what
    the waiting time is made of.
    """

    monkeypatch.setattr(player, "mpv_path", lambda: "mpv")
    monkeypatch.setattr(player, "run_mpv", lambda *args, **kwargs: 0)

    player.play_window("https://example.test/watch")
    assert "Streams: mpv extracts them from the page" in capsys.readouterr().out

    player.play_window(
        "https://example.test/watch",
        streams=Streams(video="https://example.test/video", audio=None),
    )
    assert "Streams: resolved by subcast" in capsys.readouterr().out


class FakeSocket:
    """A socket that only records what was asked."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


def test_a_property_mpv_answers_is_read_back(monkeypatch):
    """
    Every reply mpv gives carries an `error` field, and "success" is the
    value it has when mpv is answering: reading that field as a verdict is
    what made this return nothing for every property there is, which
    quietly turned resumes, end-of-file detection and the arrival rate into
    no-ops until a rate had to be read.
    """

    client = player.Ipc.__new__(player.Ipc)
    client.socket = FakeSocket()
    client.buffer = b""
    client.request_id = 0

    replies = iter(
        [
            '{"data": 6.5, "request_id": 1, "error": "success"}',
            '{"request_id": 2, "error": "property unavailable"}',
        ]
    )
    monkeypatch.setattr(client, "_read_line", lambda: next(replies))

    assert client.get("time-pos") == 6.5
    assert client.get("nonsense") is None


def test_the_format_argument_stays_off_hls(monkeypatch, capsys):
    """
    A height filter alone lands on YouTube's 1080p "premium" HLS rendition
    (4600k, measured) where the DASH formats beside it are 1417k and 2130k
    - and the wait before the first frame on this path is mpv filling its
    cache, so the bitrate is the wait.

    The same request without the filter follows it: a broadcast has HLS
    and nothing else, so the filter matches none of its formats and mpv's
    own yt-dlp run answers "Requested format is not available" instead of
    falling through to the `/best` after it.
    """

    monkeypatch.setattr(player, "mpv_path", lambda: "mpv")

    commands: list[list[str]] = []
    monkeypatch.setattr(
        player,
        "run_mpv",
        lambda command, *args, **kwargs: commands.append(command) or 0,
    )

    player.play_window("https://example.test/watch", quality=1080)

    assert (
        "--ytdl-format=bestvideo[height<=1080][protocol^=https]"
        "+bestaudio/bestvideo[height<=1080]+bestaudio/best"
    ) in commands[0]


def test_one_url_needs_no_external_track():
    assert player.stream_arguments(
        Streams(video="https://example.test/both", audio=None)
    ) == ["--ytdl=no"]


def test_a_stream_mpv_cannot_load_is_tried_once_more():
    """
    YouTube hands out signed stream URLs that answer 403 from time to
    time; a fresh extraction is the cure, and mpv stops at the first one.
    """

    attempts: list[int] = []

    def play() -> int:
        attempts.append(1)
        return player.LOAD_ERROR if len(attempts) == 1 else 0

    assert player.retry_load_error(play) == 0
    assert len(attempts) == 2


def test_a_retry_builds_a_different_second_attempt():
    """
    A stream the site refused is played by extracting the page instead, so
    the retry runs whatever `again` returns rather than the first command.
    """

    ran: list[str] = []

    def play() -> int:
        ran.append("first")
        return player.LOAD_ERROR

    def again() -> int:
        ran.append("second")
        return 0

    assert player.retry_load_error(play, again=again) == 0
    assert ran == ["first", "second"]


def test_a_second_load_failure_is_reported_as_it_stands():
    attempts: list[int] = []

    def play() -> int:
        attempts.append(1)
        return player.LOAD_ERROR

    assert player.retry_load_error(play) == player.LOAD_ERROR
    assert len(attempts) == 2


@pytest.mark.parametrize("status", [0, 1, 3, 4, 130])
def test_anything_else_is_not_a_stream_to_fetch_again(status: int):
    """A quit, a bad option or Ctrl-C must not start playback over."""

    attempts: list[int] = []

    def play() -> int:
        attempts.append(1)
        return status

    assert player.retry_load_error(play) == status
    assert len(attempts) == 1


def test_a_position_survives_to_the_next_run(tmp_path: Path):
    stem = tmp_path / "abc123"

    player.Positions(stem).update(754.0, 3600.0)

    assert player.Positions(stem).start == 754.0


def test_an_item_that_was_never_started_begins_at_the_beginning(
    tmp_path: Path,
):
    stem = tmp_path / "abc123"

    assert player.Positions(stem).start == 0.0

    # a truncated or hand-edited file is no reason to start somewhere odd
    (tmp_path / "abc123.position").write_text("half a number\n")

    assert player.Positions(stem).start == 0.0


def test_an_item_watched_to_the_end_is_not_resumed(tmp_path: Path):
    stem = tmp_path / "abc123"

    # a minute from the end: still worth resuming
    player.Positions(stem).update(3540.0, 3600.0)
    assert player.Positions(stem).start == 3540.0

    # inside the last stretch: that is watched
    player.Positions(stem).update(
        3600.0 - player.FINISHED_SECONDS,
        3600.0,
    )
    assert player.Positions(stem).start == 0.0

    # and so is anything mpv reports as having reached the end
    player.Positions(stem).update(1800.0, 3600.0)
    player.Positions(stem).update(1800.0, 3600.0, eof=True)
    assert player.Positions(stem).start == 0.0


def test_a_stream_of_unknown_length_keeps_its_position(
    tmp_path: Path,
):
    """
    mpv reporting no length is no reason to lose the position: the end
    simply cannot be recognised, and the position is all we have.
    """

    stem = tmp_path / "abc123"

    player.Positions(stem).update(754.0, None)

    assert player.Positions(stem).start == 754.0


def test_the_player_is_told_where_to_start(tmp_path: Path):
    stem = tmp_path / "abc123"
    positions = player.Positions(stem)

    assert player.start_arguments(positions) == []
    assert player.start_arguments(None) == []

    positions.update(754.04, 3600.0)

    assert player.start_arguments(
        player.Positions(stem)
    ) == ["--start=754.0"]


def test_starting_over_ignores_what_was_remembered(tmp_path: Path):
    stem = tmp_path / "abc123"

    player.Positions(stem).update(754.0, 3600.0)

    positions = player.Positions(stem, resume=False)

    assert positions.start == 0.0

    # and it takes over from there as it plays
    positions.update(60.0, 3600.0)

    assert player.Positions(stem).start == 60.0


def test_a_position_that_cannot_be_written_is_not_fatal(
    tmp_path: Path,
):
    """
    Playback is the point; being unable to remember where you are is not
    worth stopping for (a read-only cache, a full disk).
    """

    directory = tmp_path / "locked"
    directory.mkdir()
    directory.chmod(0o500)

    try:
        player.Positions(directory / "abc123").update(10.0, 3600.0)

    finally:
        directory.chmod(0o700)


class LiveClient:
    """An mpv that answers the two properties a broadcast is placed by."""

    def __init__(
        self,
        cache_time: float | None = 5000.0,
        position: float | None = 4987.0,
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.cache_time = cache_time
        self.position = position

    def get(self, name: str):
        return {
            "demuxer-cache-time": self.cache_time,
            "time-pos": self.position,
        }.get(name)

    def command(self, *command: str) -> str | None:
        self.commands.append(command)
        return None


def place(
    job: live.LiveCaptions,
    tmp_path: Path,
    sequence: int,
    at: float,
) -> live.LiveCaptions:
    """
    A chunk closed at a known moment of the broadcast, heard the way the
    worker hears one.
    """

    path = tmp_path / f"chunk_{sequence:05d}.wav"
    path.write_bytes(b"")

    job.transcribe(live.Chunk(sequence, path, at))

    return job


def broadcast(
    tmp_path: Path,
    monkeypatch,
    cues: list[tuple[float, float, str]] | None = None,
) -> live.LiveCaptions:
    """
    A live job that has already heard one chunk, without a capture behind
    it: the chunk is what the player and mpv are handed.
    """

    monkeypatch.setattr(
        live.LiveCaptions,
        "start",
        lambda self: None,
    )
    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: list(
            cues if cues is not None else [(1.0, 3.0, "Good morning.")]
        ),
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    job = live.LiveCaptions(
        tmp_path / "abc",
        model=None,
        capture=live.Capture("https://example.test/watch"),
        clock=lambda: 115.0,
    )

    job.sample(100.0, 5000.0)

    return place(job, tmp_path, 0, 5000.0)


def test_a_broadcast_is_handed_over_and_then_read_again(
    tmp_path: Path,
    monkeypatch,
):
    """
    mpv gets the file once the first cues are in it, and after that it is
    told to read it again as it grows - there is no end of it to wait for,
    and handing over the same track twice would restart what is on screen.
    """

    captions = broadcast(tmp_path, monkeypatch)
    client = LiveClient()
    view = player.LiveView(client, captions)

    view.pass_over()

    assert client.commands == [
        ("sub-add", str(captions.srt_path), "select"),
    ]

    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: [(0.5, 1.0, "And another thing.")],
    )

    place(captions, tmp_path, 1, 5005.0)

    view.pass_over()

    assert client.commands == [
        ("sub-add", str(captions.srt_path), "select"),
        ("sub-reload",),
    ]


def test_a_broadcast_with_nothing_said_yet_is_left_alone(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        live.LiveCaptions,
        "start",
        lambda self: None,
    )

    captions = live.LiveCaptions(
        tmp_path / "abc",
        model=None,
        capture=live.Capture("https://example.test/watch"),
    )

    client = LiveClient()

    player.LiveView(client, captions).pass_over()

    assert client.commands == []


def test_the_capture_starts_when_something_begins_watching(
    tmp_path: Path,
    monkeypatch,
):
    """
    Preparing a broadcast is not playing it: an item worked out for later
    has nothing on screen for its captions to be in step with, so whoever
    drives the playback is what starts the capture.
    """

    started: list[int] = []

    monkeypatch.setattr(
        live.LiveCaptions,
        "start",
        lambda self: started.append(1),
    )

    captions = live.LiveCaptions(
        tmp_path / "abc",
        model=None,
        capture=live.Capture("https://example.test/watch"),
    )

    assert started == []

    player.LiveView(LiveClient(), captions)

    assert started == [1]


def test_a_chunk_is_placed_by_where_mpv_has_read_up_to(
    tmp_path: Path,
    monkeypatch,
):
    """
    `cache-time` is the position mpv has read up to, which is the audio
    being captured right now - so the chunk that has just closed belongs a
    chunk-length behind it, not where playback is.
    """

    monkeypatch.setattr(
        live.LiveCaptions,
        "start",
        lambda self: None,
    )
    monkeypatch.setattr(
        live,
        "transcribe_cues",
        lambda model, path, **settings: [(1.0, 2.0, "Good morning.")],
    )
    monkeypatch.setattr(live.LiveCaptions, "_stitch", lambda self, p, c, d, s: False)

    captions = live.LiveCaptions(
        tmp_path / "abc",
        model=None,
        capture=live.Capture("https://example.test/watch"),
    )

    player.LiveView(
        LiveClient(cache_time=5000.0),
        captions,
    ).pass_over()

    chunk = tmp_path / "chunk_00000.wav"
    chunk.write_bytes(b"")

    captions._place([(0, chunk)])
    captions.transcribe(captions._queued.popleft())

    # A chunk-length behind the live edge, plus the second the chunk's own
    # cue starts at.
    assert captions.cues()[0][0] == pytest.approx(
        5000.0 - live.CHUNK_SECONDS + 1.0,
        abs=1.0,
    )


def test_a_live_failure_is_said_once(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    def exploded(model, path):
        raise RuntimeError("no such file")

    monkeypatch.setattr(
        live.LiveCaptions,
        "start",
        lambda self: None,
    )
    monkeypatch.setattr(live, "transcribe_cues", exploded)

    captions = live.LiveCaptions(
        tmp_path / "abc",
        model=None,
        capture=live.Capture("https://example.test/watch"),
    )

    captions.sample(time.monotonic(), 5000.0)

    place(captions, tmp_path, 0, 5000.0)

    client = LiveClient()
    view = player.LiveView(client, captions)

    view.pass_over()
    view.pass_over()

    assert capsys.readouterr().out.count("Live captions failed") == 1


def test_a_broadcast_keeps_mpv_from_printing_its_track_list(monkeypatch):
    """
    mpv answers every subtitle reload by logging its whole track list -
    four lines of terminal, every chunk of a broadcast, in both modes - so
    playback's own logging is turned down for a live run. Only that
    module: `all=warn` also takes the terminal's subtitles with it. That
    `Reloaded:` is an MP_INFO from mpv's `print_track_list` is why turning
    the OSD down does not hide it.
    """

    monkeypatch.setattr(player, "mpv_path", lambda: "mpv")

    commands: list[list[str]] = []
    monkeypatch.setattr(
        player,
        "run_mpv",
        lambda command, *args, **kwargs: commands.append(command) or 0,
    )

    player.play_window("https://example.test/watch", live=True)
    player.play_window("https://example.test/watch")
    player.play_with_mpv("https://example.test/watch", live=True)

    assert "--msg-level=cplayer=warn" in commands[0]
    assert "--msg-level=cplayer=warn" not in commands[1]
    assert "--msg-level=cplayer=warn" in commands[2]


def test_only_the_sound_of_a_broadcast_is_asked_for(monkeypatch):
    """
    A live item has no audio-only format - its formats are muxed - so the
    plain `bestaudio/best` falls back to 1080p of HLS for the sound: 5421k
    against the 144p format's 290k, measured on the same stream.
    """

    monkeypatch.setattr(player, "mpv_path", lambda: "mpv")

    commands: list[list[str]] = []
    monkeypatch.setattr(
        player,
        "run_mpv",
        lambda command, *args, **kwargs: commands.append(command) or 0,
    )

    player.play_with_mpv(
        "https://example.test/watch",
        stream=True,
        live=True,
    )
    player.play_with_mpv(
        "https://example.test/watch",
        stream=True,
    )

    assert (
        f"--ytdl-format={player.LIVE_AUDIO_FORMAT}"
        in commands[0]
    )
    assert "--ytdl-format=bestaudio/best" in commands[1]
