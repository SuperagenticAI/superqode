"""Tests for the get_context_remaining tool (model-visible context budget)."""

from typing import Any, Dict, List

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
)
from superqode.tools.base import ToolContext, ToolRegistry
from superqode.tools.context_tools import GetContextRemainingTool


@pytest.mark.asyncio
async def test_reports_budget_from_status_callback(tmp_path):
    ctx = ToolContext(
        session_id="t",
        working_directory=tmp_path,
        context_status=lambda: {"window": 32768, "used": 8000, "compaction_threshold": 28000},
    )
    result = await GetContextRemainingTool().execute({}, ctx)
    assert result.success, result.error
    assert "32,768" in result.output
    assert "8,000" in result.output
    assert result.metadata["remaining"] == 20000
    assert result.metadata["percent_used"] == 24


@pytest.mark.asyncio
async def test_handles_missing_callback_and_unknown_usage(tmp_path):
    no_cb = await GetContextRemainingTool().execute(
        {}, ToolContext(session_id="t", working_directory=tmp_path)
    )
    assert no_cb.success is False

    unknown = await GetContextRemainingTool().execute(
        {},
        ToolContext(
            session_id="t",
            working_directory=tmp_path,
            context_status=lambda: {"window": 8192, "used": None, "compaction_threshold": 7000},
        ),
    )
    assert unknown.success
    assert "not measurable" in unknown.output


def test_tool_is_read_only():
    assert GetContextRemainingTool.read_only is True


class ToolCallingGateway(GatewayInterface):
    """First response calls get_context_remaining; second finishes."""

    def __init__(self):
        self.calls: List[List[Message]] = []
        self.responses = [
            GatewayResponse(
                content="",
                tool_calls=[
                    {
                        "id": "c1",
                        "function": {"name": "get_context_remaining", "arguments": "{}"},
                    }
                ],
            ),
            GatewayResponse(content="done"),
        ]

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append(list(messages))
        return self.responses.pop(0)

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append(list(messages))
        yield StreamChunk(content="done")

    async def test_connection(self, provider, model=None) -> Dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider, model):
        return f"{provider}/{model}"


@pytest.mark.asyncio
async def test_loop_provides_live_numbers(tmp_path):
    gateway = ToolCallingGateway()
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.coding(),
        config=AgentConfig(
            provider="t", model="m", working_directory=tmp_path, context_window=16384
        ),
    )
    response = await loop.run("inspect the repository and check your context budget")
    assert response.content == "done"
    # The tool result delivered real numbers back to the model.
    tool_messages = [m for m in gateway.calls[1] if m.role == "tool"]
    assert tool_messages
    assert "Context window: 16,384" in str(tool_messages[0].content)
    assert "Used: ~" in str(tool_messages[0].content)
