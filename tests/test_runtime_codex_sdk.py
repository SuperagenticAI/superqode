"""Tests for the optional OpenAI Codex Python SDK runtime adapter."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime import create_runtime, known_runtime_names, list_runtimes
from superqode.runtime.errors import RuntimeNotInstalledError
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        provider="openai",
        model="gpt-5.4",
        working_directory=tmp_path,
        enable_session_storage=False,
        session_id="codex-test",
    )


class _FakeSandbox:
    read_only = "read-only"
    workspace_write = "workspace-write"
    full_access = "danger-full-access"


class _FakeApprovalMode:
    auto_review = "auto_review"
    deny_all = "deny_all"


@dataclass
class _FakeCodexConfig:
    cwd: str | None = None
    client_name: str = ""
    client_title: str = ""


@dataclass
class _FakeThreadStart:
    thread: Any


@dataclass
class _FakeTurnStart:
    turn: Any


@dataclass
class _FakeResult:
    status: str = "completed"
    final_response: str = "done"
    items: list[Any] | None = None
    usage: Any = None
    error: Any = None


@dataclass
class _FakeNotification:
    method: str
    payload: Any


class _FakeTurnHandle:
    def __init__(self, events: list[_FakeNotification] | None = None):
        self.id = "turn-1"
        self.interrupted = False
        self.events = events or [
            _FakeNotification(
                "item/agentMessage/delta",
                types.SimpleNamespace(delta="hello", item_id="msg-1"),
            ),
            _FakeNotification(
                "turn/completed",
                types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
            ),
        ]

    def run(self):
        return _FakeResult(final_response="final text", items=[])

    def stream(self):
        return iter(self.events)

    def interrupt(self):
        self.interrupted = True


class _FakeThread:
    def __init__(self, client, thread_id: str):
        self._client = client
        self.id = thread_id
        self.last_turn = None

    def turn(self, prompt: str, **kwargs):
        self.last_turn = _FakeTurnHandle()
        self.prompt = prompt
        self.kwargs = kwargs
        return self.last_turn


class _FakeCodexClient:
    last_instance = None

    def __init__(self, config=None, approval_handler=None):
        self.config = config
        self.approval_handler = approval_handler
        self.started = False
        self.closed = False
        self.thread_start_params = None
        _FakeCodexClient.last_instance = self

    def start(self):
        self.started = True

    def initialize(self):
        return types.SimpleNamespace(userAgent="fake-codex")

    def thread_start(self, params=None):
        self.thread_start_params = params
        return _FakeThreadStart(thread=types.SimpleNamespace(id="thread-1"))

    def model_list(self, include_hidden=False):
        return types.SimpleNamespace(data=[types.SimpleNamespace(model="gpt-5.4")])

    def close(self):
        self.closed = True


@pytest.fixture
def fake_codex_sdk(monkeypatch):
    fake = types.ModuleType("openai_codex")
    fake.ApprovalMode = _FakeApprovalMode
    fake.CodexConfig = _FakeCodexConfig
    fake.Sandbox = _FakeSandbox
    fake.Thread = _FakeThread

    fake_client_mod = types.ModuleType("openai_codex.client")
    fake_client_mod.CodexClient = _FakeCodexClient

    monkeypatch.setitem(sys.modules, "openai_codex", fake)
    monkeypatch.setitem(sys.modules, "openai_codex.client", fake_client_mod)
    return fake


def test_runtime_registry_knows_codex_sdk():
    assert "codex-sdk" in known_runtime_names()
    info = {item.name: item for item in list_runtimes()}
    assert info["codex-sdk"].install_hint == "pip install superqode[codex-sdk]"


def test_factory_reports_missing_codex_sdk_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "openai_codex", raising=False)
    monkeypatch.delitem(sys.modules, "openai_codex.client", raising=False)
    with pytest.raises(RuntimeNotInstalledError):
        create_runtime("codex-sdk", config=_config(tmp_path))


def test_factory_returns_codex_sdk_runtime(fake_codex_sdk, tmp_path):
    from superqode.runtime.codex_sdk import CodexSDKRuntime

    runtime = create_runtime("codex-sdk", config=_config(tmp_path))
    assert isinstance(runtime, CodexSDKRuntime)
    assert runtime.name == "codex-sdk"


def test_run_uses_codex_thread_and_returns_agent_response(fake_codex_sdk, tmp_path):
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    import asyncio

    response = asyncio.run(runtime.run("hello"))

    assert response.content == "final text"
    assert response.stopped_reason == "complete"
    assert runtime._thread.id == "thread-1"
    assert _FakeCodexClient.last_instance.thread_start_params["model"] == "gpt-5.4"


def test_streaming_maps_agent_delta_to_text(fake_codex_sdk, tmp_path):
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [chunk async for chunk in runtime.run_streaming("hello")]

    import asyncio

    assert asyncio.run(collect()) == ["hello"]


def test_approval_handler_accepts_allowed_shell(fake_codex_sdk, tmp_path):
    manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))
    runtime = create_runtime("codex-sdk", config=_config(tmp_path), permission_manager=manager)
    runtime.metadata

    decision = _FakeCodexClient.last_instance.approval_handler(
        "item/commandExecution/requestApproval",
        {"command": "git status"},
    )

    assert decision == {"decision": "accept"}


def test_approval_handler_rejects_ask_policy_without_interactive_bridge(fake_codex_sdk, tmp_path):
    manager = PermissionManager(PermissionConfig(default=Permission.ASK))
    runtime = create_runtime("codex-sdk", config=_config(tmp_path), permission_manager=manager)
    runtime.metadata

    decision = _FakeCodexClient.last_instance.approval_handler(
        "item/fileChange/requestApproval",
        {"path": "app.py"},
    )

    assert decision["decision"] == "reject"
    assert "interactive approval" in decision["reason"]
