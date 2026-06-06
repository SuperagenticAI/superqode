"""Tests for AgentLoop harness primitives."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop, _cached_system_prompt
from superqode.agent.system_prompts import DS4_PROMPT, SystemPromptLevel
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
async def test_ds4_keeps_tools_on_simple_query_for_kv_cache_stability():
    """DS4 must not drop tools based on the user message.

    DS4's KV-cache reuse keys on the rendered prefix; toggling tools per
    turn invalidates the cache and forces a cold prefill on every request.
    """
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
    assert gateway.tools_seen[0]


@pytest.mark.asyncio
async def test_streaming_run_persists_session_history(tmp_path):
    gateway = ScriptedGateway([])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="test",
            model="test-model",
            enable_session_storage=True,
            session_storage_dir=str(tmp_path / "sessions"),
            session_id="stream-session",
        ),
    )

    chunks = [chunk async for chunk in loop.run_streaming("remember this")]

    assert chunks == ["streamed"]
    assert loop._session_manager is not None
    stored = loop._session_manager.get_messages()
    assert [(message.role, message.content) for message in stored] == [
        ("user", "remember this"),
        ("assistant", "streamed"),
    ]


@pytest.mark.asyncio
async def test_ds4_keeps_tools_on_direct_code_request():
    """DS4 must keep tools attached even for chatty coding asks; the
    session-stable contract is what makes the rendered prefix reusable."""
    gateway = ScriptedGateway([GatewayResponse(content="def reverse_string(value): ...")])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
    )

    result = await loop.run("write a Python function that reverses a string")

    assert result.content.startswith("def reverse_string")
    assert gateway.tools_seen[0]


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
async def test_ds4_repo_summary_receives_tools():
    gateway = ScriptedGateway([GatewayResponse(content="done")])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
    )

    result = await loop.run("summarize this repository")

    assert result.content == "done"
    assert gateway.tools_seen[0]


@pytest.mark.asyncio
async def test_ds4_tool_mode_never_disables_tools_session_wide(monkeypatch):
    """SUPERQODE_DS4_TOOL_MODE=never opts out of tools for the whole session.

    This is the only honored override; per-turn flipping is intentionally
    not supported because it breaks DS4's rendered-prefix KV cache.
    """
    monkeypatch.setenv("SUPERQODE_DS4_TOOL_MODE", "never")
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
    assert gateway.tools_seen[0] is None


@pytest.mark.asyncio
async def test_ds4_tool_definitions_are_sorted_for_prefix_stability():
    """Tool defs are sorted by name so the rendered request prefix is
    byte-stable across processes (a prerequisite for KV-cache reuse)."""
    gateway = ScriptedGateway([GatewayResponse(content="done")])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="ds4",
            model="deepseek-v4-flash",
        ),
    )

    await loop.run("read README.md and summarize")

    tools = gateway.tools_seen[0]
    assert tools, "expected tools to be sent for ds4 session"
    names = [t.name for t in tools]
    assert names == sorted(names), f"tools not sorted by name: {names}"


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
async def test_plan_mode_blocks_unexpected_tool_calls_before_execution():
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[_tool_call("write_file", '{"path": "README.md", "content": "bad"}')],
            ),
            GatewayResponse(content="planned safely"),
        ]
    )
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="test",
            model="test-model",
            plan_mode=True,
        ),
        parallel_tools=False,
    )

    result = await loop.run("plan a README update")

    assert result.content == "planned safely"
    assert gateway.tools_seen == [None, None]
    assert "Plan mode blocked tool execution: write_file" in result.messages[-1].content


@pytest.mark.asyncio
async def test_streaming_plan_mode_blocks_unexpected_tool_calls_before_execution():
    class ToolCallingStreamGateway(ScriptedGateway):
        def __init__(self):
            super().__init__([])
            self.stream_calls = 0

        async def stream_completion(self, *args: Any, **kwargs: Any) -> AsyncIterator[StreamChunk]:
            self.calls.append(kwargs.get("messages") or args[0])
            self.tools_seen.append(kwargs.get("tools"))
            self.stream_calls += 1
            if self.stream_calls == 1:
                yield StreamChunk(
                    tool_calls=[_tool_call("write_file", '{"path": "README.md", "content": "bad"}')]
                )
            else:
                yield StreamChunk(content="planned safely")

    gateway = ToolCallingStreamGateway()
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.default(),
        config=AgentConfig(
            provider="test",
            model="test-model",
            plan_mode=True,
            max_iterations=2,
        ),
        parallel_tools=False,
    )

    chunks = [chunk async for chunk in loop.run_streaming("plan a README update")]

    assert "".join(chunks) == "planned safely"
    assert gateway.tools_seen == [None, None]


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
async def test_local_tool_gating_is_family_based():
    # Tool-capable family (Qwen 3) DOES receive tools — local models use family
    # detection, not a fixed registry, so modern local models (Gemma 4, Qwen 3,
    # Llama 4) can do agentic coding even with custom Ollama names.
    gw_capable = ScriptedGateway([GatewayResponse(content="done")])
    loop = AgentLoop(
        gateway=gw_capable,
        tools=ToolRegistry.default(),
        config=AgentConfig(provider="ollama", model="qwen3:8b"),
    )
    result = await loop.run("read README.md and summarize the setup")
    assert result.content == "done"
    assert gw_capable.tools_seen[0] is not None

    # Non-tool-capable family (Gemma 2) stays conservative — no tools sent.
    gw_conservative = ScriptedGateway([GatewayResponse(content="done")])
    loop2 = AgentLoop(
        gateway=gw_conservative,
        tools=ToolRegistry.default(),
        config=AgentConfig(provider="ollama", model="gemma2:9b"),
    )
    await loop2.run("read README.md and summarize the setup")
    assert gw_conservative.tools_seen[0] is None


def _build_loop_system_prompt(
    provider: str, model: str, level: SystemPromptLevel = SystemPromptLevel.MINIMAL
) -> str:
    """Construct an AgentLoop and return its rendered system prompt."""
    _cached_system_prompt.cache_clear()
    loop = AgentLoop(
        gateway=ScriptedGateway([]),
        tools=ToolRegistry.default(),
        config=AgentConfig(provider=provider, model=model, system_prompt_level=level),
    )
    return loop.system_prompt


def test_ds4_session_uses_tuned_system_prompt_at_minimal_level():
    """Default sessions on DS4 must get the DS4-tuned prompt, not the
    generic one-liner. Long generic prompts inflate DS4's thinking budget."""
    prompt = _build_loop_system_prompt("ds4", "deepseek-v4-flash")
    assert "DeepSeek V4 Flash" in prompt
    assert "Thinking:" in prompt


def test_non_ds4_session_keeps_generic_minimal_prompt():
    prompt = _build_loop_system_prompt("anthropic", "claude-opus-4-7")
    assert prompt.startswith("You are a coding assistant with access to tools.")
    assert "DeepSeek V4 Flash" not in prompt


def test_no_tool_system_prompt_does_not_claim_tool_access():
    prompt = _build_loop_system_prompt(
        "anthropic", "claude-opus-4-7", level=SystemPromptLevel.NO_TOOL
    )
    lowered = prompt.lower()

    assert "do not have access to tools" in lowered
    assert "use only the information provided" in lowered


def test_explicit_full_level_overrides_provider_prompt():
    """When users opt into FULL/EXPERT, the verbose prompt wins over the
    DS4 tuned default; the level is an explicit user choice."""
    prompt = _build_loop_system_prompt("ds4", "deepseek-v4-flash", level=SystemPromptLevel.FULL)
    assert DS4_PROMPT not in prompt
    assert "FILE OPERATIONS" in prompt


def test_deepseek_v4_model_id_triggers_tuned_prompt_via_any_provider():
    """An OpenAI-compatible provider hosting deepseek-v4 should still get
    the DS4 prompt — we key on model id, not just provider id."""
    prompt = _build_loop_system_prompt("openai-compatible", "deepseek-v4-flash")
    assert "DeepSeek V4 Flash" in prompt
