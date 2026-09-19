"""Whisper transcription and subtitle/chapter preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chapters import write_chapters_file
from .media import media_duration
from .segments import (
    build_segments,
    load_segments,
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

        except Exception as exc:

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


def prepare_subtitles(
    audio_path: Path,
    clips: list[tuple[str, float]],
    title: str,
    model_name: str,
    device: str,
) -> Prepared:
    """
    Subtitles and chapters for audio_path, transcribed once and reused.

    The transcript and the placed segment list are what get cached; the
    .srt and the chapters file are rendered from them on every run, so
    changing how captions look never costs a re-transcription. Both are
    rendered from the same placed segments, so the chapter marks and the
    segment cues cannot drift apart.

    The rendered captions and segments come back with the artifacts, for
    callers that draw the captions themselves.
    """

    srt_path = audio_path.with_suffix(
        ".srt"
    )

    cues_path = audio_path.with_name(
        audio_path.stem + ".cues.json"
    )

    segments_path = audio_path.with_name(
        audio_path.stem + ".segments.json"
    )

    chapters_path = audio_path.with_name(
        audio_path.stem + ".chapters.txt"
    )

    if cues_path.is_file() and (
        not clips
        or segments_path.is_file()
    ):

        print(
            f"    Reusing transcript: {cues_path}",
            flush=True,
        )

        cues = load_cues(
            cues_path
        )

        segments = load_segments(
            segments_path
        )

    else:

        cues = transcribe(
            audio_path,
            model_name,
            device,
        )

        save_cues(
            cues,
            cues_path,
        )

        duration = media_duration(
            audio_path
        )

        if not duration:

            # No ffprobe: the published clip durations are a lower bound.
            duration = sum(
                clip_duration
                for _, clip_duration in clips
            )

        segments = snap_segments(
            build_segments(
                clips,
                duration,
            ),
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
        title,
        chapters_path,
    )

    return Prepared(
        srt_path,
        chapters_path,
        framed,
        segments,
    )

