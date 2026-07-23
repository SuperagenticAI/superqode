"""Contract tests for the optional GitHub Copilot SDK runtime."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.agent.loop import AgentConfig


class _Decision:
    def __init__(self, feedback: str = "") -> None:
        self.feedback = feedback


class _FakeSession:
    def __init__(self, session_id: str = "copilot-session") -> None:
        self.session_id = session_id
        self.handlers = []
        self.model = ""
        self.disconnected = False
        self.aborted = False

    def on(self, handler):
        self.handlers.append(handler)

        def unsubscribe():
            self.handlers.remove(handler)

        return unsubscribe

    async def send_and_wait(self, prompt: str, timeout: float = 60.0):
        assert prompt == "inspect this repository"
        assert timeout > 0
        events = [
            ("assistant.reasoning_delta", {"deltaContent": "checking"}),
            (
                "tool.execution_start",
                {"toolName": "shell", "toolCallId": "call-1", "arguments": {"command": "pwd"}},
            ),
            (
                "tool.execution_complete",
                {
                    "toolName": "shell",
                    "toolCallId": "call-1",
                    "success": True,
                    "output": "/repo",
                },
            ),
            ("assistant.message_delta", {"deltaContent": "Done"}),
            ("assistant.usage", {"inputTokens": 10, "outputTokens": 2}),
            ("session.idle", {}),
        ]
        for event_type, data in events:
            event = SimpleNamespace(type=event_type, data=SimpleNamespace(**data))
            for handler in list(self.handlers):
                handler(event)
        return None

    async def set_model(self, model: str):
        self.model = model

    async def disconnect(self):
        self.disconnected = True

    async def abort(self):
        self.aborted = True


class _FakeClient:
    instances = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.session = _FakeSession()
        self.create_kwargs = {}
        self.__class__.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def create_session(self, **kwargs):
        self.create_kwargs = kwargs
        return self.session

    async def resume_session(self, session_id, **kwargs):
        self.create_kwargs = kwargs
        self.session = _FakeSession(session_id)
        return self.session

    async def list_models(self):
        return [SimpleNamespace(id="gpt-5.6-sol", name="GPT-5.6 Sol", supportsReasoningEffort=True)]

    async def list_sessions(self):
        return [SimpleNamespace(session_id="saved-1", title="Review")]


@pytest.fixture
def fake_copilot_sdk(monkeypatch):
    module = types.ModuleType("copilot")
    module.__path__ = []
    module.CopilotClient = _FakeClient
    rpc_module = types.ModuleType("copilot.rpc")
    rpc_module.PermissionDecisionApproveOnce = type(
        "PermissionDecisionApproveOnce", (_Decision,), {}
    )
    rpc_module.PermissionDecisionReject = type("PermissionDecisionReject", (_Decision,), {})
    monkeypatch.setitem(sys.modules, "copilot", module)
    monkeypatch.setitem(sys.modules, "copilot.rpc", rpc_module)
    _FakeClient.instances.clear()
    return module


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        provider="github-copilot",
        model="gpt-5.6-sol",
        working_directory=tmp_path,
        custom_system_prompt="Follow the repository policy.",
        session_id="superqode-session",
    )


def test_registry_knows_copilot_sdk():
    from superqode.runtime import known_runtime_names

    assert "copilot-sdk" in known_runtime_names()


@pytest.mark.asyncio
async def test_runtime_streams_normalized_events(fake_copilot_sdk, tmp_path):
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    runtime = CopilotSDKRuntime(
        config=_config(tmp_path),
        approval_callback=lambda _name, _args: True,
    )
    events = [event async for event in runtime.run_harness_events("inspect this repository")]

    assert any(e.type == "thinking" and e.data["text"] == "checking" for e in events)
    assert any(
        e.type == "tool_call"
        and e.data["tool_name"] == "bash"
        and e.data["args"] == {"command": "pwd"}
        for e in events
    )
    assert any(
        e.type == "tool_result" and e.data["success"] and e.data["output"] == "/repo"
        for e in events
    )
    assert any(e.type == "model_delta" and e.data["text"] == "Done" for e in events)
    assert events[-2].type == "turn_complete"
    assert events[-2].data["status"] == "completed"

    client = _FakeClient.instances[-1]
    assert client.started is True
    assert client.kwargs["working_directory"] == str(tmp_path)
    assert client.create_kwargs["model"] == "gpt-5.6-sol"
    assert client.create_kwargs["streaming"] is True
    assert client.create_kwargs["enable_config_discovery"] is True
    assert client.create_kwargs["system_message"]["mode"] == "append"

    await runtime.aclose()
    assert client.stopped is True


@pytest.mark.asyncio
async def test_runtime_model_discovery_switch_and_resume(fake_copilot_sdk, tmp_path):
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    runtime = CopilotSDKRuntime(config=_config(tmp_path))
    models = await runtime.models()
    assert models == [
        {
            "id": "gpt-5.6-sol",
            "name": "GPT-5.6 Sol",
            "supports_reasoning_effort": True,
        }
    ]

    runtime.set_model("gpt-5.6-sol")
    await runtime._apply_pending()
    assert runtime.active_model == "gpt-5.6-sol"
    assert runtime._session.model == "gpt-5.6-sol"

    sessions = await runtime.list_threads()
    assert sessions[0].session_id == "saved-1"
    await runtime.resume_thread("saved-1")
    assert runtime.thread_id == "saved-1"
    await runtime.aclose()


@pytest.mark.asyncio
async def test_runtime_permission_callback_controls_sdk_decision(fake_copilot_sdk, tmp_path):
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    runtime = CopilotSDKRuntime(
        config=_config(tmp_path),
        approval_callback=lambda name, args: name == "bash" and args["command"] == "pwd",
    )
    request = SimpleNamespace(fullCommandText="pwd")
    decision = await runtime._approval_handler(request)
    assert type(decision).__name__ == "PermissionDecisionApproveOnce"
