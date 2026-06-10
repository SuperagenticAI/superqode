"""Tests for stage-1 compaction: stubbing stale tool outputs without an LLM."""

import pytest

from superqode.agent.hooks import HookRegistry
from superqode.agent.loop import AgentConfig, AgentLoop, AgentMessage


class _FakeContextManager:
    def count_tokens(self, messages):
        return sum(max(1, len(str(m.get("content", ""))) // 4) for m in messages)


def _make_loop(window=4096):
    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(provider="x", model="y", context_window=window)
    loop.context_manager = _FakeContextManager()
    loop._cached_context_window = window
    loop.hooks = HookRegistry()
    loop.on_thinking = None
    loop.session_id = "test-session"
    loop._current_iteration = 0
    return loop


def _dicts(messages):
    return [
        {
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "tool_result": m.content if m.role == "tool" else None,
        }
        for m in messages
    ]


def _history_with_big_tool_output():
    return [
        AgentMessage(role="system", content="system prompt"),
        AgentMessage(role="user", content="please do the thing"),
        AgentMessage(role="assistant", content="", tool_calls=[{"id": "1"}]),
        AgentMessage(role="tool", content="X" * 30_000, tool_call_id="1", name="bash"),
        AgentMessage(role="assistant", content="done with step one"),
        AgentMessage(role="user", content="now the next step"),
        AgentMessage(role="assistant", content="working on it"),
    ]


def test_prune_stubs_old_tool_output_and_preserves_originals():
    loop = _make_loop()
    messages = _history_with_big_tool_output()
    pruned, saved = loop._prune_stale_tool_outputs(messages, _dicts(messages), keep_recent=200)
    assert saved > 20_000
    stub = next(m for m in pruned if m.role == "tool")
    assert "removed to save context" in stub.content
    assert "bash" in stub.content
    assert stub.tool_call_id == "1"  # linkage preserved for providers
    # Original objects untouched (session history safety).
    assert len(messages[3].content) == 30_000


def test_prune_skips_when_savings_too_small():
    loop = _make_loop()
    messages = [
        AgentMessage(role="user", content="hi"),
        AgentMessage(role="tool", content="small output", tool_call_id="1", name="bash"),
        AgentMessage(role="assistant", content="ok"),
    ]
    pruned, saved = loop._prune_stale_tool_outputs(messages, _dicts(messages), keep_recent=10)
    assert saved == 0
    assert pruned is messages


def test_prune_protects_recent_tail():
    loop = _make_loop()
    messages = [
        AgentMessage(role="user", content="start"),
        # Recent big tool output, inside the protected tail.
        AgentMessage(role="tool", content="Y" * 30_000, tool_call_id="1", name="grep"),
    ]
    pruned, saved = loop._prune_stale_tool_outputs(messages, _dicts(messages), keep_recent=50_000)
    assert saved == 0  # everything fits in the protected tail


@pytest.mark.asyncio
async def test_maybe_summarize_uses_prune_before_llm(monkeypatch):
    monkeypatch.delenv("SUPERQODE_AUTO_COMPACT", raising=False)
    loop = _make_loop(window=4096)
    messages = _history_with_big_tool_output()

    called = {"summarize": False}

    async def _no_summarize(*args, **kwargs):
        called["summarize"] = True
        return None

    monkeypatch.setattr("superqode.agent.compaction.compact_history", _no_summarize)

    result = await loop._maybe_summarize(messages)

    # Pruning alone brought us under threshold: no LLM summarization call.
    assert called["summarize"] is False
    tool_msg = next(m for m in result if m.role == "tool")
    assert "removed to save context" in tool_msg.content
    # Conversation skeleton intact.
    assert [m.role for m in result] == [m.role for m in messages]
