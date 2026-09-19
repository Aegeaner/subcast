"""What the command line decides before anything is played."""

from __future__ import annotations

import argparse

from subcast import cli
from subcast.sources import Captions, Media

PUBLISHED = (
    Captions(language="en", url="https://example.test/en.vtt"),
)


def args(
    subs: bool = False,
    subs_from: str = "auto",
) -> argparse.Namespace:
    return argparse.Namespace(
        subs=subs,
        subs_from=subs_from,
    )


def media(
    captions: tuple[Captions, ...] = (),
) -> Media:
    return Media(
        source="youtube",
        key="abc",
        title="A video",
        url="https://youtu.be/abc",
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
