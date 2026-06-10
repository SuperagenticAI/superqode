"""Tests for persistent interactive shell sessions."""

import pytest

from superqode.tools import shell_session as ss
from superqode.tools.base import ToolContext
from superqode.tools.shell_session import ShellSessionTool


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    ss._cleanup_all_sessions()


def _ctx(tmp_path) -> ToolContext:
    return ToolContext(session_id="t", working_directory=tmp_path)


@pytest.mark.asyncio
async def test_open_quick_command_returns_output_and_exit(tmp_path):
    result = await ShellSessionTool().execute(
        {"action": "open", "command": "echo hello-session", "yield_ms": 3000},
        _ctx(tmp_path),
    )
    assert result.success, result.error
    assert "hello-session" in result.output
    assert result.metadata["session_id"]
    assert result.metadata["running"] is False
    assert result.metadata["exit_code"] == 0


@pytest.mark.asyncio
async def test_interactive_write_roundtrip(tmp_path):
    tool = ShellSessionTool()
    opened = await tool.execute(
        {"action": "open", "command": "cat", "yield_ms": 300}, _ctx(tmp_path)
    )
    assert opened.success
    sid = opened.metadata["session_id"]
    assert opened.metadata["running"] is True

    reply = await tool.execute(
        {"action": "write", "session_id": sid, "input": "ping-42", "yield_ms": 3000},
        _ctx(tmp_path),
    )
    assert reply.success, reply.error
    assert "ping-42" in reply.output  # cat echoes it back (PTY also echoes input)

    killed = await tool.execute({"action": "kill", "session_id": sid}, _ctx(tmp_path))
    assert killed.success


@pytest.mark.asyncio
async def test_poll_returns_only_new_output(tmp_path):
    tool = ShellSessionTool()
    opened = await tool.execute(
        {
            "action": "open",
            "command": "echo first; sleep 0.5; echo second; sleep 30",
            "yield_ms": 1000,
        },
        _ctx(tmp_path),
    )
    sid = opened.metadata["session_id"]
    assert "first" in opened.output

    polled = await tool.execute(
        {"action": "poll", "session_id": sid, "yield_ms": 3000}, _ctx(tmp_path)
    )
    assert "second" in polled.output
    assert "first" not in polled.output.replace("first", "first") or "first" not in polled.output

    await tool.execute({"action": "kill", "session_id": sid}, _ctx(tmp_path))


@pytest.mark.asyncio
async def test_list_and_kill(tmp_path):
    tool = ShellSessionTool()
    opened = await tool.execute(
        {"action": "open", "command": "sleep 30", "yield_ms": 200}, _ctx(tmp_path)
    )
    sid = opened.metadata["session_id"]

    listed = await tool.execute({"action": "list"}, _ctx(tmp_path))
    assert sid in listed.output
    assert any(s["session_id"] == sid for s in listed.metadata["sessions"])

    killed = await tool.execute({"action": "kill", "session_id": sid}, _ctx(tmp_path))
    assert killed.success
    listed_after = await tool.execute({"action": "list"}, _ctx(tmp_path))
    assert sid not in listed_after.output


@pytest.mark.asyncio
async def test_unknown_session_and_action_errors(tmp_path):
    tool = ShellSessionTool()
    missing = await tool.execute({"action": "poll", "session_id": "nope"}, _ctx(tmp_path))
    assert missing.success is False
    assert "No such session" in (missing.error or "")

    bogus = await tool.execute({"action": "dance"}, _ctx(tmp_path))
    assert bogus.success is False
    assert "Unknown action" in (bogus.error or "")


@pytest.mark.asyncio
async def test_write_to_exited_session_errors(tmp_path):
    tool = ShellSessionTool()
    opened = await tool.execute(
        {"action": "open", "command": "true", "yield_ms": 1500}, _ctx(tmp_path)
    )
    sid = opened.metadata["session_id"]
    assert opened.metadata["running"] is False
    result = await tool.execute(
        {"action": "write", "session_id": sid, "input": "hi"}, _ctx(tmp_path)
    )
    assert result.success is False


@pytest.mark.asyncio
async def test_open_requires_command_and_validates_cwd(tmp_path):
    tool = ShellSessionTool()
    no_cmd = await tool.execute({"action": "open"}, _ctx(tmp_path))
    assert no_cmd.success is False

    escape = await tool.execute(
        {"action": "open", "command": "echo hi", "working_dir": "/"}, _ctx(tmp_path)
    )
    assert escape.success is False


def test_shell_session_is_mutating():
    assert ShellSessionTool.read_only is False
