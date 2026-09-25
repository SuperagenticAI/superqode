"""Query-aware tool-output pruning at the compaction boundary."""

from __future__ import annotations

import json

import pytest

from superqode.agent.hooks import HookRegistry
from superqode.agent.loop import AgentConfig, AgentLoop, AgentMessage
from superqode.tools.base import ToolContext, ToolRegistry
from superqode.tools.context_tools import ReadContextChunkTool
from superqode.systemone.client import StubSystemOneClient, SystemOneError
from superqode.systemone.context_prune import (
    apply_context_prune,
    build_state,
    cache_plan,
    context_original,
)
from superqode.systemone.pack import load_pack
from superqode.systemone.state import prepare_decision_state


class _FakeContextManager:
    def count_tokens(self, messages):
        return sum(max(1, len(str(m.get("content", ""))) // 4) for m in messages)


def _loop(window=4096):
    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(provider="x", model="y", context_window=window)
    loop.context_manager = _FakeContextManager()
    loop._cached_context_window = window
    loop.hooks = HookRegistry()
    loop.on_thinking = None
    loop.session_id = "test-session"
    loop._current_iteration = 0
    loop._systemone_client = None
    loop._context_originals = {}
    return loop


def _history(tool_output: str, *, arguments: str = '{"path": "src/app.py"}'):
    return [
        AgentMessage(role="system", content="system prompt"),
        AgentMessage(role="user", content="Fix the failing test."),
        AgentMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "function": {"name": "bash", "arguments": arguments},
                }
            ],
        ),
        AgentMessage(role="tool", content=tool_output, tool_call_id="call-1", name="bash"),
        AgentMessage(role="assistant", content="I read the output."),
        AgentMessage(role="user", content="Apply the fix in src/app.py."),
        AgentMessage(role="assistant", content="Working on the fix."),
    ]


def _answers(keep_output: float, keep_call: float = 0.2, same_task: float = 0.9):
    return {
        "same_task": {"noul": same_task},
        "keep_call_0": {"noul": keep_call},
        "keep_output_0": {"noul": keep_output},
    }


@pytest.mark.asyncio
async def test_default_compaction_leaves_the_system_prompt_and_prunes_as_before(monkeypatch):
    monkeypatch.delenv("SUPERQODE_JEV_CONTEXT", raising=False)
    monkeypatch.delenv("SUPERQODE_CONDITIONAL_INSTRUCTIONS", raising=False)
    monkeypatch.delenv("SUPERQODE_AUTO_COMPACT", raising=False)
    loop = _loop(window=4096)
    messages = _history("X" * 30_000)
    messages[0] = AgentMessage(role="system", content="system prompt\n\n")

    async def _no_summarize(*args, **kwargs):
        return None

    monkeypatch.setattr("superqode.agent.compaction.compact_history", _no_summarize)
    result = await loop._maybe_summarize(messages)
    assert result[0] is messages[0]
    assert result[0].content == "system prompt\n\n"
    tool = next(message for message in result if message.role == "tool")
    assert "removed to save context" in tool.content
    assert not hasattr(loop, "last_context_prune") or loop.last_context_prune is None


def test_pack_loads_with_confident_false_cutoff():
    pack = load_pack("context_prune")
    assert pack.context_policy is not None
    assert pack.context_policy.keep_below == 0.4
    assert pack.content_hash().startswith("sha256:")
    assert "keep_output" in pack.wire_questions()


@pytest.mark.asyncio
async def test_context_prune_off_does_not_call_the_client():
    loop = _loop()
    client = StubSystemOneClient(_answers(0.1))
    loop._systemone_client = client
    messages = _history("X" * 4000)
    updated, event = await apply_context_prune(loop, messages, keep_recent=10, threshold=100)
    assert updated == messages
    assert event["fallback"] == "disabled"
    assert client.calls == []


@pytest.mark.asyncio
async def test_shadow_records_a_stub_without_changing_the_prompt(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "shadow")
    loop = _loop()
    loop._systemone_client = StubSystemOneClient(_answers(0.1))
    messages = _history("X" * 8000)
    updated, event = await apply_context_prune(loop, messages, keep_recent=20, threshold=50)
    assert updated[3].content == messages[3].content
    assert event["applied"] is False
    assert event["status"] == "success"
    assert event["chunks"][0]["action"] == "stub"
    assert event["chunks"][0]["id"] == "tool-call-1"
    assert event["cache"]["recommended_action"] == "rebuild"
    assert event["cache"]["applied_action"] == "reuse"
    assert event["pack_hash"].startswith("sha256:")
    assert "example-secret" not in json.dumps(event)


@pytest.mark.asyncio
async def test_uncertain_output_stays_verbatim(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "enforce")
    loop = _loop()
    loop._systemone_client = StubSystemOneClient(_answers(0.5))
    messages = _history("X" * 8000)
    updated, event = await apply_context_prune(loop, messages, keep_recent=20, threshold=50)
    assert updated[3].content == messages[3].content
    assert event["fallback"] == "nothing_to_stub"
    assert event["chunks"][0]["action"] == "keep"


@pytest.mark.asyncio
async def test_enforce_stubs_only_when_the_cut_fits(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "enforce")
    monkeypatch.delenv("SUPERQODE_AUTO_COMPACT", raising=False)
    loop = _loop(window=4096)
    loop.tools = ToolRegistry.empty()
    loop._systemone_client = StubSystemOneClient(_answers(0.05))
    original = _history("TRACE " + ("Y" * 30_000))
    summarized = {"called": False}

    async def _no_summarize(*args, **kwargs):
        summarized["called"] = True
        return None

    monkeypatch.setattr("superqode.agent.compaction.compact_history", _no_summarize)
    result = await loop._maybe_summarize(original)
    tool = next(message for message in result if message.role == "tool")
    assert "context chunk tool-call-1" in tool.content
    assert tool.tool_call_id == "call-1"
    assert "TRACE" in tool.content
    assert len(original[3].content) > 30_000
    assert context_original(loop, "tool-call-1").startswith("TRACE")
    assert summarized["called"] is False
    assert [message.role for message in result] == [message.role for message in original]
    assert result[1].content == "Fix the failing test."
    assert loop.last_context_prune["applied"] is True
    assert loop.last_context_prune["cache"]["applied_action"] == "rebuild"
    assert loop.tools.get("read_context_chunk") is not None
    ctx = ToolContext(
        session_id="test-session",
        working_directory=loop.config.working_directory,
        context_chunk=loop._context_chunk,
    )
    restored = await ReadContextChunkTool().execute({"chunk_id": "tool-call-1"}, ctx)
    assert restored.success is True
    assert restored.output.startswith("TRACE")
    missing = await ReadContextChunkTool().execute({"chunk_id": "missing"}, ctx)
    assert missing.success is False


@pytest.mark.asyncio
async def test_enforce_keep_is_not_blindly_stubbed(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "enforce")
    monkeypatch.delenv("SUPERQODE_AUTO_COMPACT", raising=False)
    loop = _loop(window=4096)
    loop.gateway = None
    loop._systemone_client = StubSystemOneClient(_answers(0.95))
    original = _history("TRACE " + ("Y" * 30_000))

    async def _summarize(head, *args, **kwargs):
        return "SUMMARY"

    monkeypatch.setattr("superqode.agent.compaction.compact_history", _summarize)
    result = await loop._maybe_summarize(original)
    rendered = "\n".join(message.content or "" for message in result)
    assert "removed to save context" not in rendered
    assert "TRACE" in rendered
    assert loop.last_context_prune["chunks"][0]["action"] == "keep"


@pytest.mark.asyncio
async def test_small_cut_falls_back(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "enforce")
    loop = _loop()
    loop._systemone_client = StubSystemOneClient(_answers(0.05))
    messages = _history("Z" * 400)
    messages.append(AgentMessage(role="user", content="notes " * 4000))
    updated, event = await apply_context_prune(loop, messages, keep_recent=10, threshold=100_000)
    assert updated[3].content == messages[3].content
    assert event["fallback"] == "low_reduction"
    assert event["applied"] is False


@pytest.mark.asyncio
async def test_client_error_leaves_the_prompt(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "enforce")
    loop = _loop()
    loop._systemone_client = StubSystemOneClient(error=SystemOneError("down"))
    messages = _history("X" * 8000)
    updated, event = await apply_context_prune(loop, messages, keep_recent=20, threshold=50)
    assert updated == messages
    assert event["fallback"] == "evaluation_failed"
    assert event["applied"] is False


@pytest.mark.asyncio
async def test_decision_state_omits_tool_bodies_and_redacts_secrets(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "shadow")
    secret = "example-secret"
    loop = _loop()
    client = StubSystemOneClient(_answers(0.1))
    loop._systemone_client = client
    output = f"API_KEY={secret}\n" + ("log line\n" * 400)
    messages = _history(output, arguments=f'{{"command": "curl -H \\"token: {secret}\\""}}')
    await apply_context_prune(loop, messages, keep_recent=20, threshold=50)
    state = client.calls[0][0]
    blob = json.dumps(state)
    assert secret not in blob
    assert "log line" not in blob
    assert "[redacted]" in blob
    prepared = prepare_decision_state(build_state(messages, [], limit=4000)[0])
    assert secret not in json.dumps(prepared)


def test_cache_plan_is_deterministic():
    same = cache_plan(same_task=0.9, stub_count=0, reprocess_tokens=0, applied=False)
    assert same["recommended_action"] == "reuse"
    assert same["applied_action"] == "reuse"
    changed = cache_plan(same_task=0.1, stub_count=0, reprocess_tokens=80, applied=False)
    assert changed["recommended_action"] == "rebuild"
    assert changed["reason_code"] == "task_changed"
    assert changed["estimated_reprocess_tokens"] == 0
