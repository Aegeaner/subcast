"""The shell a run with no arguments opens.

No second way to do anything: every command is translated into the
arguments the option parser already knows, and the run that follows is the
run the command line would have made. `/feed bbcnews` is
`subcast --feed bbcnews --pick --subs` and `/add c4 <url>` is
`subcast --add-feed --name c4 <url>`, argued by the same parser, so the
listings, the picker, the feeds file, the captions and the player are the
ones that were already there.

Commands are read from standard input, so a pipe drives the shell too and
it stops at the end of its input. Ctrl-C is the one thing a shell has to
get right: it stops the command that is running - playback included, whose
mpv is terminated and whose caption block is cleared on the way out - and
the next command is read. A run told to end by a signal is not caught
here: that is the shell being told to go away.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
from collections.abc import Callable
from typing import NamedTuple

from . import feeds

PROMPT = "subcast> "

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


def typed_line(
    prompt: str,
) -> str | None:
    """
    A line typed at the prompt, or None when the input has ended.

    Ctrl-C is not caught here: what it means depends on whether anything is
    running, which the shell knows and this does not.
    """

    try:

        return input(prompt)

    except EOFError:

        return None


def read_command(
    read: Callable[[str], str | None],
    tell: Callable[[str], None],
) -> str | None:
    """
    A command typed at the prompt, or None when the input has ended.

    Ctrl-C at the prompt has nothing to stop, and the prompt comes back
    either way: /quit is how a shell is left.
    """

    try:

        return read(PROMPT)

    except KeyboardInterrupt:

        tell(NOTHING_RUNNING)

        return ""


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
HEADING = "subcast: the feeds you kept, played by name."

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


def run(
    parse: Callable[[list[str]], argparse.Namespace],
    once: Callable[[argparse.Namespace], int],
    read: Callable[[str], str | None] = typed_line,
    tell: Callable[[str], None] = print,
) -> int:
    """
    Read commands until /quit, the end of the input, or a signal.

    `parse` and `once` are the command line's own, so a command is the
    arguments it means and running one is what any other run does.
    """

    tell(greeting())

    while True:

        line = read_command(read, tell)

        if line is None:

            tell("")

            return 0

        name, _, argument = line.strip().partition(" ")

        name = name.strip()
        argument = argument.strip()

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

                return 0

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
