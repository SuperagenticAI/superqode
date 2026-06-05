"""Tests for /runtime slash-command registration."""

from __future__ import annotations

from superqode.widgets.slash_commands import (
    SlashCommandHandler,
    create_builtin_commands,
    get_command_handler,
)
from superqode.widgets.slash_complete import DEFAULT_COMMANDS, filter_slash_commands


def test_runtime_command_is_in_builtins():
    commands = create_builtin_commands(handlers={})
    names = {c.name for c in commands}
    assert "runtime" in names
    assert "codex" in names
    assert "antigravity" in names
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


def test_parse_codex_status_colon_input():
    handler = SlashCommandHandler()
    for cmd in create_builtin_commands(handlers={"codex": lambda _: None}):
        handler.register(cmd)
    parsed = handler.parse_input(":codex status")
    assert parsed is not None
    command, args = parsed
    assert command.name == "codex"
    assert args == "status"


def test_parse_antigravity_status_colon_input():
    handler = SlashCommandHandler()
    for cmd in create_builtin_commands(handlers={"antigravity": lambda _: None}):
        handler.register(cmd)
    parsed = handler.parse_input(":antigravity status")
    assert parsed is not None
    command, args = parsed
    assert command.name == "antigravity"
    assert args == "status"


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


def test_textual_completion_includes_harness_runtime_connect_and_session_commands():
    harness = filter_slash_commands(DEFAULT_COMMANDS, ":harn")
    runtime = filter_slash_commands(DEFAULT_COMMANDS, "/runtime")
    resume = filter_slash_commands(DEFAULT_COMMANDS, "/resume")
    connect = filter_slash_commands(DEFAULT_COMMANDS, ":c")

    assert any(completion.command == ":harness" for completion in harness)
    assert any(completion.command == "/runtime" for completion in runtime)
    assert any(completion.command == ":codex" for completion in filter_slash_commands(DEFAULT_COMMANDS, ":cod"))
    assert any(completion.command == "/resume" for completion in resume)
    assert [completion.command for completion in connect[:5]] == [
        ":connect",
        ":connect acp",
        ":connect antigravity",
        ":connect byok",
        ":connect local",
    ]


def test_runtime_in_prompt_completion_commands():
    """The live prompt completion panel filters COMMANDS — ':runtime' must be
    there (regression: it was only in slash_complete, so typing ':runtime' in
    the TUI showed no autocompletion)."""
    from superqode.app.constants import COMMANDS

    assert ":runtime" in COMMANDS
    assert ":runtime codex-sdk" in COMMANDS
    assert ":runtime list" in COMMANDS
    assert ":codex" in COMMANDS
    assert ":codex status" in COMMANDS
    assert ":antigravity" in COMMANDS
    assert ":connect antigravity" in COMMANDS


def test_runtime_argument_completion_lists_backends():
    """Typing ':runtime ' should suggest runtime names (incl. codex-sdk)."""
    from superqode.app_main import SuperQodeApp

    values = {c.value for c in SuperQodeApp._runtime_completion_candidates()}
    assert {"builtin", "codex-sdk", "list"} <= values


class _Log:
    def __init__(self):
        self.errors: list[str] = []

    def add_error(self, message: str):
        self.errors.append(message)


def test_codex_model_picker_selection_accepts_number_and_exact_id(monkeypatch):
    from superqode.app_main import SuperQodeApp

    app = SuperQodeApp()
    app._awaiting_codex_model = True
    app._codex_models = [
        {"id": "gpt-5.5", "name": "GPT 5.5"},
        {"id": "gpt-5.4-mini", "name": "GPT 5.4 Mini"},
    ]
    selected: list[str] = []
    monkeypatch.setattr(app, "_apply_codex_model_override", lambda model, log: selected.append(model))

    assert app._handle_codex_model_selection("2", _Log()) is True
    assert selected == ["gpt-5.4-mini"]

    app._awaiting_codex_model = True
    assert app._handle_codex_model_selection("gpt-5.5", _Log()) is True
    assert selected == ["gpt-5.4-mini", "gpt-5.5"]


def test_codex_model_picker_requires_exact_id_for_ambiguous_matches(monkeypatch):
    from superqode.app_main import SuperQodeApp

    app = SuperQodeApp()
    app._awaiting_codex_model = True
    app._codex_models = [
        {"id": "gpt-5.4", "name": "GPT 5.4"},
        {"id": "gpt-5.4-mini", "name": "GPT 5.4 Mini"},
    ]
    monkeypatch.setattr(app, "_apply_codex_model_override", lambda model, log: None)
    log = _Log()

    assert app._handle_codex_model_selection("5.4", log) is True
    assert log.errors
    assert "multiple" in log.errors[0]


def test_codex_effort_picker_selection_accepts_number_and_name(monkeypatch):
    from superqode.app_main import SuperQodeApp

    app = SuperQodeApp()
    selected: list[str] = []
    monkeypatch.setattr(app, "_codex_effort_cmd", lambda effort, log: selected.append(effort))

    app._awaiting_codex_effort = True
    assert app._handle_codex_effort_selection("4", _Log()) is True
    assert selected == ["medium"]

    app._awaiting_codex_effort = True
    assert app._handle_codex_effort_selection("xhigh", _Log()) is True
    assert selected == ["medium", "xhigh"]
