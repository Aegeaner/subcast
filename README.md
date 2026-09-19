# subcast

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Play or save an episode or video with subtitles. Subcast uses the captions a
site already publishes, and transcribes the audio on your own machine with
Whisper when there are none. A segment title tops the caption block, and you can
skip between segments while you watch.

Subcast works with **YouTube** (videos, playlists, channels and live
broadcasts, using YouTube's own captions and chapters) and **RTÉ Radio 1**
(any programme's page, with segment titles from RTÉ's clip list). A broadcast
has no finished audio and nothing to caption it with, so `--subs` transcribes
it as it plays: the captions follow the picture by a few seconds.

This page installs subcast and plays something with it. Everything else lives
in the documentation:

| Page | What it covers |
| --- | --- |
| [How-to guides](https://github.com/Aegeaner/subcast/blob/main/docs/how-to.md) | Recipes for listings, feeds, saving, captions and problems. |
| [Reference](https://github.com/Aegeaner/subcast/blob/main/docs/reference.md) | Options, files, environment variables, exit codes. |
| [Explanation](https://github.com/Aegeaner/subcast/blob/main/docs/explanation.md) | How the pipeline, streams, segments and captions work. |
| [Contributing](https://github.com/Aegeaner/subcast/blob/main/CONTRIBUTING.md) | Tests, lint, and what a good change looks like. |

## Requirements

- Python 3.10 or newer.
- `mpv` to play, and `ffmpeg` or `ffprobe` to read a stream's length.
- `yt-dlp` for YouTube. The `youtube` extra installs it.
- Chromium for Playwright. Only the RTÉ source needs it.
- `faster-whisper` for transcription. The `subs` extra installs it.

## Install subcast

Install with `uv` or `pipx`. Both keep subcast in an isolated environment on
`PATH`:

```
uv tool install ".[subs,youtube]"
uvx --from ".[subs,youtube]" playwright install chromium

pipx install ".[subs,youtube]"
pipx run --spec ".[subs,youtube]" playwright install chromium
```

To work on the code instead, install from a checkout:

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

Installing from the repository rather than a checkout? Replace
`".[subs,youtube]"` with
`"subcast[subs,youtube] @ git+https://github.com/Aegeaner/subcast"`.

## Get started

**1. Play a YouTube video.** Give subcast any video, playlist or channel URL:

```
subcast https://youtu.be/<id>
```

An mpv window opens. Captions the video publishes arrive on their own, usually
within seconds and without using the GPU.

**2. Play an episode that has no captions.** With no URL, subcast takes the
newest RTÉ Morning Ireland. Add `--subs` to transcribe it:

```
subcast --subs
```

The episode plays in the terminal, with the captions subcast draws itself:

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

Another RTÉ Radio 1 programme works the same way: its page is a listing URL,
like a channel is.

```
subcast https://www.rte.ie/radio/radio1/this-week/
```

That plays the newest episode of it; `--pick` chooses from the episodes its
page lists, and `--add-feed` keeps the programme under its own name.

**3. Pick from a channel.** A channel or playlist holds more than one item, so
ask for the list and choose:

```
subcast "https://www.youtube.com/@channel/videos" --pick
```

Type `3`, `2,5-7` or `all`, or press Enter to walk away.

**4. Keep a copy.** Download the item you just played, subtitles included:

```
subcast <url> --save --subs
```

Subcast reports the path it wrote, under `~/Videos/<source>/`.

Where next: [how-to guides](https://github.com/Aegeaner/subcast/blob/main/docs/how-to.md)
for specific tasks, [reference](https://github.com/Aegeaner/subcast/blob/main/docs/reference.md)
for every option, and [explanation](https://github.com/Aegeaner/subcast/blob/main/docs/explanation.md)
for how it all works.

## Licence and privacy

Subcast is not affiliated with RTÉ or YouTube, and not endorsed by either.
Captions are generated locally: nothing is uploaded anywhere, and no analytics
are collected. Licence: [MIT](https://github.com/Aegeaner/subcast/blob/main/LICENSE).
