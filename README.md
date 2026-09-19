# subcast

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Play or save an episode or video with subtitles. subcast uses the captions a
site already publishes, and transcribes the audio on your own machine with
Whisper when there are none. Segment titles sit above the dialogue, and you can
skip between them while you watch.

It works with:

- **YouTube** — videos, playlists and channels, using the captions and chapters
  YouTube already has.
- **RTÉ Morning Ireland** — audio, with segment titles from RTÉ's clip list and
  local transcription when you ask for it.

```
$ subcast --subs
[1/3] Finding items (rte):
    latest
    1 item(s)

[2/3] Preparing:
    Downloaded: 116.4 MB (100%)
    Published segments: 17
    Loading Whisper model small.en (cuda/float16)...
    Transcribed: 121 min / 121 min (100%)

[3/3] Playing:

▌ 8am News Bulletin
Good morning again, this is Morning Ireland with Gavin Jennings
and Sarah McInerney. We're here with you until nine...
```

## Install subcast

**You need:**

- Python 3.10 or newer.
- `mpv` to play, and `ffmpeg`/`ffprobe` to read a stream's length.
- `yt-dlp` for YouTube: the `youtube` extra installs it, or use your package
  manager.
- Chromium for Playwright. Only the RTÉ source needs it.
- `faster-whisper` for transcription: the `subs` extra installs it.

**As a tool** — for daily use, in an isolated environment on `PATH`. Either
`uv` or `pipx` works:

```
uv tool install ".[subs,youtube]"
uvx --from ".[subs,youtube]" playwright install chromium

pipx install ".[subs,youtube]"
pipx run --spec ".[subs,youtube]" playwright install chromium
```

**From a checkout** — for working on the code:

```
git clone https://github.com/Aegeaner/subcast
cd subcast
python -m venv .venv && . .venv/bin/activate
pip install -e ".[subs,dev]"
playwright install chromium
```

Install Chromium with the same tool that runs subcast. Playwright keys its
browser cache by revision (1.63 wants Chromium 1243, 1.62 wants 1234), so a
browser installed by another environment is not found.

The two routes are independent: installing the tool does not get in the way of
running from a checkout, or the other way round. Just install Chromium for
whichever one you run.

Installing from the repository rather than a checkout? Replace
`".[subs,youtube]"` with
`"subcast[subs,youtube] @ git+https://github.com/Aegeaner/subcast"`.

## Play something

```
subcast <url>                  # play: video in an mpv window
subcast                        # the latest RTÉ Morning Ireland
subcast <url> --audio-only     # audio with captions in the terminal, no window
subcast <url> --subs           # transcribe where the source has none
subcast <url> --save           # download instead of watching, then stop
subcast <url> --quality 720    # cap the video height (default 1080)
subcast <url> --no-resume      # start over, not where you stopped
subcast <url> --no-play        # prepare everything, start no player
```

With no URL, subcast plays the newest Morning Ireland. Video plays in an mpv
window; audio sources and `--audio-only` play in the terminal, where subcast
draws the captions itself.

## Browse a playlist, channel or show

```
subcast <url> --list              # print what the URL points at, then stop
subcast <url> --limit 5           # play five entries in turn (0 = all)
subcast <url> --pick              # choose from the listing
subcast --search "keyword"        # play the top YouTube search hit
subcast --search "keyword" --pick # search, then choose
```

`--pick` prints the listing and takes `3`, `2,5-7`, `all`, or Enter to walk
away — before anything is prepared or played. `--list` and playing straight
through ask the source for a current listing; a menu opens on the listing the
last run fetched and refreshes itself in the background as you look at it.
Press `r` to ask again. The numbers always mean what is on screen, so an answer
cannot land on an entry that was not there when you typed it.

A menu shows the newest 30 entries: enough to choose from, and little enough
that opening a channel with thousands of videos is not a wait. `--limit N`
asks for another number and `--limit 0` for the lot. `SUBSCAST_LIMIT` changes
what the default is.

## Follow a feed

```
subcast <url> --add-feed          # save a playlist or channel
subcast <url> --add-feed --name bbc
subcast --feeds                   # what is saved
subcast --feed bbc                # open one and pick from its newest entries
subcast --feed 2                  # by its number in --feeds
subcast --feed bbc --no-pick      # play the newest entry instead
subcast --remove-feed bbc         # forget one
```

A feed is a listing you come back to: opening one shows its newest entries as a
numbered menu, the way a podcast client does. Everything a URL takes works on a
feed too — `--subs`, `--save`, `--audio-only`, resume. Feeds are not podcast
RSS: they are a short list kept in your own config file
(`$XDG_CONFIG_HOME/subcast/feeds.json`), which subcast never edits behind your
back.

## Captions

Captions a site publishes come with it, with no flag needed. A YouTube video
arrives with its captions (seconds, no GPU), and a video whose captions are
only automatic (ASR) gets those. Where the track YouTube offers is a
translation of the video's own language, the track behind it is tried too —
translated tracks are the ones YouTube rate-limits, and captions in the
original language beat an error. If every track is refused, subcast says
YouTube is rate-limiting that video's captions rather than pretending there are
none.

Whisper is what `--subs` is for, and it is what sources without captions need:
with no URL, `subcast --subs` plays the latest Morning Ireland as audio in the
terminal, transcribed locally, with segment titles from RTÉ's clip list; plain
`subcast` plays the same audio with the segment titles alone. Two related
flags: `--subs-from asr` ignores published captions and transcribes anyway,
`--subs-from published` refuses local transcription. Transcription is in
English with voice-activity filtering, on CUDA when there is one and the CPU
otherwise.

Whisper models download from Hugging Face on first use and stay in your Hugging
Face cache. `small.en` (~480 MB) is the default and a good balance; `medium.en`
and `large-v3-turbo` are better but noticeably slower. Choose with
`--whisper-model` and `--whisper-device`.

## While it plays

- **Playback does not wait for the subtitles.** On YouTube, the resolve, the
  caption download and any transcription happen beside the playback, and the
  subtitle file is handed to the player mid-play when it lands. RTÉ waits,
  because its stream URL only comes out of a resolve.
- **A first play uses the chapter file a previous run left.** mpv cannot take
  chapters once it is playing, so a run that starts before its subtitles are
  ready has none — the run that produces them also plays without them. In the
  terminal caption bar, segment titles come from subcast itself and appear with
  the captions.
- **A stream mpv cannot load is retried once.** YouTube hands out signed URLs
  that answer 403 now and then; the retry hands mpv the page instead, which is
  the path that always works. Two failures in a row are reported as they stand.
- **A replay is cheap.** What a resolve learned, and the stream URLs it found,
  are cached, so playing an item again asks YouTube nothing until that metadata
  is a month old — the watch link and the cache name everything.
- **A slow start is mpv's own extraction plus its buffer**, not subcast's
  preparation. `--quality` is a real lever here: a 480p start has far less to
  buffer than a 1080p one.
- **Playlists, feeds and menu selections prepare the next item while the
  current one plays**, so every item after the first starts without waiting.
- **A caption failure does not stop playback.** It is reported as a line while
  the item plays, rather than ending the run.
- Press `q` to quit, `Ctrl-C` to stop. `PageUp`/`PageDown` skip between
  published segments; the segment title at the top of the terminal block shows
  which one you are in.

## Read captions in the terminal

For audio, subcast draws captions itself in a fixed block at the bottom of the
terminal:

- a dim cyan segment title,
- the line that has just finished, dimmed, so you never lose the thread
  mid-sentence,
- up to two lines of bright dialogue,
- and a clock: how far in, how long in total, and a bar between the two. A
  narrow window gets the two times alone, and a stream of unknown length just
  the position.

mpv's own terminal status line is switched off there, so this is the progress
display. The block spans the window and re-wraps when you resize or maximise,
and it repaints only when the text actually changes — nothing flickers or
jumps. It is cleared again on exit, `Ctrl-C` included.

- `--subs-style=osd` hands the captions back to mpv (plain text, reprinted on
  redraw). `auto`, the default, uses the bar when stdout is a terminal and
  mpv's OSD otherwise, so redirecting output to a file does not fill it with
  escape codes.
- `--subs-scale` sizes the captions using the terminal's own text sizing
  protocol (kitty 0.40 and newer, detected by asking the terminal). `auto`
  grows them with the window — up to 3x maximised, 1x on a narrow one.
  `--subs-scale=1` turns it off. Only the captions change: your terminal font,
  profile and config are not touched, and other terminals simply get
  normal-sized captions.

Captions are plain text, so comfort is your terminal's: font size, line spacing
and colours come from your terminal settings (zoom in with `Ctrl` + `+` in
kitty).

## Resume where you stopped

How far you got is remembered per item, so an episode or video you stop half
way through — `q`, `Ctrl-C` or closing the window — starts a few seconds behind
that point next time, and the clock picks up from there. What is remembered is
keyed by the item rather than by the stream URL, so it survives RTÉ's expiring
links. An item watched to the end forgets its position instead of resuming at
the credits, `--no-resume` starts over, and an item of unknown length (a live
stream) never keeps one.

## Save a copy

`--save` downloads into `~/Videos/<source>/` and stops. Add `--subs` to keep a
transcript with it, and `--quality` to cap the video height.

## Find the files

| What | Where |
| --- | --- |
| `--save` downloads | `~/Videos/<source>/<title>.mp3` (RTÉ) or `.mp4` (YouTube) |
| Subtitles | `$XDG_CACHE_HOME/subcast/<source>/<id>.{srt,chapters.txt}` |
| Cache | `$XDG_CACHE_HOME/subcast/<source>/<id>.{mp3,mp4,cues.json,segments.json,meta.json}` |
| Listings | `$XDG_CACHE_HOME/subcast/<source>/listings/<url hash>.json` |
| Playback position | `$XDG_CACHE_HOME/subcast/<source>/<id>.position` |
| Feeds | `$XDG_CONFIG_HOME/subcast/feeds.json` — yours, not the tool's |

The cache is keyed by the item's own id (an episode UUID, a video id). The
transcript and the placed segment list are what get kept; the `.srt` and the
chapters file are rendered from them on every run, so caption formatting can
change without another transcription. Nothing is ever deleted automatically —
clear old items yourself.

## Options

Run `subcast --help` for the same list on the command line.

| Option | What it does |
| --- | --- |
| `<url>` | A YouTube video, playlist or channel, or an RTÉ show or episode. Omit for the latest Morning Ireland. |
| `--list` | Print the listing and stop. |
| `--limit N` | How many entries to play, newest first (default 1; 0 means all). A menu shows the newest `SUBSCAST_LIMIT` (30 by default) unless N says otherwise. |
| `--pick` / `--no-pick` | Choose from the listing, or play the newest without asking. |
| `--search QUERY` | Search YouTube instead of taking a URL. |
| `--add-feed`, `--name NAME`, `--feeds`, `--feed NAME`, `--remove-feed NAME` | Save, list, open and forget feeds. |
| `--save` | Download into `~/Videos/<source>/` instead of streaming, then stop. |
| `--no-play` | Prepare everything but start no player; prints what was written. |
| `--audio-only` | Audio with terminal captions instead of video in a window. |
| `--quality HEIGHT` | Maximum video height for streaming and `--save` (default 1080). |
| `--subs` | Transcribe locally where the source publishes no captions. |
| `--subs-from {auto,published,asr}` | Where subtitles come from (default `auto`: published captions, else transcription). |
| `--whisper-model MODEL` | Whisper model for transcription (default `small.en`). |
| `--whisper-device {auto,cuda,cpu}` | Device Whisper runs on (default `auto`). |
| `--subs-scale {auto,1,2,3}` | Caption size in the terminal bar (default `auto`). |
| `--subs-style {auto,bar,osd}` | Terminal captions, mpv's own captions, or whichever suits (default `auto`). |
| `--no-resume` | Start from the beginning; the position is still remembered as it goes. |

## Troubleshoot

| Symptom | What to do |
| --- | --- |
| `YouTube is rate-limiting this video's captions (HTTP 429)` | Wait a few minutes and try again. Translated tracks are the ones YouTube limits; the original track is tried first. |
| `mpv could not load that stream; trying once more...` | Nothing to do — subcast falls back to the page URL, which resolves the stream again. |
| `mpv exited with 2` twice | The stream was refused twice. Try again later. |
| Playback takes a while to start | It is mpv's stream extraction and buffering. Lower `--quality` for less to buffer. |
| Captions did not get bigger | The terminal cannot render scaled text. subcast says so and stays at normal size; kitty 0.40+ can. |
| mpv sits paused at the end instead of exiting | Your `mpv.conf` sets `keep-open=yes`. subcast treats the end of the file as finished either way; `q` quits. |
| Resume is inconsistent | Turn off mpv's own `save-position-on-quit`/`watch-later`, which answers the same question with different keys. subcast remembers positions itself. |
| `pipx needs uv>=0.9.17` | Add `--backend pip` after `pipx run`, or upgrade uv (`python3 -m pip install --upgrade uv` — `uv self update` only works for the standalone installer). |
| A stuck player | `pkill -f input-ipc-server`. |

## Legal and privacy

subcast is **not affiliated with RTÉ or YouTube**, and not endorsed by either.
Audio and video are fetched from their public endpoints; respect their terms of
use — YouTube's in particular forbids downloading without permission — and do
not hammer the service. This project ships no media and no scraped pages, and
bundles no downloader: `yt-dlp` is an optional dependency you install and use
on your own responsibility.

Captions are generated locally on your machine. Nothing is uploaded anywhere,
and no analytics are collected. Whisper models are downloaded from Hugging Face
on first use and stay in your Hugging Face cache.

Licence: [MIT](LICENSE). Dependencies keep their own: faster-whisper is MIT,
playwright and requests Apache-2.0, beautifulsoup4 MIT. mpv is a separate
program, executed rather than linked.

## Development

`pip install -e ".[subs,dev]"`, then `pytest` and
`uvx ruff==0.16.8 check src tests`. See [CONTRIBUTING.md](CONTRIBUTING.md) for
the checks and what a good change looks like, and
[docs/technical.md](docs/technical.md) for how the pipeline, stream selection,
segment placement and mpv integration work — including the `mpv.conf` options
that change subcast's behaviour.

What's next: local files and arbitrary URLs as sources, podcast RSS feeds
alongside saved YouTube listings, and per-source options such as cookies for
age-restricted videos.
