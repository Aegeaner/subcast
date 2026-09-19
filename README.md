# subcast

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Play or save the latest [RTÉ Morning Ireland](https://www.rte.ie/radio/radio1/morning-ireland/)
episode, with subtitles generated locally and the segment titles RTÉ
publishes for the episode shown above them, so you can see what is coming
up and jump from segment to segment in mpv.

> **Status: 0.1.0, one source.** Today it knows RTÉ Morning Ireland. The
> pipeline underneath (media → transcript → segments → artifacts → player)
> is source-agnostic; other sources, including local files, arbitrary URLs
> and YouTube, are the next release. See [Roadmap](#roadmap).

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
- Chromium for Playwright (installed with the tool, see below)
- `faster-whisper` for `--subs`, pulled in by the `subs` extra

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
subcast                     # play the latest episode through mpv
subcast --save              # download it to ~/Videos/MorningIreland/
subcast --subs              # transcribe, then play with captions
subcast --save --subs       # keep audio + .srt + chapters
subcast --subs-style=osd    # let mpv print captions instead
subcast --whisper-device cpu
subcast --whisper-model medium.en
```

With `--subs`, captions are drawn by the tool itself in a fixed block at
the bottom of the terminal: a dim cyan segment title, then the line that
has just finished (dimmed, so you never lose the thread mid-sentence), and
under it up to two lines of bright dialogue. The block spans the window — resize or
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

## How the subtitles work

1. The episode audio is downloaded once and cached (a transcription run
   needs the file anyway), then transcribed with faster-whisper in
   English with voice-activity filtering.
2. The episode page embeds the segment list RTÉ publishes (`var clips =
   [...]`): titles and durations, **no offsets**.
3. `segments.py` places those titles: clock-titled segments pin their
   slot, the others are packed in published order, and then each title is
   snapped onto the nearest transcript cue that mentions it (within 180s).

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
| `--save` | `~/Videos/MorningIreland/<title>.mp3` |
| `--save --subs` | the same stem plus `.srt`, `.cues.json`, `.segments.json`, `.chapters.txt` |
| `--subs` cache | `$XDG_CACHE_HOME/subcast/<episode-uuid>.{mp3,cues.json,segments.json,srt,chapters.txt}` |

The cache is keyed by episode UUID. The transcript (`cues.json`) and the
placed segment list (`segments.json`) are what get kept; the `.srt` and
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

0.1.0 is deliberately narrow: one show, one pipeline. What comes next, in
order:

1. **A `sources` layer**: a small interface (`latest()`, `episodes()`) that
   returns a `Media` record, with the current RTÉ code moved behind it
   unchanged.
2. **Local files and arbitrary URLs** as sources, with `ffprobe` for
   duration and optional sidecar subtitles.
3. **YouTube**, videos and playlists, through `yt-dlp` as an optional
   extra — preferring the captions YouTube already has, falling back to
   transcription, and using chapters as segments.
4. **Playlist playback**: queue items through mpv's IPC interface, which the
   caption bar already uses.
5. **Video playback**: the terminal caption block only makes sense for
   audio; with video, captions belong in mpv's window.

Feature requests that map onto one of these are welcome; see the issue
templates.

## Notes

- **Not affiliated with RTÉ**, and not endorsed by them. Audio is fetched
  from RTÉ's public podcast endpoints; respect their terms of use, and do
  not hammer the service. This project ships no media and no scraped pages.
- Whisper models are downloaded from Hugging Face on first use, and stay in
  your Hugging Face cache.
- Licence: [MIT](LICENSE). Dependencies keep their own: faster-whisper is
  MIT, playwright and requests Apache-2.0, beautifulsoup4 MIT. mpv is a
  separate program, executed rather than linked.
- Captions are generated locally on your machine. Nothing is uploaded
  anywhere, and no analytics are collected.
