"""Regression contract for the public Click command tree."""

from __future__ import annotations

import hashlib
from unittest import mock

import click

from superqode.main import cli_main


EXPECTED_COMMAND_COUNT = 267
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
# Rebaselined for `superqode serve a2a`, which adds one Click command and its
# A2A 1.0, storage, authentication, and Agent Card export options.
# Rebaselined for the PiPy harness, which adds `harness-pipy` to the
# `--connect` choice list in second position, after `harness-core`.
# `--connect` derives its choices from the profile registry, so no Click
# command was added and the count is unchanged.
# Rebaselined for the Muse Code subscription profile, which adds `muse` to the
# `--connect` choice list after `antigravity`. Same registry-derived mechanism,
# so no Click command was added and the count is unchanged.
# Rebaselined for the Prime Agent subscription profile, which adds `prime-agent`
# to the `--connect` choice list after `muse`. Same registry-derived mechanism,
# so no Click command was added and the count is unchanged.
# Rebaselined for the native RLM harness, which adds `harness-rlm` to the
# `--connect` choice list after `harness-core`. No Click command was added.
# Rebaselined for the DeepSeek Harness preset, which adds `deepseek-harness` to
# the `harness init --template` choice list. No Click command was added.
# Rebaselined for the public Harness Hub: `hub`, `hub list`, and `hub show`
# expose the same versioned catalog used by the TUI and publication builds.
# Rebaselined for `hub --readiness`, whose choices now cover every published
# state (`supported` and `not-supported` were unreachable, `discover` matched
# nothing). Only the choice list changed, so no Click command was added.
# Rebaselined again after the Hub narrowed to harnesses only: model-access and
# inference routes left the catalog, so `supported` became unreachable and was
# dropped from the choice list. Still no Click command added.
# Rebaselined for `harness drift`, which compares a spec's declarations against
# what actually resolves. One Click command added, so the count moves to 267.
# Rebaselined for first-party DeepAgents support and the Hub openness filter:
# `deepagents` joins the `harness init --template` choices, `deepagents-code`
# joins the registry-derived `--connect` choices, and `hub` gains `--openness`.
# All three widen existing option lists, so the count stays at 267.
# Rebaselined for Factory Droid's Closed key path: `droid-key` joins the
# registry-derived `--connect` choices. No Click command was added.
# Rebaselined for Junie, Letta, Warp, and the rest of the Open/Closed catalog
# ids on the registry-derived `--connect` choice list. No Click command added.
# Rebaselined for fx Subscriptions (`fx`) and the Open Gateway-key row
# (`fx-key`) on the registry-derived `--connect` choice list. No Click
# command was added.
# Rebaselined for the connect IA default moving to v2: the registry-derived
# `--connect` choices now draw `agent-open-harnesses` and
# `agent-closed-harnesses` where v1 drew `other-harnesses`. The legacy id
# still resolves, so this swaps entries rather than adding a command.
EXPECTED_HELP_TREE_SHA256 = "429ca0b490d573a23f4d078c3ae47d5affd2d25783527e89494d166727aec8a4"


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
