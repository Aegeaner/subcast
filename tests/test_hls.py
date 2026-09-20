"""The playlist a broadcast publishes."""

from __future__ import annotations

import pytest

from subcast import hls

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:5
#EXT-X-MEDIA-SEQUENCE:1362
#EXTINF:5.0,
seg1362.ts
#EXTINF:4.8,
sub/dir/seg1363.ts
#EXTINF:5.0,
https://cdn.test/seg1364.ts
"""


def test_pieces_are_numbered_by_the_broadcast_not_by_the_listing():
    """
    `#EXT-X-MEDIA-SEQUENCE` is the number of the first piece listed, so the
    pieces after it follow - which is what makes a piece an identity. The
    window slides as the broadcast airs, and a listing is not an identity.
    """

    playlist = hls.parse(PLAYLIST, "https://manifest.test/pl.m3u8")

    assert [segment.sequence for segment in playlist.segments] == [
        1362,
        1363,
        1364,
    ]


def test_a_piece_is_as_long_as_the_playlist_says():
    playlist = hls.parse(PLAYLIST, "https://manifest.test/pl.m3u8")

    assert [segment.duration for segment in playlist.segments] == [
        5.0,
        4.8,
        5.0,
    ]


def test_a_piece_is_addressed_where_the_playlist_was_read():
    """
    A playlist names its pieces relative to itself, so what a piece is
    fetched from is its own URL joined to the one the playlist came from.
    """

    playlist = hls.parse(PLAYLIST, "https://manifest.test/dir/pl.m3u8")

    assert [segment.uri for segment in playlist.segments] == [
        "https://manifest.test/dir/seg1362.ts",
        "https://manifest.test/dir/sub/dir/seg1363.ts",
        "https://cdn.test/seg1364.ts",
    ]


def test_a_broadcast_that_has_ended_says_so():
    playlist = hls.parse(
        PLAYLIST + "#EXT-X-ENDLIST\n",
        "https://manifest.test/pl.m3u8",
    )

    assert playlist.ended is True
    assert hls.parse(PLAYLIST, "https://manifest.test/pl.m3u8").ended is False


def test_a_fragmented_playlist_names_what_its_pieces_are_read_with():
    """
    A fragment of a fragmented stream is not decodable on its own, so a
    playlist that has one says where the init segment is.
    """

    playlist = hls.parse(
        '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:5.0,\nseg1.m4s\n',
        "https://manifest.test/dir/pl.m3u8",
    )

    assert playlist.init == "https://manifest.test/dir/init.mp4"


def test_a_playlist_that_makes_no_sense_is_refused():
    """
    A playlist whose numbers cannot be read is refused as unavailable rather
    than parsed into pieces placed at a moment nobody said.
    """

    with pytest.raises(hls.Unavailable):

        hls.parse(
            "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:soon\n#EXTINF:5.0,\nseg1.ts\n",
            "https://manifest.test/pl.m3u8",
        )



class FakeResponse:
    """What one request answered."""

    def __init__(self, status: int, body: bytes = b"") -> None:

        self.status_code = status
        self.content = body


def test_a_session_that_is_over_is_not_the_same_as_a_request_that_failed(
    monkeypatch,
):
    """
    A googlevideo URL carries its own expiry and a broadcast outlives it, so
    the statuses that mean "ask for a fresh one" are told apart from the ones
    that mean "try again".
    """

    monkeypatch.setattr(
        hls.requests,
        "get",
        lambda url, **kwargs: FakeResponse(403),
    )

    with pytest.raises(hls.Expired):

        hls.read("https://manifest.test/pl.m3u8")

    monkeypatch.setattr(
        hls.requests,
        "get",
        lambda url, **kwargs: FakeResponse(503),
    )

    with pytest.raises(hls.Unavailable):

        hls.fetch("https://manifest.test/seg.ts")


def test_a_playlist_comes_back_as_pieces(monkeypatch):
    monkeypatch.setattr(
        hls.requests,
        "get",
        lambda url, **kwargs: FakeResponse(200, PLAYLIST.encode()),
    )

    playlist = hls.read("https://manifest.test/pl.m3u8")

    assert len(playlist.segments) == 3
