from __future__ import annotations

import asyncio
import copy
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
        usage_metadata = SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=4,
            thoughts_token_count=2,
            total_token_count=16,
            cached_content_token_count=3,
        )

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
    assert events[-2].data["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "thinking_tokens": 2,
        "total_tokens": 16,
        "cached_tokens": 3,
    }


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


def test_sdk_policy_bridge_asks_superqode_for_mutating_tools(tmp_path):
    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    approvals = []
    runtime = AntigravitySDKRuntime(
        config=AgentConfig(provider="google", model="", working_directory=tmp_path),
        approval_callback=lambda name, args: approvals.append((name, args)) or True,
    )
    tool_call = SimpleNamespace(name="edit_file", args={"path": "README.md"})

    assert runtime._approve_tool_call(tool_call) is True
    assert approvals == [("edit_file", {"path": "README.md"})]
    assert copy.deepcopy(runtime._sdk_policies())


def test_sdk_discovers_project_skills_and_converts_mcp(tmp_path):
    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    skills = tmp_path / ".agents" / "skills"
    skills.mkdir(parents=True)
    mcp_dir = tmp_path / ".superqode"
    mcp_dir.mkdir()
    (mcp_dir / "mcp.json").write_text(
        '{"mcpServers":{"local.files":{"command":"example-mcp","args":["--stdio"]},'
        '"remote":{"transport":"http","url":"https://example.invalid/mcp"}}}'
    )
    runtime = AntigravitySDKRuntime(
        config=AgentConfig(provider="google", model="", working_directory=tmp_path),
        include_mcp=True,
    )

    servers = runtime._sdk_mcp_servers()

    assert runtime.metadata["skills"] == [str(skills.resolve())]
    assert [server.name for server in servers] == ["local-files", "remote"]
    assert runtime.metadata["mcp_servers"] == 2


def test_sdk_reasoning_effort_builds_thinking_model_target(tmp_path):
    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    runtime = AntigravitySDKRuntime(
        config=AgentConfig(
            provider="google",
            model="gemini-test",
            working_directory=tmp_path,
            reasoning_effort="extra-high",
        )
    )

    target = runtime._sdk_model("not-a-live-key")

    assert target.name == "gemini-test"
    assert target.endpoint.options.thinking_level.value == "extra_high"


def test_sdk_disables_all_capabilities_for_no_tool_config(tmp_path):
    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    runtime = AntigravitySDKRuntime(
        config=AgentConfig(
            provider="google",
            model="gemini-test",
            working_directory=tmp_path,
            tools_enabled=False,
        )
    )

    capabilities = runtime._sdk_capabilities()

    assert capabilities.enable_subagents is False
    assert capabilities.enabled_tools == []


def test_sdk_cancel_reaches_active_response(monkeypatch, tmp_path):
    google = ModuleType("google")
    google.__path__ = []
    sdk = ModuleType("google.antigravity")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.antigravity", sdk)

    class Response:
        cancelled = False

        @property
        def chunks(self):
            async def stream():
                await asyncio.sleep(60)
                if False:
                    yield None

            return stream()

        async def cancel(self):
            self.cancelled = True

    response = Response()

    class Agent:
        async def chat(self, _prompt):
            return response

    from superqode.runtime.antigravity_sdk import AntigravitySDKRuntime

    runtime = AntigravitySDKRuntime(
        config=AgentConfig(provider="google", model="", working_directory=tmp_path)
    )
    runtime._agent = Agent()

    async def exercise():
        events = runtime.run_harness_events("wait")
        first = await anext(events)
        assert first.type == "model_request"
        runtime.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await events.aclose()

    asyncio.run(exercise())
    assert response.cancelled is True
