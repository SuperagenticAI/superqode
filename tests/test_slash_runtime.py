"""Tests for /runtime slash-command registration."""

from __future__ import annotations

from superqode.widgets.slash_commands import (
    SlashCommandHandler,
    create_builtin_commands,
    get_command_handler,
)
from superqode.tui import SuperQodeCompleter


def test_runtime_command_is_in_builtins():
    commands = create_builtin_commands(handlers={})
    names = {c.name for c in commands}
    assert "runtime" in names
    assert "harness" in names
    assert "status" in names
    assert "usage" in names
    assert "resume" in names
    assert "mcp" in names


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


def test_parse_harness_slash_input():
    handler = SlashCommandHandler()
    for cmd in create_builtin_commands(handlers={"harness": lambda _: None}):
        handler.register(cmd)
    parsed = handler.parse_input("/harness specs/coding.yaml")
    assert parsed is not None
    command, args = parsed
    assert command.name == "harness"
    assert args == "specs/coding.yaml"


def test_global_handler_registers_builtin_commands():
    command, args = get_command_handler().parse_input(":status")
    assert command is not None
    assert command.name == "status"
    assert args == ""


def test_tui_completer_includes_harness_runtime_and_session_commands():
    from prompt_toolkit.document import Document

    completer = SuperQodeCompleter()

    harness = list(completer.get_completions(Document(":harn"), None))
    runtime = list(completer.get_completions(Document("/runtime l"), None))
    resume = list(completer.get_completions(Document(":resume"), None))

    assert any(completion.text == ":harness" for completion in harness)
    assert any(completion.text == "/runtime list" for completion in runtime)
    assert any(completion.text == ":resume latest" for completion in resume)
