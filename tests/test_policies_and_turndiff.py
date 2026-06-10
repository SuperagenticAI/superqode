"""Tests for shell env policy, exec policy rules, turn-diff, background bash, auto-memory."""

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from superqode.agent.auto_memory import _parse_memory_array, extract_session_memories
from superqode.agent.exec_policy import ExecPolicy, ExecRule
from superqode.tools.base import ToolContext, ToolResult
from superqode.tools.diff_utils import summarize_turn_changes
from superqode.tools.env_policy import ALLOW_ENV, POLICY_ENV, build_shell_env
from superqode.tools.shell_tools import BashTool


# ----------------------------------------------------------- env policy


def test_env_inherit_by_default(monkeypatch):
    monkeypatch.delenv(POLICY_ENV, raising=False)
    assert build_shell_env() is None  # callers inherit verbatim


def test_env_filter_secrets(monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "filter-secrets")
    base = {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "sk-secret",
        "MY_TOKEN": "t",
        "DB_PASSWORD": "p",
        "AWS_SECRET_ACCESS_KEY": "k",
        "HOME": "/Users/x",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
    }
    filtered = build_shell_env(base)
    assert filtered is not None
    assert "PATH" in filtered and "HOME" in filtered
    assert "OPENAI_API_KEY" not in filtered
    assert "MY_TOKEN" not in filtered
    assert "DB_PASSWORD" not in filtered
    assert "AWS_SECRET_ACCESS_KEY" not in filtered
    assert "SSH_AUTH_SOCK" in filtered  # always kept


def test_env_allowlist(monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "filter-secrets")
    monkeypatch.setenv(ALLOW_ENV, "OPENAI_API_KEY")
    filtered = build_shell_env({"OPENAI_API_KEY": "sk", "OTHER_TOKEN": "t"})
    assert "OPENAI_API_KEY" in filtered
    assert "OTHER_TOKEN" not in filtered


@pytest.mark.asyncio
async def test_bash_respects_env_filter(tmp_path, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "filter-secrets")
    monkeypatch.setenv("LEAKY_API_KEY", "should-not-appear")
    ctx = ToolContext(session_id="t", working_directory=tmp_path)
    result = await BashTool(git_guard_enabled=False).execute(
        {"command": "printenv LEAKY_API_KEY || echo FILTERED"}, ctx
    )
    assert result.success
    assert "should-not-appear" not in result.output
    assert "FILTERED" in result.output


# ----------------------------------------------------------- exec policy


def test_exec_rule_glob_and_regex():
    glob_rule = ExecRule(pattern="git status*", action="allow")
    assert glob_rule.matches("git status --short")
    assert not glob_rule.matches("git push")
    re_rule = ExecRule(pattern=r"re:^rm\s+-rf", action="deny")
    assert re_rule.matches("rm -rf build")
    assert not re_rule.matches("firm -rf")


def test_exec_policy_first_match_wins():
    policy = ExecPolicy(
        [
            ExecRule(pattern="git push*", action="ask"),
            ExecRule(pattern="git *", action="allow"),
        ]
    )
    assert policy.evaluate("git push origin main").action == "ask"
    assert policy.evaluate("git log").action == "allow"
    assert policy.evaluate("npm install") is None


def test_exec_policy_loads_yaml(tmp_path, monkeypatch):
    policy_file = tmp_path / "execpolicy.yaml"
    policy_file.write_text(
        "rules:\n"
        "  - pattern: 'npm publish*'\n"
        "    action: deny\n"
        "    reason: 'no publishing from agents'\n"
        "  - pattern: 'pytest*'\n"
        "    action: allow\n"
        "  - pattern: 'badaction*'\n"
        "    action: bogus\n"  # invalid action: skipped
    )
    monkeypatch.setenv("SUPERQODE_EXEC_POLICY", str(policy_file))
    policy = ExecPolicy.load(tmp_path)
    assert policy.evaluate("npm publish --tag latest").action == "deny"
    assert policy.evaluate("pytest -q").action == "allow"
    assert policy.evaluate("badaction now") is None


@pytest.mark.asyncio
async def test_exec_policy_deny_blocks_in_loop(tmp_path, monkeypatch):
    policy_file = tmp_path / "execpolicy.yaml"
    policy_file.write_text("rules:\n  - pattern: 'rm -rf*'\n    action: deny\n    reason: nope\n")
    monkeypatch.setenv("SUPERQODE_EXEC_POLICY", str(policy_file))

    from superqode.agent.loop import AgentConfig, AgentLoop
    from superqode.tools.base import ToolRegistry

    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(provider="x", model="y", working_directory=tmp_path)
    from superqode.agent.hooks import HookRegistry
    from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager

    loop.hooks = HookRegistry()
    loop.session_id = "t"
    loop._current_iteration = 0
    loop.permission_manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))
    loop._approved_tool_call_ids = set()
    loop.pause_on_approval = False
    loop.tools = ToolRegistry.empty()

    denied = await loop._check_tool_permission("bash", {"command": "rm -rf /tmp/x"})
    assert denied is not None
    assert "exec policy" in (denied.error or "")
    assert denied.metadata["permission"] == "exec_policy_deny"

    allowed = await loop._check_tool_permission("bash", {"command": "echo hi"})
    assert allowed is None  # no rule: normal flow (manager default ALLOW)


# ------------------------------------------------------------- turn diff


def test_summarize_turn_changes_aggregates():
    results = [
        ToolResult(
            success=True,
            output="",
            metadata={
                "path": "a.py",
                "diff_text": "--- a\n+++ b\n+x",
                "additions": 3,
                "deletions": 1,
            },
        ),
        ToolResult(success=True, output="no diff here"),
        ToolResult(
            success=True,
            output="",
            metadata={
                "path": "b.py",
                "diff_text": "--- a\n+++ b\n-y",
                "additions": 0,
                "deletions": 2,
            },
        ),
    ]
    summary, combined = summarize_turn_changes(results)
    assert "2 file(s)" in summary
    assert "+3/-3" in summary
    assert "a.py" in summary and "b.py" in summary
    assert combined.count("+++") == 2


def test_summarize_turn_changes_empty():
    summary, combined = summarize_turn_changes([ToolResult(success=True, output="x")])
    assert summary == "" and combined == ""


# -------------------------------------------------------- background bash


@pytest.mark.asyncio
async def test_bash_run_in_background_returns_session(tmp_path):
    from superqode.tools import shell_session as ss

    ctx = ToolContext(session_id="t", working_directory=tmp_path)
    result = await BashTool(git_guard_enabled=False).execute(
        {"command": "sleep 5", "run_in_background": True}, ctx
    )
    try:
        assert result.success, result.error
        sid = result.metadata.get("session_id")
        assert sid
        assert "shell_session" in result.output  # tells the model how to follow up
        assert result.metadata.get("running") is True
    finally:
        ss._cleanup_all_sessions()


# ----------------------------------------------------------- auto-memory


def test_parse_memory_array_lenient():
    raw = 'Here you go:\n```json\n[{"kind": "preference", "content": "Use pnpm, never npm in this repo"}]\n```'
    parsed = _parse_memory_array(raw)
    assert parsed == [{"kind": "preference", "content": "Use pnpm, never npm in this repo"}]
    assert _parse_memory_array("no json at all") == []
    assert _parse_memory_array("[]") == []
    # Bad kinds normalize; tiny/huge contents are dropped.
    parsed = _parse_memory_array(
        '[{"kind": "weird", "content": "A real durable project fact here"}]'
    )
    assert parsed[0]["kind"] == "fact"
    assert _parse_memory_array('[{"kind": "fact", "content": "tiny"}]') == []


class _StubStore:
    def __init__(self):
        self.stored: List[Dict[str, Any]] = []

    def search(self, query, limit=1):
        return []

    def remember(self, content, *, kind="note", scope="project", tags=()):
        self.stored.append({"content": content, "kind": kind, "tags": tags})
        return SimpleNamespace(content=content)


class _MemoryGateway:
    async def chat_completion(self, messages, model, provider=None, **kwargs):
        return SimpleNamespace(
            content='[{"kind": "fact", "content": "Tests require the DS4 server running locally"}]'
        )


@pytest.mark.asyncio
async def test_extract_session_memories_stores(tmp_path):
    messages = [
        SimpleNamespace(role="user", content=f"message number {i} with enough text to count")
        for i in range(8)
    ]
    store = _StubStore()
    stored = await extract_session_memories(
        messages, _MemoryGateway(), "test", "test-model", tmp_path, store=store
    )
    assert stored == 1
    assert store.stored[0]["kind"] == "fact"
    assert "DS4" in store.stored[0]["content"]


@pytest.mark.asyncio
async def test_extract_skips_trivial_sessions(tmp_path):
    messages = [SimpleNamespace(role="user", content="hi")]
    stored = await extract_session_memories(
        messages, _MemoryGateway(), "test", "test-model", tmp_path, store=_StubStore()
    )
    assert stored == 0
