"""Tests for the PydanticAI runtime bridge."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from superqode.agent.loop import AgentConfig
from superqode.harness.spec import HarnessSpec, ModelPolicySpec, ObservabilitySpec, RuntimeSpec
from superqode.runtime.pydanticai import PydanticAIRuntime
from superqode.runtime.tool_bridge_pydanticai import to_pydanticai_toolsets
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo a message."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    async def execute(self, args, ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output=f"{ctx.session_id}:{args['message']}")


def install_fake_pydanticai(monkeypatch, *, agent_cls=None):
    pydantic_ai = types.ModuleType("pydantic_ai")
    toolsets = types.ModuleType("pydantic_ai.toolsets")
    abstract = types.ModuleType("pydantic_ai.toolsets.abstract")
    tools = types.ModuleType("pydantic_ai.tools")
    mcp = types.ModuleType("pydantic_ai.mcp")
    models = types.ModuleType("pydantic_ai.models")
    fallback = types.ModuleType("pydantic_ai.models.fallback")
    durable_exec = types.ModuleType("pydantic_ai.durable_exec")
    durable_prefect = types.ModuleType("pydantic_ai.durable_exec.prefect")

    class AbstractToolset:
        def __class_getitem__(cls, item):
            return cls

    @dataclass
    class ToolsetTool:
        toolset: object
        tool_def: object
        max_retries: int
        args_validator: object

    @dataclass
    class ToolDefinition:
        name: str
        parameters_json_schema: dict
        description: str | None = None

    @dataclass
    class RunContext:
        max_retries: int = 1

    class DeferredToolRequests:
        def __init__(self, *, approvals=None, calls=None):
            self.approvals = approvals or []
            self.calls = calls or []

    class DeferredToolResults:
        def __init__(self, *, approvals=None, calls=None):
            self.approvals = approvals or {}
            self.calls = calls or {}

    class ToolDenied:
        def __init__(self, message):
            self.message = message

    class FallbackModel:
        def __init__(self, default_model, *fallback_models):
            self.default_model = default_model
            self.fallback_models = fallback_models

    class PrefectAgent:
        def __init__(self, agent):
            self.agent = agent

    class Agent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def run(self, *args, **kwargs):
            return FakeResult("ok")

    def load_mcp_toolsets(path):
        return [f"mcp:{path}"]

    pydantic_ai.Agent = agent_cls or Agent
    pydantic_ai.DeferredToolRequests = DeferredToolRequests
    pydantic_ai.DeferredToolResults = DeferredToolResults
    pydantic_ai.ToolDenied = ToolDenied
    toolsets.AbstractToolset = AbstractToolset
    abstract.ToolsetTool = ToolsetTool
    tools.ToolDefinition = ToolDefinition
    tools.RunContext = RunContext
    mcp.load_mcp_toolsets = load_mcp_toolsets
    fallback.FallbackModel = FallbackModel
    durable_prefect.PrefectAgent = PrefectAgent

    monkeypatch.setitem(sys.modules, "pydantic_ai", pydantic_ai)
    monkeypatch.setitem(sys.modules, "pydantic_ai.toolsets", toolsets)
    monkeypatch.setitem(sys.modules, "pydantic_ai.toolsets.abstract", abstract)
    monkeypatch.setitem(sys.modules, "pydantic_ai.tools", tools)
    monkeypatch.setitem(sys.modules, "pydantic_ai.mcp", mcp)
    monkeypatch.setitem(sys.modules, "pydantic_ai.models", models)
    monkeypatch.setitem(sys.modules, "pydantic_ai.models.fallback", fallback)
    monkeypatch.setitem(sys.modules, "pydantic_ai.durable_exec", durable_exec)
    monkeypatch.setitem(sys.modules, "pydantic_ai.durable_exec.prefect", durable_prefect)

    return types.SimpleNamespace(
        RunContext=RunContext,
        DeferredToolRequests=DeferredToolRequests,
        DeferredToolResults=DeferredToolResults,
        ToolDenied=ToolDenied,
        FallbackModel=FallbackModel,
        PrefectAgent=PrefectAgent,
    )


class FakeResult:
    def __init__(self, output, messages=None):
        self.output = output
        self._messages = messages or ["m1"]

    def all_messages(self):
        return list(self._messages)


@pytest.mark.asyncio
async def test_pydanticai_toolset_preserves_superqode_json_schema(monkeypatch, tmp_path):
    fake = install_fake_pydanticai(monkeypatch)
    registry = ToolRegistry()
    registry.register(EchoTool())
    calls = []
    results = []

    def make_ctx():
        return ToolContext(session_id="s1", working_directory=tmp_path)

    toolsets = to_pydanticai_toolsets(
        registry,
        ctx_factory=make_ctx,
        permission_manager=PermissionManager(PermissionConfig(default=Permission.ALLOW)),
        on_tool_call=lambda name, args: calls.append((name, args)),
        on_tool_result=lambda name, result: results.append((name, result)),
    )

    toolset = toolsets[0]
    tools = await toolset.get_tools(fake.RunContext(max_retries=3))
    echo = tools["echo"]

    assert echo.tool_def.parameters_json_schema == registry.get("echo").parameters
    assert echo.max_retries == 3

    output = await toolset.call_tool(
        "echo",
        {"message": "hello"},
        fake.RunContext(),
        echo,
    )

    assert output == "s1:hello"
    assert calls == [("echo", {"message": "hello"})]
    assert results[0][0] == "echo"
    assert results[0][1].success is True


@pytest.mark.asyncio
async def test_pydanticai_runtime_surfaces_and_resumes_deferred_approvals(
    monkeypatch,
    tmp_path,
):
    captured = {}

    class ToolCall:
        tool_name = "bash"
        args = {"command": "ls"}
        tool_call_id = "call-1"

    class Agent:
        def __init__(self, *args, **kwargs):
            captured["init"] = {"args": args, "kwargs": kwargs}
            self.calls = []

        async def run(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            captured["last_run"] = {"prompt": prompt, "kwargs": kwargs}
            if len(self.calls) == 1:
                return FakeResult(fake.DeferredToolRequests(approvals=[ToolCall()]))
            return FakeResult("approved")

    fake = install_fake_pydanticai(monkeypatch, agent_cls=Agent)
    runtime = PydanticAIRuntime(
        tools=ToolRegistry.empty(),
        config=AgentConfig(
            provider="openai",
            model="gpt-5",
            working_directory=tmp_path,
        ),
    )

    response = await runtime.run("run shell")

    assert response.stopped_reason == "needs_approval"
    assert runtime.get_pending_approvals() == [
        {
            "index": 0,
            "tool_name": "bash",
            "arguments": {"command": "ls"},
            "tool_call_id": "call-1",
        }
    ]

    resumed = await runtime.approve_and_resume()

    assert resumed.content == "approved"
    assert captured["last_run"]["prompt"] is None
    assert isinstance(
        captured["last_run"]["kwargs"]["deferred_tool_results"],
        fake.DeferredToolResults,
    )
    assert runtime.get_pending_approvals() == []


def test_pydanticai_runtime_builds_fallback_model_and_native_mcp(monkeypatch, tmp_path):
    captured = {}

    class Agent:
        def __init__(self, *args, **kwargs):
            captured["init"] = {"args": args, "kwargs": kwargs}

    fake = install_fake_pydanticai(monkeypatch, agent_cls=Agent)
    spec = HarnessSpec(
        name="pydanticai-test",
        runtime=RuntimeSpec(
            backend="pydanticai",
            config={"pydanticai": {"mcp_config_path": "mcp.json"}},
        ),
        model_policy=ModelPolicySpec(fallbacks=("anthropic:claude-sonnet-4-5",)),
        observability=ObservabilitySpec(traces=False),
    )

    PydanticAIRuntime(
        tools=ToolRegistry.empty(),
        config=AgentConfig(
            provider="openai",
            model="gpt-5",
            working_directory=tmp_path,
        ),
        harness_spec=spec,
    )

    model = captured["init"]["args"][0]
    assert isinstance(model, fake.FallbackModel)
    assert model.default_model == "openai:gpt-5"
    assert model.fallback_models == ("anthropic:claude-sonnet-4-5",)
    assert captured["init"]["kwargs"]["toolsets"] == ["mcp:mcp.json"]


def test_pydanticai_runtime_can_wrap_prefect_durable_agent(monkeypatch, tmp_path):
    class Agent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    fake = install_fake_pydanticai(monkeypatch, agent_cls=Agent)
    spec = HarnessSpec(
        name="pydanticai-durable",
        runtime=RuntimeSpec(
            backend="pydanticai",
            config={"pydanticai": {"durable": "prefect"}},
        ),
    )

    runtime = PydanticAIRuntime(
        tools=ToolRegistry.empty(),
        config=AgentConfig(
            provider="openai",
            model="gpt-5",
            working_directory=tmp_path,
        ),
        harness_spec=spec,
    )

    assert isinstance(runtime._agent, fake.PrefectAgent)
    assert isinstance(runtime._agent.agent, Agent)
