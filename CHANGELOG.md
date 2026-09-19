# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Any RTÉ Radio 1 programme**, not only Morning Ireland: a programme page
  is a listing URL the way a YouTube channel is, so
  `subcast https://www.rte.ie/radio/radio1/this-week/` plays its newest
  episode and `--list`, `--pick`, `--limit`, `--save`, `--subs` and
  `--audio-only` work on it unchanged. `--add-feed` saves one under the
  programme's own name, read off its page, and a listing now carries the
  length each episode card states, so a menu shows it before anything is
  resolved.

  Nothing in the code belongs to one programme any more: the schedule a
  clock-titled clip ("8am News Bulletin") is measured against used to be
  `SHOW_START_HOUR = 7` in `segments.py`, and is now read off the programme's
  own page (`Mon - Fri • 07:00 - 09:00`) and carried to `place()` as
  `Media.clock_start`. Morning Ireland's clips are the only ones that name a
  clock time, so every other programme's clips are packed in published order
  across the episode - which is what they were always going to be. The
  programme page's newest episode is linked twice, from the hero card and
  again with its date in the list below, so a listing keys episodes by id and
  keeps the card that names the episode.

- **Live broadcasts** are captioned as they air. A YouTube broadcast has no
  finished audio and usually no captions of its own, so `subcast <live url>
  --subs` takes the audio from the stream itself - yt-dlp's cheapest format
  carrying sound (a live item offers no audio-only one), cut into five-second
  chunks by ffmpeg - and hears each chunk as it closes. Cues are written into
  `<id>.live.srt`, which mpv gets as soon as the first ones are in it
  (`sub-add`) and is told to read again each time it grows (`sub-reload`).

  Where a caption belongs is decided when its chunk closes, from mpv's own
  `demuxer-cache-time` - the position it has read up to, which is the audio
  being captured at that moment - and carried with the chunk until it is heard,
  so a slow machine costs delay rather than captions at a moment the broadcast
  has gone past. Readings that outrun the clock (mpv filling its buffer at the
  start of a run: 27 seconds of stream in 16 seconds, measured) are not a
  timeline, and placing from one put the first chunk 13 seconds early, where
  nothing showed it.

  What is left unheard of a chunk is heard again in front of the next one, cut
  where the captions stopped, so a sentence arriving across the join is not cut
  in half; a cue from the last second and a half of a chunk waits for the next
  pass, which hears it with the words after it, and a cue that starts before
  what was already said is dropped. A pass is heard as soon as its chunk closes
  (five seconds of broadcast in about 0.3s, measured with mpv playing), which
  is what has to fit inside mpv's own ten-to-sixteen seconds of buffer: at
  fifteen-second chunks it did not, and the first five seconds of every chunk
  were written after the picture had gone past them. When transcription cannot
  keep up at all, the oldest waiting chunks are dropped and the run says so
  once. The run ends with what the captions came to (`Live captions: 14
  chunk(s) heard`).

  The partial captions never touch `.cues.json`, so they cannot be mistaken for
  the transcript of the video the broadcast becomes, and `--save`/`--no-play`
  are refused on a broadcast with a line each: there is no end to download up
  to, and captions made while it airs cannot be made without it. A run asked to
  stop - `Ctrl-C`, SIGTERM or SIGHUP - ends the capture with it: the reading and
  cutting run in their own process groups, so dying outright would leave them
  reading a broadcast that nothing is watching. Watching only the sound of one
  asks for the cheapest format carrying it: a live item has no audio-only
  format, so `bestaudio/best` was falling back to the whole 1080p stream
  (5421k against 144p's 290k, measured on the same broadcast).

### Changed

- **A captioned episode plays the audio it was transcribed from.** RTÉ stitches
  ads into an episode per request - the same URL answers with different audio a
  second apart - so a run transcribed one file and mpv streamed another, and
  the captions could never be in pace however the segments were placed. The
  file is what plays now (`cli.playback_url`), the segments are placed against
  its length rather than the length the page states (`subtitles.prepare`), and
  a plain play still downloads nothing and streams.

- **Segment titles land where their words are said.** RTÉ's clip list for a
  programme whose titles name no clock time is a menu of highlights, not the
  running order: five *This Week* clips were placed by proportion at 48, 1038,
  1275, 2260 and 3155 seconds, while their own words are said at 332, 1167,
  1470, 2400 and 3057 - the error growing with each clip, and the last two
  clips having aired in the other order. Each segment is now placed at the
  mention of its own title, the list follows the transcript, and a word the
  whole programme shares can no longer anchor anything
  (`segments.ANCHOR_LIMIT`; that broadcast says "Trump" 81 times). A clip list
  whose titles carry clock times - Morning Ireland's - is still a running
  order, and its 17 segments come out exactly as before.

  The placement is worked out again on every run from the cached transcript,
  so the fix reaches an episode that was transcribed before it: the cached
  *This Week* episode's titles moved onto the passages they name without
  transcribing anything again. The subtitle, segments and chapters files are
  rendered from the transcript, which is the only thing the cache has to keep.

### Fixed

- A quoted word in a clip title kept its apostrophes as a keyword, so
  "'Appalling' - Clare protestors say Trump not welcome" could never match "It
  is appalling that we are spending taxpayers' money" and that segment was
  placed by proportion alone.

- **RTÉ episodes play again.** A listing item said `stream=True`, which is the
  flag for "mpv resolves this URL itself" - true of a YouTube page, never of
  an RTÉ one - so a run handed mpv the episode page: yt-dlp answers
  `Unsupported URL`, mpv exits 2, and nothing played, on Morning Ireland as
  much as on anything else. Both the listing and the resolve now say
  `stream=False`, and `tests/test_cli.py` reads that through
  `cli.plays_while_preparing` rather than through the field.

- **Broadcasts play again.** What subcast asked mpv for kept yt-dlp off
  YouTube's HLS renditions (`[protocol^=https]`), and a broadcast is HLS and
  nothing else - while it airs and after it ends - so the request matched none
  of its formats: `Requested format is not available`, mpv exit status 2, and
  nothing played, live or on a replay of the broadcast. The same request
  without the filter now follows the filtered one, so a video is still played
  from its DASH formats and a broadcast from what it has.

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
