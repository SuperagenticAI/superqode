from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from superqode.agent.loop import AgentConfig


class _Response:
    def __aiter__(self):
        async def stream():
            yield "hello "
            yield "world"

        return stream()


class _Agent:
    config = None

    def __init__(self, config):
        type(self).config = config

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def chat(self, _prompt):
        return _Response()


def test_antigravity_runtime_streams_and_accepts_google_key(monkeypatch):
    google = ModuleType("google")
    google.__path__ = []
    sdk = ModuleType("google.antigravity")
    sdk.Agent = _Agent
    sdk.LocalAgentConfig = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.antigravity", sdk)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    runtime = AntigravitySDKRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )
    response = asyncio.run(runtime.run("hi"))

    assert response.content == "hello world"
    assert _Agent.config.api_key == "test-key"
    assert _Agent.config.workspaces == [str(Path.cwd())]
    assert runtime.metadata["harness_owner"] == "antigravity"


def test_antigravity_runtime_normalizes_rich_sdk_events(monkeypatch):
    google = ModuleType("google")
    google.__path__ = []
    sdk = ModuleType("google.antigravity")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.antigravity", sdk)

    class Text:
        text = "done"

    class Thought:
        text = "checking"

    class ToolCall:
        name = "view_file"
        id = "call-1"
        args = {"path": "README.md"}

    class ToolResult:
        name = "view_file"
        id = "call-1"
        result = "contents"
        error = None

    class RichResponse:
        @property
        def chunks(self):
            async def stream():
                for item in (Thought(), ToolCall(), ToolResult(), Text()):
                    yield item

            return stream()

    class Agent:
        async def chat(self, _prompt):
            return RichResponse()

    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    runtime = AntigravitySDKRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )
    runtime._agent = Agent()

    async def collect():
        return [event async for event in runtime.run_harness_events("inspect")]

    events = asyncio.run(collect())
    assert [event.type for event in events] == [
        "model_request",
        "thinking",
        "tool_call",
        "tool_result",
        "model_delta",
        "turn_complete",
        "model_result",
    ]
    assert events[2].data["tool_name"] == "view_file"
    assert events[3].data["success"] is True


def test_antigravity_tool_exception_is_a_failed_result(monkeypatch):
    google = ModuleType("google")
    google.__path__ = []
    sdk = ModuleType("google.antigravity")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.antigravity", sdk)

    class ToolResult:
        name = "bash"
        id = "call-2"
        result = None
        error = None
        exception = RuntimeError("boom")

    class Response:
        @property
        def chunks(self):
            async def stream():
                yield ToolResult()

            return stream()

    class Agent:
        async def chat(self, _prompt):
            return Response()

    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    runtime = AntigravitySDKRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )
    runtime._agent = Agent()

    async def collect():
        return [event async for event in runtime.run_harness_events("inspect")]

    result = next(event for event in asyncio.run(collect()) if event.type == "tool_result")
    assert result.data["success"] is False
    assert result.data["error"] == "boom"
