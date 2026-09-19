# subcast

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Play or save an episode or video with subtitles: the captions a site
already publishes where there are any, local Whisper transcription where
there are not. Segment titles ride above the dialogue, and you can jump
between them in mpv.

```
subcast                                  # latest RTÉ Morning Ireland
subcast https://youtu.be/<id>            # a YouTube video
subcast "https://www.youtube.com/@channel/videos" --limit 5
subcast <url> --list                     # what does this URL point at?
```

Sources today: **RTÉ Morning Ireland** (audio, segment titles from the clip
list RTÉ publishes, transcribed locally with `--subs`) and **YouTube**
(videos, playlists and channels, using the captions and chapters YouTube
already has). The
pipeline underneath — media → transcript → segments → artifacts → player —
is source-agnostic; local files, arbitrary URLs and RSS feeds are next (see
[Roadmap](#roadmap)).

```
$ subcast --subs
[5/6] Preparing subtitles:
    Cache directory: /home/you/.cache/subcast
    File: /home/you/.cache/subcast/3b5345aa-....mp3
    Downloaded: 116.4 MB (100%)
    Published segments: 17
    Loading Whisper model small.en (cuda/float16)...
    Transcribed: 121 min / 121 min (100%)
    Subtitles: /home/you/.cache/subcast/3b5345aa-....srt
[6/6] Starting mpv...

▌ 8am News Bulletin
Good morning again, this is Morning Ireland with Gavin Jennings
and Sarah McInerney. We're here with you until nine...
```

## Requirements

- Python 3.10 or newer
- `mpv` for playback, `ffmpeg`/`ffprobe` for duration probing
- `yt-dlp` for YouTube (`pip install "subcast[youtube]"`, or your package
  manager); it resolves a video's streams, and mpv is handed those URLs from
  the cache, or the page URL to resolve for itself when they are not there
- Chromium for Playwright, used only by the RTÉ source (see below)
- `faster-whisper` for transcription, pulled in by the `subs` extra

## Install

Playwright's browser cache is keyed by revision (Playwright 1.63 wants
Chromium 1243, 1.62 wants 1234), so install Chromium with the tool's own
Playwright. A browser installed by another environment is not found.

**Checkout** — for hacking on the code:

```
git clone https://github.com/Aegeaner/subcast
cd subcast
python -m venv .venv && . .venv/bin/activate
pip install -e ".[subs]"
playwright install chromium
python -m subcast --subs
```

**Tool** — for daily use, in an isolated environment on `PATH`:

```
uv tool install ".[subs]"
uvx --from ".[subs]" playwright install chromium
subcast --subs
```

```
pipx install ".[subs]"
pipx run --spec ".[subs]" playwright install chromium
subcast --subs
```

Needs `uv` (`pacman -S uv`) or `pipx` (`pacman -S python-pipx`, or
`python3 -m pip install --user pipx && pipx ensurepath`). When installing
from the repository rather than a checkout, replace `".[subs]"` with
`"subcast[subs] @ git+https://github.com/Aegeaner/subcast"`.

If pipx reports `pipx needs uv>=0.9.17`, add `--backend pip` after
`pipx run`, or upgrade uv — `python3 -m pip install --upgrade uv` when uv
came from pip, since `uv self update` only works for the standalone
installer.

The two routes are independent: installing the tool does not get in the
way of running it from a checkout (or the other way round), so keeping
both is fine. Just install Chromium for whichever one you run.

## Usage

```
subcast <url>                  # play it: video in an mpv window
subcast <url> --list           # list a playlist, channel or show listing
subcast <url> --limit 5        # play five entries in turn (0 = all)
subcast <url> --audio-only     # audio plus terminal captions, no video
subcast <url> --no-resume      # start over, not where you left off
subcast <url> --subs           # transcribe too, where the source has none
subcast <url> --save           # download to ~/Videos/<source>/
subcast --save --subs          # keep a transcript with it
subcast <url> --subs-from asr  # ignore published captions, transcribe
subcast <url> --quality 720    # cap the video height
subcast --whisper-model medium.en --whisper-device cpu
subcast <url> --pick           # choose entries from a long listing
subcast --search "keyword"     # search YouTube, then pick from the hits
subcast <url> --add-feed       # save a playlist or channel as a feed
subcast --feeds                # what feeds are saved
subcast --feed bbc             # open a saved feed: a menu, then play a pick
subcast --feed bbc --no-pick   # play the newest entry instead
subcast --remove-feed bbc      # forget one
```

Long listings are browsed rather than guessed at: `--list` prints the
listing, `--pick` prints it and takes an answer — `3`, `2,5-7`, `all`, or
Enter to walk away — before anything is prepared or played. A menu opens on
the listing the last run fetched and asks the source for it again at the
same time: what comes back replaces the menu on screen, and `r` asks again
while you are looking at it. The numbers always mean what is on screen, so
an answer can never land on entries that were not there when it was typed.
`--list` and playing straight through ask the source instead of opening
what the cache has, because what is current is what those asked for. A menu
shows the newest 30 entries: enough to choose from, and little enough that
opening a channel with thousands of videos is not a wait. `--limit N` asks
for another number and `--limit 0` for the lot, and `SUBSCAST_LIMIT`
changes what the default is. `--search QUERY` turns a YouTube search into
such a listing — the top hit when it is only going to be played, a menu's
page when it is going to be browsed — so searching is `subcast --search
"morning ireland" --pick` and `subcast --search "morning ireland"` just
plays the first result.

Feeds are that idea kept: `subcast <url> --add-feed` remembers a YouTube
playlist or channel — named after itself, or by `--name` — and `--feed
<name>` (or `--feed 2`, by its number in `--feeds`) opens it the way a
podcast client opens a feed: the newest entries are printed as a numbered
menu and you type which to play — `3`, `2,5-7`, `all`, or Enter to walk
away. `--no-pick` plays the newest entry without asking, and everything a
URL takes applies to a feed too: `--subs`, `--save`, `--audio-only`,
resume. This is not podcast RSS: it is a short list of the listings you
follow, kept in your own config file.

Captions a source already publishes come with it, no flag needed: a
YouTube video arrives with the captions it has (seconds, no GPU), and a
video whose captions are only automatic (ASR) gets those. Where the track
YouTube offers is a translation of the video's own language, the track
behind it is tried too — translated tracks are the ones YouTube
rate-limits, and captions in the original language beat an error. Whisper is what
`--subs` is for, and it is what the sources without captions need: with no
URL, `subcast --subs` plays the latest RTÉ Morning Ireland as audio in the
terminal with captions transcribed locally and segment titles from RTÉ's
clip list, while plain `subcast` plays the same audio with the segment
titles alone.

Playing a YouTube video does not wait for any of that. mpv is handed the
page URL — or, for an item the cache already has stream URLs for, those
URLs themselves: a replay's first frame measured 3.4s against 15-22s when
mpv was left to extract — so the watch
link and the cache are all the run needs to start: the resolve, the caption
download and (where the video has no captions) the transcription all happen
beside the playback, and the subtitle file is handed to mpv mid-playback
the moment it is ready. Both paths ask for the same stream, so what
`--quality` caps and which formats are acceptable do not depend on which
one a run took. A run of several items — a feed, a playlist, a menu
selection — prepares the next one once the current one's own preparation is
done, so each item after the first starts without waiting either. A stream
mpv cannot load — sites refuse one every so often — is answered by handing
it the page instead, which is where it started. A first play spends its
time on the listing call and on mpv's own extraction — the two things that
cannot be moved — and a replay on mpv alone. RTÉ is different, and stays
that way: its stream URL only comes out of the resolve, so that one is found
before anything starts.

For audio, captions are drawn by the tool itself in a fixed block at
the bottom of the terminal: a dim cyan segment title, then the line that
has just finished (dimmed, so you never lose the thread mid-sentence),
under it up to two lines of bright dialogue, and — on the bottom row — the
playback clock: how far in, how long in total, and a bar between the two
(narrow windows get the two times alone, and a stream of unknown length
just the position). mpv's own terminal status line is switched off there,
so this is the progress display. The block spans the window — resize or
maximise the terminal and the captions re-wrap to the new width, moving
with the bottom edge — and it only repaints when the text actually changes,
so nothing flickers or jumps. The block is cleared again on exit
(including `Ctrl-C`). `--subs-style=osd` hands the captions back to
mpv (plain text, reprinted on redraw); `auto`, the default, uses the bar
when stdout is a terminal and mpv's OSD otherwise, so redirecting output
to a file does not fill it with escape codes.

The captions are drawn larger than the rest of the terminal by default
(`--subs-scale=auto`, i.e. 2x) through the terminal's own text sizing
protocol — kitty 0.40 and newer, which is detected by asking the terminal.
This sizes the captions only: your terminal font, profile and config are
not touched, and other terminals simply get normal-sized captions (the
width still follows the window there). `--subs-scale=3` goes bigger still,
`--subs-scale=1` turns it off.

`PageUp`/`PageDown` skip between published segments; the bar shows which
segment you land in.

Where you got to is remembered per item, so an episode or a video you stop
half way through — `Ctrl-C`, `q`, or closing the window — starts a few
seconds behind that point next time, and the clock picks the resumed time
up as its starting point. What is remembered is keyed by the item rather
than by the stream URL, so it survives RTÉ's expiring links; an item
watched to the end forgets its position instead of resuming at the credits,
`--no-resume` starts over, and an item of unknown length (a live stream)
never keeps one.

## Sources

| Source | What it does |
| --- | --- |
| `rte` | Finds the latest Morning Ireland (or the episodes on a show page), reads the segment list RTÉ publishes, and drives the RTÉ player in a headless browser to find the stream mpv should play |
| `youtube` | Lists videos, playlists and channels with `yt-dlp --flat-playlist`, reads chapters and caption tracks from the player JSON, and hands mpv the page URL with `--ytdl` to stream |

A source hands the pipeline a `Media` record: what to play, which captions
it publishes, and its segments (exact start times where the site has them,
lengths where it does not). Everything after that is shared, which is why
YouTube chapters and RTÉ clip lists need no separate code paths.

## How the subtitles work

1. Published captions are used when the source has them, with no flag
   involved — YouTube's are already timed, so nothing is generated and the
   GPU stays idle. Where there are none (RTÉ), or with `--subs-from asr`,
   the audio is downloaded once and transcribed with faster-whisper in
   English with voice-activity filtering; `--subs` is what asks for that.
2. Segments come from the source: YouTube chapters carry exact starts,
   while RTÉ's clip list (`var clips = [...]`) publishes only titles and
   durations, **no offsets**.
3. `segments.py` places them: exact starts are taken as given; derived
   ones (RTÉ) pin clock-titled segments to their slot, pack the rest in
   published order, and snap each title onto the nearest transcript cue
   that mentions it (within 180s).

   Caveat: the clip list is the *planned* running order. A bulletin
   scheduled for 8.35 can go out at 8.37, and an interview whose title
   words are never spoken keeps its derived slot, so a title can appear
   up to a couple of minutes early. Interview segments are usually exact.
4. Output next to the audio: `<episode>.srt` (captions, with each segment
   title as its own cue spanning the segment) and
   `<episode>.chapters.txt` (ffmetadata for mpv).

Captions are shaped for reading rather than for transcription: the
paragraph Whisper produces is laid out first and then cut at line
boundaries, so no cue spills past **two 42-column lines**, and each piece
gets its share of the cue's time. A cue with too little time for that
(fast speech) is left whole instead of blinking in and out. The segment
title rides above the dialogue marked with `▌`:

```
▌ 8am News Bulletin
Good morning again, this is Morning Ireland
with Gavin Jennings and Sarah McInerney.
```

Comfort here is your terminal's: font size, line spacing and colours come
from your terminal settings, and the captions are plain text so nothing
fights them (zoom in with `Ctrl` + `+` in kitty).

Model sizes and speed on a mid-range GPU: `small.en` (~480 MB, about 13x
realtime, so ~9 minutes for a two-hour show) is the default;
`medium.en` and `large-v3-turbo` are better but noticeably slower.

## mpv configuration

subcast plays through the mpv you already have. It passes the flags each mode
needs and leaves the rest of your `mpv.conf` alone, so nothing here is
required — a stock mpv works. These are the options that do change how subcast
behaves, with what they do about them:

| Option | What it changes | Suggestion |
| --- | --- | --- |
| `keep-open`, `keep-open-pause` | At the end of a video, subcast asks mpv whether playback reached the end (`eof-reached`) to decide whether the position is finished with. `keep-open=yes` leaves mpv paused at the end instead of exiting, which subcast handles as well: `q` quits, and the position is dropped either way. | either |
| `save-position-on-quit`, `watch-later-*` | mpv's own resume. subcast remembers positions itself, keyed by the item rather than by the stream URL (signed URLs change every run, so mpv's hash never matches), and passes `--start` at launch. Leaving mpv's version on means two answers to the same question. | off |
| `cache-pause-initial`, `cache-pause-wait` | How long mpv waits for its buffer to fill before the first frame. This is the wait at the start of playback: measured on a 1080p video, generous settings cost about a third of a second, not seconds — the picture itself takes longer to arrive than the buffer does. | `no` / small, if you want the fastest start |
| `cache-secs`, `demuxer-hysteresis-secs` | How much is buffered ahead. Deeper buffers ride out a poor connection; shallower ones start sooner and recover sooner after a stall. | yours to judge |
| `ytdl`, `ytdl-format` | subcast sets both for anything it streams (the format is capped by `--quality`), so a global setting only applies to videos you play outside subcast. | yours |
| `sub-auto`, `term-osd`, `term-status-msg` | Also set per run: the terminal captions turn mpv's own subtitle output and status line off, so the block keeps the bottom rows to itself. | yours |

Two consequences worth knowing when playback feels slow to start: the wait is
mpv's own yt-dlp call plus the first seconds of picture, not subcast's
preparation (which happens beside the playback), and `--quality` is a real
lever — a 480p start has far less to buffer than a 1080p one. The terminal
(audio) paths have no picture to buffer at all, which is why they make a sound
sooner than the window makes a frame.

## Where files go

| Mode | Location |
| --- | --- |
| `--save` | `~/Videos/<source>/<title>.mp3` (RTÉ) or `.mp4` (YouTube) |
| Subtitles | `$XDG_CACHE_HOME/subcast/<source>/<id>.{srt,chapters.txt}` |
| Cache | `$XDG_CACHE_HOME/subcast/<source>/<id>.{mp3,mp4,cues.json,segments.json,meta.json}` |
| Listings | `$XDG_CACHE_HOME/subcast/<source>/listings/<url hash>.json` |
| Playback position | `$XDG_CACHE_HOME/subcast/<source>/<id>.position` |
| Feeds | `$XDG_CONFIG_HOME/subcast/feeds.json` — the one file here that is the user's rather than the tool's |

The cache is keyed by the item's own id (an episode UUID, a video id). The
transcript (`cues.json`) and the placed segment list (`segments.json`) are
what get kept; the `.srt` and
the chapters file are rendered from them on every run, so caption
formatting can change without another nine-minute transcription. Nothing
is ever deleted automatically; clear old episodes yourself.

## Development

```
pip install -e ".[subs,dev]"
ruff check src tests
pytest
```

The test suite covers the pure parts (SRT and chapter writing, segment
placement and snapping, page parsing, caption layout, cache naming) against
a synthetic episode page in `tests/fixtures/`, and is deliberately offline.
Resolving the media URL needs the network and Playwright, so it is exercised
by running the tool instead. See [CONTRIBUTING.md](CONTRIBUTING.md) before
sending a pull request.

## Roadmap

Done in 0.2.0: the `sources` layer, YouTube (videos, playlists, channels),
published captions preferred over transcription, chapters as segments,
`--list`/`--limit`/`--save` for lists, video playback in an mpv window,
saved feeds, and searching with a picker for long listings.

Next:

1. **Local files and arbitrary URLs** as sources, with `ffprobe` for
   duration and sidecar subtitles picked up automatically.
2. **Podcast RSS**: real feeds alongside the saved YouTube listings, so a
   podcast can be played like a playlist.
3. **Per-source options** worth having: cookies for age-restricted videos,
   a preferred caption language, audio-only formats for `--save`.

Feature requests that map onto one of these are welcome; see the issue
templates.

## Notes

- **Not affiliated with RTÉ or YouTube**, and not endorsed by either.
  Audio and video are fetched from their public endpoints; respect their
  terms of use (YouTube's in particular forbids downloading without
  permission), and do not hammer the service. This project ships no media
  and no scraped pages, bundles no downloader — `yt-dlp` is an optional
  dependency you install and use on your own responsibility.
- Whisper models are downloaded from Hugging Face on first use, and stay in
  your Hugging Face cache.
- Licence: [MIT](LICENSE). Dependencies keep their own: faster-whisper is
  MIT, playwright and requests Apache-2.0, beautifulsoup4 MIT. mpv is a
  separate program, executed rather than linked.
- Captions are generated locally on your machine. Nothing is uploaded
  anywhere, and no analytics are collected.
- `SUBSCAST_LIMIT` sets how many entries a menu shows (30 by default);
  `--limit N` overrides it for one run, and `--limit 0` asks for the whole
  listing. `subcast --help` lists the rest.
- A replay is cheap: the transcript, the captions, the chapters and what a
  resolve learned (its title and length, in `<id>.meta.json`) are all in
  the cache, so playing a video again asks YouTube nothing — the watch
  link and the cache name everything. The resolve is asked for again once
  the metadata is a month old, or when the title no longer matches.
- Playing starts before the subtitles are ready, and mpv cannot take
  chapters once it is playing, so a video's first play uses whatever
  chapter file an earlier run left — the run that produces them also
  plays without them. On the terminal bar the segment titles are drawn by
  subcast itself and appear with the captions.
- Stream URLs are signed and short-lived, and YouTube's edge answers 403
  on a freshly minted one now and then. A stream mpv cannot load is
  therefore fetched and tried once more (`mpv could not load that stream`)
  before the run gives up on it; two failures in a row are reported as they
  stand.
