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
- **YouTube chapters** become the segments, used exactly as published, so
  nothing is guessed: the block shows the chapter you are in.
- A `sources` layer: sources hand the pipeline a `Media` record (what to
  play, which captions exist, which segments), so RTÉ and YouTube share
  everything downstream.
- `--save` downloads into `~/Videos/<source>/`; `--quality` caps the video
  height; `--audio-only` plays a video's audio with captions in the terminal.
- A caption line now lingers, dimmed, until the next one replaces it.
- `subcast[youtube]` installs the `yt-dlp` binary for convenience.

### Changed

- Cached audio, transcripts and subtitles moved under `~/.cache/subcast/<source>/`,
  and saved episodes under `~/Videos/<source>/`, so paths no longer assume
  one show. Existing caches keep working if moved into those directories.
- The CLI takes an optional URL instead of only talking to RTÉ; with no URL
  it still plays the latest Morning Ireland.

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
