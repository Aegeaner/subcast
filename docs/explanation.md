# Explanation

Why subcast behaves the way it does. For the tasks, see the
[how-to guides](how-to.md); for the facts, the [reference](reference.md).

## The pipeline

Every run moves through the same stages:

```
sources → media → transcript → segments → artifacts → player
```

A source turns a URL into a `Media` record: what to play, which captions the
site publishes, and what the item's segments are. Everything after that is
shared, so YouTube chapters and RTÉ clip lists need no separate code paths, and
adding a source does not touch the segments, the artifacts or the player.

A YouTube channel and an RTÉ programme are both listing URLs. Point subcast at
either and it plays the newest item, lists the rest, and can save the listing as
a feed. A programme's name and schedule come from its own page, so the same code
covers a show that has been on air for decades and one that started last week.

Three capabilities are looked up on the source object itself, with
`getattr(source, "caption_file", None)`, `getattr(source, "video_id", None)` and
`getattr(source, "listing_title", None)`; a module-level function of the same
name is invisible to the pipeline. The other seam is `Media.stream`, which says
who resolves the stream URL.

## Who resolves the stream

The two sources differ in one way, and most other differences follow from it.

- **YouTube is a page.** mpv can be handed the page URL and run yt-dlp itself,
  so subcast skips its own resolve and starts playback before it finishes. When
  the cache holds the URLs a resolve found, those are handed over instead, with
  mpv's own extraction off.
- **RTÉ is not.** Its stream URL only comes out of a resolve, so subcast finds
  it before anything starts. RTÉ also stitches ads in per request, so a stream
  fetched for playback is not the audio that was transcribed. A captioned
  episode is therefore played from that file, the only audio its captions can be
  in pace with, and the same length the segments are placed against. A run with
  nothing to caption streams as usual.

So `subcast --subs` on an RTÉ episode prepares first and plays second, while a
YouTube video starts as soon as the listing says what to play: a YouTube run
resolves, downloads captions and transcribes beside the playback, and hands the
subtitle file to mpv mid-play when it lands. A caption failure is reported as a
line during playback, not as the end of the run.

## Playback start and the chapter caveat

mpv has no runtime command for chapters, so they must be present when it starts.
A run that begins before its subtitles are ready uses the chapter file a
previous run left; the run that produces the chapters plays without them. The
segment titles in the terminal block come from subcast itself, so they appear
with the captions.

A first play spends its time on the listing call, the resolve and the
transcript. A replay resolves again, because a stream URL is found rather than
kept, and reuses the transcript. Lowering `--quality` helps a video here: a
smaller stream has less to buffer before the first frame.

## Streams and formats

At one height, YouTube's formats are ranked by what they cost for the same
picture: AV1 first, then VP9, then H.264. Without that ranking a height filter
lands on YouTube's 1080p premium HLS rendition, which is several times the
bitrate of the DASH formats beside it.

A broadcast is the exception and has nothing to rank. It is HLS and nothing
else, while it airs and after it ends, so a request that keeps yt-dlp off HLS
matches none of its formats and comes back as `Requested format is not
available`. Subcast therefore asks for the best format the broadcast has as
well, after the filtered request.

Subcast sends no HTTP headers to a googlevideo URL: passing yt-dlp's reported
browser headers as `--http-header-fields` makes YouTube answer HTTP 400 every
time, while the same URL plays with none.

Signed URLs expire, and YouTube's edge refuses a freshly minted one now and
then. When mpv cannot load a stream (exit status 2), subcast fetches it again
and tries once with the page URL, which is the path that always works. Quitting,
a bad option and `Ctrl-C` are not retried.

## Captions and subtitles

Two kinds of subtitles come out of a run, and subcast prefers the cheaper one.

- **Captions a site publishes.** YouTube times its own, so they cost one
  download and no GPU. Automatic (ASR) tracks count and need no option.
- **Local transcription.** Sources without captions, such as RTÉ, need `--subs`.
  Subcast downloads the audio once and transcribes it with faster-whisper in
  English, with voice-activity filtering.

The caption YouTube offers may be a translation of the video's own language, and
translated tracks are the ones YouTube rate-limits. Subcast keeps the native
track behind a translation as a second candidate and tries it before paying for
a yt-dlp extraction. When every track is refused it reports rate limiting rather
than claiming there are no captions, because that is the difference between
trying again later and giving up.

`small.en` is the default model and runs well ahead of playback; `medium.en` and
`large-v3-turbo` are more accurate and noticeably slower. Models download from
Hugging Face on first use and stay in that cache, and stay idle when a source
publishes captions.

## Segments

YouTube chapters carry exact start times. RTÉ publishes titles and durations
only, so a segment's place is derived from the clip list and then found in the
transcript, in one of two ways depending on what its title says.

A clock-titled segment names a slot in the programme's schedule ("8am News
Bulletin" on a show that airs from 07:00). Subcast pins it to that slot, packs
the segments between two slots in published order, and moves each title onto the
nearest place in the transcript where it is said. The hour comes from the
programme's own page, so a programme that airs at another time, or states no
schedule, is never pinned to the wrong hour.

The clock times also say what kind of clip list this is. Titles that carry them
are the running order of a programme aired to a schedule: a segment is refined
onto the mention of its title and keeps its place, because it cannot have
happened anywhere but its slot. Titles that carry none are a menu of highlights,
published in whatever order the site listed them, so each segment is placed at
the mention of its own title and the list follows the transcript. RTÉ's clips
for one programme were published in an order the broadcast did not use, and
placing them by proportion put them minutes from the words they name.

A title whose words are never spoken keeps its derived position and its place:
nothing in the episode says where it belongs. Otherwise the placement is close,
because in a running order the clip list is the plan rather than the record. A
bulletin scheduled for 8.35 can go out at 8.37, and an interview's title words
usually land within a minute of its slot.

## How captions are shaped and drawn

Captions are shaped for reading rather than for transcription. Subcast lays out
the paragraph Whisper produces, then cuts it at line boundaries, so no cue
spills past two 42-column lines and each piece gets its share of the cue's time.
A cue with too little time for that, such as fast speech, is left whole instead
of blinking in and out.

In the terminal, subcast draws a fixed five-row block: the segment title in dim
cyan, the line before the current one dimmed, up to two lines of dialogue in
bright white, and the playback clock. A segment title is marked with `▌`. The
block spans the window, re-wraps when you resize, repaints only on change, and
is cleared on exit.

Subcast draws that block rather than letting mpv print, because mpv's status
line cannot be styled and reprints its whole block on every redraw. The player
keeps its subtitle output and auto-loading off, so the block owns the bottom
rows.

Captions are sized through the terminal's own text sizing protocol, so they can
be large in kitty without your font, profile or colour scheme being touched. The
size follows the window, up to three times the font. Where the terminal cannot
render scaled text, subcast says so and stays at normal size.

## Broadcasts

A live item is the one that cannot be treated as a file, and three things
follow.

- **There is nothing finished to transcribe.** `yt-dlp -f bestaudio` on a
  broadcast downloads until the stream stops, so the transcription would only
  begin then. Captioning it means working while it airs.
- **Its captions cannot be fetched either.** Where YouTube captions one, the
  track is an HLS playlist of WebVTT segments that grows with the stream: a
  manifest, not a file. Subcast reads files, so a broadcast gets subtitles only
  when the run asks for transcription, which is why `wants_subtitles` answers
  for a live item from the options alone.
- **Most publish no captions at all.** The looping streams and the 24-hour
  channels have no track.

`Media.live` is what a source marks such an item with, and captioning it is a
job rather than a file. `Capture` reads the broadcast through yt-dlp again, at
the cheapest format carrying sound, and cuts it into five-second chunks. What is
heard is appended to `<id>.live.srt`, a file of its own so that partial captions
are never mistaken for the transcript of the video the broadcast becomes.

Four things are kept apart, because doing them together is what made captions
come and go.

- **A chunk is its number, not its place in a listing.** Files are deleted as
  they are heard, so a listing shifts under its own cursor. Walking by position
  dropped every second chunk of one broadcast.
- **Placement is settled when a chunk closes**, from mpv's reading edge, and
  carried until the chunk is heard. A transcriber a minute behind then costs a
  minute of delay instead of captions at a moment the broadcast has gone past.
  A queue longer than three chunks drops the oldest and says so once.
- **What is left unheard of a chunk is heard again in front of the next one**,
  cut where the captions stopped rather than at a fixed overlap, so a sentence
  across the join is not handed to the model in halves. A cue placed before that
  cut is dropped, as is anything from the last second and a half of a chunk.
- **Nothing waits on a chunk boundary.** A pass is heard as soon as a chunk
  closes, and what it adds is written at once. A caption's delay is that one
  chunk, which must fit inside mpv's buffer.

**Where a cue belongs is mpv's to say.** Its `demuxer-cache-time` is the audio
being captured at that moment, so a chunk that closed now began one chunk-length
behind that reading. Timing a live cue from the playback position instead would
put every one a buffer's worth early, because mpv plays a broadcast behind the
publisher's live edge. While mpv fills its buffer at the start of a run it reads
faster than the broadcast is published, so subcast ignores readings that outrun
the clock.

The hearing is greedy, with one beam, and runs without the voice filter an
episode gets, which drops whole sentences and cuts the fronts off words. Without
it the model invents over music, as the same sentence cue after cue, so a loop
guard keeps only the first of a run. Deliberately not `temperature=0`, which
reads like the safer choice and repeats itself more.

The cost is one more extraction of the stream beside mpv's own, which `--subs`
already costs on a video, and one chunk on disk at a time. A run turns mpv's
logging down to warnings for the player module only, because every subtitle
reload makes mpv log its whole track list; turning every module down would take
the terminal's subtitles with it.

Pausing, or seeking back into the DVR window, leaves the captions where they
were: they are placed on the broadcast's own timeline, and only watching at the
live edge keeps them lined up.

Two options are refused on a broadcast rather than quietly doing the wrong
thing: `--save`, because there is no end to download up to, and `--no-play`,
because captions made while it airs cannot be made without it.

## Resume

Positions are keyed by the item rather than by the stream URL, because signed
URLs change every run and a hash of one would never match. An item watched to
the end forgets its position instead of resuming at the credits. `--no-resume`
starts over, and an item of unknown length, such as a live stream, never keeps a
position.

## mpv integration

Subcast drives mpv over its IPC socket. Two mpv behaviours are worth knowing if
you read the code.

- Every reply carries an `error` field whose value is `"success"` when mpv is
  answering. Read the value, not the field: treating the field as a verdict
  makes every property read look empty, which is also what an unavailable
  property looks like. Resume and end-of-file detection then fail silently.
- `cache-speed` measures what mpv chose to fetch, not what the link can do, so a
  bitrate policy cannot be sized on it. `paused-for-cache` is the honest signal
  that a stream cannot keep up.

## Privacy, licence and legal

Captions are generated on your machine: nothing is uploaded, and no analytics
are collected. Whisper models come from Hugging Face and stay in your Hugging
Face cache.

Subcast is not affiliated with RTÉ or YouTube, and not endorsed by either. Audio
and video are fetched from their public endpoints, so respect their terms of
use, YouTube's in particular, and do not hammer the service. The project ships
no media and no scraped pages, and bundles no downloader: `yt-dlp` is an
optional dependency you install and use on your own responsibility. Subcast is
MIT-licensed; faster-whisper and beautifulsoup4 are MIT, playwright and requests
are Apache-2.0, and mpv is a separate program, executed rather than linked.

## What is next

Local files and arbitrary URLs as sources; podcast RSS feeds alongside saved
YouTube listings and RTÉ programmes; per-source options such as cookies for
age-restricted videos; and following a broadcast's own live caption playlist,
which needs no GPU but the same growing-subtitle plumbing a broadcast's captions
already have.

## Notes for maintainers

- Sources are added on the source object, not beside it: the pipeline looks the
  capabilities up with `getattr`, and a module-level function is silently
  ignored. Publish each one as a method and test that the pipeline reaches it.
- Work that can happen beside playback uses `background.Background` (thread,
  result, carried failure). Subtitles and listing refreshes are the two
  configured uses of it, and a second copy of that machinery is not wanted.
- The terminal block keeps its own state: repaint only on change, clear on exit,
  and cap the scale to what the window can hold.
