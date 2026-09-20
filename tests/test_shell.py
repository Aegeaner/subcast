"""The shell: the commands a run with no arguments reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from subcast import cli, config, feeds, shell


class Shell:
    """
    A shell whose commands are recorded rather than run.

    A test reads what the shell decided - the arguments each command meant,
    and what it said - and replaces `parse` or `once` when a command has to
    fail.
    """

    def __init__(self, *lines: str) -> None:

        self.script = list(lines)
        self.runs: list[list[str]] = []
        self.told: list[str] = []

    def parse(self, arguments: list[str]) -> list[str]:
        """
        The arguments a command means, which for a test is the command.
        """

        return arguments

    def once(self, arguments: list[str]) -> int:

        self.runs.append(arguments)

        return 0

    def typed(self, prompt: str) -> str | None:

        return self.script.pop(0) if self.script else None

    def run(self) -> int:

        return shell.run(
            self.parse,
            self.once,
            read=self.typed,
            tell=self.told.append,
        )


def test_a_feed_command_is_the_menu_with_captions():
    assert shell.feed_arguments("bbcnews") == [
        "--feed",
        "bbcnews",
        "--pick",
        "--subs",
    ]


def test_a_url_is_a_feed_name_and_not_a_run_of_its_own():
    """
    URLs are the command line's business; the shell is for the feeds that
    were kept, and a URL typed at it is looked up as a name and found to be
    no feed at all.
    """

    url = "https://www.rte.ie/radio/radio1/this-week/"

    assert shell.feed_arguments(url) == [
        "--feed",
        url,
        "--pick",
        "--subs",
    ]


def test_a_feed_command_with_nothing_opens_the_built_in_feed():
    """
    Which is what a run with no arguments used to open on its own.
    """

    assert shell.feed_arguments("") == [
        "--feed",
        feeds.DEFAULT_NAME,
        "--pick",
        "--subs",
    ]


def test_the_commands_that_change_the_feed_list_are_the_options_they_mean():
    assert shell.add_arguments(
        "c4 https://www.youtube.com/@Channel4News"
    ) == [
        "--add-feed",
        "--name",
        "c4",
        "https://www.youtube.com/@Channel4News",
    ]

    assert shell.remove_arguments("BBC News") == [
        "--remove-feed",
        "BBC News",
    ]


def test_a_command_without_enough_on_the_line_says_what_it_takes():
    box = Shell("/add c4", "/remove", "/list", "/quit")

    box.run()

    assert box.runs == [["--feeds"]]
    assert "    /add needs <alias> <url>" in box.told
    assert "    /remove needs <alias>" in box.told


def test_a_feed_can_be_kept_and_forgotten_from_the_shell(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    """
    The commands that write `feeds.json` run the command line's own code, so
    the name a feed may not already mean, what it is read by and what a
    refusal reads like are the same in the shell as anywhere else.
    """

    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    box = Shell(
        "/add c4 https://www.youtube.com/@Channel4News",
        "/list",
        "/remove c4",
        "/list",
        "/quit",
    )

    box.parse = cli.parse_args
    box.once = cli.run_once

    box.run()

    printed = capsys.readouterr().out

    assert "Feed: c4 (youtube)" in printed
    assert "Forgot: c4" in printed
    assert "1. c4  youtube  https://www.youtube.com/@Channel4News" in printed
    assert feeds.load() == []


def test_the_shell_runs_the_commands_it_is_given():
    box = Shell("/list", "/feed bbcnews", "/quit")

    assert box.run() == 0

    assert box.runs == [
        ["--feeds"],
        ["--feed", "bbcnews", "--pick", "--subs"],
    ]

    assert box.told == [shell.greeting()]


def test_the_shell_stops_at_quit_and_at_the_end_of_its_input():
    quitting = Shell("/list", "/quit", "/list")
    ending = Shell("/list")

    quitting.run()
    ending.run()

    assert quitting.runs == [["--feeds"]]
    assert ending.runs == [["--feeds"]]

    # End of input leaves the terminal on a line of its own.
    assert ending.told[-1] == ""


def test_a_line_that_is_not_a_command_says_where_the_commands_are():
    box = Shell("/play", "/quit")

    box.run()

    assert box.runs == []
    assert "    no command '/play'; /help lists them" in box.told


def test_a_line_with_nothing_on_it_asks_again():
    box = Shell("", "   ", "/quit")

    box.run()

    assert box.runs == []
    assert box.told == [shell.greeting()]


def test_the_help_lists_every_command_with_what_it_does():
    """
    The list comes from the commands themselves, so a command cannot be
    missing from it, and what it says a command does is what that command
    was described as doing.
    """

    lines = shell.help_text(columns=80).splitlines()

    assert len(lines) == len(shell.COMMANDS)

    for name, command in shell.COMMANDS.items():

        written = f"  {name}{command.takes}"

        assert any(
            line.startswith(written) and command.does in line
            for line in lines
        )


def test_a_description_too_long_for_the_terminal_wraps():
    """
    It goes on saying itself indented, rather than pushing the rest of the
    list about.
    """

    lines = shell.help_text(columns=40).splitlines()

    assert len(lines) > len(shell.COMMANDS)
    assert max(len(line) for line in lines) <= 40


def test_help_can_show_one_command_in_full():
    """
    Which is what it is the same as on the command line, said as the
    arguments it means.
    """

    detail = shell.help_for("feed")

    assert "/feed [<name>]" in detail
    assert "the same as: subcast --feed <name> --pick --subs" in detail

    # The shell's own commands are not anything on the command line.
    assert "the same as" not in shell.help_for("quit")

    assert shell.help_for("nope") is None


def test_the_prompt_opens_with_the_help_and_help_prints_it_again():
    box = Shell("/help", "/quit")

    box.run()

    assert box.told[0] == shell.greeting()
    assert box.told[-1] == shell.greeting()


def test_help_naming_a_command_prints_that_one():
    box = Shell("/help feed", "/help nope", "/quit")

    box.run()

    assert any(shell.help_for("feed") in line for line in box.told)
    assert "    no command 'nope'; /help lists them" in box.told


def test_a_command_line_the_parser_refuses_is_one_command_not_the_shell():
    """
    A command line argparse will not take is the same as a URL that does
    not work: the shell waits for the next command.
    """

    box = Shell("/feed --oops", "/list", "/quit")

    def parse(arguments: list[str]) -> list[str]:

        if "--feed" in arguments:

            raise SystemExit(2)

        return arguments

    box.parse = parse

    box.run()

    assert box.runs == [["--feeds"]]


def test_an_interrupted_command_returns_to_the_prompt():
    """
    Ctrl-C stops the command - playback included, whose mpv is terminated
    and whose caption block is cleared on the way out - and the shell reads
    the next one.
    """

    box = Shell("/feed c4", "/list", "/quit")

    def once(arguments: list[str]) -> int:

        if arguments[0] == "--feed":

            raise KeyboardInterrupt

        box.runs.append(arguments)

        return 0

    box.once = once

    box.run()

    assert box.runs == [["--feeds"]]
    assert shell.STOPPED in box.told


def test_an_interrupt_at_the_prompt_does_not_end_the_shell():
    box = Shell("/list", "/quit")
    asked: list[str] = []

    def typed(prompt: str) -> str | None:

        asked.append(prompt)

        if len(asked) == 1:

            raise KeyboardInterrupt

        return box.script.pop(0)

    box.typed = typed

    box.run()

    assert box.runs == [["--feeds"]]
    assert shell.NOTHING_RUNNING in box.told


def test_a_signal_asking_the_run_to_end_ends_the_shell():
    """
    A SIGTERM arrives as `cli.Stopped`, which is not a command's to keep:
    a shell that is told to go away goes away.
    """

    box = Shell("/feed c4", "/list", "/quit")

    def once(arguments: list[str]) -> int:

        raise cli.Stopped

    box.once = once

    with pytest.raises(cli.Stopped):

        box.run()


def test_a_failure_the_command_did_not_report_is_still_the_command_s(
    capsys,
):
    """
    A traceback is not what the prompt is for: anything a command raises is
    reported the way a command line reports it, and the shell reads on.
    """

    box = Shell("/feed c4", "/list", "/quit")

    def once(arguments: list[str]) -> int:

        if arguments[0] == "--feed":

            raise RuntimeError("a command that failed")

        box.runs.append(arguments)

        return 0

    box.once = once

    box.run()

    assert box.runs == [["--feeds"]]
    assert "Error: a command that failed" in capsys.readouterr().err


def test_a_typed_line_is_read_and_the_end_of_it_is_not(monkeypatch):
    """
    Ctrl-D at the prompt ends the shell rather than looping on a prompt
    nobody is answering.
    """

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: "hello",
    )

    assert shell.typed_line(shell.PROMPT) == "hello"

    def end_of_input(prompt: str) -> str:

        raise EOFError

    monkeypatch.setattr(
        "builtins.input",
        end_of_input,
    )

    assert shell.typed_line(shell.PROMPT) is None
