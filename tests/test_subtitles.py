"""The caption fallback, and subtitles worked out while playback runs."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from subcast import captionbar, config, srt, subtitles
from subcast.media import Ranged
from subcast.sources import Captions, Media, youtube

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Good morning.
"""


class FakeResponse:
    """Just enough of a response for the status code to be read."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def prepared() -> subtitles.Prepared:
    return subtitles.Prepared(
        srt_path=Path("/tmp/example.srt"),
        chapters_path=None,
        cues=[(1.0, 3.0, "Good morning.")],
        segments=[],
    )


def test_work_started_in_the_background_reports_when_it_is_done():
    release = threading.Event()

    def work():
        release.wait(timeout=5)
        return prepared()

    job = subtitles.PendingSubtitles(work)
    job.start()

    assert job.done_yet() is False
    assert job.value() is None

    release.set()

    assert job.wait() == prepared()
    assert job.done_yet() is True


def test_starting_twice_runs_the_work_once():
    runs: list[int] = []

    job = subtitles.PendingSubtitles(lambda: runs.append(1))
    job.start()
    job.start()

    job.wait()

    assert runs == [1]


def test_a_job_that_finished_before_playback_is_ready_at_once():
    job = subtitles.PendingSubtitles.finished(prepared())

    assert job.done_yet() is True
    assert job.value() == prepared()


def test_a_failure_is_carried_rather_than_raised():
    """
    Playback is already under way when this is noticed: a caption problem
    is a line to print, not a reason to stop the video.
    """

    def work():
        raise RuntimeError("the published captions were empty")

    job = subtitles.PendingSubtitles(work)
    job.start()

    assert job.wait() is None
    assert job.failure_message() == (
        "    Subtitles failed: the published captions were empty; "
        "playing without them."
    )


def test_a_job_that_worked_reports_no_failure():
    job = subtitles.PendingSubtitles.finished(prepared())

    assert job.failure_message() is None


def media() -> Media:
    return Media(
        source="youtube",
        key="abc",
        title="A video",
        url=f"{youtube.WATCH_URL}abc",
    )


def test_a_webvtt_caption_url_is_parsed_as_it_is(monkeypatch):
    monkeypatch.setattr(
        subtitles,
        "_download_caption_text",
        lambda url, session: VTT,
    )

    assert subtitles.fetch_captions(
        (Captions(language="en", url="https://example.test/en.vtt"),)
    ) == [(1.0, 3.0, "Good morning.")]


def test_a_track_youtube_refuses_is_followed_by_the_one_it_came_from(
    monkeypatch,
    tmp_path: Path,
):
    """
    Translated tracks are the ones YouTube rate-limits; the track they were
    translated from answers instead, which saves an extraction.
    """

    asked: list[str] = []

    def download(url: str, session) -> str:

        asked.append(url)

        if "tlang=" in url:

            raise requests.HTTPError(
                "429 Too Many Requests",
                response=FakeResponse(429),
            )

        return VTT

    monkeypatch.setattr(subtitles, "_download_caption_text", download)

    translated = Captions(
        language="en",
        url="https://example.test/en?lang=zh&tlang=en&fmt=vtt",
    )
    native = Captions(
        language="zh-Hant",
        url="https://example.test/zh?lang=zh-Hant&fmt=vtt",
    )

    assert subtitles.fetch_captions(
        (translated, native),
        media(),
        tmp_path / "abc",
    ) == [(1.0, 3.0, "Good morning.")]

    assert asked == [translated.url, native.url]


def test_being_told_to_come_back_later_is_said_as_that(
    monkeypatch,
    tmp_path: Path,
):
    """
    Rate limiting is not the same as captions that turned out to be empty:
    one is worth trying again, the other is how the video is.
    """

    def download(url: str, session) -> str:

        raise requests.HTTPError(
            "429 Too Many Requests",
            response=FakeResponse(429),
        )

    monkeypatch.setattr(subtitles, "_download_caption_text", download)
    monkeypatch.setattr(
        youtube.SOURCE,
        "caption_file",
        lambda url, language, stem: None,
    )

    with pytest.raises(RuntimeError) as error:
        subtitles.fetch_captions(
            (Captions(language="en", url="https://example.test/en.vtt"),),
            media(),
            tmp_path / "abc",
        )

    assert "rate-limiting" in str(error.value)
    assert "429" in str(error.value)


def test_an_empty_track_that_is_not_rate_limited_says_so(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        subtitles,
        "_download_caption_text",
        lambda url, session: "",
    )
    monkeypatch.setattr(
        youtube.SOURCE,
        "caption_file",
        lambda url, language, stem: None,
    )

    with pytest.raises(RuntimeError) as error:
        subtitles.fetch_captions(
            (Captions(language="en", url="https://example.test/en.vtt"),),
            media(),
            tmp_path / "abc",
        )

    assert "the published captions were empty" in str(error.value)


def test_the_source_fetches_captions_a_url_cannot_give(
    monkeypatch,
    tmp_path: Path,
):
    """
    The URL in a player payload is often json3 or a playlist rather than
    WebVTT - the shape YouTube hands over for automatic captions - so the
    source gets the last word.
    """

    monkeypatch.setattr(
        subtitles,
        "_download_caption_text",
        lambda url, session: '{"events": []}',
    )

    asked: list[tuple[str, str, Path]] = []

    def caption_file(url, language, stem):
        asked.append((url, language, stem))
        written = Path(stem).with_suffix(".en.vtt")
        written.write_text(VTT)
        return written

    monkeypatch.setattr(youtube.SOURCE, "caption_file", caption_file)

    stem = tmp_path / "abc"

    assert subtitles.fetch_captions(
        (Captions(language="en", url="https://example.test/en.json3"),),
        media(),
        stem,
    ) == [(1.0, 3.0, "Good morning.")]

    assert asked == [(f"{youtube.WATCH_URL}abc", "en", stem)]


def test_no_captions_from_either_route_says_so(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        subtitles,
        "_download_caption_text",
        lambda url, session: "",
    )

    monkeypatch.setattr(
        youtube.SOURCE,
        "caption_file",
        lambda url, language, stem: None,
    )

    with pytest.raises(RuntimeError) as error:
        subtitles.fetch_captions(
            (Captions(language="en", url="https://example.test/en.vtt"),),
            media(),
            tmp_path / "abc",
        )

    assert "the published captions were empty" in str(error.value)


def test_settings_replace_the_defaults_rather_than_sitting_beside_them():
    """
    A live chunk is heard without the voice filter and an episode with it,
    and both go through the same reader: a setting has to replace a default
    rather than be passed twice, which is a TypeError - and one broadcast
    lost its captions to exactly that.
    """

    class FakeModel:
        """Records what the reader was asked for."""

        def __init__(self) -> None:
            self.seen: dict = {}

        def transcribe(self, path, **options):
            self.seen = options
            return iter([]), None

    model = FakeModel()

    subtitles.transcribe_cues(
        model,
        Path("/tmp/chunk.wav"),
        vad_filter=False,
        beam_size=1,
        best_of=1,
    )

    assert model.seen["vad_filter"] is False
    assert model.seen["beam_size"] == 1
    assert model.seen["language"] == "en"
    assert model.seen["condition_on_previous_text"] is False


class Word:
    """One word, as the model timed it and wrote it."""

    def __init__(self, start: float, end: float, word: str) -> None:

        self.start = start
        self.end = end
        self.word = word


class Said:
    """
    One segment, with the timing of its words, as faster-whisper hands it
    over.
    """

    def __init__(
        self,
        text: str,
        start: float = 0.0,
        end: float = 1.0,
        words: list[Word] | None = None,
    ) -> None:

        self.text = text
        self.start = start
        self.end = end
        self.words = words


class Whisper:
    """A model that hands over what a test says it heard."""

    def __init__(self, *segments: Said) -> None:

        self.segments = list(segments)

    def transcribe(self, path, **options):

        return iter(self.segments), None


def test_a_line_the_model_was_unsure_of_is_still_written():
    """
    What the model wrote is what is written. Dropping a line because the
    model doubted it was tried and measured away: `no_speech_prob` is a whole
    window's verdict, so eight consecutive segments of one episode carried the
    same 0.69 while their words were a confident -0.12 - and cutting those on
    it took 121 words of speech out of ten minutes of audio, while on three
    minutes of a music-heavy broadcast it dropped nothing at all.
    """

    model = Whisper(
        Said("Backing track that he then would perform."),
        Said("Mum! Dad! Bingo!"),
    )

    assert subtitles.transcribe_cues(
        model,
        Path("/tmp/chunk.wav"),
    ) == [
        (0.0, 1.0, "Backing track that he then would perform."),
        (0.0, 1.0, "Mum! Dad! Bingo!"),
    ]


def test_the_voice_filter_is_not_asked_for():
    """
    The filter asks faster-whisper to drop what is not speech and put the
    timestamps back afterwards, and measured, it drops speech instead: on
    three minutes of a music-heavy broadcast, 54% of the words a filterless
    pass heard had no cue over them, and on ten minutes of an episode it kept
    the same words and cost the same time.

    What the model writes over music is kept out by `annotation` and the loop
    guards rather than by cutting the audio up.
    """

    class FakeModel:
        """Records what the reader was asked for."""

        def __init__(self) -> None:

            self.seen: dict = {}

        def transcribe(self, path, **options):

            self.seen = options

            return iter([]), None

    model = FakeModel()

    subtitles.transcribe_cues(
        model,
        Path("/tmp/chunk.wav"),
    )

    assert model.seen["vad_filter"] is False


def test_a_line_that_straddles_the_join_is_cut_where_the_captions_stopped():
    """
    A pass hears the words before its piece as context, and the model may
    make one line of those together with the piece: the words carry their own
    timing, so the line is cut at the join. Dropping the line instead would
    lose the words it ends with, which is captions that come and go.
    """

    model = Whisper(
        Said(
            "Let's play a game. Bandit takes over!",
            words=[
                Word(0.2, 0.6, " Let's"),
                Word(0.6, 0.9, " play"),
                Word(0.9, 1.2, " a"),
                Word(1.2, 1.6, " game."),
                Word(1.7, 2.1, " Bandit"),
                Word(2.1, 2.5, " takes"),
                Word(2.5, 2.9, " over!"),
            ],
        ),
    )

    # The captions have been written up to 1.5 seconds of what is heard.
    assert subtitles.transcribe_cues(
        model,
        Path("/tmp/chunk.wav"),
        after=1.5,
    ) == [
        (1.7, 2.9, "Bandit takes over!"),
    ]


def test_a_line_wholly_in_what_was_already_said_is_not_a_caption():
    """
    The words in front of a piece are context: a line the model makes of them
    alone has been said already, and there is nothing of it to say.
    """

    model = Whisper(
        Said(
            "Good morning.",
            words=[
                Word(0.1, 0.4, " Good"),
                Word(0.4, 0.9, " morning."),
            ],
        ),
    )

    assert (
        subtitles.transcribe_cues(
            model,
            Path("/tmp/chunk.wav"),
            after=1.0,
        )
        == []
    )


def test_a_segment_without_word_timing_is_taken_whole():
    """
    A model that does not hand over the timing of its words leaves nothing to
    cut a line with, so the segment is taken as it comes and the caller
    decides what of it belongs.
    """

    model = Whisper(
        Said(
            "Good morning.",
            start=0.5,
            end=2.0,
        ),
    )

    assert subtitles.transcribe_cues(
        model,
        Path("/tmp/chunk.wav"),
        after=1.0,
    ) == [
        (0.5, 2.0, "Good morning."),
    ]


class Segment:
    """One stretch of speech, as the model hands it over."""

    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class Hearing:
    """
    A model that hands its segments over one at a time, with a pause in the
    middle, so a test can look at what has been written before the file has
    been heard to its end.
    """

    def __init__(self, early, late, duration: float, gate=None) -> None:
        self._early = early
        self._late = late
        self._gate = gate
        self.info = SimpleNamespace(duration=duration)
        self.options: dict = {}

    def transcribe(self, path, **options):
        self.options = options

        def stream():
            for segment in self._early:
                yield segment

            if self._gate is not None:
                self._gate.wait(timeout=5)

            for segment in self._late:
                yield segment

        return stream(), self.info


def wait_for(check, timeout: float = 5.0) -> bool:
    """
    Let the hearing's thread run until `check` says so.
    """

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:

        if check():
            return True

        time.sleep(0.01)

    return False


def heard(
    monkeypatch,
    tmp_path,
    model,
) -> tuple[subtitles.HeardWhilePlaying, Media]:
    """
    A file being heard, in a cache of its own.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(subtitles, "load_model", lambda name, device: model)

    item = Media(
        source="bbc",
        key="one",
        title="An episode",
        url="https://example.test/page",
        kind="audio",
        duration=60.0,
    )

    audio = tmp_path / "bbc" / "one.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"audio")

    return (
        subtitles.HeardWhilePlaying(item, audio, "small.en", "auto"),
        item,
    )


def test_a_file_is_heard_while_it_plays(monkeypatch, tmp_path: Path):
    """
    The captions are written as the words are heard, so the first ones are
    on screen while the rest of the file is still going through the model -
    rather than at the end of a transcription that takes minutes.
    """

    gate = threading.Event()

    model = Hearing(
        early=[Segment(0.0, 10.0, "The first thing said.")],
        late=[
            Segment(10.0, 20.0, "The second thing said."),
            Segment(20.0, 30.0, "The last thing said."),
        ],
        duration=30.0,
        gate=gate,
    )

    captioning, item = heard(monkeypatch, tmp_path, model)
    srt = subtitles.cache_stem(item).with_suffix(".srt")

    captioning.start()

    assert wait_for(lambda: captioning.revision() > 0)

    # the audio is still being heard, and the first line is already there
    assert captioning.cues() == [(0.0, 10.0, "The first thing said.")]
    assert "The first thing said." in srt.read_text(encoding="utf-8")

    gate.set()

    assert wait_for(
        lambda: subtitles.cache_stem(item).with_suffix(".cues.json").exists()
    )

    # and when the whole file has been heard, the transcript is cached and
    # the artifacts are rendered from it, so a replay costs nothing
    assert captioning.cues() == [
        (0.0, 10.0, "The first thing said."),
        (10.0, 20.0, "The second thing said."),
        (20.0, 30.0, "The last thing said."),
    ]

    saved = (
        subtitles.cache_stem(item)
        .with_suffix(".srt")
        .read_text(encoding="utf-8")
    )

    assert "The last thing said." in saved
    assert captioning.revision() > 1
    assert captioning.summary() is None

    captioning.stop()


def test_the_block_draws_the_piece_being_said_not_the_whole_sentence(
    monkeypatch,
    tmp_path: Path,
):
    """
    The model hands over sentences, and a long one is cut into the pieces a
    caption line holds - which is what the file, mpv and the block all
    read. Drawing the sentence itself would show its opening lines while
    the words being said are further on, which reads as captions that do
    not match the audio.
    """

    said = (
        "It was the kind of morning that made the whole town stop and look "
        "at the sky, and nobody quite knew what to say about it, so they "
        "said nothing at all until the rain came."
    )

    model = Hearing(
        early=[Segment(0.0, 24.0, said)],
        late=[],
        duration=24.0,
    )

    captioning, item = heard(monkeypatch, tmp_path, model)

    captioning.start()

    assert wait_for(lambda: subtitles.has_transcript(item))

    pieces = subtitles.split_cues([(0.0, 24.0, said)])

    assert len(pieces) > 1

    # the line drawn at the end of the sentence is the piece being said
    # then, not the opening the whole sentence begins with
    _title, _history, current = captionbar.frame(
        captioning.cues(),
        [],
        22.0,
        width=srt.LINE_WIDTH,
    )

    assert " ".join(current) == pieces[-1][2]

    captioning.stop()


def test_a_run_that_ends_first_keeps_what_it_heard(monkeypatch, tmp_path: Path):
    """
    Stopping is not failing: what was heard stays on screen, and nothing is
    cached, so the next run hears the file rather than playing against a
    transcript of half an episode.
    """

    gate = threading.Event()

    model = Hearing(
        early=[Segment(0.0, 10.0, "The first thing said.")],
        late=[Segment(10.0, 20.0, "The second thing said.")],
        duration=120.0,
        gate=gate,
    )

    captioning, item = heard(monkeypatch, tmp_path, model)

    captioning.start()

    assert wait_for(lambda: captioning.revision() > 0)

    captioning.stop()
    gate.set()

    assert "The first thing said." in (
        subtitles.cache_stem(item)
        .with_suffix(".srt")
        .read_text(encoding="utf-8")
    )

    assert not subtitles.has_transcript(item)

    summary = captioning.summary()

    assert summary is not None
    assert "next run" in summary


def test_a_hearing_that_fails_is_a_line_rather_than_the_end(
    monkeypatch,
    tmp_path: Path,
):
    """
    A model that cannot be loaded, or an audio file that will not open, is
    something the run says once and plays on from - the captions are the
    thing that is lost, not the episode.
    """

    class Broken:
        info = SimpleNamespace(duration=60.0)

        def transcribe(self, path, **options):
            raise RuntimeError("no speech in that file")

    captioning, _item = heard(monkeypatch, tmp_path, Broken())

    captioning.start()
    captioning.stop()

    failure = captioning.failure_message()

    assert failure is not None
    assert "no speech in that file" in failure
    assert "playing without them" in failure


class StreamedHearing:
    """
    A model that takes a span's length from the bytes it was given, the way
    decoding a span of a stream does, and names its cue after the span.
    """

    # bytes per second of the audio the tests serve
    RATE = 10.0

    def transcribe(self, path, **options):

        seconds = len(Path(path).read_bytes()) / self.RATE

        def stream():

            # a word the cut went through the middle of: heard by the span
            # on each side of it, and wanted by the second one only
            yield Segment(0.5, 1.0, "the word the cut landed in")

            yield Segment(
                seconds / 2,
                seconds / 2 + 1.0,
                Path(path).name,
            )

        return stream(), SimpleNamespace(duration=seconds)


def streaming(
    monkeypatch,
    tmp_path: Path,
    body: bytes,
    fetched=None,
) -> tuple[subtitles.StreamedWhilePlaying, Media]:
    """
    An item being streamed into a cache of its own, with the spans served
    out of `body` and the first span kept short enough to have several.
    """

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(subtitles, "load_model", lambda name, device: StreamedHearing())
    monkeypatch.setattr(subtitles, "FIRST_SPAN_BYTES", 50)

    # the audio these tests serve is not audio: its length is the one the
    # spans came to
    monkeypatch.setattr(
        subtitles,
        "media_duration",
        lambda path: len(body) / StreamedHearing.RATE,
    )

    def range_of(url, headers, first, last):

        if fetched is not None:

            fetched.append((first, last))

        return body[first:last + 1]

    monkeypatch.setattr(subtitles, "fetch_range", range_of)

    item = Media(
        source="rte",
        key="one",
        title="An episode",
        url="https://example.test/one.mp3",
        kind="audio",
        duration=len(body) / StreamedHearing.RATE,
    )

    ranged = Ranged(
        length=len(body),
        opening=body[:1],
        extension=".mp3",
    )

    return (
        subtitles.StreamedWhilePlaying(
            item,
            item.url,
            ranged,
            {},
            tmp_path / "rte" / "one",
            "small.en",
            "auto",
        ),
        item,
    )


def test_a_stream_is_heard_a_span_at_a_time(monkeypatch, tmp_path: Path):
    """
    An item that is still arriving is heard as it arrives: each span is
    decoded and its cues placed where the audio before it ended, so they
    belong to the copy the player is reading - and the bytes fetched are the
    copy that is left on disk when the whole item has been heard.
    """

    body = bytes(512)
    fetched: list[tuple[int, int]] = []

    captioning, item = streaming(monkeypatch, tmp_path, body, fetched)

    captioning.start()

    assert wait_for(lambda: subtitles.has_transcript(item))

    # the first span is 50 bytes (5 s at this rate) and the second is the
    # rest of the item, fetched two seconds of it back to cover the cut
    assert fetched == [(0, 49), (30, 511)]

    assert [
        (start, text)
        for start, _end, text in captioning.cues()
    ] == [
        (0.5, "the word the cut landed in"),
        (2.5, "00000.mp3"),
        # 3.0 is where the second span starts (5.0 less the 2.0 overlap),
        # so the cue at 3.5 is the half-word and is dropped
        (27.1, "00001.mp3"),
    ]

    # what was fetched is the item, and it is named like a copy of it
    assert (tmp_path / "rte" / "one.mp3").read_bytes() == body
    assert not (tmp_path / "rte" / "one.mp3.part").exists()
    assert captioning.summary() is None

    captioning.stop()


def test_a_stream_that_stops_early_keeps_nothing(monkeypatch, tmp_path: Path):
    """
    A run that ends before the item has arrived has no copy of it and no
    transcript: the half-fetched audio goes with the run, and the next one
    hears the item again.
    """

    body = bytes(512)
    calls: list[int] = []

    def broken(url, headers, first, last):

        calls.append(first)

        if len(calls) > 1:

            raise RuntimeError("the stream stopped")

        return body[first:last + 1]

    captioning, item = streaming(monkeypatch, tmp_path, body)

    monkeypatch.setattr(subtitles, "fetch_range", broken)

    captioning.start()

    assert wait_for(lambda: captioning.failure_message() is not None)

    captioning.stop()

    message = captioning.failure_message()

    assert message is not None
    assert "the stream stopped" in message

    assert not subtitles.has_transcript(item)
    assert list((tmp_path / "rte").iterdir()) == []
