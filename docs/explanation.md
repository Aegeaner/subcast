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

A YouTube channel and an RTÉ programme are both listing URLs, and neither is
special: pointing subcast at either plays the newest item, lists the rest and
can be saved as a feed. What a programme knows about itself is read from its
own page - its name, and when it airs - rather than from a constant about one
programme, which is why the same code covers a show that has been on air for
decades and one that started last week.

Three hooks are found on the source object itself, through
`getattr(source, "caption_file", None)`, `getattr(source, "video_id", None)`
and `getattr(source, "listing_title", None)`; a module-level function of the
same name is invisible to the pipeline. The other seam is `Media.stream`,
which says who resolves the stream URL.

## Who resolves the stream

The two sources differ in one way that everything else follows from:

- **YouTube** is a page: mpv can be handed the page URL and run yt-dlp itself,
  so a resolve can be skipped and playback can start before it finishes. When
  the cache holds the URLs a resolve found, they are handed over instead, with
  mpv's own extraction turned off.
- **RTÉ** is not. Its stream URL only comes out of a resolve, so that one is
  found before anything starts. It also does not serve the same audio twice:
  ads are stitched in per request, so fetching the stream again for playback
  gets different audio from the file that was transcribed. A captioned episode
  is therefore played from that file - the only audio its captions can be in
  pace with, and the same length the segments are placed against - while a run
  with nothing to caption streams.

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

A first play spends its time on the listing call, on the resolve and on the
transcript; a replay spends it on the resolve again - a stream URL is found, not
kept - and on mpv's own stream extraction, which cannot be moved. Lowering
`--quality` helps a video here: a smaller stream has less to buffer before the
first frame.

## Streams and formats

At one height, formats are ranked by what they cost for the same picture: AV1
first, then VP9, then H.264. Without that ranking a height filter alone lands on
YouTube's 1080p premium HLS rendition, which is several times the bitrate of the
DASH formats beside it.

A broadcast is the exception, and has nothing to rank: it is HLS and nothing
else, while it airs and after it ends, so a request that keeps yt-dlp off HLS
matches none of its formats and comes back as `Requested format is not
available`. Subcast asks for the best format the broadcast has as well, after
that filtered request, so a broadcast plays and a video still plays from its
DASH formats.

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
publishes titles and durations only, with no offsets, so a segment's place is
derived from the clip list and then found in the transcript - in one of two
ways, depending on what its title says.

A slot is only a slot in a programme that publishes a schedule, which is why
the hour comes off the programme's own page (`Media.clock_start`) instead of
out of the code. Morning Ireland's clip titles name clock times ("8am News
Bulletin"), and its page says it airs `Mon - Fri • 07:00 - 09:00`; a programme
whose clips name no clock time, or whose page states no schedule, has its
clips packed across the episode instead - never pinned to another programme's
hour.

The clock times also say which kind of clip list this is. Titles that carry
them are the running order of a programme aired to a schedule, so a segment is
only refined onto the mention of its title - it cannot have happened somewhere
else than its slot - and it keeps its place in the list. Titles that carry none
are a menu of highlights published after the broadcast, in whichever order the
site listed them, so each segment is placed at the mention of its own title,
wherever in the episode that is, and the list follows the transcript: RTÉ's
clips for one programme were published in an order the broadcast did not use,
and by proportion they were minutes away from where their words are said, the
error growing with each clip. A title whose words are never spoken keeps its
derived position and its place, which is the honest answer for it - nothing in
the episode says where it belongs.

In a running order the clip list is the plan rather than the record, which is
why a title can appear up to a couple of minutes early: a bulletin scheduled for
8.35 can go out at 8.37. An interview whose title words are never spoken keeps
its derived slot either way. Interview segments are usually exact.

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

## Broadcasts

A live item is the one that cannot be treated as a file, and three things
follow from it:

- **There is nothing finished to transcribe.** A broadcast has no end, so
  `yt-dlp -f bestaudio` on it downloads until the stream stops, and the
  transcription would only begin then. Captioning it means working while it
  airs.
- **Its captions cannot be fetched either.** Where YouTube does caption a
  broadcast, the track it offers is an HLS playlist of WebVTT segments that
  grows for as long as the stream does - a manifest, not a file - and
  subcast's caption fetch reads files. So a broadcast has subtitles only when
  the run asks for transcription (`--subs`, or `--subs-from asr`), which is
  why `wants_subtitles` answers for a live item from the flags alone.
- **It has no captions published for the usual reason.** Most broadcasts -
  the looping streams, the 24-hour channels - have no track at all.

So `Media.live` is what a source marks such an item with, and the captioning
is a job rather than a file. `Capture` reads the broadcast through yt-dlp one
more time, at the cheapest format carrying sound - a live item has no audio-only
format, so that is 144p of muxed HLS whose picture ffmpeg drops - and cuts it
into five-second chunks. What is heard is appended to `<id>.live.srt`, which is
a file of its own on purpose: a broadcast's partial captions must never be
mistaken for the transcript of the video the broadcast becomes.

That same absence decides what `--audio-only` plays: `bestaudio/best` falls back
to the whole 1080p stream for its sound (5421k against 144p's 290k, measured on
one broadcast), so a live item is asked for the cheapest format carrying sound
instead.

**Four things are kept apart, because doing them together is what made captions
come and go:**

- **A chunk is its number, not its place in a listing.** The files are deleted
  as they are heard - and the last one is kept to be joined to the next - so a
  listing shifts under its own cursor. Walking by position dropped every second
  chunk of one broadcast: captions in fifteen-second bursts with fifteen
  seconds of nothing between them.
- **Placement is settled when a chunk closes**, from mpv's own reading edge, and
  carried with the chunk until it is heard. A transcriber that is a minute
  behind then costs a minute of delay rather than captions at a moment the
  broadcast has gone past; and a queue longer than three chunks drops the oldest
  and says so once, because for a broadcast being incomplete beats being late
  for good.
- **What is left unheard of a chunk is heard again in front of the next one**,
  cut where the captions stopped rather than at a fixed overlap, so a sentence
  arriving across the join is not handed to the model in halves and the join is
  only as long as the silence it covers. A cue the model places before that cut
  is dropped, and so is anything from the last second and a half of a chunk: the
  audio runs out there, and the next pass hears those words again with the ones
  after them.
- **Nothing waits on a chunk boundary.** A pass is heard as soon as a chunk
  closes (five seconds of broadcast, transcribed in about 0.3s), and the words
  it adds are written straight away. What a caption costs in delay is that five
  seconds, which is what has to fit inside mpv's own ten-to-sixteen seconds of
  buffer - it did not when a chunk was fifteen seconds long, and the first five
  seconds of every one of those was written after the picture had already gone
  past it.

**Where a cue belongs is mpv's to say.** Its `demuxer-cache-time` is the
position mpv has read up to, which is the audio being captured at that moment -
so a chunk that closed now began at that value less the time it took to
record. Mapping through it puts the caption at the words as mpv plays them.
Timing a live cue from the playback position instead would put every one of
them a buffer's worth early, because mpv plays a broadcast some ten to fifteen
seconds behind the publisher's live edge (measured on a live HLS item:
`time-pos` 7716.9 rising with the wall clock while `cache-time` sat 10-15s
ahead of it).

That edge is only a timeline once it keeps time with the clock. While mpv is
filling its buffer at the start of a run it reads faster than the broadcast is
published - 27 seconds of stream in 16 seconds of clock, measured - and placing
a chunk from one of those readings put the first chunk thirteen seconds early,
where mpv had already played past it and nothing showed it.

The hearing itself is greedy (one beam) and, unlike an episode, without the
voice filter. Measured through this pipeline on the same audio: 104 words
against 211 without it, and where the two disagree the filter is usually the
one that is wrong - it drops whole sentences and cuts the fronts off words
("The ants on the slide" heard as "Hands on the slide"). What the filter was
there for is a loop guard instead: over music the model invents, as the same
sentence cue after cue (measured: one line ten times, another twenty-five), and
nobody says the same words twice in five seconds of broadcast, so only the
first of a run is kept. Deliberately not `temperature=0`: it reads like the
safer choice, and measured it is the opposite - 699 words of which 40 cues were
the model repeating itself, against 456 words and 2 repeats with the default
fallbacks left in.

The cost is one more extraction of the stream beside mpv's own, which is what
`--subs` already costs on a video, and a chunk of broadcast kept on disk at a
time - each one is deleted once it has been heard. A run gets mpv's own
logging out of the way while it does this: every subtitle reload makes mpv log
its whole track list (`Reloaded:` and four lines of streams), and a broadcast
reloads every chunk, so `--msg-level=cplayer=warn` is passed with the captions.
Only that module - `all=warn` would take the terminal's subtitles with it -
and warnings and errors still get through.

Pausing, or seeking back into the DVR window, leaves the captions where they
were: they are placed on the broadcast's own timeline, and only watching at the
live edge keeps them lined up with the picture.

Two flags are refused on a broadcast rather than quietly doing the wrong
thing: `--save`, because there is no end to download up to, and `--no-play`,
because captions that are made while it airs cannot be made without it.

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
YouTube listings; per-source options such as cookies for age-restricted videos;
following a broadcast's own live caption playlist where it publishes one, which
needs no GPU but the same growing-subtitle plumbing a broadcast's captions
already have.

## Notes for maintainers

- Sources are added on the source object, not beside it: the pipeline looks the
  hooks up with `getattr`, and a module-level function is silently ignored.
  Publish the hook as a method and test that the pipeline reaches it.
- Work that can happen beside playback uses `background.Background` (thread,
  result, carried failure). Subtitles and listing refreshes are the two
  configured uses of it; a second copy of that machinery is not wanted.
- The terminal block keeps its own state: repaint only on change, clear on
  exit, and cap the scale to what the window can hold.
