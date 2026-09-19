# Reference

Options, variables, paths, keys and exit statuses. For the tasks these support,
see [how-to guides](how-to.md); for the reasoning behind them, see
[explanation](explanation.md).

## Command syntax

```
subcast [url] [options]
```

`url` is a YouTube video, playlist or channel, or an RTÉ Radio 1 programme or
episode. If you omit it, subcast works on the latest Morning Ireland.

## Options

| Option | Effect |
| --- | --- |
| `<url>` | The item, listing or programme to work on. Omitted: the latest RTÉ Morning Ireland. |
| `--list` | Print the listing and stop. |
| `--limit N` | How many entries to play, newest first. Default `1`; `0` plays all. A menu shows the newest `SUBSCAST_LIMIT` (30 by default) unless `N` says otherwise. |
| `--pick` | Print the listing and read a choice from it. |
| `--no-pick` | Play the newest entry without asking. |
| `--search QUERY` | Search YouTube instead of taking a URL. |
| `--feed NAME` | Open a saved feed, by name or by its number in `--feeds`. |
| `--feeds` | List the saved feeds and stop. |
| `--add-feed` | Save the URL (a YouTube playlist or channel, or an RTÉ programme) as a feed, named by `--name` or after the listing. |
| `--name NAME` | The name `--add-feed` saves the feed under. |
| `--remove-feed NAME` | Forget the feed called `NAME`. |
| `--save` | Download into `~/Videos/<source>/` instead of streaming, then stop. |
| `--no-play` | Prepare everything and start no player. |
| `--audio-only` | Play the audio with terminal captions instead of video in a window. |
| `--quality HEIGHT` | Maximum video height for streaming and `--save`. Default `1080`. |
| `--subs`, `--subtitles` | Transcribe the item locally where the source publishes no captions. On a live broadcast this is the only way it gets any: the audio is transcribed as it plays. |
| `--subs-from {auto,published,asr}` | Where subtitles come from. Default `auto`. On a broadcast, `published` is the one answer that leaves it with none: its captions have to be made. |
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
| Broadcast captions | `$XDG_CACHE_HOME/subcast/<source>/<id>.live.srt`, written as the broadcast plays |
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
| `<id>.srt`, `<id>.segments.json` and `<id>.chapters.txt` | rendered from the transcript on every run |
| `<id>.live.srt` | written while a broadcast plays, and left behind afterwards |
| Everything else | kept until you delete it; subcast deletes nothing on its own |

## Sources

| Source | Behaviour |
| --- | --- |
| `rte` | Any RTÉ Radio 1 programme: its page is a listing, and an episode URL is one item. Reads the clip list and the programme's own schedule off the pages it fetches; drives the RTÉ player in a headless browser for the stream URL, which is why an item of this source is never played from its page URL. Its segment titles are placed by the clock times where the clip list carries them and by the spoken words where it does not, and a captioned episode plays the audio it was transcribed from rather than fetching the stream again. |
| `youtube` | Lists videos, playlists and channels with `yt-dlp --flat-playlist`; reads chapters and caption tracks from the player JSON. A broadcast is marked as one: it is played as it airs, and captioned by transcribing it while it plays. |

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
| `msg-level` | Playback logging is turned down to warnings while a broadcast plays (`cplayer=warn`). mpv logs its whole track list whenever a subtitle file is reloaded (`Reloaded:`), and a broadcast reloads its captions every chunk - four lines of terminal each time. Every other module keeps its own level, and warnings and errors still show. |

## Exit statuses and messages

| Status or message | Meaning |
| --- | --- |
| `0` | The run finished. |
| `2` | The stream could not be played. Subcast retries once, handing mpv the page URL. |
| `4` | The player quit on a signal, such as `Ctrl-C`. |
| Any other status | Reported as `mpv exited with <status>`. |
| `Streams: resolved by subcast` | The player was given stream URLs from the cache. |
| `Streams: mpv extracts them from the page` | The player was given the page URL and resolves it itself. |
| `Streams: the stream URL subcast resolved` | The player was given the stream URL a resolve just found, for a source whose URL is a page it could not play. |
| `Streams: the audio the captions were timed against` | The player was pointed at the audio this run transcribed, because a source that stitches ads in per request does not serve the same audio twice. |
| `Using the cached transcript; not asking YouTube again.` | The cache satisfied the run. |
| `Fetching captions: <language>` | A published caption track is being downloaded. |
| `Published captions (<language>): <n> cues` | Published captions were used. |
| `Live broadcast: captions made as it plays` | The item is a broadcast and this run will transcribe it as it airs. |
| `Live captions failed: <reason>; playing without them.` | The broadcast's capture or transcription gave up. Playback carries on. |
| `Live captions cannot keep up with this broadcast; skipping ahead to the live edge.` | Transcription is slower than the broadcast, so the oldest waiting chunks are dropped to keep the captions with the live edge. Said once. |
| `Live captions: <n> chunk(s) heard, <m> with no speech, <k> skipped.` | The end of a broadcast run: what its captions came to. |
| `A live broadcast cannot be saved while it airs; wait for the video of it.` | `--save` on a broadcast, which has no end to download up to. |
| `A broadcast is prepared by playing it; --no-play leaves nothing to do.` | `--no-play` on a broadcast. |
| `mpv could not load that stream; trying once more...` | The retry after exit status 2. |
| `YouTube is rate-limiting this video's captions (HTTP 429); trying again in a few minutes usually works` | Every caption track was refused. |
| `This terminal cannot render text at <n>x; captions stay at normal size.` | Scaled captions were requested on a terminal that cannot render them. |
