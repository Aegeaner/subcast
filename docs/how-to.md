# How-to guides

Task recipes. Each section solves one problem and stops there.

Options are in the [reference](reference.md); the reasons are in the
[explanation](explanation.md).

## Play a video or an episode

Pass subcast a URL. It plays the item in an mpv window:

```bash
subcast https://youtu.be/<id>
```

With no arguments at all, subcast opens the [shell](#use-the-shell) instead;
`subcast --subs` plays the newest RTÉ Morning Ireland and transcribes it.

## Use the shell

Run subcast with no arguments at all and it waits for commands rather than
playing anything. It prints them as it opens, `/help` prints them again, and
`/help <command>` prints one in full:

```
subcast> /list
    1. c4  youtube  https://www.youtube.com/@Channel4News
    2. bbcnews  bbc  https://www.bbc.com/audio/brand/p002vsmz
    3. morning  rte  https://www.rte.ie/radio/radio1/morning-ireland/
subcast> /help feed
  /feed [<name>]
                        Open a feed and choose what to play from it.
                        the same as: subcast --feed <name> --pick --subs

subcast> /feed c4
```

`/list` prints the feeds you saved, as `subcast --feeds` does. `/feed` opens a
feed and asks what to play from it, with captions on. `/quit` stops.

Press TAB after `/feed` to complete the name of a saved feed:

```
subcast> /feed mor
```

`mor` and TAB leave `/feed morning` on the line. A name of several words is
completed a word at a time, and pressing TAB twice lists the names that match.

Give `/feed` the name or the number of a saved feed, or nothing at all for
`morning`, which is the newest RTÉ Morning Ireland:

```
subcast> /feed
subcast> /feed 2
subcast> /feed morning
```

Keep a feed, or forget one, without leaving the shell:

```
subcast> /add c4 https://www.youtube.com/@Channel4News
    Feed: c4 (youtube)
    https://www.youtube.com/@Channel4News
subcast> /remove c4
    Forgot: c4
```

`/add` takes the alias and the URL the feed is read from, with the same rules as
`subcast <url> --add-feed --name <alias>`: a name that already means another URL
is refused rather than quietly pointed elsewhere.

Each command is the options it means, so `/feed c4` is
`subcast --feed c4 --pick --subs`: the listing is printed, you choose from it,
and what plays is transcribed. When a command finishes - playback included -
the prompt comes back for the next one.

Ctrl-C stops the command that is running and the prompt comes back, which is
what you want after a stream you have heard enough of. `/quit`, or Ctrl-D, is
how the shell is left; a signal that asks the run to end - `SIGTERM`, `SIGHUP` -
ends it too.

The shell reads its commands from standard input, so a pipe can drive it:

```bash
printf '/list\n/feed c4\n/quit\n' | subcast
```

A bare `subcast` used to play the newest Morning Ireland. A script that wants
that asks for it: `subcast --no-pick` plays that feed's newest entry, and adding
`--subs` transcribes it.

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

## Play a podcast or a BBC programme

Subcast reads the pages and feeds that list audio: any BBC Audio page or
schedule, a Bloomberg podcast series, an Acast show page, a publisher's podcast
page, an Apple Podcasts show or episode, and any podcast feed.

```bash
subcast https://www.bbc.com/audio/brand/p002vsmz
subcast https://www.bbc.com/audio/category/news --pick
subcast https://www.bbc.com/audio/schedules/bbc_radio_fourfm --pick
subcast https://www.bloomberg.com/podcasts/series/bloomberg-news-now
subcast https://www.irishtimes.com/podcasts/in-the-news/
subcast https://podcasts.apple.com/us/podcast/huberman-lab/id1545953110
subcast https://podcasts.files.bbci.co.uk/p02nq0gn.rss
```

A BBC programme page lists its episodes and a category page lists the programmes
it covers, so `--pick` chooses from either; choosing a programme plays its newest
episode. A schedule lists the programmes a station puts out over a day. An Apple
Podcasts show plays the feed its publisher syndicates, and a link to one of its
episodes plays that episode. A feed states the audio its items enclose, so a
podcast plays from the file its publisher serves, whether you passed the feed or
a page that named it. Save one to come back to by name:

```bash
subcast https://www.bbc.com/audio/brand/p02nq0gn --add-feed
subcast --feed "Global News Podcast"
```

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

## Keep a listing to come back to

Save a listing under a name, then open it by that name:

```bash
subcast https://www.youtube.com/@Channel4News --add-feed --name c4
subcast https://www.rte.ie/radio/radio1/this-week/ --add-feed
subcast --feed c4
```

Any listing saves this way: a channel, a playlist, an RTÉ programme, a BBC Audio
programme, category or schedule, a Bloomberg series, an Acast show page, an
Apple Podcasts show, or a podcast feed's URL. The name is the alias you ask for
it by. Without `--name`, the listing is named after itself, so the RTÉ page
above gives `This Week`.

List what you have saved, open one, or forget one:

```bash
subcast --feeds
subcast --feed 2
subcast --remove-feed c4
```

`--feeds` prints the source each feed is read by, so a list that mixes a channel
with a radio programme says which pipeline each one goes through:

```
    1. c4  youtube  https://www.youtube.com/@Channel4News
    2. This Week  rte  https://www.rte.ie/radio/radio1/this-week/
    3. morning  rte  https://www.rte.ie/radio/radio1/morning-ireland/
```

The same show is often published twice, as a channel and as a programme, and two
names are how the two are told apart. A name that already means another URL is
refused rather than quietly pointed somewhere else - subcast answers `the feed
'c4' already points at <its url>` and saves nothing - so forget that feed first,
or save this one under another `--name`.

Opening a feed shows its newest entries as a menu. To play the newest entry
without being asked, add `--no-pick`. Every other option works on a feed too:
`--subs`, `--save`, `--audio-only` and resume.

A run with no URL opens the feed called `morning`, which a machine with no feeds
file is written the first time one is needed - so a new install has something to
play, and the feed is then yours to rename or remove like any other:

```bash
subcast --feed morning
```

## Transcribe an item that has no captions

Subcast uses the captions a source publishes. Where there are none, ask for
local transcription:

```bash
subcast <url> --subs
```

Playback does not wait for a download. The player is handed the resolved stream
and the model hears the same bytes as they arrive, a span at a time, so the first
captions are on screen within seconds of the item starting and the rest are
written as they are heard: a span is heard far faster than it plays, so the cues
keep ahead of the picture rather than trailing it. An item whose site will not
serve the same bytes to every request - one that stitches an ad into a request -
is downloaded first instead, because captions timed against one copy of an item
cannot be in pace with another.

The transcript is cached once the whole file has been heard, so the next run
reuses it. Ending the item first leaves the captions it heard and caches
nothing, and subcast says so: the next run hears the file again rather than
play against half a transcript.

Two options override that choice. `--subs-from asr` ignores published captions,
and `--subs-from published` refuses transcription. To trade accuracy for speed,
or the other way round:

```bash
subcast <url> --subs --whisper-model medium.en
subcast <url> --subs --whisper-device cpu
```

## Caption a live broadcast

A broadcast has no finished audio to transcribe and usually publishes no
captions, so `--subs` makes them while it airs: subcast takes the pieces the
broadcast's playlist names, and transcribes each one as it closes.

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

To let mpv's on-screen controller hide again, or take it off the picture
altogether:

```bash
subcast <url> --osc auto
subcast <url> --osc never
```

The controller is the title bar of a window the compositor does not decorate,
and it names the item, so subcast keeps it on screen by default. It draws bigger
than mpv's own size, in step with the captions the window shows.

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
