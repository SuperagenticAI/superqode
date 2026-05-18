"""Tests for harness backend registry and runtime adapter."""

import sys
import types

import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import (
    DeepAgentsHarnessBackend,
    ExecutionPolicySpec,
    HarnessBackendRequest,
    RuntimeHarnessBackend,
    create_harness_backend,
    get_harness_template,
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


def test_known_harness_backends_include_current_runtime_backends():
    names = known_harness_backend_names()

    assert "builtin" in names
    assert "adk" in names
    assert "openai-agents" in names
    assert "deepagents" in names


def test_create_harness_backend_returns_runtime_adapter():
    backend = create_harness_backend("builtin")

    assert isinstance(backend, RuntimeHarnessBackend)
    assert backend.name == "builtin"


def test_create_harness_backend_returns_deepagents_adapter():
    backend = create_harness_backend("deepagents")

    assert isinstance(backend, DeepAgentsHarnessBackend)
    assert backend.name == "deepagents"


def test_create_harness_backend_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown harness backend"):
        create_harness_backend("unknown-backend")


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
