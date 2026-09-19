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
  manager); mpv is pointed at the page URL and resolves it itself
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
```

Captions a source already publishes come with it, no flag needed: a
YouTube video arrives with the captions it has (seconds, no GPU), and a
video whose captions are only automatic (ASR) gets those. Whisper is what
`--subs` is for, and it is what the sources without captions need: with no
URL, `subcast --subs` plays the latest RTÉ Morning Ireland as audio in the
terminal with captions transcribed locally and segment titles from RTÉ's
clip list, while plain `subcast` plays the same audio with the segment
titles alone.

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

## Where files go

| Mode | Location |
| --- | --- |
| `--save` | `~/Videos/<source>/<title>.mp3` (RTÉ) or `.mp4` (YouTube) |
| Subtitles | `$XDG_CACHE_HOME/subcast/<source>/<id>.{srt,chapters.txt}` |
| Cache | `$XDG_CACHE_HOME/subcast/<source>/<id>.{mp3,mp4,cues.json,segments.json}` |
| Playback position | `$XDG_CACHE_HOME/subcast/<source>/<id>.position` |

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
`--list`/`--limit`/`--save` for lists, and video playback in an mpv window.

Next:

1. **Local files and arbitrary URLs** as sources, with `ffprobe` for
   duration and sidecar subtitles picked up automatically.
2. **RSS feeds** (the reference point is `podcast.sh`, which handles them
   alongside YouTube) so a podcast feed can be played like a playlist.
3. **Searching and browsing**: a picker for long listings, instead of
   `--limit` and `--list`.
4. **Per-source options** worth having: cookies for age-restricted videos,
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
- Stream URLs are signed and short-lived, and YouTube's edge answers 403
  on a freshly minted one now and then. A stream mpv cannot load is
  therefore fetched and tried once more (`mpv could not load that stream`)
  before the run gives up on it; two failures in a row are reported as they
  stand.
