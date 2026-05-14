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
        self.calls.append(messages)
        self.tools_seen.append(tools)
        yield StreamChunk(content="streamed")

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
async def test_ds4_project_question_receives_tools():
    gateway = ScriptedGateway([GatewayResponse(content="done")])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
    )

    result = await loop.run("what is this project about?")

    assert result.content == "done"
    assert gateway.tools_seen[0]


@pytest.mark.asyncio
async def test_streaming_plan_mode_does_not_send_tools():
    gateway = ScriptedGateway([])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
            plan_mode=True,
        ),
    )

    chunks = [chunk async for chunk in loop.run_streaming("plan the README update")]

    assert "".join(chunks) == "streamed"
    assert gateway.tools_seen == [None]


@pytest.mark.asyncio
async def test_agent_retries_when_model_narrates_tool_use_without_call():
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content=(
                    "I can help understand this project. "
                    "Let me start by listing the files in the repository."
                )
            ),
            GatewayResponse(
                content="",
                tool_calls=[_tool_call("list_directory", '{"path": "."}')],
            ),
            GatewayResponse(content="This project is SuperQode."),
        ]
    )
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
        parallel_tools=False,
    )

    result = await loop.run("what is this project about?")

    assert result.content == "This project is SuperQode."
    assert result.tool_calls_made == 1
    assert len(gateway.calls) == 3


@pytest.mark.asyncio
async def test_agent_stops_when_model_keeps_narrating_tool_use_without_call():
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content=(
                    "I can help understand this project. "
                    "Let me start by listing the files in the repository."
                )
            ),
            GatewayResponse(
                content=("Let me start by inspecting the README and project files first.")
            ),
            GatewayResponse(content="should not be called"),
        ]
    )
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
        parallel_tools=False,
    )

    result = await loop.run("what is this project about?")

    assert result.content == "Let me start by inspecting the README and project files first."
    assert result.stopped_reason == "complete"
    assert result.tool_calls_made == 0
    assert result.iterations == 2
    assert len(gateway.calls) == 2


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
