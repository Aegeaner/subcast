"""What a run drops from its own cache, and when."""

from __future__ import annotations

import os
import time
from pathlib import Path

from subcast import cli, config, retention

# What a sweep in these tests is measured against, so they say what they mean
# rather than what the shipped default is. The run at the end of the file is
# the one that says what a run does with it.
DAYS = 7


def in_cache(
    monkeypatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setattr(
        config,
        "CACHE_DIR",
        tmp_path,
    )

    return tmp_path


def written(
    path: Path,
    days_ago: float,
) -> Path:
    """
    A file the cache holds, last written `days_ago` days ago.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        "",
        encoding="utf-8",
    )

    stamp = time.time() - days_ago * 24 * 60 * 60

    os.utime(
        path,
        (stamp, stamp),
    )

    return path


def test_an_item_left_alone_goes_whole(monkeypatch, tmp_path: Path):
    """
    A transcript is only in pace with the audio it was heard from, so both
    go: a run left holding one of them would time its captions against
    audio nobody transcribed.
    """

    cache = in_cache(monkeypatch, tmp_path)

    audio = written(cache / "youtube" / "abc.mp3", 9)
    cues = written(cache / "youtube" / "abc.cues.json", 9)
    subtitles = written(cache / "youtube" / "abc.srt", 9)
    kept = written(cache / "youtube" / "def.mp3", 1)
    kept_cues = written(cache / "youtube" / "def.cues.json", 1)

    assert retention.sweep(days=DAYS) == 1

    assert not audio.exists()
    assert not cues.exists()
    assert not subtitles.exists()
    assert kept.exists()
    assert kept_cues.exists()


def test_an_item_used_since_is_kept_whole(monkeypatch, tmp_path: Path):
    """
    What an item's age is measured by is the last thing written for it, not
    its audio: resuming an episode, or rendering its subtitles again, is
    using it.
    """

    cache = in_cache(monkeypatch, tmp_path)

    audio = written(cache / "youtube" / "abc.mp3", 30)
    cues = written(cache / "youtube" / "abc.cues.json", 30)
    position = written(cache / "youtube" / "abc.position", 1)

    assert retention.sweep(days=DAYS) == 0

    assert audio.exists()
    assert cues.exists()
    assert position.exists()


def test_a_download_that_never_finished_goes_with_the_item(
    monkeypatch,
    tmp_path: Path,
):
    """
    A killed run leaves a `.part` behind that no other run will finish, and
    one being written now is not left alone by anybody else either.
    """

    cache = in_cache(monkeypatch, tmp_path)

    remains = written(cache / "youtube" / "abc.mp3.part", 9)
    running = written(cache / "youtube" / "def.mp3.part", 0)

    assert retention.sweep(days=DAYS) == 1

    assert not remains.exists()
    assert running.exists()


def test_a_short_broadcast_s_captions_are_an_item_too(monkeypatch, tmp_path: Path):
    """
    A broadcast's captions are the only file it leaves, and nothing else
    would ever remove them.
    """

    cache = in_cache(monkeypatch, tmp_path)

    captions = written(cache / "youtube" / "abc.live.srt", 9)

    assert retention.sweep(days=DAYS) == 1

    assert not captions.exists()


def test_a_menu_is_not_an_item(monkeypatch, tmp_path: Path):
    """
    A listing is kept for what it says, not for how new it is: it is
    re-fetched behind a menu anyway (`listing.KEEP_FOR`).
    """

    cache = in_cache(monkeypatch, tmp_path)

    menu = written(cache / "youtube" / "listings" / "0f1e2d.json", 30)

    assert retention.sweep(days=DAYS) == 0

    assert menu.exists()


def test_a_cache_nobody_wrote_is_nothing_to_sweep(monkeypatch, tmp_path: Path):
    in_cache(
        monkeypatch,
        tmp_path / "not-there",
    )

    assert retention.sweep(days=DAYS) == 0


class Source:
    """A source, for a run that only has to reach the cache."""

    name = "youtube"


def test_a_run_drops_a_cache_left_alone_for_days(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    cache = in_cache(monkeypatch, tmp_path)

    old = [
        written(cache / "youtube" / "abc.mp3", 10),
        written(cache / "youtube" / "abc.cues.json", 10),
    ]
    fresh = written(cache / "youtube" / "def.mp3", 1)

    monkeypatch.setattr(
        cli,
        "resolve_target",
        lambda args: cli.Target(
            source=Source(),
            url="https://example.test/feed",
            description="A feed",
        ),
    )
    monkeypatch.setattr(
        cli,
        "menu_entries",
        lambda source, url, args: ([], None),
    )

    assert (
        cli.run_once(
            cli.parse_args(
                [
                    "--list",
                    "https://example.test/feed",
                ]
            )
        )
        == 0
    )

    assert not any(path.exists() for path in old)
    assert fresh.exists()
    assert "Dropped 1 cached item" in capsys.readouterr().out
