"""Tests for long-lived peer agents and their tools."""

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.agent.peer_agents import PeerAgentManager
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
)
from superqode.tools.base import ToolContext, ToolRegistry
from superqode.tools.peer_agent_tools import (
    CloseAgentTool,
    ListAgentsTool,
    SendInputTool,
    SpawnAgentTool,
    WaitAgentTool,
)


class EchoGateway(GatewayInterface):
    """Answers every prompt with an echo of the last user message."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        return GatewayResponse(content=f"echo: {last_user.content if last_user else ''}")

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        yield StreamChunk(content="echo")

    async def test_connection(self, provider, model=None) -> Dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider, model) -> str:
        return f"{provider}/{model}"


def _parent_loop(delay: float = 0.0) -> AgentLoop:
    return AgentLoop(
        gateway=EchoGateway(delay=delay),
        tools=ToolRegistry.empty(),
        config=AgentConfig(provider="test", model="test-model"),
    )


def _ctx_with_manager(tmp_path, loop: AgentLoop) -> ToolContext:
    return ToolContext(
        session_id="t", working_directory=tmp_path, peer_manager=loop._get_peer_manager()
    )


@pytest.mark.asyncio
async def test_spawn_wait_roundtrip(tmp_path):
    loop = _parent_loop()
    ctx = _ctx_with_manager(tmp_path, loop)

    spawned = await SpawnAgentTool().execute(
        {"task_name": "Fix Tests", "message": "run the suite"}, ctx
    )
    assert spawned.success, spawned.error
    assert spawned.metadata["task_name"] == "fix_tests"

    waited = await WaitAgentTool().execute({"agent": "fix_tests", "timeout_s": 10}, ctx)
    assert waited.success
    assert waited.metadata["done"] is True
    assert "echo: run the suite" in waited.output

    closed = await CloseAgentTool().execute({"agent": "fix_tests"}, ctx)
    assert closed.success


@pytest.mark.asyncio
async def test_send_input_queues_followup(tmp_path):
    loop = _parent_loop()
    ctx = _ctx_with_manager(tmp_path, loop)
    await SpawnAgentTool().execute({"task_name": "worker", "message": "first"}, ctx)
    await WaitAgentTool().execute({"agent": "worker", "timeout_s": 10}, ctx)

    sent = await SendInputTool().execute({"agent": "worker", "message": "second task"}, ctx)
    assert sent.success
    assert sent.metadata["delivery"] == "queued"

    waited = await WaitAgentTool().execute({"agent": "worker", "timeout_s": 10}, ctx)
    assert "echo: second task" in waited.output
    await CloseAgentTool().execute({"agent": "worker"}, ctx)


@pytest.mark.asyncio
async def test_send_input_steers_busy_agent(tmp_path):
    loop = _parent_loop(delay=0.3)  # slow model keeps the peer busy
    ctx = _ctx_with_manager(tmp_path, loop)
    await SpawnAgentTool().execute({"task_name": "busy", "message": "long task"}, ctx)
    await asyncio.sleep(0.05)  # let it enter the model call

    sent = await SendInputTool().execute({"agent": "busy", "message": "while running"}, ctx)
    assert sent.success
    assert sent.metadata["delivery"] == "steered"

    waited = await WaitAgentTool().execute({"agent": "busy", "timeout_s": 10}, ctx)
    assert waited.metadata["done"] is True
    # The steered message extended the same run; the final echo answers it.
    assert "while running" in waited.output
    await CloseAgentTool().execute({"agent": "busy"}, ctx)


@pytest.mark.asyncio
async def test_list_agents_and_unknown_target(tmp_path):
    loop = _parent_loop()
    ctx = _ctx_with_manager(tmp_path, loop)
    await SpawnAgentTool().execute({"task_name": "alpha", "message": "go"}, ctx)

    listed = await ListAgentsTool().execute({}, ctx)
    assert listed.success
    assert "alpha" in listed.output

    missing = await WaitAgentTool().execute({"agent": "nope"}, ctx)
    assert missing.success is False

    manager = loop._get_peer_manager()
    await manager.close_all()


@pytest.mark.asyncio
async def test_peer_tools_unavailable_without_manager(tmp_path):
    ctx = ToolContext(session_id="t", working_directory=tmp_path, peer_manager=None)
    result = await SpawnAgentTool().execute({"task_name": "x", "message": "y"}, ctx)
    assert result.success is False
    assert "not available" in (result.error or "")


@pytest.mark.asyncio
async def test_peer_loops_cannot_spawn_peers(tmp_path):
    loop = _parent_loop()
    peer_loop = loop._create_peer_loop("child")
    assert peer_loop._get_peer_manager() is None


@pytest.mark.asyncio
async def test_duplicate_task_names_get_suffixed(tmp_path):
    loop = _parent_loop()
    manager = loop._get_peer_manager()
    a = await manager.spawn("worker", "one")
    b = await manager.spawn("worker", "two")
    assert a.task_name == "worker"
    assert b.task_name == "worker_2"
    await manager.close_all()
