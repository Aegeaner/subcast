# subcast internals

How subcast works inside, for people changing it. The user-facing contract is
[README.md](README.md); the commands and standards for a change are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## The pipeline

```
sources → Media → transcript → segments → artifacts → player
```

A source hands the pipeline a `Media` record: what to play, which captions it
publishes, and its segments. Everything after that is shared, which is why
YouTube chapters and RTÉ clip lists need no separate code paths.

Two seams are easy to get wrong:

- **Source hooks live on the source object.** The pipeline finds them with
  `getattr(source, "caption_file", None)` and
  `getattr(source, "video_id", None)`. A module-level function of the same name
  is invisible and fails silently.
- **`Media.stream` says who resolves the stream URL.** True (YouTube): a
  resolve can be skipped and playback can start on the page URL, with mpv
  running yt-dlp itself — or, when the cache holds the URLs a resolve found, on
  those URLs with `--ytdl=no`. False (RTÉ): `source.resolve()` finds a signed
  stream URL and playback cannot start without it. `cli.plays_while_preparing`
  and `cli.meta` hang off this.

Prepared work runs beside playback through `background.Background` (thread,
result, carried failure). Subtitles (`PendingSubtitles`) and listing refreshes
(`listing.Refresh`) are configured uses of it.

## Streams and formats

- `meta.CODEC_SCORES` decides between formats of one height: AV1 is the
  cheapest bytes for the same picture, then VP9, then H.264. A bare
  `bestvideo[height<=N]` lands on YouTube's 1080p premium HLS rendition;
  `[protocol^=https]` gets the DASH formats. `--ytdl-format` on mpv's command
  line beats the user's `mpv.conf`, so what subcast passes is what is played.
- **Do not send headers to a googlevideo URL.** Passing yt-dlp's reported
  `http_headers` as `--http-header-fields` makes YouTube answer HTTP 400 every
  time; the same URL plays with none, which is what `stream_arguments` does.
- Exit status 2 means "the file could not be played" (`player.LOAD_ERROR`) and
  is retried once with the page URL instead of resolved streams; 4 means mpv
  quit on a signal. Quitting, a bad option and Ctrl-C are not retried.
- `keep-open=yes` leaves mpv paused at end of file instead of exiting:
  `eof-reached` is what says playback finished.
- Every mpv reply carries an `error` field whose value is `"success"` when mpv
  is answering. Read the value, not the field — treating the field as a verdict
  made `Ipc.get` return None for every property and silently turned resume,
  `eof-reached` and mute into no-ops.

## Segment placement

`segments.py` places what the source published:

1. Exact starts (YouTube chapters) are taken as given.
2. Derived ones (RTÉ) pin clock-titled segments to their slot, pack the rest in
   published order, and snap each title onto the nearest transcript cue that
   mentions it (within 180s).

Caveat: the clip list is the *planned* running order. A bulletin scheduled for
8.35 can go out at 8.37, and an interview whose title words are never spoken
keeps its derived slot, so a title can appear up to a couple of minutes early.
Interview segments are usually exact.

## Captions

- `youtube.as_vtt` rewrites a caption URL to `fmt=vtt`, which keeps a second
  extraction out of the run.
- `youtube._choose_captions` returns the native track behind a translation as a
  second candidate; `subtitles.fetch_captions` tries candidates in order before
  paying for the yt-dlp fallback, and a 429 is reported as rate limiting rather
  than as empty captions.
- Captions are shaped for reading: the paragraph Whisper produces is laid out
  first and then cut at line boundaries, so no cue spills past **two 42-column
  lines**, and each piece gets its share of the cue's time. A cue with too
  little time for that (fast speech) is left whole instead of blinking in and
  out. A segment title rides above the dialogue marked with `▌`.
- The terminal block is `captionbar.py`: a fixed five rows (title, the line
  that just finished, two lines of dialogue, the clock), a scale step of 45
  columns capped at 3x, and a repaint only when the text changes.

## Whisper

`--subs` downloads the audio once and transcribes it with faster-whisper,
English, voice-activity filtered. Model sizes and speed on a mid-range GPU:
`small.en` (~480 MB, about 13x realtime, so ~9 minutes for a two-hour show) is
the default; `medium.en` and `large-v3-turbo` are better but noticeably slower.

## mpv configuration

subcast plays through the mpv you already have. It passes the flags each mode
needs and leaves the rest of your `mpv.conf` alone, so nothing here is required
— a stock mpv works. These are the options that do change how subcast behaves:

| Option | What it changes | Suggestion |
| --- | --- | --- |
| `keep-open`, `keep-open-pause` | At the end of a video, subcast asks mpv whether playback reached the end (`eof-reached`) to decide whether the position is finished with. `keep-open=yes` leaves mpv paused at the end instead of exiting, which subcast handles as well: `q` quits, and the position is dropped either way. | either |
| `save-position-on-quit`, `watch-later-*` | mpv's own resume. subcast remembers positions itself, keyed by the item rather than by the stream URL (signed URLs change every run, so mpv's hash never matches), and passes `--start` at launch. Leaving mpv's version on means two answers to the same question. | off |
| `cache-pause-initial`, `cache-pause-wait` | How long mpv waits for its buffer to fill before the first frame. This is the wait at the start of playback: measured on a 1080p video, generous settings cost about a third of a second, not seconds — the picture itself takes longer to arrive than the buffer does. | `no` / small, if you want the fastest start |
| `cache-secs`, `demuxer-hysteresis-secs` | How much is buffered ahead. Deeper buffers ride out a poor connection; shallower ones start sooner and recover sooner after a stall. | yours to judge |
| `ytdl`, `ytdl-format` | subcast sets both for anything it streams (the format is capped by `--quality`), so a global setting only applies to videos you play outside subcast. | yours |
| `sub-auto`, `term-osd`, `term-status-msg` | Also set per run: the terminal captions turn mpv's own subtitle output and status line off, so the block keeps the bottom rows to itself. | yours |

`cache-speed` (the same as `demuxer-cache-state/raw-input-rate`) measures what
mpv chose to fetch, not what the link can do — with on-demand caching it reads
at the stream's own bitrate. Do not size a bitrate policy on it;
`paused-for-cache` is the honest "this stream cannot keep up" signal.

## Files that are the user's, not the repo's

`$XDG_CACHE_HOME/subcast/<source>/` holds `<id>.cues.json` and
`<id>.segments.json` (what makes a replay cheap), `<id>.meta.json` (title,
length and when a resolve learned them; 30-day TTL), `<id>.position` (resume),
and the `<id>.srt` and `<id>.chapters.txt` that are rendered from the kept
files on every run. `listings/<hash>.json` is a menu's listing, kept for a
week. `$XDG_CONFIG_HOME/subcast/feeds.json` is the user's own list.

## Testing

`pytest` is offline by design: every test fakes the network. A test that needs
yt-dlp, YouTube, Playwright or mpv does not belong in the suite — prove those
with a throwaway harness under `/tmp` and say what it measured. Lint with
`uvx ruff==0.16.8 check src tests`; the `ruff` on `PATH` in a checkout is older
and reports less. Do not run `ruff format`: this codebase is hand-formatted.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the rest.
