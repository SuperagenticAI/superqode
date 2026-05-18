"""Phase 6 tests: HITL approval surface on OpenAIAgentsRuntime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from superqode.agent.loop import AgentConfig
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult

pytest.importorskip("agents", reason="openai-agents not installed")

from superqode.runtime.openai_agents import OpenAIAgentsRuntime  # noqa: E402


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output=args.get("text", ""))


def _registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(_EchoTool())
    return r


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        provider="openai",
        model="gpt-4o-mini",
        working_directory=tmp_path,
        enable_session_storage=False,
        session_id="hitl-test",
    )


class _FakeApprovalItem:
    """Stand-in for agents.items.ToolApprovalItem."""

    def __init__(self, tool_name: str, args: Dict[str, Any]):
        self.tool_name = tool_name

        class _Raw:
            pass

        raw = _Raw()
        raw.name = tool_name
        raw.arguments = args
        self.raw_item = raw


class _FakeState:
    """Stand-in for agents.run_state.RunState; records approve/reject calls."""

    def __init__(self):
        self.approved = []
        self.rejected = []

    def approve(self, item, always_approve: bool = False):
        self.approved.append((item, always_approve))

    def reject(self, item, always_reject: bool = False, rejection_message: str | None = None):
        self.rejected.append((item, always_reject, rejection_message))


class _FakeResult:
    """Stand-in for an interrupted RunResult."""

    def __init__(self, items, state: _FakeState):
        self.interruptions = items
        self._state = state
        self.new_items: list = []
        self.raw_responses: list = []
        self.final_output = ""

    def to_state(self):
        return self._state


def test_get_pending_approvals_empty_when_no_pending(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    assert runtime.get_pending_approvals() == []


def test_get_pending_approvals_returns_serializable_entries(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    runtime.pending_state = _FakeResult(
        items=[_FakeApprovalItem("bash", {"command": "ls"})],
        state=_FakeState(),
    )
    pending = runtime.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0]["index"] == 0
    assert pending[0]["tool_name"] == "bash"
    assert pending[0]["arguments"] == {"command": "ls"}


def test_take_pending_returns_state_and_item(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    state = _FakeState()
    item = _FakeApprovalItem("bash", {"command": "ls"})
    runtime.pending_state = _FakeResult(items=[item], state=state)
    s, i = runtime._take_pending(0)
    assert s is state
    assert i is item


def test_take_pending_raises_when_no_pending(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    with pytest.raises(RuntimeError):
        runtime._take_pending(0)


def test_take_pending_raises_on_out_of_range(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    runtime.pending_state = _FakeResult(items=[_FakeApprovalItem("bash", {})], state=_FakeState())
    with pytest.raises(RuntimeError):
        runtime._take_pending(5)


@pytest.mark.asyncio
async def test_approve_and_resume_records_approval_and_clears_pending(tmp_path, monkeypatch):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    state = _FakeState()
    item = _FakeApprovalItem("bash", {"command": "ls"})
    runtime.pending_state = _FakeResult(items=[item], state=state)

    async def fake_resume(_state):
        # Mimic a completed resume that produced no further interruptions.
        return runtime._translate_result(prompt="", result=_FakeResult(items=[], state=state))

    monkeypatch.setattr(runtime, "resume", fake_resume)
    resp = await runtime.approve_and_resume(index=0, always=True)
    assert state.approved == [(item, True)]
    assert runtime.pending_state is None
    assert resp.stopped_reason == "complete"


@pytest.mark.asyncio
async def test_reject_and_resume_records_message(tmp_path, monkeypatch):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    state = _FakeState()
    item = _FakeApprovalItem("delete_file", {"path": "secret.txt"})
    runtime.pending_state = _FakeResult(items=[item], state=state)

    async def fake_resume(_state):
        return runtime._translate_result(prompt="", result=_FakeResult(items=[], state=state))

    monkeypatch.setattr(runtime, "resume", fake_resume)
    await runtime.reject_and_resume(index=0, message="not now")
    assert state.rejected == [(item, False, "not now")]


@pytest.mark.asyncio
async def test_reject_without_message_omits_kwarg(tmp_path, monkeypatch):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    state = _FakeState()
    item = _FakeApprovalItem("bash", {})
    runtime.pending_state = _FakeResult(items=[item], state=state)

    async def fake_resume(_state):
        return runtime._translate_result(prompt="", result=_FakeResult(items=[], state=state))

    monkeypatch.setattr(runtime, "resume", fake_resume)
    await runtime.reject_and_resume(index=0)
    # Default-kwargs path: rejection_message stays default (None handled by SDK).
    assert state.rejected and state.rejected[0][0] is item


def test_clear_pending_drops_state(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    runtime.pending_state = _FakeResult(items=[_FakeApprovalItem("bash", {})], state=_FakeState())
    runtime.clear_pending()
    assert runtime.pending_state is None


def test_translate_result_with_interruptions_sets_needs_approval(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    fake = _FakeResult(items=[_FakeApprovalItem("bash", {})], state=_FakeState())
    resp = runtime._translate_result(prompt="run a thing", result=fake)
    assert resp.stopped_reason == "needs_approval"
    assert runtime.pending_state is fake
