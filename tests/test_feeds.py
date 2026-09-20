"""The feeds list: the listings the user saved under a name."""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import config, feeds, sources
from subcast.sources import podcast
from subcast.sources.rte import Rte
from subcast.sources.youtube import Youtube

SKY = "https://www.youtube.com/@SkyNews"
BBC = "https://www.youtube.com/@BBCNews"

FEED = (
    Path(__file__).parent
    / "fixtures"
    / "podcast_feed.rss"
)


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


def test_a_name_that_means_another_url_is_refused(
    monkeypatch,
    tmp_path: Path,
):
    """
    A name is how a feed is asked for, and the same show is often
    published twice - a channel and the programme's own page - so a name
    that quietly started meaning another URL is how a run plays the wrong
    thing.
    """

    in_config_dir(monkeypatch, tmp_path)

    feeds.add("sky", SKY)

    with pytest.raises(RuntimeError) as error:
        feeds.add("SKY", BBC)

    assert "already points at" in str(error.value)

    assert feeds.load() == [
        feeds.Feed(name="sky", url=SKY)
    ]


def test_a_name_is_freed_by_removing_the_feed(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    feeds.add("sky", SKY)
    feeds.remove("sky")
    feeds.add("sky", BBC)

    assert feeds.load() == [
        feeds.Feed(name="sky", url=BBC)
    ]


def test_the_same_url_under_its_own_name_is_not_a_conflict(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    feeds.add("sky", SKY)
    feeds.add("sky", SKY)

    assert feeds.load() == [
        feeds.Feed(name="sky", url=SKY)
    ]


def test_a_name_is_tried_before_a_number(
    monkeypatch,
    tmp_path: Path,
):
    """
    The numbers --feeds prints are positions, so a feed that is itself
    called "2" would otherwise be unreachable by the one name it has.
    """

    in_config_dir(monkeypatch, tmp_path)

    feeds.add("2", SKY)
    feeds.add("bbc", BBC)

    assert feeds.find("2").url == SKY
    assert feeds.find("1").url == SKY


def test_the_built_in_feed_is_found_by_its_name(
    monkeypatch,
    tmp_path: Path,
):
    """
    The feed a run with no URL opens is a feed like any other: it answers
    to its name, so it can also be opened on purpose.
    """

    in_config_dir(monkeypatch, tmp_path)

    assert feeds.find("morning ireland") == feeds.DEFAULT


def test_the_built_in_feed_cannot_be_saved_over(
    monkeypatch,
    tmp_path: Path,
):
    in_config_dir(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError) as error:
        feeds.add(feeds.DEFAULT.name, SKY)

    assert "built-in" in str(error.value)
    assert feeds.load() == []


def test_the_built_in_feed_cannot_be_forgotten(
    monkeypatch,
    tmp_path: Path,
):
    """
    It is not in the file, so forgetting it would do nothing at all -
    which is worth saying rather than answering with silence.
    """

    in_config_dir(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError) as error:
        feeds.remove(feeds.DEFAULT.name)

    assert "built-in" in str(error.value)


def test_a_feed_says_which_source_reads_its_url():
    """
    The source is not what was saved - the URL decides it - so the list
    can say which pipeline each feed goes through, and say so for a URL
    that nothing reads any more rather than failing over it.
    """

    assert feeds.source_of(SKY) == "youtube"

    assert feeds.source_of(
        "https://www.rte.ie/radio/radio1/this-week/"
    ) == "rte"

    assert feeds.source_of(
        "https://podcasts.files.bbci.co.uk/p02nq0gn.rss"
    ) == "podcast"

    assert feeds.source_of("https://example.test/listings/9") == ""


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
    def named(self, url):
        return "Sky News"

    monkeypatch.setattr(Youtube, "listing_title", named)

    assert feeds.title_for(SKY) == "Sky News"


def test_a_programme_names_a_feed_after_itself(
    monkeypatch,
):
    def named(self, url):
        return "Example Show"

    monkeypatch.setattr(Rte, "listing_title", named)

    assert feeds.title_for(
        "https://www.rte.ie/radio/radio1/example-show/"
    ) == "Example Show"


def test_a_podcast_feed_is_saved_under_its_own_name(
    monkeypatch,
    tmp_path: Path,
):
    """
    A feed URL is saved the way a channel is: the source is asked what
    the listing calls itself, and that is the name it is kept under.
    """

    in_config_dir(monkeypatch, tmp_path)

    monkeypatch.setattr(
        podcast,
        "fetch_text",
        lambda url, session=None: FEED.read_text(encoding="utf-8"),
    )

    url = "https://example.test/show.rss"

    feeds.add(
        feeds.title_for(url),
        url,
    )

    assert feeds.load() == [
        feeds.Feed(
            name="Example Podcast",
            url=url,
        )
    ]


def test_a_source_that_cannot_name_a_listing_needs_a_name(
    monkeypatch,
):
    class Source:
        """A source that knows no name for what it lists."""

        name = "files"

    monkeypatch.setattr(
        sources,
        "detect",
        lambda url: Source(),
    )

    with pytest.raises(RuntimeError) as error:
        feeds.title_for(SKY)

    assert "--name" in str(error.value)
