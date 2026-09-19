# Reference

Options, variables, paths, keys and exit statuses. For the tasks these support,
see [how-to guides](how-to.md); for the reasoning behind them, see
[explanation](explanation.md).

## Command syntax

```
subcast [url] [options]
```

`url` is a YouTube video, playlist or channel, or an RTÉ Morning Ireland show
or episode. If you omit it, subcast works on the latest Morning Ireland.

## Options

| Option | Effect |
| --- | --- |
| `<url>` | The item, listing or show to work on. Omitted: the latest RTÉ Morning Ireland. |
| `--list` | Print the listing and stop. |
| `--limit N` | How many entries to play, newest first. Default `1`; `0` plays all. A menu shows the newest `SUBSCAST_LIMIT` (30 by default) unless `N` says otherwise. |
| `--pick` | Print the listing and read a choice from it. |
| `--no-pick` | Play the newest entry without asking. |
| `--search QUERY` | Search YouTube instead of taking a URL. |
| `--feed NAME` | Open a saved feed, by name or by its number in `--feeds`. |
| `--feeds` | List the saved feeds and stop. |
| `--add-feed` | Save the URL as a feed, named by `--name` or after the listing. |
| `--name NAME` | The name `--add-feed` saves the feed under. |
| `--remove-feed NAME` | Forget the feed called `NAME`. |
| `--save` | Download into `~/Videos/<source>/` instead of streaming, then stop. |
| `--no-play` | Prepare everything and start no player. |
| `--audio-only` | Play the audio with terminal captions instead of video in a window. |
| `--quality HEIGHT` | Maximum video height for streaming and `--save`. Default `1080`. |
| `--subs`, `--subtitles` | Transcribe the item locally where the source publishes no captions. |
| `--subs-from {auto,published,asr}` | Where subtitles come from. Default `auto`. |
| `--whisper-model MODEL` | The faster-whisper model used for transcription. Default `small.en`. |
| `--whisper-device {auto,cuda,cpu}` | Device for transcription. Default `auto`. |
| `--subs-scale {auto,1,2,3}` | Caption size for the terminal block. Default `auto`. |
| `--subs-style {auto,bar,osd}` | `bar` draws the terminal block, `osd` lets mpv print captions, `auto` decides. Default `auto`. |
| `--no-resume` | Start from the beginning. The position is still remembered as it plays. |
| `-h`, `--help` | Print the options and stop. |

## Environment variables

| Variable | Effect |
| --- | --- |
| `SUBSCAST_LIMIT` | Entries a menu shows. Default `30`. `--limit` overrides it for one run. A value that is not a number leaves the default in place. |
| `XDG_CACHE_HOME` | Cache root. Default `~/.cache`. The cache goes in `<root>/subcast/<source>/`. |
| `XDG_CONFIG_HOME` | Config root. Default `~/.config`. Saved feeds live in `<root>/subcast/feeds.json`. |

## Files and directories

| Item | Path |
| --- | --- |
| `--save` output | `~/Videos/<source>/<title>.mp3` (RTÉ) or `.mp4` (YouTube) |
| Subtitles | `$XDG_CACHE_HOME/subcast/<source>/<id>.srt`, `<id>.chapters.txt` |
| Cache | `$XDG_CACHE_HOME/subcast/<source>/<id>.mp3`, `.mp4`, `.cues.json`, `.segments.json`, `.meta.json` |
| Listings | `$XDG_CACHE_HOME/subcast/<source>/listings/<url hash>.json` |
| Playback position | `$XDG_CACHE_HOME/subcast/<source>/<id>.position` |
| Feeds | `$XDG_CONFIG_HOME/subcast/feeds.json` |

The cache is keyed by the item's own id: an episode UUID for RTÉ, a video id
for YouTube.

## Cache lifetimes

| Item | Lifetime |
| --- | --- |
| `<id>.meta.json` (title, length, stream URLs) | 30 days, or until the title no longer matches |
| `listings/<hash>.json` | 7 days; a menu refreshes it in the background anyway |
| Signed stream URLs | reused until 10 minutes before they expire |
| `<id>.srt` and `<id>.chapters.txt` | rendered from the cache on every run |
| Everything else | kept until you delete it; subcast deletes nothing on its own |

## Sources

| Source | Behaviour |
| --- | --- |
| `rte` | Finds the latest Morning Ireland, or the episodes on a show page; reads the segment list RTÉ publishes; drives the RTÉ player in a headless browser for the stream URL. |
| `youtube` | Lists videos, playlists and channels with `yt-dlp --flat-playlist`; reads chapters and caption tracks from the player JSON. |

## Keys

Keys go to mpv, so any binding in your `mpv.conf` works.

| Key | Effect |
| --- | --- |
| `q` | Quit. |
| `m` | Mute or unmute. The terminal block marks a muted stream with `[muted]`. |
| `PageUp`, `PageDown` | Jump to the previous or next published segment. |
| `Ctrl-C` | Stop subcast and clear the terminal block. |

## Terminal support

| Feature | Requirement |
| --- | --- |
| Terminal caption block | `--subs-style=bar`, or `auto` with stdout on a terminal. |
| Scaled captions | A terminal that renders scaled text: kitty 0.40 and newer. Subcast asks the terminal and falls back to normal size elsewhere. |
| Block width | Follows the window, including resizes and maximises. |

## mpv options that affect subcast

Subcast passes the flags each mode needs and leaves the rest of your `mpv.conf`
alone, so a stock mpv works.

| Option | Effect on subcast |
| --- | --- |
| `keep-open`, `keep-open-pause` | Subcast reads `eof-reached` to decide whether an item is finished. `keep-open=yes` leaves mpv paused at the end instead of exiting, which subcast handles: `q` quits and the position is dropped either way. |
| `save-position-on-quit`, `watch-later-*` | The player's own resume, which answers the same question as subcast's, on different keys. Subcast passes `--start` at launch. |
| `cache-pause-initial`, `cache-pause-wait` | How long mpv waits for its buffer to fill before the first frame: the wait at the start of playback. |
| `cache-secs`, `demuxer-hysteresis-secs` | How much is buffered ahead. Deeper buffers ride out a poor connection; shallower ones start sooner. |
| `ytdl`, `ytdl-format` | Subcast sets both for anything it streams, so a global setting applies only to videos you play outside subcast. |
| `sub-auto`, `term-osd`, `term-status-msg` | Subcast sets these per run, so the terminal block owns the bottom rows. |

## Exit statuses and messages

| Status or message | Meaning |
| --- | --- |
| `0` | The run finished. |
| `2` | The stream could not be played. Subcast retries once, handing mpv the page URL. |
| `4` | The player quit on a signal, such as `Ctrl-C`. |
| Any other status | Reported as `mpv exited with <status>`. |
| `Streams: resolved by subcast` | The player was given stream URLs from the cache. |
| `Streams: mpv extracts them from the page` | The player was given the page URL and resolves it itself. |
| `Using the cached transcript; not asking YouTube again.` | The cache satisfied the run. |
| `Fetching captions: <language>` | A published caption track is being downloaded. |
| `Published captions (<language>): <n> cues` | Published captions were used. |
| `mpv could not load that stream; trying once more...` | The retry after exit status 2. |
| `YouTube is rate-limiting this video's captions (HTTP 429); trying again in a few minutes usually works` | Every caption track was refused. |
| `This terminal cannot render text at <n>x; captions stay at normal size.` | Scaled captions were requested on a terminal that cannot render them. |
