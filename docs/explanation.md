# Explanation

Why subcast behaves the way it does. This page discusses the design; for the
tasks, see [how-to guides](how-to.md), and for the facts, see
[reference](reference.md).

## The pipeline

Every run moves through the same stages:

```
sources → media → transcript → segments → artifacts → player
```

A source hands the pipeline a `Media` record: what to play, which captions it
publishes, and its segments. Everything after that is shared, which is why
YouTube chapters and RTÉ clip lists need no separate code paths. Sources are
more than URL handlers bolted onto the side: the differences between them are
confined to that record, and adding one does not touch the segments, artifacts
or player.

Two hooks are found on the source object itself, through
`getattr(source, "caption_file", None)` and `getattr(source, "video_id", None)`;
a module-level function of the same name is invisible to the pipeline. The other
seam is `Media.stream`, which says who resolves the stream URL.

## Who resolves the stream

The two sources differ in one way that everything else follows from:

- **YouTube** is a page: mpv can be handed the page URL and run yt-dlp itself,
  so a resolve can be skipped and playback can start before it finishes. When
  the cache holds the URLs a resolve found, they are handed over instead, with
  mpv's own extraction turned off.
- **RTÉ** is not. Its stream URL only comes out of a resolve, so that one is
  found before anything starts.

That is why `subcast --subs` on an RTÉ episode prepares first and plays second,
while a YouTube video starts as soon as the listing says what to play: the
resolve, the caption download and any transcription run beside the playback,
and the subtitle file is handed to mpv mid-play when it lands. A caption
failure is reported as a line during playback rather than ending the run.

## Playback start and the chapter caveat

There is no runtime command for chapters in mpv, so they must be present at
startup. A run that starts before its subtitles are ready therefore uses the
chapter file a previous run left, and the run that produces the chapters plays
without them.
The segment titles in the terminal block come from subcast itself, so they
appear with the captions.

A first play spends its time on the listing call and on mpv's own stream
extraction, which cannot be moved. A replay spends it on mpv alone, because the
metadata and the stream URLs a resolve learned are cached. Lowering `--quality`
helps here: a smaller stream has less to buffer before the first frame.

## Streams and formats

At one height, formats are ranked by what they cost for the same picture: AV1
first, then VP9, then H.264. Without that ranking a height filter alone lands on
YouTube's 1080p premium HLS rendition, which is several times the bitrate of the
DASH formats beside it.

Subcast does not send HTTP headers to a googlevideo URL. Passing yt-dlp's
reported browser headers as `--http-header-fields` makes YouTube answer HTTP
400 every time, while the same URL plays with no headers at all.

Signed URLs expire, and YouTube's edge refuses a freshly minted one now and
then. A stream mpv cannot load (exit status 2) is fetched again and tried once
more with the page URL, which is the path that always works. Quitting, a bad
option and `Ctrl-C` are not retried.

## Captions and subtitles

Two kinds of subtitles come out of a run, and subcast prefers the cheaper one:

- **Captions a site publishes.** YouTube times its own, so they cost one
  download and no GPU. Automatic (ASR) tracks count, and arrive without a flag.
- **Local transcription.** Sources without captions, such as RTÉ, need
  `--subs`, which downloads the audio once and transcribes it with
  faster-whisper in English with voice-activity filtering.

YouTube offers several tracks per caption, and the one it offers may be a
translation of the video's own language. Translated tracks are the ones YouTube
rate-limits, so the native track behind a translation is kept as a second
candidate and tried before paying for a yt-dlp extraction. When every track is
refused, subcast reports rate limiting rather than claiming the video has no
captions: that is the difference between trying again later and giving up.

Whisper models differ in accuracy and speed. On a mid-range GPU, `small.en`
(about 480 MB) runs at roughly 13 times realtime, so a two-hour episode takes
about nine minutes; `medium.en` and `large-v3-turbo` are better and noticeably
slower. Models download from Hugging Face on first use and stay in that cache.
It also stays idle when a source publishes captions.

## Segments

Segments come from the source. YouTube chapters carry exact start times. RTÉ
publishes only titles and durations, with no offsets, so those are derived: a
clock-titled segment is pinned to its slot, the rest are packed in published
order, and each title is snapped onto the nearest transcript cue that mentions
it, within 180 seconds.

The clip list is the planned running order, which is why a title can appear up
to a couple of minutes early: a bulletin scheduled for 8.35 can go out at 8.37,
and an interview whose title words are never spoken keeps its derived slot.
Interview segments are usually exact.

## How captions are shaped and drawn

Captions are shaped for reading rather than for transcription. The paragraph
Whisper produces is laid out first and then cut at line boundaries, so no cue
spills past two 42-column lines, and each piece gets its share of the cue's
time. A cue with too little time for that, such as fast speech, is left whole
instead of blinking in and out.

In the terminal, subcast draws a fixed five-row block: the segment title in dim
cyan, the line before the current one, dimmed, up to two lines of dialogue in
bright white, and the playback clock. A segment title is marked with `▌`. The
block spans the window, re-wraps when you resize, repaints only when the text
changes, and is cleared on exit.

The block replaces mpv's terminal output for audio playback, because mpv's own
status line cannot be styled and reprints its whole block on every redraw. The
player still keeps its subtitle output and auto-loading off, so the block owns
the bottom rows.

Captions are sized through the terminal's own text sizing protocol, which is why
they can be large in kitty without your font, profile or colour scheme being
touched. The size follows the window: bigger text on a wider window, up to 3x.
Where the terminal cannot render scaled text, subcast says so and stays at
normal size.

## Resume

Positions are keyed by the item rather than by the stream URL, because signed
URLs change every run and a hash of one would never match. An item watched to
the end forgets its position instead of resuming at the credits, `--no-resume`
starts over, and an item of unknown length, such as a live stream, never keeps
one.

## mpv integration

Subcast drives mpv over its IPC socket. Two mpv behaviours are worth knowing
if you read the code:

- Every reply carries an `error` field whose value is `"success"` when mpv is
  answering. Read the value, not the field: treating the field as a verdict
  makes every property read look empty, which is also what an unavailable
  property looks like, so resume and end-of-file detection fail silently.
- `cache-speed` measures what mpv chose to fetch, not what the link can do, so
  a bitrate policy cannot be sized on it. `paused-for-cache` is the honest
  signal that a stream cannot keep up.

## Privacy, licence and legal

Captions are generated on your machine. Nothing is uploaded and no analytics
are collected. Whisper models come from Hugging Face and stay in your Hugging
Face cache.

Subcast is not affiliated with RTÉ or YouTube, and not endorsed by either.
Audio and video are fetched from their public endpoints, so respect their terms
of use, YouTube's in particular, and do not hammer the service. The project
ships no media and no scraped pages, and bundles no downloader: `yt-dlp` is an
optional dependency you install and use on your own responsibility. Subcast is
MIT-licensed; faster-whisper and beautifulsoup4 are MIT, playwright and requests
are Apache-2.0, and mpv is a separate program, executed rather than linked.

## What is next

Local files and arbitrary URLs as sources; podcast RSS feeds alongside saved
YouTube listings; per-source options such as cookies for age-restricted videos.

## Notes for maintainers

- Sources are added on the source object, not beside it: the pipeline looks the
  hooks up with `getattr`, and a module-level function is silently ignored.
  Publish the hook as a method and test that the pipeline reaches it.
- Work that can happen beside playback uses `background.Background` (thread,
  result, carried failure). Subtitles and listing refreshes are the two
  configured uses of it; a second copy of that machinery is not wanted.
- The terminal block keeps its own state: repaint only on change, clear on
  exit, and cap the scale to what the window can hold.
