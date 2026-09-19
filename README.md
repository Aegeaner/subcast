# subcast

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Play or save an episode or video with subtitles.

Subcast uses the captions a site already publishes. When a site publishes none,
it transcribes the audio on your own machine with Whisper. A segment title sits
above the captions, and you can jump between segments while you watch.

Two sources are supported:

- **YouTube** — videos, playlists, channels and live broadcasts. Subcast uses
  YouTube's own captions and chapters.
- **RTÉ Radio 1** — any programme page. Subcast reads the segment list RTÉ
  publishes, and transcribes the audio where the programme has no captions.

A live broadcast has no finished audio and usually no captions, so `--subs`
transcribes it while it airs. Its captions follow the picture by a few seconds.

## Requirements

- Python 3.10 or newer.
- `mpv` to play. `ffmpeg` or `ffprobe` to read a stream's length.
- `yt-dlp` for YouTube. The `youtube` extra installs it.
- Chromium for Playwright, which only the RTÉ source needs.
- `faster-whisper` for transcription. The `subs` extra installs it.

## Install

Install subcast with `uv` or `pipx`. Both keep it in an isolated environment on
`PATH`:

```bash
uv tool install ".[subs,youtube]"
uvx --from ".[subs,youtube]" playwright install chromium

pipx install ".[subs,youtube]"
pipx run --spec ".[subs,youtube]" playwright install chromium
```

Install Chromium with the same tool that runs subcast. Playwright keys its
browser cache by revision, so a browser installed by another environment is not
found.

To install from the repository instead of a checkout, replace
`".[subs,youtube]"` with
`"subcast[subs,youtube] @ git+https://github.com/Aegeaner/subcast"`.

To work on the code, install from a checkout:

```bash
git clone https://github.com/Aegeaner/subcast
cd subcast
python -m venv .venv && . .venv/bin/activate
pip install -e ".[subs,dev]"
playwright install chromium
```

## Get started

**Play a YouTube video.** Give subcast any video, playlist or channel URL:

```bash
subcast https://youtu.be/<id>
```

An mpv window opens. Captions the video publishes arrive on their own, usually
within seconds and without using the GPU.

**Play an episode that has no captions.** With no URL, subcast plays the newest
RTÉ Morning Ireland. Add `--subs` to transcribe it:

```bash
subcast --subs
```

The episode plays in the terminal, with captions drawn by subcast:

```
[1/3] Finding items (rte):
    latest
    1 item(s)

[2/3] Preparing:
    Published segments: 17
    Loading Whisper model small.en (cuda/float16)...
    Transcribed: 121 min / 121 min (100%)

[3/3] Playing:

▌ 8am News Bulletin
Good morning again, this is Morning Ireland with Gavin Jennings
and Sarah McInerney. We're here with you until nine...
```

The first run downloads a Whisper model (about 480 MB) and takes minutes to
transcribe a two-hour episode. Later runs reuse the transcript.

**Play another RTÉ Radio 1 programme.** A programme page is a listing, so you
can pass it the way you pass a channel URL:

```bash
subcast https://www.rte.ie/radio/radio1/this-week/
```

`--pick` chooses from the episodes the page lists, and `--add-feed` saves the
programme under its own name.

**Choose from a long listing.** A channel or playlist holds more than one item,
so ask for the listing and pick from it:

```bash
subcast "https://www.youtube.com/@channel/videos" --pick
```

Type `3`, `2,5-7` or `all`. Press Enter to stop without playing anything.

**Keep a copy.** Download an item and its subtitles instead of watching:

```bash
subcast <url> --save --subs
```

Subcast prints the path it wrote, under `~/Videos/<source>/`.

## Documentation

| Guide | Contents |
| --- | --- |
| [How-to guides](https://github.com/Aegeaner/subcast/blob/main/docs/how-to.md) | Recipes for listings, feeds, saving, captions and problems. |
| [Reference](https://github.com/Aegeaner/subcast/blob/main/docs/reference.md) | Options, files, environment variables and exit codes. |
| [Explanation](https://github.com/Aegeaner/subcast/blob/main/docs/explanation.md) | How the pipeline, streams, segments and captions work. |
| [Contributing](https://github.com/Aegeaner/subcast/blob/main/CONTRIBUTING.md) | Tests, lint, and the shape of a good change. |

## Licence and privacy

Captions are generated on your machine. Nothing is uploaded and no analytics
are collected.

Subcast is not affiliated with RTÉ or YouTube and is not endorsed by either.
Licence: [MIT](https://github.com/Aegeaner/subcast/blob/main/LICENSE).
