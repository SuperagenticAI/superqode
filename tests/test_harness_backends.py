"""Tests for harness backend registry and runtime adapter."""

import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import (
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


def test_create_harness_backend_returns_runtime_adapter():
    backend = create_harness_backend("builtin")

    assert isinstance(backend, RuntimeHarnessBackend)
    assert backend.name == "builtin"


def test_create_harness_backend_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown harness backend"):
        create_harness_backend("deepagents")


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
