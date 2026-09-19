"""Whisper transcription and subtitle/chapter preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from . import config
from .chapters import write_chapters_file
from .media import media_duration
from .segments import (
    load_segments,
    place,
    save_segments,
    snap_segments,
)
from .srt import (
    load_cues,
    save_cues,
    split_cues,
    write_srt,
)


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


def transcribe(
    audio_path: Path,
    model_name: str,
    device: str,
) -> list[tuple[float, float, str]]:
    """
    Transcribe with faster-whisper.

    Returns the speech cues as (start, end, text).
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

    print(
        "    Transcribing (this takes a while)...",
        flush=True,
    )

    stream, info = model.transcribe(
        str(audio_path),
        language="en",
        vad_filter=True,
        condition_on_previous_text=False,
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
    captions,
    media=None,
    stem: Path | None = None,
    session: requests.Session | None = None,
) -> list[tuple[float, float, str]]:
    """
    Get a subtitle track the source already publishes, as cues.

    The URL in a player's metadata is sometimes the WebVTT itself and
    sometimes a playlist pointing at it; when the plain download does not
    yield captions, the source gets a chance to fetch them its own way
    (yt-dlp, for YouTube).
    """

    from . import sources
    from .vtt import parse_vtt

    session = session or requests.Session()

    cues: list[tuple[float, float, str]] = []

    try:

        text = _download_caption_text(
            captions.url,
            session,
        )

    except requests.RequestException:
        text = ""

    if text.lstrip().startswith("WEBVTT"):

        cues = parse_vtt(text)

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
                captions.language,
                stem,
            )

            if path is not None:

                cues = parse_vtt(
                    path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )

    if not cues:

        raise RuntimeError(
            "the published captions were empty"
        )

    print(
        f"    Published captions ({captions.language}): "
        f"{len(cues)} cues",
        flush=True,
    )

    return cues


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
                published[0],
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
