"""Tests for the ACP local slash command dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from superqode.acp.client import ACPStats
from superqode.acp.slash import (
    SlashCommandSpec,
    SlashRegistry,
    UnknownSlashCommandError,
    builtin_registry,
    handle_clear,
    handle_commands,
    handle_history,
    handle_model,
    handle_session,
    handle_status,
    parse_slash_input,
)


# ---------------------------------------------------------------------------
# Fake ACPClient — small enough that we don't pull in the real one's lifecycle.
# Only the surface the built-in handlers actually touch is implemented.
# ---------------------------------------------------------------------------


@dataclass
class _FakeStoredSession:
    session_id: str
    label: str = ""


@dataclass
class _FakeClient:
    model: Optional[str] = "claude-sonnet-4-5-20250929"
    session_id_value: str = "ses_abc123"
    running: bool = True
    capabilities: Dict[str, Any] = field(
        default_factory=lambda: {"loadSession": True, "promptCapabilities": {"image": True}}
    )
    stats: ACPStats = field(
        default_factory=lambda: ACPStats(
            tool_count=3,
            files_read=["a.py", "b.py"],
            files_modified=["c.py"],
            duration=12.4,
        )
    )
    persisted: List[_FakeStoredSession] = field(default_factory=list)
    available_commands: List[Dict[str, str]] = field(default_factory=list)
    reset_called: bool = False
    reset_result: bool = True
    raise_on: Optional[str] = None  # method name that should raise

    def is_running(self) -> bool:
        return self.running

    def get_session_id(self) -> str:
        return self.session_id_value

    def get_current_model(self) -> Optional[str]:
        return self.model

    def supports_resume(self) -> bool:
        return bool(self.capabilities.get("loadSession"))

    def get_agent_capabilities(self) -> Dict[str, Any]:
        return dict(self.capabilities)

    def get_stats(self) -> ACPStats:
        return self.stats

    async def list_persisted_sessions(
        self, *, cwd_only: bool = True, limit: int = 50
    ) -> List[_FakeStoredSession]:
        if self.raise_on == "list_persisted_sessions":
            raise RuntimeError("storage down")
        return self.persisted[:limit]

    async def get_available_commands(self) -> List[Dict[str, str]]:
        if self.raise_on == "get_available_commands":
            raise RuntimeError("agent busy")
        return list(self.available_commands)

    async def reset_session(self) -> bool:
        if self.raise_on == "reset_session":
            raise RuntimeError("cannot reset")
        self.reset_called = True
        return self.reset_result


# ---------------------------------------------------------------------------
# parse_slash_input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [
        ("/status", ("status", "")),
        (":status", ("status", "")),
        ("  /status  ", ("status", "")),
        ("/history --all --limit=5", ("history", "--all --limit=5")),
        (":Model", ("model", "")),
        ("/help me", ("help", "me")),
    ],
)
def test_parse_slash_input_recognized(line, expected):
    assert parse_slash_input(line) == expected


@pytest.mark.parametrize("line", ["", "   ", "hello", "/", ":", "  /  "])
def test_parse_slash_input_not_a_command(line):
    assert parse_slash_input(line) is None


# ---------------------------------------------------------------------------
# Registry mechanics
# ---------------------------------------------------------------------------


def test_registry_register_get_unregister():
    reg = SlashRegistry()

    async def h(client, args):
        return "ok"

    reg.register(SlashCommandSpec("foo", "test", h))
    assert reg.has("foo")
    assert reg.has("FOO")  # case-insensitive
    assert reg.get("foo").description == "test"
    assert reg.unregister("Foo") is True
    assert reg.unregister("foo") is False


def test_registry_replace_on_duplicate():
    reg = SlashRegistry()

    async def first(client, args):
        return "first"

    async def second(client, args):
        return "second"

    reg.register(SlashCommandSpec("foo", "v1", first))
    reg.register(SlashCommandSpec("foo", "v2", second))
    assert reg.get("foo").description == "v2"


@pytest.mark.asyncio
async def test_dispatch_routes_to_handler():
    reg = SlashRegistry()
    captured = []

    async def h(client, args):
        captured.append(args)
        return "done"

    reg.register(SlashCommandSpec("echo", "echo args", h))
    result = await reg.dispatch(_FakeClient(), "/echo hello world")
    assert result == "done"
    assert captured == ["hello world"]


@pytest.mark.asyncio
async def test_dispatch_supports_sync_handler():
    reg = SlashRegistry()

    def sync_h(client, args):
        return f"sync:{args}"

    reg.register(SlashCommandSpec("s", "sync", sync_h))
    assert await reg.dispatch(_FakeClient(), "/s hi") == "sync:hi"


@pytest.mark.asyncio
async def test_dispatch_unknown_command_raises():
    reg = SlashRegistry()
    with pytest.raises(UnknownSlashCommandError):
        await reg.dispatch(_FakeClient(), "/missing")


@pytest.mark.asyncio
async def test_dispatch_non_slash_line_raises_value_error():
    reg = SlashRegistry()
    with pytest.raises(ValueError):
        await reg.dispatch(_FakeClient(), "not a slash command")


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_status_shows_running_session():
    client = _FakeClient()
    output = await handle_status(client, "")
    assert "running" in output
    assert "ses_abc123" in output
    assert "claude-sonnet-4-5-20250929" in output
    assert "tools called: 3" in output
    assert "files read: 2" in output
    assert "files modified: 1" in output
    assert "loadSession" in output


@pytest.mark.asyncio
async def test_handle_status_shows_stopped_session():
    client = _FakeClient(running=False, session_id_value="", model=None)
    output = await handle_status(client, "")
    assert "stopped" in output
    assert "<none>" in output


@pytest.mark.asyncio
async def test_handle_status_with_no_capabilities():
    client = _FakeClient(capabilities={})
    output = await handle_status(client, "")
    assert "(none reported)" in output


@pytest.mark.asyncio
async def test_handle_model():
    assert "claude" in await handle_model(_FakeClient(), "")
    assert await handle_model(_FakeClient(model=None), "") == "no model selected"


@pytest.mark.asyncio
async def test_handle_session_reports_resume_support():
    client = _FakeClient()
    output = await handle_session(client, "")
    assert "ses_abc123" in output
    assert "supports resume: yes" in output


@pytest.mark.asyncio
async def test_handle_session_no_resume():
    client = _FakeClient(capabilities={"loadSession": False})
    assert "supports resume: no" in await handle_session(client, "")


@pytest.mark.asyncio
async def test_handle_history_empty():
    client = _FakeClient()
    out = await handle_history(client, "")
    assert "no persisted sessions" in out
    assert "this project" in out


@pytest.mark.asyncio
async def test_handle_history_with_sessions():
    client = _FakeClient(
        persisted=[
            _FakeStoredSession("ses_1", "feature work"),
            _FakeStoredSession("ses_2", ""),
        ]
    )
    out = await handle_history(client, "")
    assert "sessions (2" in out
    assert "ses_1" in out
    assert "feature work" in out
    assert "ses_2" in out


@pytest.mark.asyncio
async def test_handle_history_honors_all_flag():
    client = _FakeClient()
    out = await handle_history(client, "--all")
    assert "all projects" in out


@pytest.mark.asyncio
async def test_handle_history_honors_limit_flag():
    sessions = [_FakeStoredSession(f"ses_{i}") for i in range(10)]
    client = _FakeClient(persisted=sessions)
    out = await handle_history(client, "--limit=3")
    # the fake honors the limit kwarg
    assert out.count("\n") == 3  # header + 3 entries -> 3 newlines


@pytest.mark.asyncio
async def test_handle_history_reports_errors():
    client = _FakeClient(raise_on="list_persisted_sessions")
    out = await handle_history(client, "")
    assert "history unavailable" in out
    assert "storage down" in out


@pytest.mark.asyncio
async def test_handle_commands_empty():
    out = await handle_commands(_FakeClient(), "")
    assert "no slash commands" in out


@pytest.mark.asyncio
async def test_handle_commands_lists_agent_commands():
    client = _FakeClient(
        available_commands=[
            {"name": "init", "description": "Initialize project"},
            {"name": "review", "description": "Run code review"},
        ]
    )
    out = await handle_commands(client, "")
    assert "/init" in out
    assert "Initialize project" in out
    assert "/review" in out


@pytest.mark.asyncio
async def test_handle_commands_reports_errors():
    client = _FakeClient(raise_on="get_available_commands")
    out = await handle_commands(client, "")
    assert "agent busy" in out


@pytest.mark.asyncio
async def test_handle_clear_success():
    client = _FakeClient()
    out = await handle_clear(client, "")
    assert "cleared" in out
    assert client.reset_called


@pytest.mark.asyncio
async def test_handle_clear_no_change():
    client = _FakeClient(reset_result=False)
    out = await handle_clear(client, "")
    assert "no change" in out


@pytest.mark.asyncio
async def test_handle_clear_error():
    client = _FakeClient(raise_on="reset_session")
    out = await handle_clear(client, "")
    assert "clear failed" in out


# ---------------------------------------------------------------------------
# builtin_registry
# ---------------------------------------------------------------------------


def test_builtin_registry_contains_expected_commands():
    reg = builtin_registry()
    names = {spec.name for spec in reg.list_commands()}
    assert names == {"status", "model", "session", "history", "commands", "clear", "help"}


@pytest.mark.asyncio
async def test_builtin_help_lists_all_registered():
    reg = builtin_registry()
    out = await reg.dispatch(_FakeClient(), "/help")
    for expected in ("status", "model", "session", "history", "commands", "clear", "help"):
        assert expected in out


@pytest.mark.asyncio
async def test_builtin_status_end_to_end():
    reg = builtin_registry()
    out = await reg.dispatch(_FakeClient(), "/status")
    assert "ACP session: running" in out
