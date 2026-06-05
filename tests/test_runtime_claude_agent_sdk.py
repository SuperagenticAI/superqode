"""Tests for the Claude Agent SDK runtime adapter.

Where possible these exercise the adapter against the *real* installed
``claude_agent_sdk`` types (message/block/options), which doubles as a drift
guard. No network/CLI is touched — only pure mapping + logic.
"""

from __future__ import annotations

import sys

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime import create_runtime, known_runtime_names
from superqode.runtime.errors import RuntimeNotInstalledError
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager

pytest.importorskip("claude_agent_sdk")


def _cfg(tmp_path, model=""):
    return AgentConfig(
        provider="anthropic",
        model=model,
        working_directory=tmp_path,
        enable_session_storage=False,
        session_id="claude-test",
    )


def test_registry_knows_claude_agent_sdk():
    assert "claude-agent-sdk" in known_runtime_names()


def test_missing_extra_raises(monkeypatch, tmp_path):
    # Simulate the SDK not installed even though it is in this env.
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    with pytest.raises(RuntimeNotInstalledError):
        create_runtime("claude-agent-sdk", config=_cfg(tmp_path))


def test_event_mapping_assistant_text_and_tool(tmp_path):
    from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

    rt = create_runtime("claude-agent-sdk", config=_cfg(tmp_path))
    names: dict = {}
    msg = AssistantMessage(
        content=[
            TextBlock(text="hello"),
            ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}),
        ],
        model="claude-x",
    )
    events = rt._events_from_message(msg, names)
    types = [e.type for e in events]
    assert "model_delta" in types and "tool_call" in types
    assert names["t1"] == "Bash"
    tool_ev = next(e for e in events if e.type == "tool_call")
    assert tool_ev.data["tool_name"] == "Bash"
    assert tool_ev.data["args"] == {"command": "ls"}


def test_event_mapping_tool_result_and_result(tmp_path):
    from claude_agent_sdk import ResultMessage, ToolResultBlock, UserMessage

    rt = create_runtime("claude-agent-sdk", config=_cfg(tmp_path))
    names = {"t1": "Bash"}
    um = UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="files…", is_error=False)])
    tr = rt._events_from_message(um, names)
    assert tr and tr[0].type == "tool_result"
    assert tr[0].data["tool_name"] == "Bash" and tr[0].data["success"] is True

    rm = ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s1",
    )
    out = rt._events_from_message(rm, names)
    assert out and out[0].type == "turn_complete" and out[0].data["status"] == "completed"
    assert rt.thread_id == "s1"


def test_default_approval_denies_without_callback(tmp_path):
    rt = create_runtime("claude-agent-sdk", config=_cfg(tmp_path))
    decision, reason = rt._decide_permission("bash", {"command": "ls"})
    assert decision == "deny" and "interactive approval" in reason


def test_approval_uses_callback_when_default_pm(tmp_path):
    calls = []
    rt = create_runtime(
        "claude-agent-sdk",
        config=_cfg(tmp_path),
        approval_callback=lambda n, a: calls.append((n, a)) or True,
    )
    assert rt._decide_permission("bash", {"command": "ls"})[0] == "allow"
    assert calls and calls[0][0] == "bash"


def test_explicit_permission_manager(tmp_path):
    allow = PermissionManager(PermissionConfig(default=Permission.ALLOW))
    rt = create_runtime("claude-agent-sdk", config=_cfg(tmp_path), permission_manager=allow)
    assert rt._decide_permission("bash", {})[0] == "allow"


def test_setters_validate(tmp_path):
    rt = create_runtime("claude-agent-sdk", config=_cfg(tmp_path))
    rt.set_model("claude-opus-4-8")
    assert rt.config.model == "claude-opus-4-8"
    rt.set_reasoning_effort("high")
    assert rt.reasoning_effort == "high"
    rt.set_permission_mode("plan")
    assert rt.permission_mode == "plan"
    with pytest.raises(ValueError):
        rt.set_reasoning_effort("turbo")
    with pytest.raises(ValueError):
        rt.set_permission_mode("yolo")


def test_models_curated_list(tmp_path):
    rt = create_runtime("claude-agent-sdk", config=_cfg(tmp_path))
    ids = {m["id"] for m in rt.models()}
    assert "claude-opus-4-8" in ids and "" in ids  # "" = Claude Code default


def test_options_keys_match_real_sdk_contract(tmp_path):
    """Drift guard: every ClaudeAgentOptions key the adapter sets must be real."""
    import dataclasses

    from claude_agent_sdk import ClaudeAgentOptions

    allowed = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    used = {"cwd", "can_use_tool", "model", "permission_mode", "effort", "system_prompt", "resume"}
    assert used <= allowed, used - allowed


def test_tool_name_normalized_for_permission_check(tmp_path):
    """Claude's 'Bash' must be normalized to 'bash' so SHELL policy applies
    (raw 'Bash' would slip past group checks)."""
    from superqode.tools.permissions import PermissionConfig, PermissionManager, ToolGroup

    pm = PermissionManager(
        PermissionConfig(default=Permission.ALLOW, groups={ToolGroup.SHELL: Permission.DENY})
    )
    rt = create_runtime("claude-agent-sdk", config=_cfg(tmp_path), permission_manager=pm)
    assert rt._decide_permission("Bash", {"command": "ls"})[0] == "deny"


def test_pure_mode_passes_approval_bridge_to_claude(tmp_path, monkeypatch):
    """The TUI approval callback must reach the Claude runtime (not only Codex)."""
    import superqode.pure_mode as pm_mod

    captured = {}

    def _fake_create_runtime(name, **kwargs):
        captured["name"] = name
        captured["approval_callback"] = kwargs.get("approval_callback")
        return object()

    monkeypatch.setattr(pm_mod, "create_runtime", _fake_create_runtime)
    pure = pm_mod.PureMode()
    pure.runtime_name = "claude-agent-sdk"
    pure.on_permission_request = lambda n, a: True
    pure.connect(provider="anthropic", model="")
    assert captured["name"] == "claude-agent-sdk"
    assert captured["approval_callback"] is not None


def test_handle_harness_event_tool_call_then_result_no_double_card():
    """A tool_call followed by its tool_result must produce ONE tool-call card."""
    from superqode.harness.events import HarnessEvent
    from superqode.pure_mode import PureMode

    pure = PureMode()
    calls, results = [], []
    pure.on_tool_call = lambda name, args: calls.append((name, args))
    pure.on_tool_result = lambda name, res: results.append(name)
    pure._runtime_seen_tool_calls = set()

    pure._handle_runtime_harness_event(
        HarnessEvent(
            type="tool_call",
            data={"tool_name": "Bash", "tool_call_id": "t1", "args": {"command": "ls"}},
        )
    )
    pure._handle_runtime_harness_event(
        HarnessEvent(
            type="tool_result",
            data={"tool_name": "Bash", "tool_call_id": "t1", "success": True, "output": "x"},
        )
    )
    assert len(calls) == 1  # not doubled
    assert results == ["Bash"]
