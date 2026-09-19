# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-19

### Added

- **YouTube**: videos, playlists and channels, through `yt-dlp` (a URL works
  with no extra flags: `subcast <url>`). Channels and `@handles` are
  normalised to their `/videos` listing, `--list` shows what a URL points at,
  and `--limit N` plays several entries in turn (`0` for all).
- **Published captions win**: where a site already has subtitles (YouTube
  usually does), they are downloaded and used instead of transcribing, so an
  episode is ready in seconds with no GPU. `--subs-from asr` forces local
  transcription, `--subs-from published` forbids it.
- Published captions now arrive on their own: an item whose source times
  its own captions is prepared and played with them without `--subs` (ASR
  tracks included), and `--subs` is left for the local transcription that
  sources without captions - RTÉ - need.
- **Feeds**: `--add-feed` saves a YouTube playlist or channel into
  `$XDG_CONFIG_HOME/subcast/feeds.json`, named after the listing itself or
  by `--name`; `--feeds` lists them, and `--feed NAME` (or `--feed 2`)
  opens one the way a podcast client does - the newest entries as a
  numbered menu to choose from. `--no-pick` plays the newest straight
  through instead, and `--remove-feed` forgets one. Not podcast RSS: a
  short list of the listings you follow, and the file is yours, so it stays
  out of the checkout.
- **Searching and a picker for long listings**: `--search QUERY` turns a
  YouTube search into a listing, and `--pick` prints a listing and takes
  `3`, `2,5-7` or `all` from it before anything is prepared or played. A
  menu shows the newest `SUBSCAST_LIMIT` entries (30 by default) rather
  than paging a whole channel: `--limit N` asks for another number and
  `--limit 0` for all of them.
- **YouTube chapters** become the segments, used exactly as published, so
  nothing is guessed: the block shows the chapter you are in.
- A `sources` layer: sources hand the pipeline a `Media` record (what to
  play, which captions exist, which segments), so RTÉ and YouTube share
  everything downstream.
- `--save` downloads into `~/Videos/<source>/`; `--quality` caps the video
  height; `--audio-only` plays a video's audio with captions in the terminal.
- **Resume**: how far into an item playback got is written next to its cache
  entry as it plays, and the next run of the same item starts from there.
  The position is keyed by the item rather than by the stream URL, so it
  survives RTÉ's expiring links; an item watched to the end (or mpv
  reporting EOF) forgets its position, `--no-resume` starts over, and a
  stream of unknown length is not remembered at all.
- **Playback progress**: the caption block's bottom row is now a clock — how
  far in and how long in total, with a bar that fills as the episode plays.
  mpv's own terminal status line stays off in the bar, so this is the
  progress display there.
- A caption line now lingers, dimmed, until the next one replaces it.
- `subcast[youtube]` installs the `yt-dlp` binary for convenience.

### Changed

- Cached audio, transcripts and subtitles moved under `~/.cache/subcast/<source>/`,
  and saved episodes under `~/Videos/<source>/`, so paths no longer assume
  one show. Existing caches keep working if moved into those directories.
- The CLI takes an optional URL instead of only talking to RTÉ; with no URL
  it still plays the latest Morning Ireland. `--subs` now means "transcribe
  where the source has none" rather than "produce subtitles at all".
- `--list` prints a page of the listing now — the newest 30, or `--limit N`
  — instead of the single entry playback would have stopped at.

### Fixed

- A stream mpv cannot load is fetched and tried once more. YouTube hands
  out signed stream URLs that answer 403 from time to time — a fresh
  extraction is the cure, and mpv stops at the first one, which used to end
  the run with "mpv exited with 2". Only mpv's own "couldn't be played"
  (exit 2) is retried: quitting, a bad option and Ctrl-C are not.
- YouTube captions that do not arrive as WebVTT: the hand-off to yt-dlp was
  looked up as a method on the source while it only existed as a module
  function, so it never ran. The URL YouTube hands over for automatic
  captions answers with json3 or a playlist rather than WebVTT, so those
  videos failed with "the published captions were empty". The source now
  carries the hook, and a yt-dlp failure reports what yt-dlp said.

## [0.1.0] - 2026-09-19

First release: RTÉ Morning Ireland only.

### Added

- Find the latest episode and play it through mpv, or save it with `--save`.
- `--subs` transcription with faster-whisper, cached per episode, with
  device auto-detection (CUDA, then CPU) and a configurable model.
- Captions drawn by the tool in a fixed block at the bottom of the terminal
  (`--subs-style=bar`), coloured, repainted only when the text changes, and
  cleared on exit; `--subs-style=osd` keeps mpv's plain output.
- Caption size scaling (`--subs-scale`) through the terminal's text sizing
  protocol, detected by asking the terminal; captions only, no terminal
  configuration is touched.
- Segment titles from the list RTÉ publishes with each episode, aligned to
  the transcript, shown above the dialogue and written out as chapter marks.
- Subtitle shaping: at most two lines per cue, no sub-second flashes, no
  lone-word pieces.
- Cached transcripts and placed segments, so caption changes never cost a
  re-transcription, plus `--save --subs` to keep audio, `.srt`,
  `.segments.json` and `.chapters.txt` together.

[Unreleased]: https://github.com/Aegeaner/subcast/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Aegeaner/subcast/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Aegeaner/subcast/releases/tag/v0.1.0
