"""Tests for structured conversation compaction."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from superqode.agent.compaction import (
    COMPACTION_PROMPT,
    compact_history,
    serialize_for_compaction,
)
from superqode.agent.loop import AgentConfig, AgentLoop, AgentMessage
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
)
from superqode.tools.base import ToolRegistry


class RecordingGateway(GatewayInterface):
    """Gateway that records every chat_completion request and returns a script."""

    def __init__(self, responses: List[GatewayResponse]):
        self.responses = list(responses)
        self.requests: List[List[Message]] = []
        self.tools_seen: List[Optional[List[ToolDefinition]]] = []

    async def chat_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        self.requests.append(messages)
        self.tools_seen.append(tools)
        if not self.responses:
            return GatewayResponse(content="")
        return self.responses.pop(0)

    async def stream_completion(self, *args, **kwargs) -> AsyncIterator[StreamChunk]:
        if False:
            yield  # pragma: no cover

    async def test_connection(self, provider: str, model: Optional[str] = None) -> Dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider: str, model: str) -> str:
        return f"{provider}/{model}"


class FailingGateway(RecordingGateway):
    """Gateway whose chat_completion always raises."""

    async def chat_completion(self, *args, **kwargs) -> GatewayResponse:
        self.requests.append(args[0] if args else [])
        raise RuntimeError("simulated provider failure")


def test_compaction_prompt_contains_every_template_section():
    """The prompt is the contract; if a section is missing, downstream
    callers that key on the headings will silently break."""
    sections = [
        "## Goal",
        "## Constraints & Preferences",
        "## Progress",
        "### Done",
        "### In Progress",
        "### Blocked",
        "## Key Decisions",
        "## Next Steps",
        "## Critical Context",
        "## Relevant Files",
    ]
    for section in sections:
        assert section in COMPACTION_PROMPT, f"missing section: {section}"


def test_serialize_skips_empty_messages_and_summarizes_tool_calls():
    msgs = [
        AgentMessage(role="user", content="fix the bug"),
        AgentMessage(role="assistant", content=""),  # empty: skipped
        AgentMessage(
            role="assistant",
            content="reading files",
            tool_calls=[
                {"id": "t1", "function": {"name": "read_file", "arguments": "{}"}},
                {"id": "t2", "function": {"name": "grep", "arguments": "{}"}},
            ],
        ),
        AgentMessage(role="tool", content="a.py b.py", tool_call_id="t1"),
    ]
    out = serialize_for_compaction(msgs)
    assert "--- user ---\nfix the bug" in out
    assert "[tool calls: read_file, grep]" in out
    assert "--- tool ---\na.py b.py" in out
    # the empty assistant turn should not produce an empty section
    assert "--- assistant ---\n\n" not in out


@pytest.mark.asyncio
async def test_compact_history_returns_model_summary():
    gateway = RecordingGateway([GatewayResponse(content="## Goal\n- summary returned by model")])
    messages = [
        AgentMessage(role="user", content="fix README typo"),
        AgentMessage(role="assistant", content="done"),
    ]

    summary = await compact_history(
        messages, gateway, provider="anthropic", model="claude-opus-4-7"
    )

    assert summary == "## Goal\n- summary returned by model"
    assert len(gateway.requests) == 1
    sent = gateway.requests[0]
    assert sent[0].role == "system"
    assert "## Goal" in sent[0].content  # the template prompt
    assert sent[1].role == "user"
    assert "fix README typo" in sent[1].content


@pytest.mark.asyncio
async def test_compact_history_returns_none_when_gateway_fails():
    """Failures must surface as ``None`` so the agent loop falls back to
    mechanical pruning instead of crashing mid-turn."""
    gateway = FailingGateway([])
    messages = [AgentMessage(role="user", content="hello")]

    summary = await compact_history(
        messages, gateway, provider="anthropic", model="claude-opus-4-7"
    )

    assert summary is None


@pytest.mark.asyncio
async def test_compact_history_returns_none_on_empty_input():
    gateway = RecordingGateway([])
    assert await compact_history([], gateway, "anthropic", "claude-opus-4-7") is None


@pytest.mark.asyncio
async def test_agent_loop_uses_structured_compaction_when_over_limit():
    """When summarization is enabled and the history is over budget, the
    loop replaces head turns with a structured summary system message and
    keeps the recent tail intact."""
    # First response: the compaction summary. Second: the actual model reply.
    gateway = RecordingGateway(
        [
            GatewayResponse(content="## Goal\n- ship the fix"),
            GatewayResponse(content="all done"),
        ]
    )
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="anthropic",
            model="claude-opus-4-7",
            # Adaptive compaction: a small window forces compaction. keep_recent
            # is a token budget (not a fixed message count).
            context_window=2000,
            compaction_reserve_tokens=200,
            keep_recent_tokens=400,
        ),
    )

    # Seed long history so token estimator goes over the 1800-token threshold.
    long_text = "x " * 800
    history = [AgentMessage(role="user", content=f"step {i}: {long_text}") for i in range(6)]

    compacted = await loop._maybe_summarize(history)

    # Expect: one summary system message + a token-budgeted recent tail.
    summary_msgs = [m for m in compacted if m.role == "system"]
    assert summary_msgs, "expected a summary system message"
    assert "## Goal" in summary_msgs[0].content
    assert "Earlier conversation summary" in summary_msgs[0].content
    # A non-empty recent tail is kept (sized by tokens, not a fixed 4).
    tail = [m for m in compacted if m.role != "system"]
    assert 1 <= len(tail) < len(history)
    # The first compaction call should be the only LLM call so far.
    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_agent_loop_falls_back_to_prune_when_compaction_fails():
    """If the compaction call raises, the loop must still trim history
    rather than abort the user's turn."""
    gateway = FailingGateway([])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="anthropic",
            model="claude-opus-4-7",
            context_window=2000,
            compaction_reserve_tokens=200,
            keep_recent_tokens=400,
        ),
    )

    long_text = "y " * 800
    history = [AgentMessage(role="user", content=f"step {i}: {long_text}") for i in range(6)]

    result = await loop._maybe_summarize(history)

    # Fallback path produces non-empty pruned history without raising.
    assert result
    assert len(result) <= len(history)
