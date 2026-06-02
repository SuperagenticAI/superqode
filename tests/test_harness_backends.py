"""Tests for harness backend registry and runtime adapter."""

import sys
import types
from dataclasses import replace

import pytest

from superqode.agent.loop import AgentResponse
from superqode.tools.base import ToolResult
from superqode.harness import (
    ADKHarnessBackend,
    CodexSDKHarnessBackend,
    DeepAgentsHarnessBackend,
    ExecutionPolicySpec,
    HarnessBackendRequest,
    HarnessEvent,
    ModelPolicySpec,
    OpenAIAgentsHarnessBackend,
    PydanticAIHarnessBackend,
    RuntimeHarnessBackend,
    backend_capabilities,
    create_harness_backend,
    get_harness_template,
    inspect_harness_backend,
    known_harness_backend_names,
)


class FakeRuntime:
    name = "fake-runtime"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def run(self, prompt: str) -> AgentResponse:
        tools = self.kwargs["tools"]
        config = self.kwargs["config"]
        return AgentResponse(
            content=f"{prompt}|tools={len(tools.list())}|enabled={config.tools_enabled}",
            messages=[],
            tool_calls_made=len(tools.list()),
            iterations=1,
            stopped_reason="complete",
        )


class FakeApprovalRuntime(FakeRuntime):
    async def run(self, prompt: str) -> AgentResponse:
        return AgentResponse(
            content="",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="needs_approval",
        )

    def get_pending_approvals(self):
        return [{"index": 0, "tool_name": "bash", "arguments": {"command": "ls"}}]


class FakeEventRuntime(FakeRuntime):
    async def run_harness_events(self, prompt: str):
        yield HarnessEvent(type="model_delta", data={"text": prompt})
        yield HarnessEvent(type="tool_call", data={"tool_name": "echo"})


class FakeCallbackRuntime(FakeRuntime):
    async def run(self, prompt: str) -> AgentResponse:
        self.kwargs["on_tool_call"]("bash", {"command": "echo hi"})
        self.kwargs["on_tool_result"](
            "bash",
            ToolResult(success=True, output="hi\n"),
        )
        return AgentResponse(
            content=f"done:{prompt}",
            messages=[],
            tool_calls_made=1,
            iterations=1,
            stopped_reason="complete",
        )


def install_fake_deepagents(monkeypatch, agent):
    class FakeFilesystemBackend:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeFilesystemPermission:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    deepagents_module = types.ModuleType("deepagents")
    backends_module = types.ModuleType("deepagents.backends")
    graph_module = types.ModuleType("deepagents.graph")
    middleware_module = types.ModuleType("deepagents.middleware")
    filesystem_module = types.ModuleType("deepagents.middleware.filesystem")
    backends_module.FilesystemBackend = FakeFilesystemBackend
    graph_module.create_deep_agent = lambda **kwargs: agent
    filesystem_module.FilesystemPermission = FakeFilesystemPermission

    monkeypatch.setitem(sys.modules, "deepagents", deepagents_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setitem(sys.modules, "deepagents.graph", graph_module)
    monkeypatch.setitem(sys.modules, "deepagents.middleware", middleware_module)
    monkeypatch.setitem(sys.modules, "deepagents.middleware.filesystem", filesystem_module)


def test_known_harness_backends_include_current_runtime_backends():
    names = known_harness_backend_names()

    assert "builtin" in names
    assert "adk" in names
    assert "codex-sdk" in names
    assert "openai-agents" in names
    assert "deepagents" in names
    assert "pydanticai" in names


def test_create_harness_backend_returns_runtime_adapter():
    backend = create_harness_backend("builtin")

    assert isinstance(backend, RuntimeHarnessBackend)
    assert backend.name == "builtin"


def test_create_harness_backend_returns_deepagents_adapter():
    backend = create_harness_backend("deepagents")

    assert isinstance(backend, DeepAgentsHarnessBackend)
    assert backend.name == "deepagents"


def test_create_harness_backend_returns_direct_runtime_adapters():
    assert isinstance(create_harness_backend("adk"), ADKHarnessBackend)
    assert isinstance(create_harness_backend("codex-sdk"), CodexSDKHarnessBackend)
    assert isinstance(create_harness_backend("openai-agents"), OpenAIAgentsHarnessBackend)
    assert isinstance(create_harness_backend("pydanticai"), PydanticAIHarnessBackend)


def test_create_harness_backend_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown harness backend"):
        create_harness_backend("unknown-backend")


def test_backend_capabilities_are_advertised():
    assert create_harness_backend("builtin").capabilities.supports_no_tool is True
    assert create_harness_backend("builtin").capabilities.supports_approvals is True
    assert create_harness_backend("openai-agents").capabilities.supports_approvals is True
    assert create_harness_backend("codex-sdk").capabilities.supports_streaming is True
    assert create_harness_backend("codex-sdk").capabilities.supports_approvals is False
    assert create_harness_backend("deepagents").capabilities.supports_no_tool is False
    assert create_harness_backend("pydanticai").capabilities.supports_coding is True


def test_backend_capabilities_lookup_reports_availability():
    capabilities = backend_capabilities("builtin")

    assert capabilities.backend == "builtin"
    assert capabilities.availability == "available"
    assert capabilities.install_hint is None


def test_inspect_harness_backend_flags_unsupported_no_tool():
    inspection = inspect_harness_backend("deepagents", get_harness_template("no-tool"))

    assert inspection.ok is False
    assert inspection.issues[0].code == "no_tool_unsupported"


def test_inspect_harness_backend_accepts_pydanticai_coding():
    inspection = inspect_harness_backend("pydanticai", get_harness_template("coding"))

    assert inspection.ok is True
    assert inspection.capabilities.supports_coding is True


def test_inspect_harness_backend_accepts_builtin_no_tool():
    inspection = inspect_harness_backend("builtin", get_harness_template("no-tool"))

    assert inspection.ok is True
    assert inspection.capabilities.supports_no_tool is True
    assert inspection.to_dict()["capabilities"]["supports_streaming"] is True


def test_inspect_harness_backend_warns_for_unverified_model_policy():
    spec = replace(
        get_harness_template("coding"),
        model_policy=ModelPolicySpec(
            primary="gpt-5.4",
            reasoning="high",
            temperature=0.2,
            config={"max_iterations": 7},
        ),
    )

    inspection = inspect_harness_backend("deepagents", spec)
    codes = {issue.code for issue in inspection.issues}

    assert "reasoning_policy_unverified" in codes
    assert "temperature_policy_unverified" in codes
    assert "max_iterations_policy_unverified" in codes


@pytest.mark.asyncio
async def test_runtime_harness_backend_clamps_no_tool_registry(monkeypatch, tmp_path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        created["name"] = name
        created["kwargs"] = kwargs
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    backend = RuntimeHarnessBackend("builtin")
    request = HarnessBackendRequest(
        spec=get_harness_template("no-tool"),
        prompt="think",
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="s",
    )

    result = await backend.run(request)

    assert result.backend == "builtin"
    assert result.runtime == "builtin"
    assert result.response.content == "think|tools=0|enabled=False"
    assert created["kwargs"]["tools"].list() == []
    assert created["kwargs"]["config"].tools_enabled is False


@pytest.mark.asyncio
async def test_runtime_harness_backend_surfaces_pending_approvals(monkeypatch, tmp_path):
    def fake_create_runtime(name, **kwargs):
        return FakeApprovalRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    backend = RuntimeHarnessBackend("openai-agents")
    request = HarnessBackendRequest(
        spec=get_harness_template("coding"),
        prompt="run shell",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    result = await backend.run(request)

    assert result.response.stopped_reason == "needs_approval"
    assert result.metadata["pending_approvals"] == [
        {"index": 0, "tool_name": "bash", "arguments": {"command": "ls"}}
    ]
    assert isinstance(result.metadata["pending_runtime"], FakeApprovalRuntime)


@pytest.mark.asyncio
async def test_builtin_runtime_backend_collects_rich_run_events(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "superqode.harness.backends.runtime.create_runtime",
        lambda name, **kwargs: FakeCallbackRuntime(**kwargs),
    )
    backend = RuntimeHarnessBackend("builtin")
    request = HarnessBackendRequest(
        spec=get_harness_template("coding"),
        prompt="code",
        provider="openai",
        model="gpt-4o-mini",
        working_directory=tmp_path,
        session_id="s",
    )

    result = await backend.run(request)

    event_types = [event.type for event in result.metadata["events"]]
    assert event_types == ["model_request", "tool_call", "tool_result", "model_result"]
    assert result.metadata["events"][1].data["tool_name"] == "bash"


@pytest.mark.asyncio
async def test_deepagents_backend_rejects_no_tool_without_importing_dependency(tmp_path):
    backend = DeepAgentsHarnessBackend()
    request = HarnessBackendRequest(
        spec=get_harness_template("no-tool"),
        prompt="think",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    with pytest.raises(ValueError, match="requires a tool-capable harness"):
        await backend.run(request)


@pytest.mark.asyncio
async def test_deepagents_backend_rejects_shell_disabled_specs(tmp_path):
    base = get_harness_template("coding")
    spec = base.__class__(
        **{
            **base.__dict__,
            "execution_policy": ExecutionPolicySpec(
                allow_read=True,
                allow_write=True,
                allow_shell=False,
            ),
        }
    )
    backend = DeepAgentsHarnessBackend()
    request = HarnessBackendRequest(
        spec=spec,
        prompt="code",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    with pytest.raises(ValueError, match="requires allow_shell=True"):
        await backend.run(request)


@pytest.mark.asyncio
async def test_deepagents_backend_maps_coding_spec_to_create_deep_agent(monkeypatch, tmp_path):
    captured = {}

    class FakeFilesystemBackend:
        def __init__(self, **kwargs):
            captured["filesystem_backend"] = kwargs

    class FakeFilesystemPermission:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeDeepAgent:
        async def ainvoke(self, payload):
            captured["payload"] = payload
            return {
                "messages": [
                    {"role": "user", "content": payload["messages"][0]["content"]},
                    {"role": "assistant", "content": "done", "tool_calls": [{"name": "read_file"}]},
                ]
            }

    def fake_create_deep_agent(**kwargs):
        captured["create_deep_agent"] = kwargs
        return FakeDeepAgent()

    deepagents_module = types.ModuleType("deepagents")
    backends_module = types.ModuleType("deepagents.backends")
    graph_module = types.ModuleType("deepagents.graph")
    middleware_module = types.ModuleType("deepagents.middleware")
    filesystem_module = types.ModuleType("deepagents.middleware.filesystem")
    backends_module.FilesystemBackend = FakeFilesystemBackend
    graph_module.create_deep_agent = fake_create_deep_agent
    filesystem_module.FilesystemPermission = FakeFilesystemPermission

    monkeypatch.setitem(sys.modules, "deepagents", deepagents_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setitem(sys.modules, "deepagents.graph", graph_module)
    monkeypatch.setitem(sys.modules, "deepagents.middleware", middleware_module)
    monkeypatch.setitem(sys.modules, "deepagents.middleware.filesystem", filesystem_module)

    backend = DeepAgentsHarnessBackend()
    request = HarnessBackendRequest(
        spec=get_harness_template("coding"),
        prompt="implement",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    result = await backend.run(request)

    assert result.backend == "deepagents"
    assert result.runtime == "deepagents"
    assert result.response.content == "done"
    assert result.response.tool_calls_made == 1
    assert captured["filesystem_backend"] == {"root_dir": str(tmp_path), "virtual_mode": True}
    assert captured["create_deep_agent"]["model"] == "openai:gpt-5"
    assert captured["create_deep_agent"]["tools"] == []
    assert captured["create_deep_agent"]["name"] == "superqode-coding"
    assert captured["create_deep_agent"]["skills"] is None
    assert captured["create_deep_agent"]["memory"] is None
    assert captured["payload"]["messages"][0]["content"] == "implement"


@pytest.mark.asyncio
async def test_deepagents_backend_streams_rich_graph_events(monkeypatch, tmp_path):
    class FakeDeepAgent:
        async def astream_events(self, payload):
            assert payload["messages"][0]["content"] == "implement"
            yield {"event": "on_chat_model_stream", "data": {"chunk": "hello"}}
            yield {
                "event": "on_tool_start",
                "name": "execute",
                "data": {"input": {"command": "pytest"}},
            }
            yield {
                "event": "on_tool_end",
                "name": "execute",
                "data": {"output": "ok"},
            }
            yield {
                "event": "on_tool_start",
                "name": "task",
                "data": {"input": {"subagent_type": "researcher"}},
            }
            yield {
                "event": "on_tool_end",
                "name": "write_file",
                "data": {"path": "/memories/user/preferences.md", "output": "saved"},
            }
            yield {"event": "on_chain_end", "data": {"output": "done"}}

    install_fake_deepagents(monkeypatch, FakeDeepAgent())
    backend = DeepAgentsHarnessBackend()
    request = HarnessBackendRequest(
        spec=get_harness_template("coding"),
        prompt="implement",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    events = [event async for event in backend.stream(request)]

    event_types = [event.type for event in events]
    assert "model_request" in event_types
    assert "model_delta" in event_types
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "subagent_start" in event_types
    assert "memory_write" in event_types
    assert "sandbox_command" in event_types
    assert "model_result" in event_types
    assert events[-1].type == "end"


@pytest.mark.asyncio
async def test_deepagents_backend_stream_falls_back_to_model_result(monkeypatch, tmp_path):
    class FakeDeepAgent:
        async def ainvoke(self, payload):
            return {"messages": [{"role": "assistant", "content": "fallback"}]}

    install_fake_deepagents(monkeypatch, FakeDeepAgent())
    backend = DeepAgentsHarnessBackend()
    request = HarnessBackendRequest(
        spec=get_harness_template("coding"),
        prompt="implement",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    events = [event async for event in backend.stream(request)]

    assert [event.type for event in events] == ["model_request", "model_result", "end"]
    assert events[1].data["output"] == "fallback"


@pytest.mark.asyncio
async def test_pydanticai_backend_delegates_to_runtime(monkeypatch, tmp_path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        created["name"] = name
        created["kwargs"] = kwargs
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    backend = PydanticAIHarnessBackend()
    request = HarnessBackendRequest(
        spec=get_harness_template("coding"),
        prompt="code",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    result = await backend.run(request)

    assert created["name"] == "pydanticai"
    assert result.backend == "pydanticai"
    assert result.runtime == "pydanticai"
    assert result.response.content.startswith("code|tools=")


@pytest.mark.asyncio
async def test_runtime_harness_backend_preserves_rich_runtime_events(monkeypatch, tmp_path):
    def fake_create_runtime(name, **kwargs):
        return FakeEventRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    backend = RuntimeHarnessBackend("pydanticai")
    request = HarnessBackendRequest(
        spec=get_harness_template("coding"),
        prompt="code",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
        session_id="s",
    )

    events = [event async for event in backend.stream(request)]

    assert [event.type for event in events[:2]] == ["model_delta", "tool_call"]
    assert events[0].session_id == "s"
    assert events[-1].type == "end"
