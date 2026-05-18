"""Behavioral parity tests: BuiltinRuntime should produce identical results to AgentLoop."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from superqode.agent.loop import AgentConfig
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
)
from superqode.runtime import AgentRuntime, BuiltinRuntime, create_runtime
from superqode.tools.base import ToolRegistry


class ScriptedGateway(GatewayInterface):
    """Replays a scripted sequence of GatewayResponses (mirrors test_agent_loop_harness)."""

    def __init__(self, responses: List[GatewayResponse]):
        self.responses = responses

    async def chat_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> GatewayResponse:
        if not self.responses:
            return GatewayResponse(content="done")
        return self.responses.pop(0)

    async def stream_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="hello")
        yield StreamChunk(content=" world")

    async def test_connection(self, provider: str, model: Optional[str] = None) -> Dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider: str, model: str) -> str:
        return f"{provider}/{model}"


def _config() -> AgentConfig:
    return AgentConfig(provider="test", model="test-model")


def _make_runtime(gateway: GatewayInterface) -> AgentRuntime:
    return create_runtime(
        "builtin",
        gateway=gateway,
        tools=ToolRegistry.full(),
        config=_config(),
        parallel_tools=False,
    )


def test_create_runtime_builtin_returns_builtin_runtime():
    runtime = _make_runtime(ScriptedGateway([]))
    assert isinstance(runtime, BuiltinRuntime)
    assert runtime.name == "builtin"


def test_builtin_runtime_exposes_underlying_agent_loop():
    runtime = _make_runtime(ScriptedGateway([]))
    assert runtime.loop is not None
    # The wrapped loop must hold the same config we passed in
    assert runtime.loop.config.provider == "test"
    assert runtime.loop.config.model == "test-model"


@pytest.mark.asyncio
async def test_builtin_runtime_run_returns_agent_response():
    gateway = ScriptedGateway([GatewayResponse(content="hi there")])
    runtime = _make_runtime(gateway)

    response = await runtime.run("hello")

    assert response.content == "hi there"
    assert response.stopped_reason == "complete"
    assert response.error is None


@pytest.mark.asyncio
async def test_builtin_runtime_streaming_yields_chunks():
    gateway = ScriptedGateway([])
    runtime = _make_runtime(gateway)

    chunks: list[str] = []
    async for chunk in runtime.run_streaming("hello"):
        chunks.append(chunk)

    # ScriptedGateway emits "hello" + " world"
    joined = "".join(chunks)
    assert "hello" in joined and "world" in joined


def test_builtin_runtime_cancel_propagates_to_loop():
    runtime = _make_runtime(ScriptedGateway([]))
    runtime.cancel()
    assert runtime.loop._cancelled is True
    runtime.reset_cancellation()
    assert runtime.loop._cancelled is False
