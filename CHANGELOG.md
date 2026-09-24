# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Apple Podcasts shows, and the episodes of them.** A link to
  `podcasts.apple.com` is read as the feed the show is published as, which is the
  URL a podcast client is served, so a show plays from the audio its publisher
  publishes and `--pick`, `--save`, `--subs` and resume work on it as they do on
  any feed. A link to one episode plays that episode rather than the newest one:
  the page states the guid the feed gives it, and the item is found by that guid
  rather than by matching a title against the feed (measured on one show,
  2026-09-23: the guid the page names is the guid the feed carries, and the title
  and length it states are the feed's). Both forms of a link are read - the
  storefront and the slug in the path are optional, and
  `itunes.apple.com/us/podcast/id<n>` is still served - and a link to a channel
  is refused by what it is, because a channel is a group of shows rather than one
  of them.

- **TAB completes a feed's name in the shell.** `/feed bb` finishes into
  `/feed bbcnews`, a name of several words is completed a word at a time, and
  pressing TAB twice lists the names that match. The names are the feeds file
  read when TAB is pressed (`shell.completions`), so a feed kept with `/add` or
  forgotten with `/remove` in the same session is completed by the next TAB with
  no index to keep in step. Nothing else on the line is completed, and the line
  editor is the one `input` already reads with: a platform without one reads
  commands and completes nothing.

- **Acast shows, and The Irish Times podcasts.** A show published on Acast is
  read as the feed it is published as, from either end. `shows.acast.com/<show>`
  is Acast's own page for a show, and it links that feed; the slug in its path is
  not the feed's own name - `inside-politics` is published as
  `inside-politics-2`, `america-2026` as `irish-times-sport` - so the page is
  read rather than the URL rewritten. A publisher's page links nothing: it
  carries its episodes' audio, every card of one show plays from the same Acast
  stream, and that stream's id is the show's, which is how
  `subcast https://www.irishtimes.com/podcasts/in-the-news/` plays the show. A
  page about several shows is refused with the feeds it holds rather than read as
  one of them, and the "listen on" links every page of a site carries name one
  other show, so they are not read either. Both ends are a podcast feed after
  that, so `--list`, `--pick`, `--limit`, `--save`, `--audio-only`, `--subs` and
  resume work as they do for any feed, and the show's episodes are the same items
  whichever end they were reached through.

- **BBC schedules.** `subcast https://www.bbc.com/audio/schedules/<service>`
  lists the programmes a station puts out over a day, from the payload every page
  of the audio site is rendered from: the day is one card's blocks, and an entry
  states the programme it is a slot of, the time it airs and how long the slot
  runs. An entry plays the programme's own on-demand audio, so `--pick`, `--save`
  and `--subs` work as they do on a programme page, and the page names itself
  after its station for `--add-feed`.

- **An mpv window names the item it is playing.** What mpv is handed is a URL -
  the page, or the signed stream link a resolve found - and a window titles
  itself after what it was handed, so a video played from a resolve showed a
  googlevideo URL where its name belongs. The name the run prints is forced onto
  mpv's `media-title`, which the window title is built from, so the episode is
  named rather than the URL, and a user's own `title` setting still formats it.
  Audio is named the same way for the surfaces mpv has that subcast does not,
  the OSD in particular.

### Changed

- **A window keeps naming what it plays, and draws its captions and its own
  controls bigger.** mpv's on-screen controller is the title bar of a window the
  compositor does not decorate, and mpv hides it the moment the mouse stops, so
  the name the run was given went off screen with it; a run now keeps it up
  unless `--osc auto` or `--osc never` asks for something else. The controller is
  drawn at a size of subcast's own rather than the small one mpv keeps for it
  (`osc-scalewindowed` and `osc-scalefullscreen`, not `osd-font-size`), and the
  subtitles mpv draws over the picture are asked for bigger too, because the
  captions are what the item was opened for. Both are appended to `script-opts`
  with `--script-opts-add`, so a user's own settings for other scripts are kept,
  and the terminal paths are unaffected: their captions are drawn in the
  terminal's font, not mpv's.

### Fixed

- **A listing that lands behind the menu leaves only the list it found on
  screen.** The menu redraws itself by walking the cursor up over the rows it
  wrote and clearing from there, and it counted the entries and the question but
  none of the rows the terminal had moved down for it: the echo of an answer,
  the `Refreshing the listing...` line, a `?` for an answer that could not be
  read. Each of those left the erase short, so the head of the old listing
  stayed above the redrawn one, and the numbering on screen named entries the
  menu no longer held. Measured through a model of the terminal on the path from
  the report (2026-09-23: a cached listing, `r` pressed twice while the feed was
  still answering): the old list's first four entries stayed on screen, and
  typing `1` played the new list's first entry. The rows are counted as the menu
  writes them (`picker.Screen`), the echo included, and `picker.erase` returns to
  the start of the line before it clears, so a redraw takes back exactly the rows
  the menu put up.

- **A streamed run's copy of an item is its own, not the last run's with
  this one's written after it.** The bytes fetched for hearing are assembled
  into the file the run keeps, a span at a time, and that file was opened for
  appending. A run that was killed leaves its partial copy behind - a stop
  removes it, a kill does not - so the next run wrote its spans after those
  bytes, and what came out was the item with its own opening stitched into the
  middle of it: a copy a later run plays once it is named like one. Measured on
  two interrupted runs of one programme: one run's 11,356,000 bytes with the
  next run's spans written after them, 16,156,196 bytes. The first span of a
  run now starts the file, and the spans after it append.

- **A long sentence's pieces are drawn when they are said, not spread evenly
  over it.** Whisper hands over sentences, a long one is cut into the pieces a
  caption line holds, and each piece was timed by an equal share of the whole
  cue. Speech is not even - a pause inside a sentence, a phrase said quickly -
  so the second half of a sentence went on screen before or after it was said,
  and 83 of the 270 cues of one 16 minute programme were long enough to be
  split. Measured against the model's own word times over that item: 76 of its
  353 pieces started more than half a second from the word they begin with, the
  worst by 2.4 seconds. The words carry their own timing and the reader asks for
  it now (`subtitles._stream`), so a piece is timed by the words it holds
  (`srt.split_heard`). Asking for it costs nothing measurable over 22 minutes of
  one programme (79 seconds against 78, 3212 of 3294 words identical), and a
  test that fails without it puts a sentence's second piece at 6.67 seconds
  where the words put it at 0.65.

- **A model already on disk is loaded without asking Hugging Face for it.**
  `WhisperModel` asks the Hub about the repository unless it is told not to, and
  when that answer does not come - a rate limit, a link that is down - the load
  never returns: the player plays and the caption block has nothing to draw,
  and nothing says so. Measured: the same model read from disk loads in 0.4
  seconds, and a streamed run sat with an empty block for two and a half
  minutes while its load waited on the Hub. The model is now loaded from disk
  first, and fetched only when it is not there yet.

- **A join between two spans no longer takes the words it runs through with
  it.** An item heard from a stream is decoded a span at a time, and each span
  is fetched from a little before the join so the model is not left to make out
  a sentence from its middle. The line it makes of that overlap and the new
  audio together starts in the overlap, and every cue that started there was
  dropped whole - so the words the line ended with, which were the new audio's,
  went with it, at every join of the item. The line is now cut at the join where
  the captions stopped, word by word, which is how a live pass has always cut a
  piece (`subtitles._heard`, `subtitles.JOINED_HEARING`). A stretch with nothing
  in front of it - a file that was downloaded first, an episode - is heard with
  the settings it was heard with before, so nothing already measured changes.
  Measured on one Radio 4 programme heard end to end (42 minutes, ten spans,
  2026-09-21): words of a whole-file transcript of the same audio that had no
  cue over them within ten seconds of a join, 114 before and 34 after; over the
  whole item, 269 of 6941 words before and 226 after. One join lost a whole
  sentence ("the beginning of Greek philosophical thinking, who clearly was
  also reacting to") and the next began mid-phrase in its place.

- **A broadcast's captions are made from the pieces its playlist names, not
  from a pipe read for hours.** The capture used to run
  `yt-dlp -f worstaudio/worst -o - | ffmpeg -f segment` for the whole
  broadcast: one process that has to survive it, no way to know how long a
  chunk was, and a chunk thrown away whenever mpv had not yet said where it
  was reading. It now resolves the playlist of the same rendition the player
  is given, fetches each new piece of it by its `EXT-X-MEDIA-SEQUENCE`,
  decodes it on its own, and renames it into place when it is whole; a piece
  that will not come down is retried and skipped, and a playlist past the
  expiry its URL carries is resolved again. Measured against a reference
  transcript of the same three minutes of one broadcast (a cartoon channel,
  overlapping 20-second windows, beam 5, no voice filter, times verified
  against the same audio cut into slices), 2026-09-20:

  | | before | after |
  | --- | --- | --- |
  | reference words with no cue over them | 116 of 360 (32%) | 59 of 360 (16%) |
  | cues the reference supports | 55 of 72 (76%) | 70 of 80 (88%) |
  | seconds of cues written | 142s | 111s (the reference's speech: 117s) |
  | listening time for 180s of broadcast | 8.7s | 12.7s |

- **A broadcast's captions are placed by where mpv has read up to, because the
  audio carries no clock it can be placed by.** Placing a piece by its own first
  timestamp assumed the stream says when the piece aired; measured 2026-09-21,
  the pieces of a live item's audio rendition (`worstaudio/worst`, itag 233) are
  raw ADTS AAC, and `ffprobe -show_entries stream=start_time` answers `N/A` for
  every one of them. The first piece therefore could not be placed at all and the
  run was refused with `the broadcast's audio would not say when it aired` - a
  broadcast that had captions before this had none. `live.timestamp_of` and the
  placement built on it are gone, with the state and the failure that went with
  them; `LiveCaptions._place` gives each piece the moment mpv's reading edge was
  at when it closed (`live.edge_at`, fed by `GrowingCaptions.sample`), which is
  what the pipeline did before. Measured on the same broadcast: mpv reports
  `time-pos` 9.3s and `demuxer-cache-time` 25.0s after eight seconds of playback,
  and the capture against that playlist answers no pieces and that reason.

- **A transcript is what the model wrote, heard without a voice filter, less
  the notes it makes about the soundtrack.** Two ways of keeping invention out
  were tried and measured away. `vad_filter=True` asked faster-whisper to drop
  what is not speech and put the timestamps back afterwards - measured,
  2026-09-20, on three minutes of a music-heavy broadcast, 54% of the words a
  filterless pass heard had no cue over them against 8% without it, and what it
  did write was merged (one cue was fourteen seconds of dialogue placed where
  the audio was not); on ten minutes of an episode from a podcast it kept no
  more words than the filter and cost no less time (1774 against 1776 words;
  38.5s against 36.9s for 600s of audio). A gate on the model's own doubts
  (`no_speech_prob`, `avg_logprob`, `compression_ratio`) went the same way:
  `no_speech_prob` is a whole window's verdict, so eight consecutive segments of
  that episode carried the same 0.69 while their words were a confident -0.12,
  and the gate took 121 words of speech out of those ten minutes while dropping
  nothing at all from the music-heavy three. What keeps invention out is what
  the model *wrote*: a note about the soundtrack is not a caption
  (`annotation`), a line it repeats is a line it invented (the loop guards), and
  a line that reaches back into what has already been said is cut at the join,
  word by word, rather than kept whole.

  A live pass also hears the tail of the piece before it as context, so the
  model is not left to make out a sentence from its middle. Measured over the
  three minutes: cues the reference transcript supports 55 of 72 (76%) before
  and 73 of 85 (86%) after, reference words with no cue over them 116 of 360
  (32%) before and 54 of 360 (15%) after, and the episode path measured 91% of
  its cues supported with 8% of the reference's words uncaptioned.

- **The version of a BBC programme that plays is the one BBC publishes for
  download.** A programme that has aired lists the version it aired as first, and
  the syndication URL every podcast client is served answers 404 for that one.
  Measured across one Radio 4 day, 8 entries: every aired version tried answered
  404, 4 of them list a podcast version that answers 200, 2 list one that answers
  404 as well, and 2 list none. The podcast version is now preferred, so a
  schedule entry plays instead of failing in the player. `hasOnDemand` on the
  entry does not predict it: the entry for the programme that played carried
  `false`.

- **BBC Audio, Bloomberg podcasts and podcast feeds.** Three more sources, each
  reading what the publisher already states about an item rather than scraping a
  player.

  A podcast feed is a listing and an episode list in one document, so
  `subcast <feed url>` plays the newest item of any RSS feed whose items enclose
  audio - the enclosure is the audio and `itunes:duration` its length. A feed can
  be saved as a feed by name like any other listing.

  Bloomberg's own series pages are served by a bot filter that answers 403 to
  anything that is not a browser - measured with a browser user agent and with a
  browser's whole header set - so a series URL is read where Bloomberg publishes
  the show. Its host's show page names the programme and links the feed the show
  is syndicated as, and the slug is the same on both (`/podcasts/series/<name>`
  and `omny.fm/shows/<name>`). The feed takes a page size, so a run that plays
  one episode asks for one episode rather than downloading a thousand.

  BBC Audio reads the payload every page of the audio site is rendered from, so a
  programme, a series, a category or one episode costs one request for the whole
  listing. A category is a directory of programmes, and an item that is a
  programme plays its newest episode; a programme page carries ten episodes at a
  time and a deeper listing asks for the pages it needs. The version the audio is
  addressed by is not in the listing, so it comes from the programme's own JSON
  when an item is played - a few kilobytes - and the audio is the mp3 BBC
  syndicates to podcast clients.

  All three work with `--list`, `--pick`, `--limit`, `--save`, `--audio-only`,
  `--subs` and resume, and any of them can be saved as a feed by name.

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

- **A shell for the runs with no arguments.** `subcast` on its own reads
  commands: `/list` is `--feeds`, `/feed [<name or number>]` opens a saved feed
  and asks what to play from it with captions on (with no name, the feed called
  `morning`), `/add <alias> <url>` keeps a feed and `/remove <alias>` forgets
  one, `/help [<command>]` prints the commands or one of them in full, and
  `/quit` stops. The commands are listed as the prompt opens, one to a line with
  what each does, in the layout `subcast --help` puts its options in. A command
  is the arguments it means, parsed by the same parser the command line uses
  (`shell.COMMANDS`, `cli.parse_args`), so nothing about the pipeline is a
  second implementation, and the rules a name and a URL obey are the ones
  `feeds.add` already has.

### Changed

- **A captioned item is heard from the stream while it plays instead of being
  downloaded first.** The audio used to be fetched whole before the first frame,
  because the captions have to belong to the copy that plays, and for a
  two-hour episode that was the whole file in front of the picture. RTÉ's
  resolved URL answers the same bytes to every request (measured: three fetches
  of one episode with the first 2 MB byte-identical, the length and the opening
  unchanged over 90 seconds, `Accept-Ranges: bytes`), so the player is handed
  the URL and the model asks the same URL for the audio again, a span at a time
  (`subtitles.StreamedWhilePlaying`): playback starts in seconds and captions
  arrive within tens of seconds, written as each span is heard. What is fetched
  is also written to the cache file, so a run ends holding the copy it heard,
  and the transcript, the segments and the chapters are rendered from it once
  the whole item has been heard.

  A span is placed by what the model measured of the audio before it - the
  model's own decode, not an estimate from the size of a byte range - and a
  two-second overlap between spans keeps a word the cut went through the middle
  of from being lost. An item whose URL fails the check - a different length or
  opening on the second probe, as Bloomberg's host answers a podcast enclosure
  with a pre-roll on some fetches - is downloaded whole first and heard from
  that file, exactly as before: captions timed against one copy of an item
  cannot be in pace with another. `--save` and `--no-play` runs, and items whose
  audio is already on disk, keep the file path too, and a stream that was never
  finished is deleted rather than left looking like a copy of the item.

- **The default programme is an ordinary feed called `morning`, not a built-in
  one.** The feed a run with no URL opens used to be a record in the code: it
  was printed apart from the saved feeds, could not be removed, and would not
  have been in the file at all. It is now a feed like the others - `morning`,
  which is Morning Ireland - and a machine whose feeds file has never been
  written is seeded with it once (`feeds.seed`), only when the file is not
  there, so removing it means removing it. `/feed` with no name and a run with
  no URL are the same lookup by the same name.

- **A bare `subcast` no longer plays the newest Morning Ireland: it opens the
  shell.** What a command does not do is end the shell - playback finishing, a
  URL nothing reads, a feed that does not answer and a command line argparse
  refuses all leave the prompt waiting for the next command. Ctrl-C stops the
  command that is running, mpv terminated and the caption block cleared, so the
  prompt that follows is the prompt that was there before; `/quit`, Ctrl-D,
  `SIGTERM` and `SIGHUP` stop the shell, and a signal arrives as its own
  exception (`cli.Stopped`) so that a shell told to go away goes away. Any
  argument is still a run, so the documented `subcast --subs` is unchanged, and
  a script that wants what a bare run used to do asks for it with `--no-pick`.
  `cli.main` takes the command line as an argument now, so what a run was told
  comes from whatever starts it rather than from the process's own argv.

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

- **Captions are made while the item plays, and written as they are heard.** A
  run of a source whose stream comes out of a resolve used to resolve, fetch the
  audio, transcribe it and only then start: a five-minute bulletin meant waiting
  for a download and a transcription before the first word, and for the whole
  transcription before the first caption. What has to be in hand before playback
  is the audio, because that is the copy the captions belong to
  (`cli.captions_audio`); after that the run plays, and the cues are written as
  the model produces them, so mpv reads the subtitle file again each time it
  grows and the captions keep ahead of the picture - a file is heard far faster
  than it plays (`subtitles.HeardWhilePlaying`).

  A broadcast is the same mechanism with the audio arriving in real time, so
  both now present one interface (`subtitles.GrowingCaptions`) that the player
  and the caption bar drive without caring which they have. Only a transcript
  heard to the end is cached: a run that ends first keeps the captions it heard
  and says what it got, and the next run hears the file rather than playing
  against half an episode. Nothing is per-source: the resolve, the audio and the
  player are the same three steps for every one of them.

- **A feed is a listing you saved, and nothing else.** Which source reads a feed
  was never part of what was saved - the URL decides that - but the code let a
  source own a programme: `sources.default()` answered with the RTÉ source and
  Morning Ireland's URL attached to it, so "RTÉ" and "the programme that opens
  by default" were one fact. The default is a feed now, opened through the same
  path a saved one takes, and the RTÉ source lists Morning Ireland and This
  Week alike without owning either.

  A name is the whole of how a feed is asked for, so saving one over a name that
  already means another URL is refused rather than silently replacing it: the
  same show is often published twice - a channel, and the programme's own page -
  and two names are how the two are told apart. `--feeds` prints the source each
  feed is read by, and says `?` for a URL nothing reads, which is what a feed
  saved ahead of its source looks like; `--add-feed` prints the source it
  detected; and `--feed` reaches the feed a run with no URL opens by name as
  well as by being that run.

### Fixed

- **The caption block swallowed stop signals.** Playing with the block
  installed the caption bar's own SIGTERM/SIGHUP handlers over the process's,
  for the length of that play and never restored, and the flag they set was
  never cleared. `cli.stop_signals` is what turns those two signals into
  `cli.Stopped` so a run's teardown happens - it stops a broadcast's capture
  and removes its chunks - and one bar-mode play replaced it for good: in the
  shell, which is one process running many commands, a signal that arrived
  during a later run no longer ended it, and a signal that arrived during a
  run with the block left the flag set, so the next command's block loop
  exited at once and the mpv it had just started was killed before a caption
  was drawn. The block leaves the signals alone now: the `finally` that clears
  the block and stops mpv runs on the way out either way.

- **A streamed item's captions were drawn from the wrong part of the
  sentence.** The block was handed the model's segments as they came - a
  sentence at a time - where the subtitle file, mpv, a broadcast's captions and
  a replay all work from those segments split into the pieces a caption line
  holds (`srt.split_cues`). A segment longer than the two lines the block shows
  kept its opening on screen for its whole length and never reached its ending:
  measured on one RTÉ episode, 452 of 682 segments (66%) do not fit the block
  at 39 cells a line, and the longest one still showed "understand there are
  different obligations on RTE in respect of the" while the words being spoken
  were "broadcasting of Eurovision". The caption on screen stops matching the
  audio, and further into a sentence the worse it is - pausing is what makes it
  obvious rather than what causes it, which is how it was reported.
  `subtitles.HeardFile.cues` now answers with the cues the file holds, so the
  block, the file and mpv draw the same captions.

- A published transcript is not captions. Omny's enclosure for one Bloomberg
  episode is served with ads stitched round the content - the first fetch of a
  session carried a pre-roll the next three did not, and the served file ran
  6:42 where the publisher states 5:30 - while the `podcast:transcript` track is
  timed against the publisher's own file: its last line landed at 343.6s in the
  audio and 321.8s in the track. Showing it put the captions a sentence ahead of
  the words, so the track is no longer read and a podcast's captions are heard
  from the audio the run plays, which is in pace with it by construction.

- A listing cache dropped what an entry carried beyond its name: `Media.kind`
  and the caption tracks went missing on the way through
  `<source>/listings/<hash>.json`, so an audio item read back from the menu's
  copy came back as a video with nothing published. A source whose listing says
  everything - a podcast feed, which states the audio and the transcript beside
  it - had nothing left to re-derive either one from, so the cache now
  round-trips both. An entry written by an older run still reads, as a video
  with no captions, which is what it was.

- A subtitle file offered to mpv while it was still starting was refused
  (`error running command`) and never offered again, which lost the captions
  for the whole run. mpv opens its IPC socket before its core will take a
  command - of 30 commands sent the moment the socket appeared, 17 were refused
  and the same command a moment later always worked - and a run whose captions
  were ready before playback began asked on its first poll, inside that window.
  The file is offered again a couple of times now (`player.ATTACH_TRIES`).

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
