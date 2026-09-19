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
- **Menus open on the last listing and refresh themselves**: a channel's
  listing takes tens of seconds, so a menu shows what the previous fetch
  returned and asks the source again behind it - the fresh entries replace
  the menu on screen when they arrive, and `r` asks again. Numbers always
  mean what is on screen. `--list` and playing straight through still ask
  the source, because being current is what those asked for.
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

- Following a feed, playing a playlist or taking several entries from a
  menu prepares the next item while the current one plays: the item after
  this one is resolved and captioned as soon as this one's own preparation
  is done, so every item after the first starts without waiting either.
  Only where mpv resolves the source's URL itself, and only when something
  is being watched.
- Playback no longer waits for the subtitles. Where mpv resolves the
  source's URL itself (YouTube), the resolve and the transcript now happen
  beside the playback: mpv starts as soon as the listing says what to
  play, and the subtitle file is handed to it mid-playback (`sub-add`)
  when it lands. Measured on the video from the report: first frame at
  ~9.4s cold against ~11.5s, ~3.5s on a replay against ~8s, with the
  captions ready before the first frame in both. RTÉ, whose stream URL
  only comes out of the resolve, and `--no-play`/`--save`, which are not
  watching, prepare first exactly as before. A caption failure is now a
  line printed during playback rather than the end of the run. mpv cannot
  take chapters once it is playing, so a first play uses the chapter file
  a previous run left.
- Playing a video again no longer asks YouTube anything. What a resolve
  learned (title, length, when) is written beside the transcript, so a
  replay whose captions are cached skips both the resolve and the listing
  call: measured on a published-captions video, `--no-play` went from 2.6s
  to 0.18s. A caption URL that is not WebVTT is now asked for WebVTT
  instead of costing a second extraction (6.7s when it happened); the
  yt-dlp fallback is still there for what that cannot rescue. Sources whose
  stream URL has to be found first (RTÉ) are resolved as before, and the
  steps that remain say what they are doing (`Resolving:`,
  `Fetching captions:`) instead of waiting in silence.
- A resolve now keeps the stream URLs it found next to the title, and an
  item the cache has them for is handed to mpv as those URLs rather than as
  a page for it to extract: a replay's first frame measured 3.4-3.8s
  against 15-22s with the extraction left to mpv. They are handed over with
  no HTTP headers of ours: YouTube refuses a googlevideo URL asked for with
  the browser headers yt-dlp reports (`HTTP error 400`, reproduced both
  ways) while the same URL plays when mpv sends its own, so the fewer of
  ours on the request, the better. An item the cache has no URLs for - a
  first play, whose resolve is still running - gets the page exactly as
  before, and a stream mpv cannot load falls back to the page on the retry.
- Cached audio, transcripts and subtitles moved under `~/.cache/subcast/<source>/`,
  and saved episodes under `~/Videos/<source>/`, so paths no longer assume
  one show. Existing caches keep working if moved into those directories.
- The CLI takes an optional URL instead of only talking to RTÉ; with no URL
  it still plays the latest Morning Ireland. `--subs` now means "transcribe
  where the source has none" rather than "produce subtitles at all".
- `--list` prints a page of the listing now — the newest 30, or `--limit N`
  — instead of the single entry playback would have stopped at.

- Playback no longer plays 1080p through YouTube's "premium" HLS
  rendition. Subcast's own resolve only ever hands over DASH URLs; the
  format argument mpv extracts with now says the same, so both paths land
  on the same stream. Measured on the video from the report: a height
  filter alone picked itag 616 (1080p, HLS, 4600k) where the DASH formats
  beside it are 399 (AV1, 1417k) and 248 (VP9, 2130k) - 17.25MB to fill a
  30-second buffer against 5.31MB, and on a link YouTube throttles that
  bitrate is the whole wait before the first frame. A replay measured
  4.11s to the first frame against 5.33s on the VP9 format chosen before.
  What a format costs now decides between formats of one height, with the
  codec that gets the same picture out of fewest bytes preferred.
- A run says which of the two things mpv was given. The page URL is
  printed either way, so `Streams: resolved by subcast` against `Streams:
  mpv extracts them from the page` is what tells the paths apart - and
  which one it was is what a run's start-up wait is made of.

### Fixed

- Resume, end-of-file detection and every other mpv property read were
  silently returning nothing: the IPC client read mpv's `error` field as a
  verdict rather than as its value, and every reply mpv gives carries
  `"error": "success"` when it is answering. A run's position was therefore
  never written down, so the resume feature had nothing to resume from, and
  an item watched to the end was never forgotten either. Nothing failed
  visibly - the reads just came back empty, which is also what an
  unavailable property looks like.
- A caption track YouTube refuses is followed by the track it was
  translated from. Translated tracks are the ones YouTube rate-limits
  (HTTP 429) — a video whose detected source language YouTube got wrong is
  offered as a translation into English, and that URL is refused while the
  original answers. Measured on a video from the report: the `en`
  translation answered 429 and `ar-orig`, the track it was translated from,
  gave 696 cues. When every track is refused the message now says so
  ("YouTube is rate-limiting this video's captions") instead of calling
  them empty, which is the difference between trying again later and
  giving up on that video's captions.
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
