# How-to guides

Task recipes. Each section solves one problem and stops there. For the meaning
of an option, see [reference](reference.md); for why subcast behaves this way,
see [explanation](explanation.md).

## Play a video or an episode

Give subcast a URL. It plays the item in an mpv window:

```
subcast https://youtu.be/<id>
```

With no URL, subcast plays the newest RTÉ Morning Ireland.

## Play audio only

To skip the video window and read captions in the terminal, add
`--audio-only`:

```
subcast <url> --audio-only
```

Useful on a slow connection, or when the picture is not what you came for.

## Play several entries in turn

A playlist or channel plays its newest entry unless `--limit` says otherwise.
This plays the five newest, in turn:

```
subcast <url> --limit 5
```

`--limit 0` plays every entry. The next entry is prepared while the current one
plays, so each one after the first starts without waiting.

## Choose from a long listing

To see what a URL points at, print the listing:

```
subcast <url> --list
```

To choose from it, print it and answer:

```
subcast <url> --pick
```

Type one number (`3`), a range (`2,5-7`), `all`, or press Enter to stop. A menu
opens on the listing the last run fetched and refreshes it behind the menu, so
it appears at once: what comes back replaces it on screen. Press `r` to ask the
source again. The numbers always mean what is on screen, so an answer cannot
land on an entry that was not there when you typed it.

A menu shows the newest 30 entries. Change that for one run with `--limit N`,
or for every run with `SUBSCAST_LIMIT`.

## Search YouTube

Search instead of taking a URL. This plays the top hit:

```
subcast --search "morning ireland"
```

Add `--pick` to choose from the results:

```
subcast --search "morning ireland" --pick
```

## Follow a channel or playlist as a feed

Save a listing you return to:

```
subcast <url> --add-feed
subcast <url> --add-feed --name bbc
```

List what is saved, open one, or forget one:

```
subcast --feeds
subcast --feed bbc
subcast --feed 2
subcast --remove-feed bbc
```

Opening a feed shows its newest entries as a menu. To play the newest entry
without being asked, add `--no-pick`. Every other option works on a feed too:
`--subs`, `--save`, `--audio-only` and resume.

## Transcribe an item that has no captions

Captions a source publishes are used automatically. Where there are none, ask
for local transcription:

```
subcast <url> --subs
```

Two flags override the choice: `--subs-from asr` ignores published captions,
and `--subs-from published` refuses transcription. To trade accuracy for speed,
or the other way round:

```
subcast <url> --subs --whisper-model medium.en
subcast <url> --subs --whisper-device cpu
```

## Save an item and its subtitles

Download instead of watching, then stop:

```
subcast <url> --save
subcast <url> --save --subs
```

`--quality` caps the video height of what is saved.

## Resume or start over

Playback is remembered per item, so an interrupted item starts a few seconds
behind where you stopped. To ignore that and start from the beginning:

```
subcast <url> --no-resume
```

## Change how captions look

To size the captions up or down in the terminal, set a multiple of the terminal
font:

```
subcast --subs --subs-scale 3
subcast --subs --subs-scale 1
```

To hand the captions back to mpv instead of the block subcast draws:

```
subcast --subs --subs-style osd
```

Captions need a terminal that renders scaled text (kitty 0.40 and newer). On
any other terminal subcast keeps them at normal size and says so.

## Use less bandwidth or start faster

Cap the video height. A 480p start has far less to buffer than a 1080p one:

```
subcast <url> --quality 480
```

## Prepare without playing

To download, resolve and subtitle everything, and start no player:

```
subcast <url> --no-play
```

Subcast prints what it wrote. Useful for warming the cache before a replay.

## Fix problems

### mpv refuses the stream

`mpv could not load that stream; trying once more...` is subcast retrying with
the page URL, because YouTube hands out signed URLs that answer 403 now and
then. Wait for the retry. Two failures in a row are reported as they stand, and
trying again later is the fix.

### YouTube rate-limits the captions

`YouTube is rate-limiting this video's captions (HTTP 429)` means YouTube
refused every caption track for that video, including the original language
one. Try again in a few minutes.

### The captions stay at normal size

The terminal cannot render scaled text. Subcast prints `This terminal cannot
render text at 2x; captions stay at normal size.` and carries on. Nothing else
needs configuring: kitty 0.40 and newer can render scaled text.

### mpv sits paused at the end instead of exiting

Your `mpv.conf` sets `keep-open=yes`. Subcast treats end of file as finished
either way; press `q` to quit.

### Resume behaves inconsistently

Turn off `save-position-on-quit` and the `watch-later` options in your
`mpv.conf`: mpv's own resume answers the same question as subcast's, and
subcast keeps positions itself.

### A player is stuck

Kill it by its IPC socket, which matches a running mpv:

```
pkill -f input-ipc-server
```

### pipx reports `pipx needs uv>=0.9.17`

Add `--backend pip` after `pipx run`, or upgrade uv with
`python3 -m pip install --upgrade uv`. The `uv self update` command only works
for uv's standalone installer.
