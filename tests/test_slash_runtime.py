"""Tests for /runtime slash-command registration."""

from __future__ import annotations

from superqode.widgets.slash_commands import (
    SlashCommandHandler,
    create_builtin_commands,
)


def test_runtime_command_is_in_builtins():
    commands = create_builtin_commands(handlers={})
    names = {c.name for c in commands}
    assert "runtime" in names


def test_runtime_command_has_description():
    commands = create_builtin_commands(handlers={})
    runtime_cmd = next(c for c in commands if c.name == "runtime")
    assert "runtime" in runtime_cmd.description.lower()
    assert any(
        name in runtime_cmd.description.lower() for name in ("builtin", "adk", "openai-agents")
    )


def test_parse_runtime_slash_input():
    handler = SlashCommandHandler()
    for cmd in create_builtin_commands(handlers={"runtime": lambda _: None}):
        handler.register(cmd)
    parsed = handler.parse_input("/runtime adk")
    assert parsed is not None
    command, args = parsed
    assert command.name == "runtime"
    assert args == "adk"


def test_parse_runtime_colon_input():
    handler = SlashCommandHandler()
    for cmd in create_builtin_commands(handlers={"runtime": lambda _: None}):
        handler.register(cmd)
    parsed = handler.parse_input(":runtime")
    assert parsed is not None
    command, args = parsed
    assert command.name == "runtime"
    assert args == ""
