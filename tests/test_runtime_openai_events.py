"""Tests for OpenAI Agents rich harness event streaming."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.openai_agents import OpenAIAgentsRuntime
from superqode.tools.base import ToolRegistry


class FakeStreamResult:
    def __init__(self, events, *, interruptions=None, final_output="done"):
        self._events = events
        self.interruptions = interruptions or []
        self.final_output = final_output
        self.new_items = []
        self.raw_responses = ["r1"]
        self.cancelled = False

    async def stream_events(self):
        for event in self._events:
            yield event

    def cancel(self):
        self.cancelled = True


class FakeRunner:
    stream_result: FakeStreamResult | None = None

    @classmethod
    def run_streamed(cls, *args, **kwargs):
        assert cls.stream_result is not None
        return cls.stream_result


class FakeAgent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeRunConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeRawResponsesStreamEvent:
    def __init__(self, text):
        self.data = types.SimpleNamespace(delta=text)


class FakeItemStreamEvent:
    def __init__(self, item):
        self.item = item


def install_fake_agents(monkeypatch):
    agents = types.ModuleType("agents")
    run = types.ModuleType("agents.run")
    stream_events = types.ModuleType("agents.stream_events")
    tool = types.ModuleType("agents.tool")

    class FakeFunctionTool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    agents.Agent = FakeAgent
    agents.Runner = FakeRunner
    run.RunConfig = FakeRunConfig
    stream_events.RawResponsesStreamEvent = FakeRawResponsesStreamEvent
    tool.FunctionTool = FakeFunctionTool

    monkeypatch.setitem(sys.modules, "agents", agents)
    monkeypatch.setitem(sys.modules, "agents.run", run)
    monkeypatch.setitem(sys.modules, "agents.stream_events", stream_events)
    monkeypatch.setitem(sys.modules, "agents.tool", tool)


def make_runtime(tmp_path: Path, monkeypatch, *, sandbox_backend: str | None = None):
    install_fake_agents(monkeypatch)
    if sandbox_backend:
        sandbox = types.ModuleType("superqode.harness.sandbox")
        sandbox.supported_sandbox_backends = lambda: {sandbox_backend}
        sandbox.build_sandbox_client = lambda name: f"client:{name}"
        sandbox.build_manifest = lambda config: {"root": str(config.working_directory)}
        sandbox.build_sandbox_agent = lambda **kwargs: FakeAgent(**kwargs)
        sandbox.build_sandbox_run_config = lambda client, base_run_config: base_run_config
        monkeypatch.setitem(sys.modules, "superqode.harness.sandbox", sandbox)

    return OpenAIAgentsRuntime(
        tools=ToolRegistry.empty(),
        config=AgentConfig(
            provider="openai",
            model="gpt-5",
            working_directory=tmp_path,
            enable_session_storage=False,
            session_id="openai-events",
        ),
        sandbox_backend=sandbox_backend,
    )


def raw_item(name: str = "echo", arguments: Any = None, output: str | None = None):
    return types.SimpleNamespace(name=name, arguments=arguments or {}, output=output)


@pytest.mark.asyncio
async def test_openai_agents_runtime_streams_rich_harness_events(monkeypatch, tmp_path):
    runtime = make_runtime(tmp_path, monkeypatch)
    FakeRunner.stream_result = FakeStreamResult(
        [
            FakeRawResponsesStreamEvent("hello"),
            FakeItemStreamEvent(
                types.SimpleNamespace(
                    type="tool_call_item",
                    raw_item=raw_item("echo", {"text": "hi"}),
                )
            ),
            FakeItemStreamEvent(
                types.SimpleNamespace(
                    type="tool_call_output_item",
                    raw_item=raw_item("echo", output="ok"),
                )
            ),
        ],
        final_output="done",
    )

    events = [event async for event in runtime.run_harness_events("stream")]

    assert [event.type for event in events] == [
        "model_request",
        "model_delta",
        "tool_call",
        "tool_result",
        "model_result",
    ]
    assert events[1].data["text"] == "hello"
    assert events[2].data["tool_name"] == "echo"
    assert events[3].data["content"] == "ok"
    assert events[4].data["output"] == "done"


@pytest.mark.asyncio
async def test_openai_agents_runtime_streams_approval_required(monkeypatch, tmp_path):
    runtime = make_runtime(tmp_path, monkeypatch)
    approval_item = types.SimpleNamespace(
        tool_name="bash",
        raw_item=raw_item("bash", {"command": "ls"}),
    )
    FakeRunner.stream_result = FakeStreamResult([], interruptions=[approval_item], final_output="")

    events = [event async for event in runtime.run_harness_events("stream")]

    assert events[-1].type == "approval_required"
    assert events[-1].data["pending_approvals"] == [
        {"index": 0, "tool_name": "bash", "arguments": {"command": "ls"}}
    ]
    assert runtime.get_pending_approvals()[0]["tool_name"] == "bash"


@pytest.mark.asyncio
async def test_openai_agents_runtime_streams_sandbox_start(monkeypatch, tmp_path):
    runtime = make_runtime(tmp_path, monkeypatch, sandbox_backend="local")
    FakeRunner.stream_result = FakeStreamResult([], final_output="done")

    events = [event async for event in runtime.run_harness_events("stream")]

    assert events[0].type == "model_request"
    assert events[1].type == "sandbox_start"
    assert events[1].data["backend"] == "local"
