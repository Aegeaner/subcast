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

A YouTube channel, a BBC programme page and an RTÉ programme are all listing
URLs. Point subcast at one and it plays the newest item, lists the rest, and can
save the listing as a feed. A programme's name and schedule come from its own
page, so the same code covers a show that has been on air for decades and one
that started last week.

A podcast feed is a listing and an episode list in one document, which is why it
needs no separate resolve: every item states the audio it plays and how long it
runs.

Three capabilities are looked up on the source object itself, with
`getattr(source, "caption_file", None)`, `getattr(source, "video_id", None)` and
`getattr(source, "listing_title", None)`; a module-level function of the same
name is invisible to the pipeline. The other seam is `Media.stream`, which says
who resolves the stream URL.

## Sources, listings and items

A **source** is a pipeline for one site: how a URL's items are listed, and how
one of them becomes something playable. `youtube`, `rte`, `bbc`, `bloomberg`,
`acast` and `podcast` are the sources. The URL decides which one a run uses -
hosts and path shapes do not overlap - so the choice is never the user's.

A **listing** is a URL that points at items: a channel, a playlist, a programme,
a series, a category, or a podcast feed. One source lists many of them, and the
word a site uses for its own kind stays with the site: RTÉ and the BBC publish
*programmes*, YouTube publishes *channels* and *playlists*, and an RSS document
is a *feed*. None of that is a layer of the code, because nothing downstream
asks what kind of listing produced an item - it asks the item, whose
`Media.stream`, `Media.kind` and `Media.live` say who resolves it, what plays
and whether it is a broadcast.

A **feed**, as `--feed` and `--feeds` mean it, is a listing the user saved: a URL
with the name it is asked for by. That name is the whole of how a feed is
addressed, so a name that already means another URL is refused rather than
replaced, and the list of feeds says which source reads each one. One name is
looked for by a run with no URL - `morning`, which is Morning Ireland - and it is
a feed in the file like any other: a machine with no feeds file is written it
once (`feeds.seed`), and it can be renamed or removed like the rest.

## Who resolves the stream

Sources differ in one way, and most other differences follow from it.

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
- **A feed needs no resolve.** Every item a podcast feed publishes states what
  playing it needs, so an item is played as the listing gave it and the audio
  goes to mpv directly. Bloomberg reaches that state by another route: its own
  series pages refuse anything that is not a browser, so the show is read as the
  feed its host publishes. Acast reaches it from either end: its own page for a
  show links that show's feed, and a publisher's page names the show in the audio
  its cards carry. BBC Audio reads a listing from the page's own payload and the
  audio from the version the programme's JSON names, which is the syndication
  every podcast client is served - and of the versions a programme lists, that is
  the one published for download.

Captions are made while the item plays, and what is written as they are heard
is the subtitle file mpv reads again each time it grows. The model hears far
faster than audio plays, so each cue is written as soon as the words after it
have been heard and stays ahead of the picture.

What the captions belong to is the copy of the item that plays, and that is what
the run arranges: an item whose URL serves the same bytes to every request is
heard from the stream itself, a span at a time, while the player reads it
(`subtitles.StreamedWhilePlaying`), so nothing is downloaded before the first
frame. A site that answers a different length to a second request - an ad
stitched into one of them - is downloaded whole first, and heard from the file
(`subtitles.HeardWhilePlaying`): captions timed against one copy of an item
cannot be in pace with another.

A broadcast is the same idea with the audio arriving in real time
(`live.LiveCaptions`), and both present it the same way: the player hands the
file to mpv once and reloads it whenever the source says there is more. A
YouTube video skips even the audio: mpv is handed the page URL and resolves it
while the download happens behind. A caption failure is reported as a line
during playback, not as the end of the run.

Only a transcript that was heard to the end is cached. A run that ends first
keeps the captions it heard and caches nothing, so the next run hears the file
again rather than play against a transcript of part of an episode.

The audio has to be the same copy for both, because a site can serve a different
one each time: RTÉ stitches ads in per request, and Bloomberg's host serves a
file with ads round the content. A transcript timed against one copy is out of
pace with another - the transcript Omny publishes for an episode ran a sentence
ahead of the audio its enclosure served - which is why captions come from
hearing the audio this run fetched, and why a transcript a feed publishes is not
used.

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
  Subcast hears the audio with faster-whisper in English, with voice-activity
  filtering, either from the stream while it plays or from a copy downloaded
  first when the stream cannot be trusted to be one copy.

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
spills past two 42-column lines and each piece gets its share of the cue's time,
and the block draws those pieces rather than the paragraph they came from. A cue
with too little time for that, such as fast speech, is left whole instead of
blinking in and out.

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
job rather than a file. `Capture` reads the playlist the player is reading - the
same rendition, because captions timed against one copy of a broadcast cannot be
in pace with another - and takes the pieces it names one at a time. What is
heard is appended to `<id>.live.srt`, a file of its own so that partial captions
are never mistaken for the transcript of the video the broadcast becomes.

A piece at a time rather than a pipe is what lets the capture outlive the
broadcast. A pipe has to keep reading for hours, and the first read error ends
the captions for the rest of the run; a piece is a bounded request that can be
retried, skipped, or taken again from a playlist that has been resolved a second
time, because the URL a broadcast is published under expires long before the
broadcast does. It is also the only way to know where a piece belongs: the
playlist says how long each one is and when the first of them aired.

Four things are kept apart, because doing them together is what made captions
come and go.

- **A piece is its number, not its place in a listing.** Files are deleted as
  they are heard, so a listing shifts under its own cursor. Walking by position
  dropped every second piece of one broadcast.
- **Placement is settled when a piece closes**, from where the player says it
  has read up to, and carried until it is heard. A transcriber a minute behind
  then costs a minute of delay instead of captions at a moment the broadcast has
  gone past. A queue longer than three pieces drops the oldest and says so once.
- **A piece is heard with the tail of the one before it**, so the model is not
  left to make out a sentence from its middle. The line it makes of those words
  and the piece together is cut where the captions stopped, word by word,
  because dropping the line would lose the words it ends with. The last of a
  piece waits for the pass that hears its ending.
- **Nothing waits on a piece boundary.** A pass is heard as soon as a piece
  closes, and what it adds is written at once. A caption's delay is that one
  piece, which must fit inside mpv's buffer.

**Where a cue belongs is what the player says.** A piece of a broadcast carries
no clock a run can read: the audio of a YouTube live stream comes down as raw
ADTS AAC, whose first timestamp `ffprobe` answers `N/A` for, so nothing in the
stream says when a piece aired. The one thing that knows where the broadcast is,
is the player reading it, so a piece is placed where mpv's reading edge was when
it closed - a reading carried back along the wall clock, because between
readings the edge moves with it. Placing from the reading edge puts a cue a
little before the words, by as much as the edge lags the publisher's live edge,
which is what a listener sees as captions running early. A cue timed from the
playback position instead would be worse: the player is a whole buffer behind
the edge, so those captions would be that much later than the words.

The hearing is greedy, with one beam, and nothing is heard through a voice
filter. Asking the model to drop what is not speech and put the timestamps back
afterwards reads like a way to hear a broadcast more cheaply, and measured it
drops speech: on three minutes of a music-heavy channel, over half the words a
filterless pass heard had no cue over them, and on ten minutes of an episode it
kept no more words than the filter and cost no less time. What a model writes
over music is kept out by what it says instead: a note about the soundtrack is
not a caption, and a line it repeats is a line it invented, so a loop guard
keeps only the first of a run and refuses a line the pass before it has just
said. Deliberately not `temperature=0`, which reads like the safer choice and
repeats itself more.

The cost is one more extraction of the stream beside mpv's own, which `--subs`
already costs on a video, and one piece on disk at a time. A run turns mpv's
logging down to warnings for the player module only, because every subtitle
reload makes mpv log its whole track list; turning every module down would take
the terminal's subtitles with it.

Pausing, or seeking back into the DVR window, leaves the captions where they
were: they are placed on the timeline the player reads the stream against, and
only watching at the live edge keeps them lined up.

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
- The window title is built from `media-title`, which defaults to what play was
  handed - a page URL, or the signed link a resolve found. Subcast forces the
  item's name onto that property instead of setting `title`, so the window names
  the episode and a user's own `title` template still formats it.
- mpv's on-screen controller is the title bar of a window the compositor does
  not decorate, and a compositor can decline to decorate one: GNOME on Wayland
  advertises no `xdg-decoration`, and mpv draws no decoration of its own. The
  controller also hides as soon as the mouse stops moving, which would take the
  item's name off screen with it, so a run keeps it up - unless `--osc` asks for
  mpv's own behaviour, or for no controller at all.
- The controller is drawn at sizes mpv keeps for itself, and `osd-font-size` is
  not what scales it: `osc-scalewindowed` and `osc-scalefullscreen` are, one for
  each kind of window, so a run asks for both. Its caption-sized text is read at
  a glance, which is why the captions a window draws are asked for bigger too.
- The captions mpv draws over the picture are sized by `sub-font-size`, whose
  default suits a stray subtitle rather than a run opened for its captions, so a
  window run asks for a size of its own. The terminal paths draw their captions
  in the terminal's font, where mpv's size says nothing.

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

Local files and arbitrary URLs as sources; an `--rss` surface for podcast feeds,
which play by URL today; per-source options such as cookies for age-restricted
videos; and following a broadcast's own live caption playlist, which needs no
GPU but the same growing-subtitle plumbing a broadcast's captions already have.

## The shell

A run with no arguments opens a shell, and a shell is only worth having if a
command cannot mean anything the command line does not: `/feed bbcnews` is
translated into `--feed bbcnews --pick --subs` and parsed by the same parser,
so the listings, the picker, the captions and the player are the ones that were
already there, and a command cannot drift away from them
(`shell.feed_arguments`).

What the shell adds is a lifetime. A command line is one run and one ending, so
a failure there is the process's; a shell is a session, so the same failure is
one command that did not work - a URL nothing reads, a feed that does not
answer, a parse the options refuse - and the prompt comes back for the next one.
Nothing a command does ends the shell.

Ctrl-C is where that shows. In a session, Ctrl-C means "stop what you are
doing", so playback stops - the player terminates mpv and clears the caption
block on the way out, which is why the prompt that follows it is the prompt
that was there before - and the shell reads the next command. A `SIGTERM` is
the process being told to go away, so it arrives as its own exception
(`cli.Stopped`) and is not caught: a shell that is told to leave leaves. The
one thing Ctrl-C cannot be, in a shell, is an exit; `/quit` and Ctrl-D are.

Every argument on the command line is still a run. A bare `subcast` used to
play the newest Morning Ireland, and that is what `/feed` opens now; a script
asks for it with `--no-pick`, because a flag is a request for something and the
shell is what a request for nothing looks like.

## Notes for maintainers

- Sources are added on the source object, not beside it: the pipeline looks the
  capabilities up with `getattr`, and a module-level function is silently
  ignored. Publish each one as a method and test that the pipeline reaches it.
- Work that can happen beside playback uses `background.Background` (thread,
  result, carried failure). Subtitles and listing refreshes are the two
  configured uses of it, and a second copy of that machinery is not wanted.
- The terminal block keeps its own state: repaint only on change, clear on exit,
  and cap the scale to what the window can hold.
