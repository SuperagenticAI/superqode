"""Regression contract for the public Click command tree."""

from __future__ import annotations

import hashlib

import click

from superqode.main import cli_main


EXPECTED_COMMAND_COUNT = 209
EXPECTED_HELP_TREE_SHA256 = "17f40dbc84c324b9b6048f814f08270e5af27a90fb87a689558cb0d51c4c7ceb"


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
