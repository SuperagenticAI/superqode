"""Regression contract for the public Click command tree."""

from __future__ import annotations

import hashlib
from unittest import mock

import click

from superqode.main import cli_main


EXPECTED_COMMAND_COUNT = 262
# Rebaselined for `superqode update` (261 -> 262: exactly one command added),
# and again for the `copilot-cli` / `grok-cli` subscription runtimes, which
# widen the --runtime choice list without adding a Click command. The same work
# dropped `gemini-cli` from --connect, because it is an API-key route and a
# subscription entry must never put the user on metered API billing; the agent
# stays reachable via `:connect acp gemini`.
#
# Rebaselined again for the `:connect` ownership ladder. `--connect` derives its
# choices from the profile registry, so the new `agents` / `models` / `build`
# root and the four `build-*` routes widen the choice list, and the help text
# now names those rungs instead of the old five-option screen. No Click command
# was added or removed, so the count is unchanged.
EXPECTED_HELP_TREE_SHA256 = "363586628418e98acca96a418fe6ea4b3daf8afa5ca10fabf2b3349cdf01ac1f"


def _render_help_tree() -> tuple[int, str]:
    """Render every help page in Click registration order without invoking callbacks."""
    blocks: list[str] = []

    def visit(command: click.Command, context: click.Context, path: tuple[str, ...]) -> None:
        blocks.append(f"$ {' '.join((*path, '--help'))}\n{command.get_help(context)}")
        if not isinstance(command, click.Group):
            return
        for name, child in command.commands.items():
            child_context = click.Context(child, info_name=name, parent=context)
            visit(child, child_context, (*path, name))

    root_context = click.Context(cli_main, info_name="superqode")
    visit(cli_main, root_context, ("superqode",))
    payload = "\n".join(blocks).encode()
    return len(blocks), hashlib.sha256(payload).hexdigest()


def test_cli_help_tree_matches_refactor_baseline():
    """Commands, ordering, options, and rendered help must remain byte-identical."""
    command_count, help_digest = _render_help_tree()

    assert command_count == EXPECTED_COMMAND_COUNT
    assert help_digest == EXPECTED_HELP_TREE_SHA256


class TestHeadlessStdinNeverBlocks:
    """`superqode -p` must not hang on an inherited stdin that never sends EOF."""

    def test_idle_pipe_is_not_treated_as_input(self):
        """An open pipe with no data must not be read (this caused the hang)."""
        import os

        from superqode.main import _stdin_has_input

        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "r") as handle:
                with mock.patch("superqode.main.sys.stdin", handle):
                    assert _stdin_has_input() is False
        finally:
            os.close(write_fd)

    def test_pipe_with_data_is_still_read(self):
        """Real piped input (`cat f | superqode -p ...`) must keep working."""
        import os

        from superqode.main import _stdin_has_input

        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"piped prompt\n")
        os.close(write_fd)
        try:
            with os.fdopen(read_fd, "r") as handle:
                with mock.patch("superqode.main.sys.stdin", handle):
                    assert _stdin_has_input() is True
        finally:
            pass
