# Reference

Options, variables, paths, keys and exit statuses.

For the tasks these support, see the [how-to guides](how-to.md). For the
reasoning behind them, see the [explanation](explanation.md).

## Command syntax

```
subcast [url] [options]
```

`url` is a YouTube video, playlist or channel, a BBC Audio page or schedule, a
Bloomberg podcast series, an Acast show page or a publisher's page it serves, a
podcast feed, or an RTÉ Radio 1 programme or episode. If you omit it, subcast
opens the feed called `morning`, which is the latest episode of RTÉ Morning
Ireland. A machine whose feeds file has never been written is given that feed
the first time a run needs one.

Run subcast with no arguments at all and it opens its shell instead, reading
commands from standard input until `/quit` or the end of it. The prompt prints
the commands, one to a line, as it opens:

| Command | Effect |
| --- | --- |
| `/list` | The saved feeds with the source each is read by: `--feeds`. |
| `/feed [<name or number>]` | Open a feed and choose what to play: `--feed <name> --pick --subs`. With no name, `morning`, the feed a run with no URL opens. |
| `/add <alias> <url>` | Keep a feed under an alias: `--add-feed --name <alias> <url>`. A name that already means another URL is refused. |
| `/remove <alias>` | Forget a feed: `--remove-feed <alias>`. |
| `/help [<command>]` | Print the commands, or one of them with the command line it is the same as. |
| `/quit` | Stop the shell. Ctrl-D and a signal do the same. |

A command is the arguments it means, so everything in this reference applies:
`/feed c4` is `subcast --feed c4 --pick --subs`. The name a feed is asked for by
is a name rather than a URL - `/feed` given a URL looks it up as a name and
finds none - and `/add` is the one command a URL is given to, where it is kept
rather than played. What a command does not do is
end the shell: a URL that does not work, a feed that does not answer and an
interrupted playback all report themselves and the prompt returns. A command
that fails prints its `Error:` line and the shell reads the next command.
Ctrl-C stops the command that is running; `/quit`, Ctrl-D, `SIGTERM` and
`SIGHUP` stop the shell. Every argument on the command line is a run, so
`subcast --subs` plays the feed a run with no URL opens rather than opening the
shell.

## Options

| Option | Effect |
| --- | --- |
| `<url>` | The item, listing or programme to work on. Omitted: subcast opens the feed called `morning`. |
| `--list` | Print the listing and stop. |
| `--limit N` | How many entries to play, newest first. Default `1`; `0` plays all. A menu shows the newest `SUBSCAST_LIMIT` (30 by default) unless `N` says otherwise. |
| `--pick` | Print the listing and read a choice from it. |
| `--no-pick` | Play the newest entry without asking. |
| `--search QUERY` | Search YouTube instead of taking a URL. |
| `--feed NAME` | Open a saved feed, by name or by its number in `--feeds`. With no URL, the feed called `morning` is the one opened. |
| `--feeds` | List the saved feeds with the source each is read by, then stop. |
| `--add-feed` | Save the URL as a feed: a YouTube playlist or channel, an RTÉ programme, a BBC Audio programme, category or schedule, a Bloomberg podcast series, an Acast show page or a publisher's page it serves, or any podcast feed. Named by `--name`, or after the listing. A name that already means another URL is refused. |
| `--name NAME` | The name `--add-feed` saves the feed under, which is the alias `--feed` asks for it by. |
| `--remove-feed NAME` | Forget the feed called `NAME`. |
| `--save` | Download into `~/Videos/<source>/` instead of streaming, then stop. |
| `--no-play` | Prepare everything and start no player. |
| `--audio-only` | Play the audio with terminal captions instead of video in a window. |
| `--quality HEIGHT` | Maximum video height for streaming and `--save`. Default `1080`. |
| `--subs`, `--subtitles` | Transcribe the item locally where the source publishes no captions. The captions are heard from the audio the item plays - the stream itself, by range, when the site serves the same bytes to every request, and a copy downloaded first otherwise - and are written as they are heard: they appear while the item plays and keep ahead of it. On a live broadcast this is the only way it gets captions at all. |
| `--subs-from {auto,published,asr}` | Where subtitles come from. Default `auto`. On a broadcast, `published` leaves it with none, because its captions have to be made. |
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
| `--save` output | `~/Videos/<source>/<title>.mp3` (RTÉ, BBC, Bloomberg, Acast and podcasts) or `.mp4` (YouTube) |
| Subtitles | `$XDG_CACHE_HOME/subcast/<source>/<id>.srt`, `<id>.chapters.txt` |
| Broadcast captions | `$XDG_CACHE_HOME/subcast/<source>/<id>.live.srt`, written as the broadcast airs |
| Cache | `$XDG_CACHE_HOME/subcast/<source>/<id>.mp3`, `.mp4`, `.cues.json`, `.segments.json`, `.meta.json` |
| Listings | `$XDG_CACHE_HOME/subcast/<source>/listings/<url hash>.json` |
| Playback position | `$XDG_CACHE_HOME/subcast/<source>/<id>.position` |
| Feeds | `$XDG_CONFIG_HOME/subcast/feeds.json` |

The cache is keyed by the item's own id: an episode UUID for RTÉ, a video id for
YouTube, an episode id for BBC, and a clip id for a podcast or an Acast show.

## Cache lifetimes

| Item | Lifetime |
| --- | --- |
| `<id>.meta.json` (title, length, stream URLs) | 30 days, or until the title no longer matches |
| `listings/<hash>.json` | 7 days; a menu refreshes it in the background anyway |
| Signed stream URLs | reused until 10 minutes before they expire |
| `<id>.srt`, `<id>.segments.json`, `<id>.chapters.txt` | rendered from the transcript on every run |
| `<id>.live.srt` | written while a broadcast airs, and left behind afterwards |
| Everything else | kept until you delete it; subcast deletes nothing on its own |

## Sources

| Source | Behaviour |
| --- | --- |
| `acast` | A show published on Acast: Acast's own page for it (`shows.acast.com/<show>`), or a publisher's page whose episodes Acast serves, such as an Irish Times podcast. Acast's page links the feed the show is published as; a publisher's page names the show in the stream its own cards play from, and a page carrying more than one show is refused with the feeds it holds. Everything after that is a podcast feed. |
| `bbc` | A BBC Audio page: a programme, a series, a category, a station's schedule, or one episode. Subcast reads the payload the page is rendered from, so a listing costs one request; the version the audio is addressed by comes from the programme's own JSON when an item is played, and that is the version BBC publishes for download. A category lists programmes, an item that is a programme plays its newest episode, and a schedule lists the programmes a station puts out over a day. A programme page carries ten episodes at a time, and a deeper listing asks for the pages it needs. |
| `bloomberg` | A Bloomberg podcast series. Bloomberg's own pages refuse anything that is not a browser, so the show is read where it is hosted: its show page names the programme and links the feed it is syndicated as. Everything after that is a podcast feed. |
| `podcast` | Any RSS feed whose items enclose audio. The enclosure is the audio and `itunes:duration` its length, and a resolve has nothing left to find. A transcript a feed publishes is not read: it is timed against the file the publisher made, which is not always the file that arrives (`--subs` hears the audio that plays). |
| `rte` | Any RTÉ Radio 1 programme. Its page is a listing, and an episode URL is one item. Subcast reads the clip list and the programme's own schedule from the pages it fetches, and drives the RTÉ player in a headless browser for the stream URL, so an item of this source is never played from its page URL. Segment titles come from the clock times where the clip list carries them, and from the spoken words where it does not. A captioned episode plays the audio it was transcribed from, not a second fetch of the stream. |
| `youtube` | Videos, playlists and channels, listed with `yt-dlp --flat-playlist`. Chapters and caption tracks come from the player JSON. A broadcast is marked as one: it is played as it airs, and captioned by transcribing it while it plays. |

## Keys

Keys go to mpv, so any binding in your `mpv.conf` works.

| Key | Effect |
| --- | --- |
| `q` | Quit. |
| `m` | Mute or unmute. The terminal block marks a muted stream with `[muted]`. |
| `PageUp`, `PageDown` | Jump to the previous or next published segment. |
| `Ctrl-C` | Stop what is running and clear the terminal block. In the shell this stops the command and the prompt returns; `/quit` leaves the shell. |

## Terminal support

| Feature | Requirement |
| --- | --- |
| Terminal caption block | `--subs-style=bar`, or `auto` with stdout on a terminal. |
| Scaled captions | A terminal that renders scaled text, such as kitty 0.40 or newer. Subcast asks the terminal and falls back to normal size elsewhere. |
| Block width | Follows the window, including resizes and maximises. |

## mpv options that affect subcast

Subcast passes the flags each mode needs and leaves the rest of your `mpv.conf`
alone, so a stock mpv works.

| Option | Effect on subcast |
| --- | --- |
| `keep-open`, `keep-open-pause` | Subcast reads `eof-reached` to decide whether an item is finished. `keep-open=yes` leaves mpv paused at the end instead of exiting, which subcast handles: `q` quits, and the position is dropped either way. |
| `save-position-on-quit`, `watch-later-*` | The player's own resume, on different keys from subcast's. Subcast passes `--start` at launch. |
| `cache-pause-initial`, `cache-pause-wait` | How long mpv waits for its buffer to fill before the first frame. |
| `cache-secs`, `demuxer-hysteresis-secs` | How much is buffered ahead. Deeper buffers ride out a poor connection; shallower ones start sooner. |
| `ytdl`, `ytdl-format` | Subcast sets both for anything it streams, so a global setting applies only to videos you play outside subcast. |
| `sub-auto`, `term-osd`, `term-status-msg` | Subcast sets these per run, so the terminal block owns the bottom rows. |
| `msg-level` | Subcast turns playback logging down to warnings for the player module while a broadcast plays, because every subtitle reload makes mpv log its whole track list. Other modules keep their level, and warnings and errors still show. |

## Exit statuses and messages

| Status or message | Meaning |
| --- | --- |
| `0` | The run finished. |
| `2` | The stream could not be played. Subcast retries once, handing mpv the page URL. |
| `4` | The player quit on a signal, such as `Ctrl-C`. |
| `130` | The run was interrupted: `Ctrl-C` outside the shell, or a signal asking it to end. In the shell, `Ctrl-C` stops the command and this status is not reached. |
| Any other status | Reported as `mpv exited with <status>`. |
| `Streams: resolved by subcast` | The player was given stream URLs from the cache. |
| `Streams: mpv extracts them from the page` | The player was given the page URL and resolves it itself. |
| `Streams: the stream URL subcast resolved` | The player was given the stream URL a resolve just found, for a source whose URL is a page it could not play. |
| `Streams: the audio the captions were timed against` | The player was given the audio this run transcribed, because a source that stitches ads in per request does not serve the same audio twice. |
| `Captions are heard from the stream while it plays.` | The captions are being heard from the same URL the player is reading, a span at a time. |
| `Fetching the audio to transcribe: <length>.` | The item is being downloaded before playback: its site will not serve it in spans, or no player is waiting for it. |
| `Using the cached transcript; not asking YouTube again.` | The cache satisfied the run. |
| `Fetching captions: <language>` | A published caption track is being downloaded. |
| `Published captions (<language>): <n> cues` | Published captions were used. |
| `Live broadcast: captions made as it plays` | The item is a broadcast, and this run transcribes it as it airs. |
| `Live captions failed: <reason>; playing without them.` | The broadcast's capture or transcription gave up. Playback carries on. |
| `Live captions cannot keep up with this broadcast; skipping ahead to the live edge.` | Transcription is slower than the broadcast, so the oldest waiting chunks are dropped. Said once. |
| `Live captions: <n> chunk(s) heard, <m> with no speech, <k> skipped.` | The end of a broadcast run: what its captions came to. |
| `Heard <n> min / <m> min (<p>%)` | How much of a file being transcribed has been heard. |
| `Captions heard to <n> min of <m> min; the rest is made next run.` | The item ended before the whole file had been heard, so nothing was cached. |
| `Captions failed: <reason>; playing without them.` | The transcription gave up. Playback carries on. |
| `A live broadcast cannot be saved while it airs; wait for the video of it.` | `--save` on a broadcast, which has no end to download up to. |
| `A broadcast is prepared by playing it; --no-play leaves nothing to do.` | `--no-play` on a broadcast. |
| `mpv could not load that stream; trying once more...` | The retry after exit status 2. |
| `YouTube is rate-limiting this video's captions (HTTP 429); trying again in a few minutes usually works` | Every caption track was refused. |
| `This terminal cannot render text at <n>x; captions stay at normal size.` | Scaled captions were requested on a terminal that cannot render them. |
| `the feed '<name>' already points at <url>` | `--add-feed` was given a name another URL is saved under. Save under another `--name`, or remove that feed first. |
