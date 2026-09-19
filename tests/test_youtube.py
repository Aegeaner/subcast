"""YouTube listings, resolution and downloads, without a network.

Every payload here is written inline - the shape yt-dlp prints - and
every call that would reach the binary is answered by a fake, so these
tests say what subcast asks YouTube for and what it does with the
answer, not what YouTube happens to return today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast.sources import Captions, Media, Segment, youtube
from subcast.sources.youtube import (
    SOURCE,
    as_vtt,
    audio_download,
    flatten_url,
    listing_title,
    parse_entries,
    parse_media,
    yt_dlp_available,
    yt_dlp_json,
)

WATCH = "https://www.youtube.com/watch?v="


def entry(
    video_id: str,
    title: str = "A video",
    duration: float | None = 300.0,
) -> dict:
    """One flat listing entry, the way --flat-playlist prints it."""

    return {
        "_type": "url",
        "id": video_id,
        "title": title,
        "url": f"{WATCH}{video_id}",
        "duration": duration,
    }


def playlist() -> dict:
    """A listing with a gap, a nested playlist and an id-less entry."""

    return {
        "_type": "playlist",
        "id": "PL123",
        "title": "A playlist",
        "entries": [
            entry("aaa", "First"),
            None,
            {
                "_type": "playlist",
                "id": "PL456",
                "title": "A nested playlist",
                "entries": [entry("zzz", "Hidden")],
            },
            {
                "_type": "url",
                "title": "A video whose id is missing",
                "url": "https://www.youtube.com/",
            },
            entry("bbb", "Second"),
            entry("ccc", "Third"),
        ],
    }


def video() -> dict:
    """A resolved video: chapters, published captions, automatic ones."""

    return {
        "id": "abc123",
        "title": "A talk",
        "webpage_url": f"{WATCH}abc123",
        "duration": 812.5,
        "chapters": [
            {"start_time": 0.0, "title": "Intro"},
            {"start_time": 61.0, "title": "The middle"},
        ],
        "subtitles": {
            "en": [
                {"ext": "json3", "url": "https://example.test/en.json3"},
                {"ext": "vtt", "url": "https://example.test/en.vtt"},
            ],
        },
        "automatic_captions": {
            "en": [
                {"ext": "vtt", "url": "https://example.test/auto-en.vtt"},
            ],
        },
    }


def fake_yt_dlp(
    monkeypatch,
    result: str = "{}",
    stderr: str = "",
    returncode: int = 0,
    side_effect=None,
) -> list[list[str]]:
    """A yt-dlp binary on PATH that answers with `result`."""

    monkeypatch.setattr(
        youtube.shutil,
        "which",
        lambda name: "/usr/bin/yt-dlp",
    )

    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)

        if side_effect is not None:
            side_effect(command)

        return youtube.subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout=result,
            stderr=stderr,
        )

    monkeypatch.setattr(youtube.subprocess, "run", run)

    return commands


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc",
        "https://www.youtube.com/watch?v=abc",
        "https://m.youtube.com/watch?v=abc",
        "https://music.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://www.youtube.com/@someone/videos",
    ],
)
def test_youtube_urls_are_this_source(url: str):
    assert SOURCE.matches(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://notyoutube.com/watch?v=abc",
        "https://www.youtube.com.example.test/watch?v=abc",
        "https://www.rte.ie/radio/radio1/morning-ireland/",
        "not a url",
    ],
)
def test_other_urls_are_not(url: str):
    """A host that merely contains youtube.com is not YouTube."""

    assert not SOURCE.matches(url)


def test_a_handle_gains_a_videos_listing():
    assert flatten_url(
        "https://www.youtube.com/@Someone"
    ) == "https://www.youtube.com/@Someone/videos"

    assert flatten_url(
        "https://www.youtube.com/@Someone/"
    ) == "https://www.youtube.com/@Someone/videos"


def test_channel_and_user_urls_gain_a_videos_listing():
    assert flatten_url(
        "https://www.youtube.com/channel/UCabc123"
    ) == "https://www.youtube.com/channel/UCabc123/videos"

    assert flatten_url(
        "https://www.youtube.com/user/someone"
    ) == "https://www.youtube.com/user/someone/videos"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@Someone/videos",
        "https://www.youtube.com/channel/UCabc123/streams",
        "https://www.youtube.com/user/someone/playlists",
        "https://www.youtube.com/@Someone/shorts",
        "https://www.youtube.com/watch?v=abc123",
        "https://www.youtube.com/playlist?list=PL123",
        "https://youtu.be/abc123",
    ],
)
def test_urls_that_already_point_at_what_to_play_are_left_alone(url: str):
    assert flatten_url(url) == url


def test_listing_entries_skip_gaps_nested_playlists_and_missing_ids():
    media = parse_entries(playlist())

    assert [item.key for item in media] == ["aaa", "bbb", "ccc"]

    assert media[0] == Media(
        source="youtube",
        key="aaa",
        title="First",
        url=f"{WATCH}aaa",
        kind="video",
        duration=300.0,
        stream=True,
    )


def test_a_limit_stops_the_listing():
    assert [
        item.key
        for item in parse_entries(playlist(), limit=2)
    ] == ["aaa", "bbb"]

    assert len(parse_entries(playlist(), limit=0)) == 3


def test_a_single_video_payload_is_one_entry():
    media = parse_entries(
        {
            "id": "abc123",
            "title": "A talk",
            "webpage_url": f"{WATCH}abc123",
            "duration": 812.5,
        }
    )

    assert media == [
        Media(
            source="youtube",
            key="abc123",
            title="A talk",
            url=f"{WATCH}abc123",
            kind="video",
            duration=812.5,
            stream=True,
        )
    ]


def test_an_entry_without_a_title_or_webpage_url_still_names_a_video():
    media = parse_entries(
        {
            "_type": "url",
            "id": "abc123",
            "duration": None,
        }
    )

    assert media[0].title == "Untitled"
    assert media[0].url == f"{WATCH}abc123"
    assert media[0].duration is None


def test_a_resolved_video_carries_its_chapters_and_published_captions():
    assert parse_media(video()) == Media(
        source="youtube",
        key="abc123",
        title="A talk",
        url=f"{WATCH}abc123",
        kind="video",
        duration=812.5,
        stream=True,
        captions=(
            Captions(
                language="en",
                url="https://example.test/en.vtt",
                ext="vtt",
            ),
        ),
        segments=(
            Segment(title="Intro", start=0.0),
            Segment(title="The middle", start=61.0),
        ),
    )


def test_english_variants_are_preferred_over_other_languages():
    payload = video()

    payload["subtitles"] = {}

    payload["automatic_captions"] = {
        "de": [{"ext": "vtt", "url": "https://example.test/de.vtt"}],
        "en-GB": [{"ext": "vtt", "url": "https://example.test/en-gb.vtt"}],
    }

    assert parse_media(payload).captions == (
        Captions(
            language="en-GB",
            url="https://example.test/en-gb.vtt",
            ext="vtt",
        ),
    )


def test_any_language_beats_no_captions():
    payload = video()

    payload["subtitles"] = {}

    payload["automatic_captions"] = {
        "de": [{"ext": "vtt", "url": "https://example.test/de.vtt"}],
    }

    assert parse_media(payload).captions == (
        Captions(
            language="de",
            url="https://example.test/de.vtt",
            ext="vtt",
        ),
    )

    payload["automatic_captions"] = {}

    assert parse_media(payload).captions == ()


@pytest.mark.parametrize(
    ("url", "wanted"),
    [
        ("https://www.youtube.com/watch?v=abc123", "abc123"),
        ("https://www.youtube.com/watch?v=abc123&t=30s", "abc123"),
        ("https://youtu.be/abc123", "abc123"),
        ("https://youtu.be/abc123?t=30", "abc123"),
        ("https://www.youtube.com/playlist?list=PL1", None),
        ("https://www.youtube.com/@BBCNews", None),
        ("https://www.youtube.com/watch", None),
        ("https://example.test/watch?v=abc123", None),
    ],
)
def test_a_watch_link_names_its_video(url: str, wanted: str | None):
    assert SOURCE.video_id(url) == wanted


def test_a_translated_track_is_followed_by_the_one_it_came_from():
    """
    YouTube rate-limits translated tracks (a 429 the native one does not
    get), so the track behind them is worth having: it is captions either
    way, and trying it costs nothing.
    """

    payload = video()

    payload["subtitles"] = {}

    payload["automatic_captions"] = {
        "zh-Hant": [
            {"ext": "vtt", "url": "https://example.test/zh?lang=zh-Hant"},
        ],
        "en": [
            {
                "ext": "vtt",
                "url": "https://example.test/en?lang=zh&tlang=en",
            },
        ],
    }

    captions = parse_media(payload).captions

    assert [caption.language for caption in captions] == ["en", "zh-Hant"]
    assert "tlang=" in captions[0].url
    assert "tlang=" not in captions[1].url


def test_a_native_track_has_nothing_behind_it():
    assert len(parse_media(video()).captions) == 1


def test_a_tracks_own_entry_beats_a_translation_of_it():
    payload = video()

    payload["subtitles"] = {
        "en": [
            {"ext": "vtt", "url": "https://example.test/en?tlang=de"},
            {"ext": "vtt", "url": "https://example.test/en?lang=en"},
        ],
    }

    payload["automatic_captions"] = {}

    assert (
        parse_media(payload).captions[0].url
        == "https://example.test/en?lang=en"
    )


def test_a_track_without_vtt_is_asked_for_vtt():
    """
    YouTube serves WebVTT for any of a track's formats when the URL asks
    for it, which is what keeps a second extraction out of the run.
    """

    payload = video()

    payload["subtitles"] = {
        "en": [
            {"ext": "json3", "url": "https://example.test/en.json3?fmt=json3"},
        ],
    }

    payload["automatic_captions"] = {}

    assert parse_media(payload).captions == (
        Captions(
            language="en",
            url="https://example.test/en.json3?fmt=vtt",
            ext="vtt",
        ),
    )


@pytest.mark.parametrize(
    ("given", "wanted"),
    [
        # a format the URL does not name yet
        ("https://example.test/en", "https://example.test/en?fmt=vtt"),
        # one it names, in the middle of other parameters
        (
            "https://example.test/en?lang=en&fmt=srv3&signature=abc",
            "https://example.test/en?lang=en&signature=abc&fmt=vtt",
        ),
        # already WebVTT: asking again changes nothing
        (
            "https://example.test/en?v=x&fmt=vtt",
            "https://example.test/en?v=x&fmt=vtt",
        ),
    ],
)
def test_as_vtt_asks_for_webvtt(given: str, wanted: str):
    assert as_vtt(given) == wanted


def test_a_live_video_has_no_duration():
    payload = video()

    payload["is_live"] = True

    assert parse_media(payload).duration is None


def test_yt_dlp_available_follows_the_path(monkeypatch):
    monkeypatch.setattr(
        youtube.shutil,
        "which",
        lambda name: None,
    )

    assert not yt_dlp_available()

    monkeypatch.setattr(
        youtube.shutil,
        "which",
        lambda name: "/usr/bin/yt-dlp",
    )

    assert yt_dlp_available()


def test_a_flat_listing_is_bounded_at_the_command_line(monkeypatch):
    commands = fake_yt_dlp(
        monkeypatch,
        result='{"_type": "playlist", "entries": []}',
    )

    assert yt_dlp_json(
        "https://www.youtube.com/@someone",
        limit=5,
        flat=True,
    ) == {
        "_type": "playlist",
        "entries": [],
    }

    assert commands == [
        [
            "yt-dlp",
            "-J",
            "--no-warnings",
            "--socket-timeout",
            "15",
            "--retries",
            "2",
            "--flat-playlist",
            "--playlist-end",
            "5",
            "https://www.youtube.com/@someone",
        ]
    ]


def test_a_single_video_is_asked_for_without_playlist_flags(monkeypatch):
    commands = fake_yt_dlp(
        monkeypatch,
        result='{"id": "abc123"}',
    )

    assert yt_dlp_json(
        f"{WATCH}abc123",
        limit=0,
    ) == {"id": "abc123"}

    assert "--flat-playlist" not in commands[0]
    assert "--playlist-end" not in commands[0]


def test_a_failed_run_reports_the_last_thing_yt_dlp_said(monkeypatch):
    fake_yt_dlp(
        monkeypatch,
        returncode=1,
        stderr=(
            "WARNING: Falling back on generic extractor\n"
            "ERROR: Video unavailable\n"
        ),
    )

    with pytest.raises(RuntimeError) as error:
        yt_dlp_json(f"{WATCH}gone")

    assert str(error.value) == (
        f"yt-dlp failed for {WATCH}gone: ERROR: Video unavailable"
    )


def test_a_run_with_nothing_usable_on_stdout_fails(monkeypatch):
    fake_yt_dlp(
        monkeypatch,
        result="",
        stderr="ERROR: nothing to print\n",
    )

    with pytest.raises(RuntimeError) as error:
        yt_dlp_json(f"{WATCH}gone")

    assert "ERROR: nothing to print" in str(error.value)


def test_a_missing_binary_says_how_to_install_it(monkeypatch):
    monkeypatch.setattr(
        youtube.shutil,
        "which",
        lambda name: None,
    )

    with pytest.raises(RuntimeError) as error:
        yt_dlp_json(f"{WATCH}abc123")

    assert str(error.value) == (
        "yt-dlp is required for YouTube support; install it "
        "(e.g. pipx install yt-dlp) or use --source rte"
    )


def test_episodes_flatten_the_url_and_ask_for_a_flat_bounded_listing(monkeypatch):
    asked = []

    def fake_json(
        url,
        limit=None,
        flat=False,
    ):
        asked.append(
            {
                "url": url,
                "limit": limit,
                "flat": flat,
            }
        )

        return playlist()

    monkeypatch.setattr(youtube, "yt_dlp_json", fake_json)

    media = SOURCE.episodes(
        "https://www.youtube.com/@someone",
        limit=2,
    )

    assert asked == [
        {
            "url": "https://www.youtube.com/@someone/videos",
            "limit": 2,
            "flat": True,
        }
    ]

    assert [item.key for item in media] == ["aaa", "bbb"]


def test_resolve_asks_for_the_whole_video(monkeypatch):
    asked = []

    def fake_json(
        url,
        limit=None,
        flat=False,
    ):
        asked.append(
            {
                "url": url,
                "limit": limit,
                "flat": flat,
            }
        )

        return video()

    monkeypatch.setattr(youtube, "yt_dlp_json", fake_json)

    resolved = SOURCE.resolve(
        Media(
            source="youtube",
            key="abc123",
            title="A talk",
            url=f"{WATCH}abc123",
        )
    )

    assert asked == [
        {
            "url": f"{WATCH}abc123",
            "limit": None,
            "flat": False,
        }
    ]

    assert resolved.duration == 812.5
    assert resolved.captions == (
        Captions(
            language="en",
            url="https://example.test/en.vtt",
            ext="vtt",
        ),
    )
    assert resolved.segments == (
        Segment(title="Intro", start=0.0),
        Segment(title="The middle", start=61.0),
    )


def test_downloading_audio_returns_the_file_yt_dlp_wrote(
    monkeypatch,
    tmp_path: Path,
):
    stem = tmp_path / "abc123"

    def write(command):
        (tmp_path / "abc123.webm").write_bytes(b"audio")
        (tmp_path / "abc123.webm.part").write_bytes(b"half")

    commands = fake_yt_dlp(
        monkeypatch,
        side_effect=write,
    )

    assert audio_download(
        f"{WATCH}abc123",
        stem,
    ) == tmp_path / "abc123.webm"

    assert commands == [
        [
            "yt-dlp",
            "-f",
            "bestaudio",
            "-o",
            f"{stem}.%(ext)s",
            "--no-playlist",
            f"{WATCH}abc123",
        ]
    ]


def test_a_download_that_writes_nothing_fails(
    monkeypatch,
    tmp_path: Path,
):
    fake_yt_dlp(
        monkeypatch,
        stderr="ERROR: unable to download video data\n",
    )

    with pytest.raises(RuntimeError) as error:
        audio_download(
            f"{WATCH}abc123",
            tmp_path / "abc123",
        )

    assert "ERROR: unable to download video data" in str(error.value)


def test_downloading_audio_without_yt_dlp_says_how_to_install_it(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        youtube.shutil,
        "which",
        lambda name: None,
    )

    with pytest.raises(RuntimeError) as error:
        audio_download(
            f"{WATCH}abc123",
            tmp_path / "abc123",
        )

    assert "pipx install yt-dlp" in str(error.value)


def test_downloading_captions_returns_the_vtt_yt_dlp_wrote(
    monkeypatch,
    tmp_path: Path,
):
    stem = tmp_path / "abc123"

    def write(command):
        (tmp_path / "abc123.en.vtt").write_text("WEBVTT\n")

    commands = fake_yt_dlp(
        monkeypatch,
        side_effect=write,
    )

    assert SOURCE.caption_file(
        f"{WATCH}abc123",
        "en",
        stem,
    ) == tmp_path / "abc123.en.vtt"

    assert commands == [
        [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en",
            "--sub-format",
            "vtt",
            "-o",
            f"{stem}.%(ext)s",
            "--no-playlist",
            f"{WATCH}abc123",
        ]
    ]


def test_a_video_without_that_caption_language_returns_nothing(
    monkeypatch,
    tmp_path: Path,
):
    fake_yt_dlp(monkeypatch)

    assert (
        SOURCE.caption_file(
            f"{WATCH}abc123",
            "en",
            tmp_path / "abc123",
        )
        is None
    )


def test_a_caption_download_that_fails_reports_what_yt_dlp_said(
    monkeypatch,
    tmp_path: Path,
):
    fake_yt_dlp(
        monkeypatch,
        stderr="ERROR: Unable to download video subtitles\n",
        returncode=1,
    )

    with pytest.raises(RuntimeError) as error:
        SOURCE.caption_file(
            f"{WATCH}abc123",
            "en",
            tmp_path / "abc123",
        )

    assert "Unable to download video subtitles" in str(error.value)


def test_a_channel_listing_is_named_after_the_channel(monkeypatch):
    fake_yt_dlp(
        monkeypatch,
        result='{"title": "BBC News - Videos", "entries": []}',
    )

    assert (
        listing_title("https://www.youtube.com/@BBCNews")
        == "BBC News"
    )


def test_a_playlist_is_named_after_itself(monkeypatch):
    fake_yt_dlp(
        monkeypatch,
        result='{"title": "Morning Ireland clips", "entries": []}',
    )

    assert (
        listing_title("https://www.youtube.com/playlist?list=PL1")
        == "Morning Ireland clips"
    )


def test_a_listing_without_a_title_says_so(monkeypatch):
    fake_yt_dlp(monkeypatch, result='{"entries": []}')

    with pytest.raises(RuntimeError) as error:
        listing_title("https://www.youtube.com/@BBCNews")

    assert "playlist or channel" in str(error.value)
