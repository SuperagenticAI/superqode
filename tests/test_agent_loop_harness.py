"""Tests for AgentLoop harness primitives."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
)
from superqode.tools.base import ToolRegistry


class ScriptedGateway(GatewayInterface):
    """Gateway that returns a scripted sequence of responses."""

    def __init__(self, responses: List[GatewayResponse]):
        self.responses = responses
        self.calls: List[List[Message]] = []
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
        **kwargs: Any,
    ) -> GatewayResponse:
        self.calls.append(messages)
        self.tools_seen.append(tools)
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
        yield StreamChunk(content="")

    async def test_connection(self, provider: str, model: Optional[str] = None) -> Dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider: str, model: str) -> str:
        return f"{provider}/{model}"


def _tool_call(name: str, arguments: str) -> Dict[str, Any]:
    return {
        "id": f"call-{name}",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def _loop(gateway: ScriptedGateway, *, require_confirmation: bool = False) -> AgentLoop:
    return AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.full(),
        config=AgentConfig(
            provider="test",
            model="test-model",
            require_confirmation=require_confirmation,
        ),
        parallel_tools=False,
    )


def test_agent_loop_loads_parent_and_local_project_instructions(tmp_path):
    root = tmp_path / "repo"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    (root / "AGENTS.md").write_text("Root instruction", encoding="utf-8")
    (nested / "CLAUDE.md").write_text("Nested instruction", encoding="utf-8")

    loop = AgentLoop(
        gateway=ScriptedGateway([]),
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="test",
            model="test-model",
            working_directory=nested,
        ),
    )

    assert "# Project Instructions" in loop.system_prompt
    assert "Root instruction" in loop.system_prompt
    assert "Nested instruction" in loop.system_prompt
    assert loop.system_prompt.index("Root instruction") < loop.system_prompt.index(
        "Nested instruction"
    )


@pytest.mark.asyncio
async def test_agent_loop_blocks_dangerous_shell_commands_before_execution():
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[_tool_call("bash", '{"command": "rm -rf important"}')],
            ),
            GatewayResponse(content="saw denial"),
        ]
    )

    result = await _loop(gateway).run("run a dangerous command")

    assert result.content == "saw denial"
    assert result.tool_calls_made == 1
    assert "Permission denied for tool: bash" in result.messages[-1].content


@pytest.mark.asyncio
async def test_agent_loop_requires_approval_when_confirmation_mode_is_enabled():
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[_tool_call("read_file", '{"path": "README.md"}')],
            ),
            GatewayResponse(content="permission handled"),
        ]
    )

    result = await _loop(gateway, require_confirmation=True).run("read README")

    assert result.content == "permission handled"
    assert "Permission required for tool: read_file" in result.messages[-1].content


@pytest.mark.asyncio
async def test_agent_tool_runs_child_agent_loop_with_isolated_history():
    gateway = ScriptedGateway(
        [
            GatewayResponse(content="child final"),
        ]
    )

    loop = _loop(gateway)
    spawn_result = await loop._execute_tool(
        "agent",
        {
            "action": "spawn",
            "task": "answer from child",
            "allowed_tools": ["read_file"],
        },
    )
    task_id = spawn_result.metadata["task_id"]
    wait_result = await loop._execute_tool("agent", {"action": "wait", "task_id": task_id})

    assert wait_result.success
    assert "child final" in wait_result.output
    assert len(gateway.calls) == 1
    assert gateway.calls[0][-1].content == "answer from child"


@pytest.mark.asyncio
async def test_ds4_local_provider_receives_tools_for_coding_tasks():
    gateway = ScriptedGateway([GatewayResponse(content="done")])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
    )

    result = await loop.run("read README.md and summarize the setup")

    assert result.content == "done"
    assert gateway.tools_seen[0]
    assert any(tool.name == "read_file" for tool in gateway.tools_seen[0] or [])


@pytest.mark.asyncio
async def test_simple_ds4_query_skips_tools():
    gateway = ScriptedGateway([GatewayResponse(content="hello")])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
    )

    result = await loop.run("what is 2+2?")

    assert result.content == "hello"
    assert gateway.tools_seen[0] is None


@pytest.mark.asyncio
async def test_generic_local_provider_stays_conservative_with_tools():
    gateway = ScriptedGateway([GatewayResponse(content="done")])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ollama",
            model="qwen3:8b",
        ),
    )

    result = await loop.run("read README.md and summarize the setup")

    assert result.content == "done"
    assert gateway.tools_seen[0] is None
