"""Whisper transcription and subtitle/chapter preparation."""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from . import config
from .background import Background
from .chapters import write_chapters_file
from .media import fetch_range, find_cached_audio, media_duration
from .segments import (
    place,
    save_segments,
    snap_segments,
)
from .sources import Captions
from .srt import (
    load_cues,
    save_cues,
    split_cues,
    split_heard,
    write_srt,
)

if TYPE_CHECKING:
    # A live item's captions are a job that keeps running, not a file: the
    # two are what this job can hand back.
    from .live import LiveCaptions


@dataclass(frozen=True)
class Prepared:
    """
    Subtitle artifacts plus the captions and segments they were rendered
    from, so a caller can draw the captions itself.
    """

    srt_path: Path
    chapters_path: Path | None
    cues: list[tuple[float, float, str]]
    segments: list[tuple[float, float, str]]


class GrowingCaptions:
    """
    Captions that arrive while the item plays.

    A source of them answers three questions - `start`, `cues` and
    `revision`, and `stop` when the play is over - and where it answers
    from is its own business: a broadcast heard piece by piece as it airs
    (`live.LiveCaptions`), a file being heard (`HeardWhilePlaying`), or an
    item still arriving by range (`StreamedWhilePlaying`). Playback drives
    either the same way: the subtitle file is handed to mpv once and
    reloaded whenever `revision` changes, so a caption is on screen as soon
    as it is written.
    """

    srt_path: Path

    def start(self) -> None:
        """
        Begin, however many times this is asked.
        """

        raise NotImplementedError

    def cues(self) -> list[tuple[float, float, str]]:
        """
        The captions to draw: what has been said so far, in the pieces a
        caption line holds.

        A source's own units are not what can be shown - the model hands
        over sentences, a broadcast hears a chunk at a time - so what is
        drawn is the laid-out form, the same cues the subtitle file holds
        and mpv is given.
        """

        raise NotImplementedError

    def revision(self) -> int:
        """
        A number that changes when the subtitles on disk do.
        """

        raise NotImplementedError

    def sample(
        self,
        wall: float,
        edge: float,
    ) -> None:
        """
        Where mpv has read up to, and when it said so.

        Carried because a broadcast is placed from that reading, and
        ignored by a source whose cues are already on the item's own
        timeline.
        """

    def take_notes(self) -> list[str]:
        """
        What is worth saying, each line once, and nothing twice.
        """

        return []

    def failure_message(self) -> str | None:
        """
        What went wrong, as a line to print, or None when nothing did.
        """

        return None

    def summary(self) -> str | None:
        """
        What the captions came to, for the end of the run.
        """

        return None

    def stop(self) -> None:
        """
        Stop hearing, keeping what has been written.
        """

        raise NotImplementedError


class PendingSubtitles(Background["Prepared | LiveCaptions | None"]):
    """
    Subtitles worked out while playback is already under way.

    Waiting for a transcript before the first frame is what made a YouTube
    run feel slow: the source round trip, the caption download and (where
    there are no captions) a transcription are all things mpv does not need
    - it is handed the page URL and resolves the stream itself. So the work
    moves to a thread, and the player attaches the result when it lands.

    A broadcast has no result: what lands there is the job that keeps
    making the captions, which the player drives for as long as it plays.
    """

    def __init__(
        self,
        work: Callable[[], Prepared | LiveCaptions | None],
    ) -> None:

        super().__init__(
            work,
            "Subtitles",
            "playing without them",
        )

    @classmethod
    def finished(
        cls,
        prepared: Prepared | LiveCaptions | None,
    ) -> PendingSubtitles:
        """
        A job that ran to completion before playback started, for the paths
        that cannot start without it.
        """

        job = cls(lambda: prepared)

        job._value = prepared
        job._done.set()

        return job


def transcribe(
    audio_path: Path,
    model_name: str,
    device: str,
) -> list[tuple[float, float, str]]:
    """
    Transcribe with faster-whisper.

    Returns the speech cues as (start, end, text).
    """

    model = load_model(
        model_name,
        device,
    )

    print(
        "    Transcribing (this takes a while)...",
        flush=True,
    )

    stream, info = _stream(
        model,
        audio_path,
    )

    cues: list[tuple[float, float, str]] = []

    last_reported = -1

    for segment in stream:

        text = segment.text.strip()

        if text:

            cues.extend(
                split_heard(
                    float(segment.start),
                    float(segment.end),
                    text,
                    segment.words,
                )
            )

        # One progress line per transcribed minute of audio.
        minute = int(segment.end // 60)

        if (
            minute != last_reported
            and info.duration
        ):

            last_reported = minute

            print(
                f"\r    Transcribed: "
                f"{minute} min / "
                f"{info.duration / 60:.0f} min "
                f"({segment.end / info.duration * 100:.0f}%)",
                end="",
                flush=True,
            )

    print()

    if not cues:

        raise RuntimeError(
            "Whisper produced no speech for this episode."
        )

    return cues


def transcribe_cues(
    model,
    audio_path: Path,
    after: float = 0.0,
    **settings,
) -> list[tuple[float, float, str]]:
    """
    One file's speech, as cues relative to where it starts.

    The same model the whole-episode path uses, on a piece of a
    broadcast: a chunk has no beginning of its own, so where it belongs on
    the timeline is the caller's to say. `settings` are for what only a
    chunk needs - it is heard while it is still being followed, where an
    episode is heard once and for good.

    `after` is the second of the audio the captions have already been
    written up to - a pass hears the words before it so the model is not
    left to make out a sentence from its middle - and what comes back from
    there on is what the model wrote (`_heard`).
    """

    stream, _info = _stream(
        model,
        audio_path,
        **settings,
    )

    cues: list[tuple[float, float, str]] = []

    for segment in stream:

        text, start, end = _heard(segment, after)

        if text:

            cues.append((start, end, text))

    return cues


def _heard(
    segment,
    after: float,
) -> tuple[str, float, float]:
    """
    What one segment said from a given second of its audio on.

    A segment that straddles the join holds the words in front of the piece
    and the words of the piece together, and only the second half of it is
    new: its words carry their own timing (`word_timestamps`), so the line is
    cut where the captions stopped. Dropping the segment instead would lose
    the words it ends with, which is captions coming and going.

    Without word timings there is nothing to cut with, and the segment is
    taken whole - the caller drops what falls in what has been said.
    """

    if not segment.words:

        return (
            segment.text.strip(),
            float(segment.start),
            float(segment.end),
        )

    words = [
        word
        for word in segment.words
        if float(word.start) >= after
    ]

    # What the model wrote carries its own spacing - " Bandit" - so the
    # words join without any being added.
    text = "".join(
        word.word for word in words
    ).strip()

    if not text:

        return "", 0.0, 0.0

    return (
        text,
        float(words[0].start),
        float(words[-1].end),
    )


def annotation(
    text: str,
) -> bool:
    """
    Whether a line is a note about the soundtrack rather than speech:
    "[Music]", "(laughs)", nothing but music symbols.

    Whisper writes these where it heard no speech, and what it writes beside
    them it was not sure of either.
    """

    line = text.strip().strip("♪").strip()

    if not line:

        return True

    return (
        line.startswith("[") and line.endswith("]")
    ) or (
        line.startswith("(") and line.endswith(")")
    )


def _stream(
    model,
    audio_path: Path,
    **settings,
):
    """
    The model reading a file: English speech, and the notes it writes about
    the soundtrack dropped.

    One definition, because these settings are what the transcript is - an
    episode and a live chunk have to be heard the same way - and `settings`
    are for what only one of them needs: how the decoder is run. They
    replace a default rather than sit beside it.

    The voice filter is not used. It asks faster-whisper to drop what is not
    speech and put the timestamps back afterwards, and measured, it drops
    speech instead: on three minutes of a music-heavy broadcast it left 54%
    of the words a filterless pass heard with no cue over them, and on a
    ten-minute episode it kept the same words and cost the same time (1774
    against 1776 words; 38.5s against 36.9s for 600s of audio). What the
    model writes over music is kept out by `annotation` and, for a
    broadcast, by the loop guards, rather than by cutting the audio up.
    """

    options = {
        "language": "en",
        "vad_filter": False,
        "condition_on_previous_text": False,
        # The words carry their own timing, which is what lets a sentence's
        # pieces be placed where they are said rather than by an equal share
        # of the cue (`srt.split_heard`). Measured over 22 minutes of one
        # programme: 79 seconds with it against 78 without, and 3212 of 3294
        # words identical - the same reading, faster than the difference
        # between two runs.
        "word_timestamps": True,
    }

    options.update(settings)

    reading, info = model.transcribe(
        str(audio_path),
        **options,
    )

    return (
        (
            segment
            for segment in reading
            if not annotation(segment.text)
        ),
        info,
    )


def load_model(
    model_name: str,
    device: str,
):
    """
    A Whisper model on the first device that will take it.

    `auto` is the GPU when it works and the CPU when it does not, and a
    device that cannot run the model costs speed rather than the run.
    """

    try:

        from faster_whisper import (
            WhisperModel,
        )

    except ImportError as exc:

        raise RuntimeError(
            "Subtitles need faster-whisper "
            "(pip install faster-whisper)."
        ) from exc

    candidates = {
        "auto": (
            ("cuda", "float16"),
            ("cpu", "int8"),
        ),
        "cuda": (
            ("cuda", "float16"),
        ),
        "cpu": (
            ("cpu", "int8"),
        ),
    }[device]

    model = None
    last_error: Exception | None = None

    for candidate_device, compute_type in candidates:

        print(
            f"    Loading Whisper model "
            f"{model_name} "
            f"({candidate_device}/"
            f"{compute_type})...",
            flush=True,
        )

        try:

            model = WhisperModel(
                model_name,
                device=candidate_device,
                compute_type=compute_type,
            )

            break

        # Any failure means this device cannot run the model.
        except Exception as exc:  # noqa: BLE001 - try the next device

            last_error = exc

            print(
                f"    {candidate_device} "
                f"unavailable: {exc}",
                flush=True,
            )

    if model is None:

        raise RuntimeError(
            f"Could not load Whisper model "
            f"{model_name}: {last_error}"
        )

    return model


def _download_caption_text(
    url: str,
    session: requests.Session,
) -> str:

    response = session.get(
        url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0 Safari/537.36"
            ),
        },
    )

    response.raise_for_status()

    return response.text


def cache_stem(
    media,
) -> Path:
    """
    Where an item's cached transcript, segments and subtitles live.
    """

    return config.cache_dir(
        media.source
    ) / media.key


def has_transcript(
    media,
) -> bool:
    """
    Whether the transcript is already cached.

    The transcript alone: the segments, the subtitles and the chapters are
    rendered from it on every run, so their files say nothing about
    whether the expensive part has been done.
    """

    stem = cache_stem(media)

    return stem.with_suffix(
        ".cues.json"
    ).is_file()


def fetch_captions(
    captions: tuple[Captions, ...],
    media=None,
    stem: Path | None = None,
    session: requests.Session | None = None,
) -> list[tuple[float, float, str]]:
    """
    Get a subtitle track the source publishes, as cues.

    Each candidate is asked in turn - a translation YouTube may refuse is
    followed by the track it was translated from - and only when none of
    them answers does the source get a chance of its own (yt-dlp, for
    YouTube), which costs a second extraction.

    A refusal to serve the captions at all (HTTP 429) is reported as that,
    rather than as captions that turned out to be empty: the difference is
    whether trying again later is worth anything.
    """

    from . import sources
    from .vtt import parse_vtt

    session = session or requests.Session()

    cues: list[tuple[float, float, str]] = []
    worked: Captions | None = None
    refused = False

    for captions_track in captions:

        print(
            f"    Fetching captions: {captions_track.language}",
            flush=True,
        )

        try:

            text = _download_caption_text(
                captions_track.url,
                session,
            )

        except requests.RequestException as error:

            refused = refused or _asked_too_often(error)
            text = ""

        if text.lstrip().startswith("WEBVTT"):

            cues = parse_vtt(text)

        if cues:

            worked = captions_track
            break

    if not cues and media is not None and stem is not None:

        source = sources.by_name(media.source)

        fetcher = getattr(
            source,
            "caption_file",
            None,
        )

        if fetcher is not None:

            print(
                "    Fetching captions with yt-dlp...",
                flush=True,
            )

            path = fetcher(
                media.url,
                captions[0].language,
                stem,
            )

            if path is not None:

                cues = parse_vtt(
                    path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )

                worked = captions[0]

    if not cues:

        if refused:

            raise RuntimeError(
                "YouTube is rate-limiting this video's captions "
                "(HTTP 429); trying again in a few minutes usually works"
            )

        raise RuntimeError(
            "the published captions were empty"
        )

    print(
        f"    Published captions ({worked.language}): "
        f"{len(cues)} cues",
        flush=True,
    )

    return cues


def _asked_too_often(
    error: requests.RequestException,
) -> bool:
    """
    Whether the captions were refused for being asked for too often.
    """

    response = getattr(
        error,
        "response",
        None,
    )

    return (
        getattr(response, "status_code", None)
        == 429
    )


def prepare(
    media,
    audio_path: Path | None,
    model_name: str,
    device: str,
    subs_from: str = "auto",
) -> Prepared:
    """
    Subtitles and chapters for one media item, prepared once and reused.

    Published captions win when the source has them - they are already
    timed, and cost nothing but a download. Otherwise the audio is
    transcribed locally. The transcript is what gets cached: the placed
    segments, the subtitles and the chapters are rendered from it on every
    run, so changing how they are worked out costs a re-render rather than
    a transcription.
    """

    stem = cache_stem(media)

    stem.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    cues_path = stem.with_suffix(".cues.json")

    if has_transcript(media):

        print(
            f"    Reusing transcript: {cues_path}",
            flush=True,
        )

        cues = load_cues(cues_path)

    else:

        published = list(media.captions)

        if (
            subs_from in ("auto", "published")
            and published
        ):

            cues = fetch_captions(
                tuple(published),
                media,
                stem,
            )

        else:

            if audio_path is None:

                raise RuntimeError(
                    "this item has no published captions and "
                    "no audio was fetched to transcribe"
                )

            cues = transcribe(
                audio_path,
                model_name,
                device,
            )

        save_cues(
            cues,
            cues_path,
        )

    return render(
        media,
        cues,
        audio_path,
    )


def render(
    media,
    cues: list[tuple[float, float, str]],
    audio_path: Path | None,
) -> Prepared:
    """
    The segments, the subtitles and the chapters a transcript comes to.

    Separated from the hearing that produced the cues because a file being
    heard while it plays has its transcript already: it renders the same
    artifacts at the end, from the text it has just written down.
    """

    stem = cache_stem(media)

    stem.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    srt_path = stem.with_suffix(".srt")

    segments_path = stem.with_suffix(
        ".segments.json"
    )

    chapters_path = stem.with_suffix(
        ".chapters.txt"
    )

    # Where the segments go is worked out again on every run, from the
    # transcript: it is where the segment titles come from, the rules for
    # placing them change with the code, and placing a cached transcript
    # costs nothing next to the transcription that reuse saves.
    #
    # The length that matters is the length of the audio the transcript
    # came from. RTÉ states the length of the episode its page was loaded
    # for, and the audio it stitches is not always that: one URL answered
    # with 57,154,080 bytes and 56,829,745 bytes a second later.
    heard = audio_path

    if heard is None:

        heard = find_cached_audio(
            config.cache_dir(media.source),
            media.key,
        )

    duration = 0.0

    if heard is not None:
        duration = media_duration(heard)

    if not duration:

        duration = media.duration or 0.0

    if not duration:

        duration = sum(
            segment.duration or 0.0
            for segment in media.segments
        )

    segments, exact, running_order = place(
        list(media.segments),
        duration,
        media.clock_start,
    )

    if not exact:

        segments = snap_segments(
            segments,
            cues,
            running_order=running_order,
        )

    save_segments(
        segments,
        segments_path,
    )

    # Segment titles ride along as cues spanning their own segment, so
    # the terminal shows the title above the dialogue; the speech is
    # split so no cue spills past two lines.
    framed = split_cues(cues)

    write_srt(
        [
            (
                start,
                end,
                f"▌ {segment_title}",
            )
            for start, end, segment_title in segments
        ]
        + framed,
        srt_path,
    )

    print(
        f"    Subtitles: {srt_path}",
        flush=True,
    )

    if not segments:
        return Prepared(srt_path, None, framed, [])

    write_chapters_file(
        segments,
        media.title,
        chapters_path,
    )

    return Prepared(
        srt_path,
        chapters_path,
        framed,
        segments,
    )


# How much of the audio is heard before the first cues are written, and how
# much more between one write and the next: soon enough that a run starts
# showing captions while it is still saying hello, rarely enough that the
# file is not rewritten under mpv for every sentence.
FIRST_FLUSH_SECONDS = 8.0
FLUSH_SECONDS = 30.0

# How much of an item that is still arriving is fetched and heard at once.
# The first span is a fixed small size, so that captions arrive while the
# episode is still starting; what follows is a stretch of time, because the
# rate the bytes arrive at is what the first span measures, and the model
# hears a stretch of it far faster than the stretch plays.
FIRST_SPAN_BYTES = 1_500_000
SPAN_SECONDS = 300.0

# How much of the end of a span is fetched again with the one after it, so a
# word the cut went through the middle of is heard whole by one of them: a
# span's cues are placed by where the model says the audio before it ended,
# and the overlap is what keeps that boundary out of a word.
SPAN_OVERLAP_SECONDS = 2.0

# How long the hearing is given to come out of the stretch of audio it is in
# when playback ends: it is the model's own decode of one window, and the
# thread is a daemon, so waiting longer buys nothing.
HEARING_STOP_SECONDS = 5.0


class HeardFile(GrowingCaptions):
    """
    Captions heard from audio, written while the item plays.

    The model hears faster than audio plays, so a cue is written as soon as
    the words after it have been heard and is then ahead of the picture
    rather than behind it. What differs between the ways of hearing is only
    where the audio comes from, so that is what a subclass says
    (`_stretches`): a file that was downloaded first is one stretch, and an
    item still arriving is a span at a time.

    The artifacts are written once the whole item has been heard, so a
    replay is as cheap as any other. A run that ends first keeps the
    captions it heard and caches nothing: the next run hears the audio again
    rather than play against a transcript of half an episode.
    """

    def __init__(
        self,
        media,
        audio_path: Path,
        model_name: str,
        device: str,
    ) -> None:

        self.srt_path = cache_stem(media).with_suffix(
            ".srt"
        )

        self._media = media
        self._audio = audio_path
        self._model_name = model_name
        self._device = device

        self._lock = threading.Lock()

        # What the model has said, and the same cues laid out into the
        # pieces a caption line holds - which is what the file, the player
        # and the block all read (`cues`).
        self._cues: list[tuple[float, float, str]] = []
        self._shown: list[tuple[float, float, str]] = []
        self._revision = 0
        self._failure: str | None = None
        self._notes: list[str] = []

        # How far the hearing has got, in the item's own timeline: what the
        # model has decoded (`_covered`) and what the cues have reached
        # (`_heard`), against how long the item is (`_total`).
        self._heard = 0.0
        self._covered = 0.0
        self._total = 0.0
        self._complete = False

        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """
        Set the hearing going. Starting twice does nothing.
        """

        if self._thread is not None:

            return

        self.srt_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._thread = threading.Thread(
            target=self._work,
            daemon=True,
        )

        self._thread.start()

    def cues(self) -> list[tuple[float, float, str]]:
        """
        What has been said so far, as the subtitle file holds it.

        The model hands over sentences rather than captions, and a long one
        is cut into the pieces a line can hold (`_write` does it once per
        cue, for the file). The block draws the same pieces: the sentence
        itself would show its opening lines while the words being said are
        further on, which reads as captions that do not match the audio.
        """

        with self._lock:

            return list(self._shown)

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
            f"    Captions failed: {failure}; "
            f"playing without them."
        )

    def take_notes(self) -> list[str]:
        """
        What is worth saying, each line once.

        Carried rather than printed: the hearing runs while a caption block
        is drawing, and only the run that owns the terminal may write to
        it.
        """

        with self._lock:

            notes = self._notes
            self._notes = []

        return notes

    def summary(self) -> str | None:
        """
        What the captions came to, when the item was not heard to its end.
        """

        with self._lock:

            heard = self._heard
            total = self._total
            complete = self._complete

        if complete or not heard:

            return None

        return (
            f"    Captions heard to {heard / 60:.0f} min of "
            f"{total / 60:.0f} min; the rest is made next run."
        )

    def stop(self) -> None:
        """
        Stop hearing, keeping the captions it wrote.
        """

        self._stopping.set()

        if self._thread is not None:

            self._thread.join(
                timeout=HEARING_STOP_SECONDS
            )

    def _work(self) -> None:
        """
        Hear the audio, writing the captions as they are heard.
        """

        try:

            self._hear()

        except Exception as exc:  # noqa: BLE001 - reported as a line

            with self._lock:

                self._failure = str(exc)

    def _stretches(self) -> Iterator[tuple[Path, float, float]]:
        """
        The audio to hear, in the order it plays: the file to hear, where
        it starts in the item, and the point before which its cues belong to
        the stretch before it and are dropped.
        """

        raise NotImplementedError

    def _hear(self) -> None:
        """
        Hear the audio, a stretch at a time, and settle when it is all in.
        """

        model = load_model(
            self._model_name,
            self._device,
        )

        said: list[tuple[float, float, str]] = []

        for audio, offset, cut in self._stretches():

            if self._stopping.is_set():

                return

            self._hear_one(
                model,
                audio,
                offset,
                cut,
                said,
            )

        if not said:

            raise RuntimeError(
                "Whisper produced no speech for this episode."
            )

        if self._stopping.is_set():

            return

        self._write(said)

        save_cues(
            said,
            cache_stem(self._media).with_suffix(
                ".cues.json"
            ),
        )

        with self._lock:

            self._complete = True

        render(
            self._media,
            said,
            self._audio,
        )

        self._settled()

    def _settled(self) -> None:
        """
        What to do once the whole item has been heard and rendered, which is
        nothing unless the audio was still arriving when it began.
        """

    def _hear_one(
        self,
        model,
        audio: Path,
        offset: float,
        cut: float,
        said: list[tuple[float, float, str]],
    ) -> None:
        """
        Hear one stretch of audio, adding its cues to what has been said.

        The cues are timed from where the stretch starts - `offset`, and
        what the model says they are within the stretch - so a stretch of a
        stream is placed by the audio before it rather than by an estimate
        of how many seconds a byte range holds.

        A stretch that follows another one is heard from a little before the
        join, so the model is not left to make out a sentence from its
        middle: `heard` is where this stretch's own words begin within it,
        and a line that straddles the join is cut there (`_heard`). A line
        the model made of the overlap alone has been said already. Only the
        timing of the words can cut a line, so a model that hands over none
        leaves such a line dropped rather than written twice.
        """

        heard = cut - offset

        stream, info = _stream(
            model,
            audio,
        )

        covered = offset + float(info.duration or 0.0)

        with self._lock:

            self._total = max(self._total, covered)
            self._covered = max(self._covered, covered)

        next_flush = offset + FIRST_FLUSH_SECONDS
        reported = -1

        for segment in stream:

            if self._stopping.is_set():

                return

            text, start, end = _heard(
                segment,
                heard,
            )

            if text and offset + start >= cut:

                said.extend(
                    (
                        offset + piece_start,
                        offset + piece_end,
                        piece,
                    )
                    for piece_start, piece_end, piece in split_heard(
                        start,
                        end,
                        text,
                        segment.words,
                        after=heard,
                    )
                )

            # How far the model has been through is the segment's own
            # timing, whether or not the line was this stretch's to say:
            # what is flushed and reported follows the audio heard.
            played = offset + float(segment.end)

            if played >= next_flush:

                next_flush = played + FLUSH_SECONDS

                self._write(said)

            minute = int(played // 60)

            if (
                minute != reported
                and self._total
            ):

                reported = minute

                self._note(
                    f"    Heard {minute} min / "
                    f"{self._total / 60:.0f} min "
                    f"({played / self._total * 100:.0f}%)"
                )

    def _write(
        self,
        said: list[tuple[float, float, str]],
    ) -> None:
        """
        Write what has been heard so far, so mpv can read it again.

        Only the cues that are new are laid out: the file is rewritten whole
        every time, but the work of fitting it to the terminal is done once
        per cue however often it is written.
        """

        with self._lock:

            fresh = said[len(self._cues):]

            self._cues = list(said)
            self._shown.extend(
                split_cues(fresh)
            )

            if said:

                self._heard = said[-1][1]

            shown = list(self._shown)

        write_srt(
            shown,
            self.srt_path,
        )

        with self._lock:

            self._revision += 1

    def _note(
        self,
        line: str,
    ) -> None:

        with self._lock:

            self._notes.append(line)


class HeardWhilePlaying(HeardFile):
    """
    A file's captions, heard and written while it plays: the audio is in
    hand, so the model hears it in one pass.
    """

    def _stretches(self) -> Iterator[tuple[Path, float, float]]:

        yield self._audio, 0.0, 0.0


class StreamedWhilePlaying(HeardFile):
    """
    Captions for an item that is still arriving.

    The player is handed the URL, so the first frame is seconds away, and
    the model hears the bytes the player is reading by asking the server for
    them again - a span at a time, by HTTP range, which the item was probed
    for before any of this (`media.range_probe`). What is fetched is also
    written to the audio file, so a run ends holding the copy it heard and
    the artifacts are rendered from it like any other.

    What this rests on is a site serving the same bytes to every request: an
    item whose second probe answers a different length - an ad stitched into
    one of them - is downloaded whole first instead, because captions timed
    against one copy of an item cannot be in pace with another.
    """

    def __init__(
        self,
        media,
        url: str,
        ranged,
        headers: dict[str, str],
        audio_stem: Path,
        model_name: str,
        device: str,
    ) -> None:

        super().__init__(
            media,
            audio_stem.with_name(
                audio_stem.name + ranged.extension + ".part"
            ),
            model_name,
            device,
        )

        self._url = url
        self._length = ranged.length
        self._headers = headers

        # The page's own figure for the item, until the audio says better:
        # it is what the progress lines are shown against.
        self._total = float(media.duration or 0.0)

        self._fetched = 0
        self._rate = 0.0
        self._spans: Path | None = None

    def stop(self) -> None:
        """
        Stop hearing, keeping the captions it wrote.

        The bytes of a fetch that never finished are not a copy of the item
        and are dropped with the spans: the transcript is not cached either,
        so a later run hears the item again.
        """

        super().stop()

        with self._lock:

            complete = self._complete

        if not complete:

            self._audio.unlink(missing_ok=True)

        if self._spans is not None:

            shutil.rmtree(
                self._spans,
                ignore_errors=True,
            )

    def _stretches(self) -> Iterator[tuple[Path, float, float]]:
        """
        Fetch a span of the item, write it down, and say where it belongs.

        A span that is heard has already been fetched when the next one is
        asked for, so the size of a request is set by how long a stretch of
        audio takes to hear (the first is a fixed size, because the rate the
        bytes come at is what the first heard span measures).
        """

        spans = Path(
            tempfile.mkdtemp(
                prefix="subcast-span-"
            )
        )

        self._spans = spans

        self._audio.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        number = 0

        while self._fetched < self._length:

            if self._stopping.is_set():

                return

            self._rate = (
                self._fetched / self._covered
                if self._covered
                else 0.0
            )

            overlap = int(
                SPAN_OVERLAP_SECONDS * self._rate
            )

            first = max(0, self._fetched - overlap)

            wanted = (
                FIRST_SPAN_BYTES
                if not self._rate
                else int(SPAN_SECONDS * self._rate)
            )

            last = min(
                self._length - 1,
                first + wanted - 1,
            )

            body = fetch_range(
                self._url,
                self._headers,
                first,
                last,
            )

            span = spans / f"{number:05d}.mp3"

            span.write_bytes(body)

            # The overlap is already in the file: it was the end of the span
            # before this one.
            with self._audio.open("ab") as audio:

                audio.write(
                    body[self._fetched - first:]
                )

            self._fetched = first + len(body)
            number += 1

            overlap_seconds = (
                overlap / self._rate
                if self._rate
                else 0.0
            )

            yield (
                span,
                max(0.0, self._covered - overlap_seconds),
                self._covered,
            )

            span.unlink(missing_ok=True)

    def _settled(self) -> None:
        """
        The item has been heard end to end: the bytes are a copy of it now,
        so they are named like one.
        """

        self._audio.replace(
            self._audio.with_name(
                self._audio.name.removesuffix(".part")
            )
        )
