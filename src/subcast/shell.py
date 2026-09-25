"""The shell a run with no arguments opens.

No second way to do anything: every command is translated into the
arguments the option parser already knows, and the run that follows is the
run the command line would have made. `/feed bbcnews` is
`subcast --feed bbcnews --pick --subs` and `/add c4 <url>` is
`subcast --add-feed --name c4 <url>`, argued by the same parser, so the
listings, the picker, the feeds file, the captions and the player are the
ones that were already there.

Commands are read from standard input, so a pipe drives the shell too and
it stops at the end of its input. TAB completes the name `/feed` is given,
and what it completes from is the feeds file read at that moment, so a feed
kept or forgotten in the same session completes without anything being kept
in step. Ctrl-C is the one thing a shell has to get right: it stops the
command that is running - playback included, whose mpv is terminated and
whose caption block is cleared on the way out - and the next command is
read. A run told to end by a signal is not caught here: that is the shell
being told to go away.

An item a command asked to keep outlives the command: the prompt comes back
while it is downloaded and heard, and the shell is what says the lines the
work has to say - over the prompt, and again when a command has been read
(`Keeper`). Leaving the shell is the one moment it waits for that work
(`leave`), because the thread goes with the process.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
import threading
from collections.abc import Callable
from typing import NamedTuple

from . import caching, feeds

# What `input` reads a line with when a line editor is there to read it.
# TAB completion is the editor's, so a platform that has none is a prompt
# that reads commands and completes nothing.
try:

    import readline

except ImportError:  # pragma: no cover - no line editor to complete with

    readline = None

PROMPT = "subcast> "

# How often the prompt looks for a line the cache work has to say. Short
# enough that a completion lands while the user is still looking at it, long
# enough that looking costs nothing.
NOTICE_SECONDS = 0.25

# Ctrl-C, said where it landed: a command was stopped, or there was nothing
# running to stop and what the prompt is waiting for is a command.
STOPPED = "    Stopped."

NOTHING_RUNNING = "    Nothing is running; /quit stops subcast."

# What `/feed` asks for on top of the name it is given: you choose from the
# listing, and what plays is transcribed.
FEED_OPTIONS = (
    "--pick",
    "--subs",
)


def feed_arguments(
    argument: str,
) -> list[str]:
    """
    What `/feed <argument>` means, as arguments the parser takes.

    A name, or the number `--feeds` prints, is a saved feed; nothing at all
    is the feed a run with no URL opens (`feeds.DEFAULT_NAME`). A URL is
    never played from here - `/add` is the command that is given one, and it
    keeps it - so a URL typed at `/feed` is looked up as a name and found to
    be no feed.
    """

    if not argument:

        return [
            "--feed",
            feeds.DEFAULT_NAME,
            *FEED_OPTIONS,
        ]

    return [
        "--feed",
        argument,
        *FEED_OPTIONS,
    ]


def remove_arguments(
    argument: str,
) -> list[str] | None:
    """
    What `/remove <alias>` means, or None when it names nothing.

    The name is the rest of the line, because a feed saved under the name
    it publishes ("BBC News") is called that by the whole of it.
    """

    if not argument:

        return None

    return ["--remove-feed", argument]


def add_arguments(
    argument: str,
) -> list[str] | None:
    """
    What `/add <alias> <url>` means, or None when one of them is missing.

    Keeping a feed from the shell is keeping it from the command line: the
    alias is `--name` and the URL is the URL, so the name it may not already
    mean, and the source it is read by, are the same rules either way. This
    is the one place a URL is given to the shell, and it is kept rather than
    played.
    """

    alias, _, url = argument.partition(" ")

    alias = alias.strip()
    url = url.strip()

    if not alias or not url:

        return None

    return [
        "--add-feed",
        "--name",
        alias,
        url,
    ]


def completions(
    line: str,
    word_start: int,
    word_end: int,
) -> list[str]:
    """
    What TAB offers where `/feed` is being given a name, as the text that
    replaces the word being completed.

    The word is completed into the whole of the name it is the beginning of:
    `/feed mor` offered `morning` replaces `mor`, and a name with a space in
    it is completed a word at a time - `/feed bbc n` offered `News` leaves
    the line reading `/feed bbc News`, which is how that name is spelled.
    Nothing else is completed, so TAB after `/add` offers nothing.

    The names are the feeds file, read now rather than kept in a list beside
    it: `/add` and `/remove` are then in the next TAB's answers with nothing
    to invalidate, and reading a file of a few lines is the whole of the
    cost. The feeds are offered in the order they were kept, which is the
    order `--feeds` numbers them in.
    """

    command, space, head = line[:word_start].lstrip().partition(" ")

    if command != "/feed" or not space:

        return []

    typed = (head + line[word_start:word_end]).lower()

    return [
        feed.name[len(head):]
        for feed in feeds.load()
        if feed.name.lower().startswith(typed)
    ]


def feed_completer() -> Callable[[str, int], str | None]:
    """
    The completer `readline` is given: what it calls, once per candidate, on
    the line the user is looking at.

    What readline offers along with the call is the word it split the line
    into, which is not necessarily where the name begins - `/feed bbc n` is
    completing from `bbc` - so the line and the word's place in it are read
    and the word itself is not.

    The candidates are worked out on the first call and handed over one at a
    time after that - readline asks the same question again until it is told
    there is no more - and they are worked out then rather than held from
    the last time TAB was pressed, so a feed kept in this session is
    completed by the next one.
    """

    offered: list[str] = []

    def complete(
        text: str,
        state: int,
    ) -> str | None:

        if not state:

            offered.clear()

            offered.extend(
                completions(
                    readline.get_line_buffer(),
                    readline.get_begidx(),
                    readline.get_endidx(),
                )
            )

        return offered[state] if state < len(offered) else None

    return complete


def typed_line(
    prompt: str,
) -> str | None:
    """
    A line typed at the prompt, or None when the input has ended.

    Ctrl-C is not caught here: what it means depends on whether anything is
    running, which the shell knows and this does not. TAB finishes a feed's
    name, which is the one thing the prompt has to offer: a feed is asked
    for by the name it was kept under.
    """

    if readline is not None:

        readline.set_completer(feed_completer())

        # GNU readline and libedit are told about TAB differently, and an
        # editor that was not told leaves TAB doing nothing at all.
        readline.parse_and_bind(
            "bind ^I rl_complete"
            if "libedit" in (readline.__doc__ or "")
            else "tab: complete"
        )

    try:

        return input(prompt)

    except EOFError:

        return None


def kept_lines(
    jobs: caching.Caching,
    tell: Callable[[str], None],
) -> None:
    """
    Whatever the cache work has said since the last look.
    """

    for line in jobs.take_notes():

        tell(line)


class Keeper(threading.Thread):
    """
    Says what the cache work has to say while the prompt waits for a command.

    The prompt is the screen's owner between commands, so the lines are said
    there rather than by the worker that produced them: the prompt line is
    taken back, the lines are written, and the prompt is put back for the
    command about to be typed. Nothing typed means nothing is lost.

    Something typed means the lines wait - they are only taken when they are
    about to be written, so none of them is said twice - and the shell says
    them once the command has been read, or the run that command starts says
    them while it plays.

    A platform whose `input` has no line editor cannot say what is on the
    line, so it says nothing and leaves every line to those moments.
    """

    def __init__(
        self,
        jobs: caching.Caching,
    ) -> None:

        super().__init__(daemon=True)

        self._jobs = jobs
        self._stopping = threading.Event()

    def run(self) -> None:

        while not self._stopping.wait(NOTICE_SECONDS):

            if readline is None or readline.get_line_buffer():

                continue

            lines = self._jobs.take_notes()

            if not lines:

                continue

            sys.stdout.write("\r\x1b[K")

            for line in lines:

                sys.stdout.write(line + "\n")

            sys.stdout.write(PROMPT)
            sys.stdout.flush()

    def stop(self) -> None:

        self._stopping.set()


def read_command(
    read: Callable[[str], str | None],
    tell: Callable[[str], None],
    jobs: caching.Caching,
) -> str | None:
    """
    A command typed at the prompt, or None when the input has ended.

    Ctrl-C at the prompt has nothing to stop, and the prompt comes back
    either way: /quit is how a shell is left. What the cache work has to say
    is said while the prompt is up (`Keeper`), because that is the only
    moment the shell owns the screen between commands.
    """

    keeper = Keeper(jobs)

    keeper.start()

    try:

        return read(PROMPT)

    except KeyboardInterrupt:

        tell(NOTHING_RUNNING)

        return ""

    finally:

        keeper.stop()


def run_command(
    parse: Callable[[list[str]], argparse.Namespace],
    once: Callable[[argparse.Namespace], int],
    arguments: list[str],
    tell: Callable[[str], None],
) -> None:
    """
    Run one command, and let nothing it does end the shell.

    Ctrl-C is the command's own: the player terminates mpv and clears its
    block on the way out, so the prompt that follows is the prompt that was
    there before. A failure is one command that did not work, reported the
    way a command line reports it - in case a command ever fails outside
    the reporting `once` already does - and a signal asking the whole run
    to end is not caught at all: that one is the shell being told to go.
    """

    try:

        once(parse(arguments))

    except KeyboardInterrupt:

        tell(STOPPED)

    except SystemExit:

        # The parser has said what was wrong with the arguments.
        pass

    except Exception as exc:  # noqa: BLE001 - reported, and the shell goes on

        print(
            f"\nError: {exc}",
            file=sys.stderr,
        )


class Command(NamedTuple):
    """
    One command: what it takes, what it does, and the arguments it means.

    `arguments` answers the arguments a line becomes, or None when the line
    did not say enough for it. A command whose arguments are None is the
    shell's own: it is carried out here rather than run.
    """

    takes: str
    does: str
    arguments: Callable[[str], list[str] | None] | None


# Every command in one place, so the help, the complaint about a line that is
# not a command and the complaint about a command that was not given enough
# cannot disagree.
COMMANDS: dict[str, Command] = {
    "/list": Command(
        "",
        "Print the feeds you saved, and where each is read from.",
        lambda argument: ["--feeds"],
    ),
    "/feed": Command(
        " [<name>]",
        "Open a feed and choose what to play from it.",
        feed_arguments,
    ),
    "/add": Command(
        " <alias> <url>",
        "Keep a feed under an alias.",
        add_arguments,
    ),
    "/remove": Command(
        " <alias>",
        "Forget a feed, by the name it was kept under.",
        remove_arguments,
    ),
    "/help": Command(
        " [<command>]",
        "Print this list, or one command in full.",
        None,
    ),
    "/quit": Command(
        "",
        "Stop the shell. Ctrl-D does the same.",
        None,
    ),
}

# What the prompt says when it opens, and again when /help is typed.
HEADING = (
    "subcast: the feeds you kept, played by name. "
    "TAB after /feed completes a feed's name."
)

# Where the help puts the description, and how far the terminal may be used.
# These are the columns `subcast --help` puts its options in: a list of
# commands is the same problem argparse solves, and somebody who has read one
# already knows how to read the other.
HELP_INDENT = 2
HELP_COLUMN = 24


def spelled_out(
    command: Command,
) -> list[str] | None:
    """
    What a command means when it is given what it takes, which is how /help
    says what it is the same as. A command of the shell's own means nothing
    on the command line and answers None.
    """

    if command.arguments is None:

        return None

    return command.arguments(
        command.takes.strip().strip("[]")
    )


def help_text(
    columns: int | None = None,
) -> str:
    """
    The commands, one to a line, with what each of them does.

    The invocation starts the line and the description follows in a column,
    wrapped to the terminal, so a command that says more than fits goes on
    saying it indented rather than pushing the rest of the list about.
    """

    width = max(
        columns or shutil.get_terminal_size().columns,
        HELP_COLUMN + 1,
    )

    return "\n".join(
        textwrap.fill(
            command.does,
            width=width,
            initial_indent=(
                f"{' ' * HELP_INDENT}{name}{command.takes}"
            ).ljust(HELP_COLUMN),
            subsequent_indent=" " * HELP_COLUMN,
        )
        for name, command in COMMANDS.items()
    )


def help_for(
    topic: str,
) -> str | None:
    """
    One command in full: what it takes, what it does, and the command line
    it is the same as. None means there is no such command.
    """

    name = topic if topic.startswith("/") else f"/{topic}"

    command = COMMANDS.get(name)

    if command is None:

        return None

    lines = [
        f"{' ' * HELP_INDENT}{name}{command.takes}",
        f"{' ' * HELP_COLUMN}{command.does}",
    ]

    arguments = spelled_out(command)

    if arguments is not None:

        lines.append(
            f"{' ' * HELP_COLUMN}the same as: "
            f"subcast {' '.join(arguments)}"
        )

    # Both kinds of help end with the blank line the prompt follows.
    return "\n".join(lines) + "\n"


def greeting() -> str:
    """
    What the shell says when it opens, and what /help says again.
    """

    return f"{HEADING}\n\n{help_text()}\n"


def show_help(
    argument: str,
    tell: Callable[[str], None],
) -> None:
    """
    What /help prints: every command, or the one it names in full.

    The blank line is what separates it from whatever was printed before it,
    which is the output of the command that was run last.
    """

    if not argument:

        tell("")
        tell(greeting())

        return

    detail = help_for(argument)

    if detail is None:

        tell(f"    no command {argument!r}; /help lists them")

        return

    tell("")
    tell(detail)


def leave(
    jobs: caching.Caching,
    tell: Callable[[str], None],
) -> int:
    """
    End the shell, giving the cache work what it is still waiting for.

    Leaving while an item is being kept would drop it, because the thread
    goes with the process: the shell says so and waits, and Ctrl-C is how to
    leave without it - which is what a second Ctrl-C would mean anywhere
    else here.
    """

    if not jobs.done_yet():

        tell("")
        tell(
            "    Still keeping an item in the cache; "
            "Ctrl-C leaves without it."
        )

        jobs.wait()

    kept_lines(jobs, tell)

    return 0


def run(
    parse: Callable[[list[str]], argparse.Namespace],
    once: Callable[[argparse.Namespace], int],
    read: Callable[[str], str | None] = typed_line,
    tell: Callable[[str], None] = print,
    jobs: caching.Caching | None = None,
) -> int:
    """
    Read commands until /quit, the end of the input, or a signal.

    `parse` and `once` are the command line's own, so a command is the
    arguments it means and running one is what any other run does. `jobs` is
    the queue the runs of this shell ask to keep items in - the process's
    own unless a caller says otherwise - and the shell is what says its
    lines while the prompt is up.
    """

    jobs = jobs if jobs is not None else caching.shared()

    tell(greeting())

    while True:

        kept_lines(jobs, tell)

        line = read_command(read, tell, jobs)

        if line is None:

            tell("")

            return leave(jobs, tell)

        name, _, argument = line.strip().partition(" ")

        name = name.strip()
        argument = argument.strip()

        # Typed while a notice was waiting for an empty line, or read by a
        # platform that cannot say what is on the line.
        kept_lines(jobs, tell)

        if not name:

            continue

        command = COMMANDS.get(name)

        if command is None:

            tell(f"    no command {name!r}; /help lists them")

            continue

        if command.arguments is None:

            # The shell's own two: /quit ends the reading, and /help is the
            # only other one, which prints rather than runs.
            if name == "/quit":

                return leave(jobs, tell)

            show_help(argument, tell)

            continue

        arguments = command.arguments(argument)

        if arguments is None:

            tell(f"    {name} needs{command.takes}")

            continue

        run_command(
            parse,
            once,
            arguments,
            tell,
        )
