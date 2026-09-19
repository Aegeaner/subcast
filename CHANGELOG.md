# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Source abstraction: local files, arbitrary URLs, and YouTube (videos and
  playlists) alongside RTÉ, preferring published captions over transcription
  when a source provides them.

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

[Unreleased]: https://github.com/Aegeaner/subcast/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Aegeaner/subcast/releases/tag/v0.1.0
