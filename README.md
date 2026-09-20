# subcast

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Play or save an episode or video with subtitles.

Subcast uses the captions a site already publishes. When a site publishes none,
it transcribes the audio on your own machine with Whisper. A segment title sits
above the captions, and you can jump between segments while you watch.

Sources:

- **YouTube** — videos, playlists, channels and live broadcasts. Subcast uses
  YouTube's own captions and chapters.
- **BBC Audio** — a programme, a series, or a category of programmes. Subcast
  reads what the page carries, and plays the version BBC syndicates.
- **Bloomberg podcasts** — a series page, read through the feed the show is
  published as.
- **Podcast feeds** — any RSS feed whose items enclose audio, played from that
  audio.
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

**Open the shell.** Run subcast with no arguments at all and it waits for
commands instead of playing anything:

```
subcast: the feeds you kept, played by name.

  /list                 Print the feeds you saved, and where each is read from.
  /feed [<name>]        Open a feed and choose what to play from it.
  /add <alias> <url>    Keep a feed under an alias.
  /remove <alias>       Forget a feed, by the name it was kept under.
  /help [<command>]     Print this list, or one command in full.
  /quit                 Stop the shell. Ctrl-D does the same.

subcast> /feed
```

`/feed` with no name opens the feed called `morning`, which is the newest RTÉ
Morning Ireland; `/feed bbcnews` opens a feed you saved, and `/feed 3` opens the
third one. Each lists its entries and asks what to play, with captions on.
`/help feed` prints one command in full, including the command line it is the
same as.

**Play an episode that has no captions.** A flag with no URL opens the feed
called `morning`, which is the newest RTÉ Morning Ireland, and `--subs`
transcribes it:

```bash
subcast --subs
```

The episode plays in the terminal, with captions drawn by subcast:

```
[1/3] Finding items (rte):
    Morning Ireland: https://www.rte.ie/radio/radio1/morning-ireland/
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

The audio is fetched first, because that is the copy the captions belong to,
and then playback starts: the captions arrive while it plays, written as the
model hears them, and mpv reads the file again each time it grows. Nothing waits
for the whole transcription. The transcript is cached when it is complete, so
later runs reuse it.

**Play another RTÉ Radio 1 programme.** A programme page is a listing, so you
can pass it the way you pass a channel URL:

```bash
subcast https://www.rte.ie/radio/radio1/this-week/
```

`--pick` chooses from the episodes the page lists, and `--add-feed` saves the
programme under its own name.

**Play a podcast.** Pass a feed, a Bloomberg series page, or a BBC Audio page:

```bash
subcast https://www.bloomberg.com/podcasts/series/bloomberg-news-now
subcast https://www.bbc.com/audio/brand/p002vsmz --subs
```

A feed states the audio and its length, so a podcast plays from the file its
publisher serves. Its captions are heard from that audio, the way they are for
an RTÉ programme.

**Keep a listing to come back to.** A channel, a programme or a podcast feed
saves under a name you choose:

```bash
subcast https://www.rte.ie/radio/radio1/this-week/ --add-feed --name this-week
subcast --feed this-week
```

`--feeds` lists what you saved and the source each one is read by, so a list
that mixes a channel with a radio programme says which pipeline each goes
through.

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

Subcast is not affiliated with RTÉ, YouTube, the BBC or Bloomberg, and is not
endorsed by any of them. Licence:
[MIT](https://github.com/Aegeaner/subcast/blob/main/LICENSE).
