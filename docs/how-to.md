# How-to guides

Task recipes. Each section solves one problem and stops there.

Options are in the [reference](reference.md); the reasons are in the
[explanation](explanation.md).

## Play a video or an episode

Pass subcast a URL. It plays the item in an mpv window:

```bash
subcast https://youtu.be/<id>
```

With no URL, subcast plays the newest RTÉ Morning Ireland.

## Play another RTÉ Radio 1 programme

A programme's page is a listing, so every recipe here works on it. Give the URL
you see in the browser:

```bash
subcast https://www.rte.ie/radio/radio1/this-week/
subcast https://www.rte.ie/radio/radio1/this-week/ --pick
```

The first plays that programme's newest episode; the second chooses from the
episodes its page lists. Save one to come back to by name:

```bash
subcast https://www.rte.ie/radio/radio1/this-week/ --add-feed
subcast --feed "This Week"
```

A programme names itself, so you only need `--name` to call it something else.
Every option works the same way on any programme: `--subs`, `--save`,
`--audio-only`, `--limit` and resume.

## Play audio only

To skip the video window and read the captions in your terminal, add
`--audio-only`:

```bash
subcast <url> --audio-only
```

Useful on a slow connection, or when you are listening rather than watching.

## Play several entries in turn

A playlist or channel plays its newest entry unless `--limit` says otherwise.
This plays the five newest, one after another:

```bash
subcast <url> --limit 5
```

`--limit 0` plays every entry. The next entry is prepared while the current one
plays, so each one after the first starts without waiting.

## Choose from a long listing

To see what a URL points at, print the listing:

```bash
subcast <url> --list
```

To choose from it, print it and answer:

```bash
subcast <url> --pick
```

Type one number (`3`), several (`2,5-7`), `all`, or press Enter to stop. Press
`r` to fetch the listing again; the menu is redrawn with what came back.

The menu opens on the listing the previous run fetched, so it appears at once,
and refreshes it behind the menu. The numbers always mean what is on screen, so
an answer cannot land on an entry that was not there when you typed it.

A menu shows the newest 30 entries. Change that for one run with `--limit N`, or
for every run with `SUBSCAST_LIMIT`.

## Search YouTube

Search instead of passing a URL. This command plays the top hit:

```bash
subcast --search "morning ireland"
```

Add `--pick` to choose from the results:

```bash
subcast --search "morning ireland" --pick
```

## Follow a channel or playlist as a feed

Save a listing you return to:

```bash
subcast <url> --add-feed
subcast <url> --add-feed --name bbc
```

List the saved feeds, open one, or forget one:

```bash
subcast --feeds
subcast --feed bbc
subcast --feed 2
subcast --remove-feed bbc
```

Opening a feed shows its newest entries as a menu. To play the newest entry
without being asked, add `--no-pick`. Every other option works on a feed too:
`--subs`, `--save`, `--audio-only` and resume.

## Transcribe an item that has no captions

Subcast uses the captions a source publishes. Where there are none, ask for
local transcription:

```bash
subcast <url> --subs
```

Two options override that choice. `--subs-from asr` ignores published captions,
and `--subs-from published` refuses transcription. To trade accuracy for speed,
or the other way round:

```bash
subcast <url> --subs --whisper-model medium.en
subcast <url> --subs --whisper-device cpu
```

## Caption a live broadcast

A broadcast has no finished audio to transcribe and usually publishes no
captions, so `--subs` makes them while it airs: subcast takes the audio from the
stream, cuts it into chunks, and transcribes each chunk as it closes.

```bash
subcast <url> --subs
```

The first captions appear soon after playback starts, and each one follows the
words by a short delay. Watch at the live edge: pausing or seeking back leaves
the captions behind, and returning to the live edge brings them back.

Two options are refused on a broadcast, with a line rather than a wait. `--save`
has no end to download up to, and `--no-play` has nothing to prepare without
playback.

## Save an item and its subtitles

Download instead of watching, then stop:

```bash
subcast <url> --save
subcast <url> --save --subs
```

`--quality` caps the video height of what is saved.

## Resume or start over

Subcast remembers the position of each item, so an interrupted item starts a few
seconds behind where you stopped. To ignore that and start from the beginning:

```bash
subcast <url> --no-resume
```

## Change how captions look

To size the terminal captions up or down, set a multiple of the terminal font:

```bash
subcast --subs --subs-scale 3
subcast --subs --subs-scale 1
```

To hand the captions back to mpv instead of the block subcast draws:

```bash
subcast --subs --subs-style osd
```

Scaled captions need a terminal that renders them, such as kitty 0.40 or newer.
On any other terminal subcast keeps them at normal size and says so.

## Use less bandwidth or start faster

Cap the video height. A 480p start has far less to buffer than a 1080p one:

```bash
subcast <url> --quality 480
```

## Prepare without playing

To resolve, download and subtitle an item, and start no player:

```bash
subcast <url> --no-play
```

Subcast prints what it wrote. This is useful for warming the cache before a
replay.

## Fix problems

### mpv refuses the stream

`mpv could not load that stream; trying once more...` means subcast is retrying
with the page URL, because YouTube hands out signed URLs that answer 403 now and
then. Wait for the retry. Two failures in a row are reported as they stand, and
trying again later is the fix.

### YouTube rate-limits the captions

`YouTube is rate-limiting this video's captions (HTTP 429)` means YouTube
refused every caption track for that video, including the original-language one.
Try again in a few minutes.

### The captions stay at normal size

Your terminal cannot render scaled text. Subcast prints `This terminal cannot
render text at 2x; captions stay at normal size.` and carries on. Nothing else
needs configuring; kitty 0.40 and newer can render scaled text.

### mpv sits paused at the end instead of exiting

Your `mpv.conf` sets `keep-open=yes`. Subcast treats end of file as finished
either way. Press `q` to quit.

### Resume behaves inconsistently

Turn off `save-position-on-quit` and the `watch-later` options in your
`mpv.conf`. mpv's own resume answers the same question as subcast's, on
different keys, and subcast keeps positions itself.

### A player is stuck

Kill the player by its IPC socket, which matches a running mpv:

```bash
pkill -f input-ipc-server
```

### pipx reports `pipx needs uv>=0.9.17`

Add `--backend pip` after `pipx run`, or upgrade uv with
`python3 -m pip install --upgrade uv`. The `uv self update` command only works
for uv's standalone installer.
