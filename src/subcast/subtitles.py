"""Whisper transcription and subtitle/chapter preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from . import config
from .background import Background
from .chapters import write_chapters_file
from .media import media_duration
from .segments import (
    load_segments,
    place,
    save_segments,
    snap_segments,
)
from .sources import Captions
from .srt import (
    load_cues,
    save_cues,
    split_cues,
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

            cues.append(
                (
                    float(segment.start),
                    float(segment.end),
                    text,
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
    **settings,
) -> list[tuple[float, float, str]]:
    """
    One file's speech, as cues relative to where it starts.

    The same model the whole-episode path uses, on a piece of a
    broadcast: a chunk has no beginning of its own, so where it belongs on
    the timeline is the caller's to say. `settings` are for what only a
    chunk needs - it is heard while it is still being followed, where an
    episode is heard once and for good.
    """

    stream, _info = _stream(
        model,
        audio_path,
        **settings,
    )

    return [
        (
            float(segment.start),
            float(segment.end),
            segment.text.strip(),
        )
        for segment in stream
        if segment.text.strip()
    ]


def _stream(
    model,
    audio_path: Path,
    **settings,
):
    """
    The model reading a file: English speech, silence dropped.

    One definition, because these settings are what the transcript is -
    an episode and a live chunk have to be heard the same way - and
    `settings` are only for the two that are not: how the decoder is run,
    and how much of the sound the voice filter is allowed to keep. They
    replace a default rather than sit beside it.
    """

    options = {
        "language": "en",
        "vad_filter": True,
        "condition_on_previous_text": False,
    }

    options.update(settings)

    return model.transcribe(
        str(audio_path),
        **options,
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
    Whether the transcript and the placed segments are already cached.
    """

    stem = cache_stem(media)

    return stem.with_suffix(
        ".cues.json"
    ).is_file() and (
        not media.segments
        or stem.with_suffix(
            ".segments.json"
        ).is_file()
    )


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
    transcribed locally. The transcript and the placed segments are what
    get cached, so re-rendering never costs a transcription.
    """

    stem = cache_stem(media)

    stem.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    srt_path = stem.with_suffix(".srt")
    cues_path = stem.with_suffix(".cues.json")

    segments_path = stem.with_suffix(
        ".segments.json"
    )

    chapters_path = stem.with_suffix(
        ".chapters.txt"
    )

    if has_transcript(media):

        print(
            f"    Reusing transcript: {cues_path}",
            flush=True,
        )

        cues = load_cues(cues_path)

        segments = load_segments(
            segments_path
        )

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

        duration = media.duration or 0.0

        if not duration and audio_path is not None:
            duration = media_duration(audio_path)

        if not duration:

            duration = sum(
                segment.duration or 0.0
                for segment in media.segments
            )

        segments, exact = place(
            list(media.segments),
            duration,
        )

        if not exact:

            segments = snap_segments(
                segments,
                cues,
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
