"""The feeds list: the listings the user saved under a name."""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import config, feeds
from subcast.sources import youtube

SKY = "https://www.youtube.com/@SkyNews"
BBC = "https://www.youtube.com/@BBCNews"


def in_config_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """
    Feeds live in the user's config directory; keep the tests out of it.
    """

    monkeypatch.setattr(
        config,
        "CONFIG_DIR",
        tmp_path,
    )


def test_a_feed_survives_to_the_next_run(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    feeds.add("sky", SKY)

    assert feeds.load() == [
        feeds.Feed(name="sky", url=SKY)
    ]


def test_no_usable_feeds_file_means_no_feeds(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    assert feeds.load() == []

    path = config.feeds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ half a file")

    assert feeds.load() == []


def test_a_name_holds_one_feed(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    feeds.add("sky", SKY)
    feeds.add("SKY", BBC)

    assert feeds.load() == [
        feeds.Feed(name="SKY", url=BBC)
    ]


def test_a_feed_is_found_by_name_or_by_number(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    feeds.add("sky", SKY)
    feeds.add("bbc", BBC)

    assert feeds.find("SKY").url == SKY
    assert feeds.find("1").url == SKY
    assert feeds.find("2").url == BBC

    with pytest.raises(RuntimeError) as error:
        feeds.find("c4")

    assert "--feeds lists" in str(error.value)


def test_a_feed_can_be_forgotten(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    feeds.add("sky", SKY)
    feeds.remove("sky")

    assert feeds.load() == []

    with pytest.raises(RuntimeError):
        feeds.remove("sky")


def test_a_feed_without_a_name_is_named_after_the_listing(
    monkeypatch,
):
    monkeypatch.setattr(
        youtube,
        "listing_title",
        lambda url: "Sky News",
    )

    assert feeds.title_for(SKY) == "Sky News"


def test_a_source_that_is_not_a_listing_needs_a_name():
    with pytest.raises(RuntimeError) as error:
        feeds.title_for(
            "https://www.rte.ie/radio/radio1/morning-ireland/"
        )

    assert "--name" in str(error.value)
