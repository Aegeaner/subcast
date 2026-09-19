"""What the command line decides before anything is played."""

from __future__ import annotations

import argparse

from subcast import cli, player
from subcast.sources import Captions, Media

PUBLISHED = (
    Captions(language="en", url="https://example.test/en.vtt"),
)


def args(
    subs: bool = False,
    subs_from: str = "auto",
    resume: bool = True,
) -> argparse.Namespace:
    return argparse.Namespace(
        subs=subs,
        subs_from=subs_from,
        resume=resume,
    )


def media(
    captions: tuple[Captions, ...] = (),
    duration: float | None = 300.0,
) -> Media:
    return Media(
        source="youtube",
        key="abc",
        title="A video",
        url="https://youtu.be/abc",
        duration=duration,
        captions=captions,
    )


def test_published_captions_are_used_without_being_asked_for():
    """
    A site that already times its own captions should not need a flag:
    fetching them costs a download, not a transcription.
    """

    assert cli.wants_subtitles(media(PUBLISHED), args())


def test_transcribing_needs_to_be_asked_for():
    assert not cli.wants_subtitles(media(), args())
    assert cli.wants_subtitles(media(), args(subs=True))
    assert cli.wants_subtitles(media(), args(subs_from="asr"))


def test_playing_starts_where_the_item_was_left(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media: tmp_path / media.key,
    )

    player.Positions(tmp_path / "abc").update(754.0, 3600.0)

    assert cli.saved_positions(media(), args()).start == 754.0


def test_starting_over_forgets_the_position_for_this_run(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media: tmp_path / media.key,
    )

    player.Positions(tmp_path / "abc").update(754.0, 3600.0)

    assert cli.saved_positions(
        media(),
        args(resume=False),
    ).start == 0.0


def test_a_stream_of_unknown_length_is_not_remembered(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        cli,
        "cache_stem",
        lambda media: tmp_path / media.key,
    )

    assert cli.saved_positions(media(duration=None), args()) is None
