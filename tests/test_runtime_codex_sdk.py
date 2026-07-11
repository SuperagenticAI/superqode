"""Tests for the optional OpenAI Codex Python SDK runtime adapter."""

from __future__ import annotations

import sys
import os
import threading
import time
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
    config_overrides: tuple[str, ...] = ()
    codex_bin: str | None = None
    cwd: str | None = None
    client_name: str = ""
    client_title: str = ""
    client_version: str = ""


@dataclass
class _FakeThreadStart:
    thread: Any
    model: str | None = None


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
    active_runs = 0
    max_active_runs = 0
    run_delay = 0.0
    run_lock = threading.Lock()

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
        with self.run_lock:
            type(self).active_runs += 1
            type(self).max_active_runs = max(type(self).max_active_runs, type(self).active_runs)
        try:
            if self.run_delay:
                time.sleep(self.run_delay)
            return _FakeResult(final_response="final text", items=[])
        finally:
            with self.run_lock:
                type(self).active_runs -= 1

    def stream(self):
        return iter(self.events)

    def interrupt(self):
        self.interrupted = True


class _FakeThread:
    next_events = None

    def __init__(self, client, thread_id: str):
        self._client = client
        self.id = thread_id
        self.last_turn = None

    def turn(self, prompt: str, **kwargs):
        self.last_turn = _FakeTurnHandle(events=self.next_events)
        _FakeThread.next_events = None
        self.prompt = prompt
        self.kwargs = kwargs
        return self.last_turn

    def read(self, *, include_turns: bool = False):
        return self._client.thread_read(self.id, include_turns=include_turns)

    def set_name(self, name: str):
        return self._client.thread_set_name(self.id, name)

    def compact(self):
        return self._client.thread_compact(self.id)


class _FakeCodexClient:
    last_instance = None

    def __init__(self, config=None, approval_handler=None):
        self.config = config
        self.approval_handler = approval_handler
        self.started = False
        self.closed = False
        self.thread_start_params = None
        self.resumed = None
        self.forked = None
        self.archived = None
        self.renamed = None
        self.compacted = None
        _FakeCodexClient.last_instance = self

    def start(self):
        self.started = True

    def initialize(self):
        return types.SimpleNamespace(userAgent="fake-codex")

    def thread_start(self, params=None):
        self.thread_start_params = params
        return _FakeThreadStart(
            thread=types.SimpleNamespace(id="thread-1"),
            model=params.get("model") if params else "gpt-5.4",
        )

    def model_list(self, include_hidden=False):
        return types.SimpleNamespace(
            data=[
                types.SimpleNamespace(
                    model="gpt-5.4",
                    display_name="GPT-5.4",
                    hidden=False,
                    supported_reasoning_efforts=[
                        types.SimpleNamespace(reasoning_effort=types.SimpleNamespace(value="high"))
                    ],
                )
            ]
        )

    def account_read(self, params=None):
        return types.SimpleNamespace(account=types.SimpleNamespace(email="user@example.com"))

    def account_logout(self):
        return types.SimpleNamespace(status="ok")

    def thread_list(self, params=None):
        return types.SimpleNamespace(
            data=[
                types.SimpleNamespace(
                    id="thread-1",
                    name="Main thread",
                    preview="hello",
                    model="gpt-5.4",
                )
            ]
        )

    def thread_resume(self, thread_id, params=None):
        self.resumed = (thread_id, params)
        return types.SimpleNamespace(thread=types.SimpleNamespace(id=thread_id), model="gpt-5.4")

    def thread_fork(self, thread_id, params=None):
        self.forked = (thread_id, params)
        return types.SimpleNamespace(thread=types.SimpleNamespace(id="fork-1"), model="gpt-5.4")

    def thread_archive(self, thread_id):
        self.archived = thread_id
        return types.SimpleNamespace(status="ok")

    def thread_read(self, thread_id, include_turns=False):
        return types.SimpleNamespace(
            thread=types.SimpleNamespace(id=thread_id, name="Main thread", preview="hello")
        )

    def thread_set_name(self, thread_id, name):
        self.renamed = (thread_id, name)
        return types.SimpleNamespace(status="ok")

    def thread_compact(self, thread_id):
        self.compacted = thread_id
        return types.SimpleNamespace(status="ok")

    def close(self):
        self.closed = True


@pytest.fixture
def fake_codex_sdk(monkeypatch):
    from superqode.runtime import codex_sdk

    fake = types.ModuleType("openai_codex")
    fake.ApprovalMode = _FakeApprovalMode
    fake.CodexConfig = _FakeCodexConfig
    fake.Sandbox = _FakeSandbox
    fake.Thread = _FakeThread

    fake_client_mod = types.ModuleType("openai_codex.client")
    fake_client_mod.CodexClient = _FakeCodexClient

    monkeypatch.setitem(sys.modules, "openai_codex", fake)
    monkeypatch.setitem(sys.modules, "openai_codex.client", fake_client_mod)
    # Unit fakes must not depend on whichever Codex executable happens to be
    # installed on the test runner. Individual tests opt into a local CLI.
    monkeypatch.setattr(codex_sdk, "_newer_local_codex_binary", lambda: None)
    return fake


def test_runtime_registry_knows_codex_sdk():
    assert "codex-sdk" in known_runtime_names()
    info = {item.name: item for item in list_runtimes()}
    codex = info["codex-sdk"]
    # install_hint is an env-aware uv command when the SDK is absent, None when present.
    if codex.installed:
        assert codex.install_hint is None
    else:
        assert codex.install_hint.startswith("uv ")
        assert "[codex-sdk]" in codex.install_hint


def test_factory_reports_missing_codex_sdk_when_not_installed(monkeypatch, tmp_path):
    # Simulate "not installed" even if the codex-sdk extra is present in the env:
    # setting the module to None in sys.modules makes `import openai_codex` raise
    # ImportError (deleting it would just let an installed package re-import).
    monkeypatch.setitem(sys.modules, "openai_codex", None)
    monkeypatch.setitem(sys.modules, "openai_codex.client", None)
    with pytest.raises(RuntimeNotInstalledError):
        create_runtime("codex-sdk", config=_config(tmp_path))


def test_factory_returns_codex_sdk_runtime(fake_codex_sdk, tmp_path):
    from superqode.runtime.codex_sdk import CodexSDKRuntime

    runtime = create_runtime("codex-sdk", config=_config(tmp_path))
    assert isinstance(runtime, CodexSDKRuntime)
    assert runtime.name == "codex-sdk"


def test_runtime_prefers_a_newer_local_codex_cli(fake_codex_sdk, monkeypatch, tmp_path):
    """A local newer app-server must drive the live Codex model catalogue."""
    from superqode.runtime import codex_sdk

    monkeypatch.setattr(
        codex_sdk,
        "_newer_local_codex_binary",
        lambda: ("/opt/homebrew/bin/codex", "0.144.0"),
    )
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    assert runtime.metadata.userAgent == "fake-codex"
    assert _FakeCodexClient.last_instance.config.codex_bin == "/opt/homebrew/bin/codex"
    assert runtime.app_server_source == "local Codex CLI 0.144.0"
    assert runtime.active_model == "gpt-5.4"


def test_installed_sdk_protocol_contract_has_translated_fields():
    sdk_types = pytest.importorskip("openai_codex.generated.v2_all")

    assert "item_id" in sdk_types.AgentMessageDeltaNotification.model_fields
    assert "aggregated_output" in sdk_types.CommandExecutionThreadItem.model_fields
    assert "exit_code" in sdk_types.CommandExecutionThreadItem.model_fields
    assert "changes" in sdk_types.FileChangeThreadItem.model_fields
    assert "result" in sdk_types.McpToolCallThreadItem.model_fields
    assert "content_items" in sdk_types.DynamicToolCallThreadItem.model_fields


def test_installed_sdk_accepts_newer_codex_reasoning_efforts():
    """New server-advertised efforts must not make model/list fail to parse."""
    pytest.importorskip("openai_codex")
    from openai_codex.types import ReasoningEffort
    from superqode.runtime.codex_sdk import _enable_forward_compatible_reasoning_efforts

    _enable_forward_compatible_reasoning_efforts()

    assert ReasoningEffort("max").value == "max"
    assert ReasoningEffort("ultra").value == "ultra"


def test_codex_model_response_conversion_uses_live_ids():
    from superqode.app_main import SuperQodeApp

    response = types.SimpleNamespace(
        data=[
            types.SimpleNamespace(
                model="gpt-5.6-terra",
                display_name="GPT-5.6-Terra",
                supported_reasoning_efforts=[
                    types.SimpleNamespace(reasoning_effort=types.SimpleNamespace(value="max")),
                    types.SimpleNamespace(reasoning_effort=types.SimpleNamespace(value="ultra")),
                ],
            ),
            types.SimpleNamespace(model="gpt-5.5"),
            types.SimpleNamespace(id="gpt-5.4-mini"),
        ]
    )

    models = SuperQodeApp._models_from_codex_response(response)
    assert [model["id"] for model in models] == [
        "gpt-5.6-terra",
        "gpt-5.5",
        "gpt-5.4-mini",
    ]
    assert models[0]["name"] == "GPT-5.6-Terra"
    assert models[0]["efforts"] == ["max", "ultra"]
    assert models[1]["name"] == "Gpt 5.5"


@pytest.mark.skipif(
    os.getenv("SUPERQODE_CODEX_REAL_TEST") != "1",
    reason="set SUPERQODE_CODEX_REAL_TEST=1 to run the real Codex SDK/app-server smoke test",
)
def test_real_codex_sdk_smoke_turn(tmp_path):
    from superqode.codex import make_codex_runtime

    runtime = make_codex_runtime(cwd=tmp_path, tools=False)
    try:
        import asyncio

        response = asyncio.run(runtime.run("Reply with exactly: superqode codex ok"))
    finally:
        runtime.close()

    assert "superqode codex ok" in response.content.lower()


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


def test_streaming_requires_turn_completed(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "item/agentMessage/delta",
            types.SimpleNamespace(delta="partial", item_id="msg-1"),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [chunk async for chunk in runtime.run_streaming("hello")]

    import asyncio

    with pytest.raises(RuntimeError, match="turn/completed"):
        asyncio.run(collect())


def test_completed_agent_message_is_streaming_fallback(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "item/completed",
            types.SimpleNamespace(
                item=types.SimpleNamespace(
                    root=types.SimpleNamespace(
                        type="agentMessage",
                        id="msg-1",
                        text="final fallback",
                    )
                )
            ),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [chunk async for chunk in runtime.run_streaming("hello")]

    import asyncio

    assert asyncio.run(collect()) == ["final fallback"]


def test_completed_agent_message_does_not_duplicate_streamed_delta(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "item/agentMessage/delta",
            types.SimpleNamespace(delta="hello", item_id="msg-1"),
        ),
        _FakeNotification(
            "item/completed",
            types.SimpleNamespace(
                item=types.SimpleNamespace(
                    root=types.SimpleNamespace(
                        type="agentMessage",
                        id="msg-1",
                        text="hello",
                    )
                )
            ),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [chunk async for chunk in runtime.run_streaming("hello")]

    import asyncio

    assert asyncio.run(collect()) == ["hello"]


def test_cancelled_stream_without_turn_completed_does_not_raise(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "item/agentMessage/delta",
            types.SimpleNamespace(delta="partial", item_id="msg-1"),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        events = []
        async for event in runtime.run_harness_events("hello"):
            events.append(event)
            if event.type == "model_delta":
                runtime.cancel()
        return events

    import asyncio

    events = asyncio.run(collect())
    assert [event.type for event in events] == [
        "model_request",
        "model_delta",
        "turn_complete",
        "model_result",
    ]
    assert events[-2].data["status"] == "cancelled"


def test_runtime_serializes_concurrent_turns(fake_codex_sdk, tmp_path):
    _FakeTurnHandle.active_runs = 0
    _FakeTurnHandle.max_active_runs = 0
    _FakeTurnHandle.run_delay = 0.05
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def run_two():
        return await asyncio.gather(runtime.run("one"), runtime.run("two"))

    import asyncio

    try:
        responses = asyncio.run(run_two())
    finally:
        _FakeTurnHandle.run_delay = 0.0

    assert [response.content for response in responses] == ["final text", "final text"]
    assert _FakeTurnHandle.max_active_runs == 1


def test_command_completion_uses_aggregated_output_and_exit_code(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "item/completed",
            types.SimpleNamespace(
                item=types.SimpleNamespace(
                    root=types.SimpleNamespace(
                        type="commandExecution",
                        id="cmd-1",
                        status="failed",
                        aggregated_output="boom",
                        exit_code=2,
                    )
                )
            ),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [event async for event in runtime.run_harness_events("hello")]

    import asyncio

    events = asyncio.run(collect())
    tool_result = next(event for event in events if event.type == "tool_result")
    assert tool_result.data["tool_name"] == "bash"
    assert tool_result.data["success"] is False
    assert tool_result.data["output"] == "boom"
    assert tool_result.data["exit_code"] == 2


def test_file_change_output_delta_maps_to_patch_tool_delta(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "item/fileChange/outputDelta",
            types.SimpleNamespace(delta="applying patch", item_id="patch-1"),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [event async for event in runtime.run_harness_events("hello")]

    import asyncio

    events = asyncio.run(collect())
    tool_delta = next(event for event in events if event.type == "tool_delta")
    assert tool_delta.data == {
        "tool_name": "patch",
        "text": "applying patch",
        "tool_call_id": "patch-1",
    }


def test_codex_plan_update_maps_to_plan_update(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "turn/plan/updated",
            types.SimpleNamespace(
                explanation="Need to inspect first",
                plan=[
                    types.SimpleNamespace(step="Inspect files", status="inProgress"),
                    types.SimpleNamespace(step="Run tests", status="pending"),
                ],
            ),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [event async for event in runtime.run_harness_events("hello")]

    import asyncio

    events = asyncio.run(collect())
    plan_update = next(event for event in events if event.type == "plan_update")
    assert plan_update.data["source_event"] == "turn/plan/updated"
    assert plan_update.data["explanation"] == "Need to inspect first"
    assert plan_update.data["todos"] == [
        {
            "id": "1",
            "content": "Inspect files",
            "status": "in_progress",
            "priority": "medium",
        },
        {"id": "2", "content": "Run tests", "status": "pending", "priority": "medium"},
    ]


def test_codex_todo_list_item_maps_to_plan_update(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "item/completed",
            types.SimpleNamespace(
                item=types.SimpleNamespace(
                    root=types.SimpleNamespace(
                        type="todo_list",
                        id="todo-list-1",
                        items=[
                            types.SimpleNamespace(text="Inspect files", completed=True),
                            types.SimpleNamespace(text="Run tests", completed=False),
                        ],
                    )
                )
            ),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [event async for event in runtime.run_harness_events("hello")]

    import asyncio

    events = asyncio.run(collect())
    plan_update = next(event for event in events if event.type == "plan_update")
    assert plan_update.data["tool_call_id"] == "todo-list-1"
    assert plan_update.data["source_event"] == "item/completed"
    assert plan_update.data["todos"] == [
        {
            "id": "1",
            "content": "Inspect files",
            "status": "completed",
            "priority": "medium",
        },
        {"id": "2", "content": "Run tests", "status": "pending", "priority": "medium"},
    ]


def test_default_approval_handler_rejects_without_interactive_bridge(fake_codex_sdk, tmp_path):
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))
    runtime.metadata

    decision = _FakeCodexClient.last_instance.approval_handler(
        "item/commandExecution/requestApproval",
        {"command": "git status"},
    )

    assert decision["decision"] == "reject"
    assert "outside the TUI" in decision["reason"]
    assert "~/.codex" in decision["reason"]


def test_approval_handler_uses_bridge_callback_when_available(fake_codex_sdk, tmp_path):
    calls = []
    runtime = create_runtime(
        "codex-sdk",
        config=_config(tmp_path),
        approval_callback=lambda name, args: calls.append((name, args)) or True,
    )
    runtime.metadata

    decision = _FakeCodexClient.last_instance.approval_handler(
        "item/commandExecution/requestApproval",
        {"command": "git status"},
    )

    assert decision == {"decision": "accept"}
    assert calls == [("bash", {"command": "git status"})]


def test_approval_handler_rejects_when_bridge_callback_denies(fake_codex_sdk, tmp_path):
    runtime = create_runtime(
        "codex-sdk",
        config=_config(tmp_path),
        approval_callback=lambda _name, _args: False,
    )
    runtime.metadata

    decision = _FakeCodexClient.last_instance.approval_handler(
        "item/fileChange/requestApproval",
        {"path": "app.py"},
    )

    assert decision["decision"] == "reject"
    assert "user rejected patch" in decision["reason"]


def test_pure_mode_passes_approval_bridge_to_codex_runtime(fake_codex_sdk, tmp_path):
    from superqode.pure_mode import PureMode

    calls = []
    pure = PureMode(runtime="codex-sdk")
    pure.on_permission_request = lambda name, args: calls.append((name, args)) or True

    assert pure.connect("openai", "", working_directory=tmp_path) is True
    pure._runtime.metadata

    decision = _FakeCodexClient.last_instance.approval_handler(
        "item/commandExecution/requestApproval",
        {"command": "git status"},
    )

    assert decision == {"decision": "accept"}
    assert calls == [("bash", {"command": "git status"})]


def test_make_codex_runtime_passes_approval_policy_and_session_id(fake_codex_sdk, tmp_path):
    from superqode.codex import make_codex_runtime

    calls = []
    manager = PermissionManager(PermissionConfig(default=Permission.ASK))
    runtime = make_codex_runtime(
        cwd=tmp_path,
        approval_callback=lambda name, args: calls.append((name, args)) or True,
        permission_manager=manager,
        session_id="custom-codex-session",
    )
    runtime.metadata

    decision = _FakeCodexClient.last_instance.approval_handler(
        "item/fileChange/requestApproval",
        {"path": "app.py"},
    )

    assert runtime.session_id == "custom-codex-session"
    assert decision == {"decision": "accept"}
    assert calls == [("patch", {"path": "app.py"})]


def test_pure_mode_forwards_codex_tool_events_to_callbacks(fake_codex_sdk, tmp_path):
    from superqode.pure_mode import PureMode

    _FakeThread.next_events = [
        _FakeNotification(
            "item/completed",
            types.SimpleNamespace(
                item=types.SimpleNamespace(
                    root=types.SimpleNamespace(
                        type="commandExecution",
                        id="cmd-1",
                        command="git status",
                        status="completed",
                        aggregated_output="clean",
                        exit_code=0,
                    )
                )
            ),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    tool_calls = []
    tool_results = []
    pure = PureMode(runtime="codex-sdk")
    pure.on_tool_call = lambda name, args: tool_calls.append((name, args))
    pure.on_tool_result = lambda name, result: tool_results.append((name, result))
    assert pure.connect("openai", "", working_directory=tmp_path) is True

    async def collect():
        return [chunk async for chunk in pure.run_streaming("hello")]

    import asyncio

    assert asyncio.run(collect()) == []
    assert tool_calls == [("bash", {"command": "git status"})]
    assert len(tool_results) == 1
    assert tool_results[0][0] == "bash"
    assert tool_results[0][1].success is True
    assert tool_results[0][1].output == "clean"


def test_pure_mode_forwards_codex_plan_updates_to_todo_callbacks(fake_codex_sdk, tmp_path):
    from superqode.pure_mode import PureMode

    _FakeThread.next_events = [
        _FakeNotification(
            "turn/plan/updated",
            types.SimpleNamespace(
                explanation="Plan before edits",
                plan=[
                    types.SimpleNamespace(step="Inspect files", status="inProgress"),
                    types.SimpleNamespace(step="Patch code", status="pending"),
                ],
            ),
        ),
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="completed")),
        ),
    ]
    tool_calls = []
    tool_results = []
    pure = PureMode(runtime="codex-sdk")
    pure.on_tool_call = lambda name, args: tool_calls.append((name, args))
    pure.on_tool_result = lambda name, result: tool_results.append((name, result))
    assert pure.connect("openai", "", working_directory=tmp_path) is True

    async def collect():
        return [chunk async for chunk in pure.run_streaming("hello")]

    import asyncio

    assert asyncio.run(collect()) == []
    assert tool_calls == [
        (
            "todo_write",
            {
                "todos": [
                    {
                        "id": "1",
                        "content": "Inspect files",
                        "status": "in_progress",
                        "priority": "medium",
                    },
                    {
                        "id": "2",
                        "content": "Patch code",
                        "status": "pending",
                        "priority": "medium",
                    },
                ]
            },
        )
    ]
    assert len(tool_results) == 1
    assert tool_results[0][0] == "todo_write"
    assert tool_results[0][1].success is True
    assert tool_results[0][1].metadata["source_event"] == "turn/plan/updated"
    assert tool_results[0][1].metadata["explanation"] == "Plan before edits"


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


def test_empty_model_defers_to_local_codex_config(fake_codex_sdk, tmp_path):
    """'Codex owns it': an empty model + no sandbox override must NOT be sent in
    thread_start, so the machine's ~/.codex config decides them."""
    cfg = AgentConfig(
        provider="openai",
        model="",  # defer to local Codex default
        working_directory=tmp_path,
        enable_session_storage=False,
        session_id="codex-defer",
    )
    runtime = create_runtime("codex-sdk", config=cfg)
    _ = runtime.metadata  # triggers start + thread_start
    params = _FakeCodexClient.last_instance.thread_start_params
    assert params["cwd"] == str(tmp_path)
    assert "model" not in params  # deferred to ~/.codex
    assert "approvalPolicy" not in params  # SuperQode imposes nothing
    assert "sandbox" not in params


def test_self_contained_runtime_set_includes_codex():
    from superqode.app_main import SuperQodeApp

    assert "codex-sdk" in SuperQodeApp._SELF_CONTAINED_RUNTIMES


def test_client_identity_is_superqode_versioned(fake_codex_sdk, tmp_path):
    """SuperQode must identify itself (name + version) to Codex so usage is
    attributable for adoption tracking."""
    from superqode import __version__

    runtime = create_runtime("codex-sdk", config=_config(tmp_path))
    _ = runtime.metadata  # triggers client construction
    cfg = _FakeCodexClient.last_instance.config
    assert cfg.client_name == "superqode_codex_sdk"
    assert cfg.client_version == __version__


def test_turn_kwargs_excludes_wire_only_fields(fake_codex_sdk, tmp_path):
    """modelProvider/developerInstructions are thread_start wire fields, NOT
    Thread.turn() kwargs — they must never appear in per-turn kwargs."""
    cfg = AgentConfig(
        provider="anthropic",  # non-openai would have added modelProvider
        model="some-model",
        working_directory=tmp_path,
        custom_system_prompt="be terse",  # would have added developerInstructions
        enable_session_storage=False,
        session_id="codex-turnkw",
    )
    runtime = create_runtime("codex-sdk", config=cfg)
    kw = runtime._turn_kwargs()
    assert "modelProvider" not in kw
    assert "developerInstructions" not in kw
    assert set(kw) <= {"cwd", "model", "sandbox", "effort"}


def test_turn_kwargs_match_real_sdk_turn_signature(tmp_path):
    """Contract test against the installed SDK: every per-turn kwarg must be a
    real Thread.turn() parameter (catches SDK drift the fakes can't)."""
    import inspect

    pytest.importorskip("openai_codex")
    from openai_codex import Thread

    allowed = set(inspect.signature(Thread.turn).parameters)
    cfg = AgentConfig(
        provider="anthropic",
        model="some-model",
        working_directory=tmp_path,
        custom_system_prompt="be terse",
        enable_session_storage=False,
        session_id="codex-sig",
    )
    runtime = create_runtime("codex-sdk", config=cfg)
    assert set(runtime._turn_kwargs()) <= allowed


def test_runtime_model_effort_and_one_shot_sandbox_controls(fake_codex_sdk, tmp_path):
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    runtime.set_model("gpt-5.5")
    runtime.set_reasoning_effort("high")
    runtime.set_next_turn_sandbox("read-only")

    first = runtime._turn_kwargs()
    second = runtime._turn_kwargs()

    assert first["model"] == "gpt-5.5"
    assert getattr(first["effort"], "value", first["effort"]) == "high"
    assert first["sandbox"] == "read-only"
    assert "sandbox" not in second


def test_runtime_supports_none_effort_and_default_reset(fake_codex_sdk, tmp_path):
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    runtime.set_reasoning_effort("none")
    assert runtime.reasoning_effort == "none"
    effort = runtime._turn_kwargs()["effort"]
    assert getattr(effort, "value", effort) == "none"

    runtime.set_reasoning_effort("default")
    assert runtime.reasoning_effort is None
    assert "effort" not in runtime._turn_kwargs()


def test_runtime_supports_newer_efforts_with_a_newer_local_cli(
    fake_codex_sdk, monkeypatch, tmp_path
):
    from superqode.runtime import codex_sdk

    monkeypatch.setattr(
        codex_sdk,
        "_newer_local_codex_binary",
        lambda: ("/opt/homebrew/bin/codex", "0.144.0"),
    )
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    runtime.set_reasoning_effort("max")
    effort = runtime._turn_kwargs()["effort"]
    assert getattr(effort, "value", effort) == "max"

    runtime.set_reasoning_effort("ultra")
    effort = runtime._turn_kwargs()["effort"]
    assert getattr(effort, "value", effort) == "ultra"


def test_runtime_retries_with_compatible_effort_for_newer_config(
    fake_codex_sdk, monkeypatch, tmp_path
):
    """A newer global Codex config must not block the pinned SDK protocol."""
    attempts = []

    class _ConfigMismatchThenSystemClient(_FakeCodexClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            attempts.append(self)

        def initialize(self):
            if len(attempts) == 1:
                raise RuntimeError(
                    "failed to load configuration: ~/.codex/config.toml:2:26: "
                    "unknown variant `ultra`, expected one of `none`, `minimal`, `low`, "
                    "`medium`, `high`, `xhigh`"
                )
            return super().initialize()

    monkeypatch.setattr(
        sys.modules["openai_codex.client"], "CodexClient", _ConfigMismatchThenSystemClient
    )

    runtime = create_runtime("codex-sdk", config=_config(tmp_path))
    assert runtime.metadata.userAgent == "fake-codex"
    assert attempts[0].closed is True
    assert attempts[1].config.config_overrides == ('model_reasoning_effort="xhigh"',)
    assert runtime._app_server_config_overrides == ('model_reasoning_effort="xhigh"',)


def test_runtime_thread_lifecycle_helpers(fake_codex_sdk, tmp_path):
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))
    runtime.metadata

    assert runtime.thread_id == "thread-1"
    assert runtime.list_threads().data[0].id == "thread-1"
    assert runtime.read_thread().thread.id == "thread-1"

    runtime.rename_thread("New name")
    assert _FakeCodexClient.last_instance.renamed == ("thread-1", "New name")

    runtime.compact_thread()
    assert _FakeCodexClient.last_instance.compacted == "thread-1"

    runtime.resume_thread("thread-2")
    assert runtime.thread_id == "thread-2"
    assert _FakeCodexClient.last_instance.resumed[0] == "thread-2"

    runtime.fork_thread("thread-2")
    assert runtime.thread_id == "fork-1"
    assert _FakeCodexClient.last_instance.forked[0] == "thread-2"

    runtime.archive_thread("fork-1")
    assert _FakeCodexClient.last_instance.archived == "fork-1"
    assert runtime.account().account.email == "user@example.com"
    assert runtime.logout().status == "ok"


def test_failed_turn_raises_with_provider_reason(fake_codex_sdk, tmp_path):
    """A usage-limit rejection must surface, not end as a silent empty turn."""
    _FakeThread.next_events = [
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(
                turn=types.SimpleNamespace(
                    status="failed",
                    error=types.SimpleNamespace(
                        message="You've hit your usage limit. Try again at 3:58 PM."
                    ),
                )
            ),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [event async for event in runtime.run_harness_events("hello")]

    import asyncio

    with pytest.raises(RuntimeError, match="usage limit"):
        asyncio.run(collect())


def test_failed_turn_without_message_still_raises(fake_codex_sdk, tmp_path):
    _FakeThread.next_events = [
        _FakeNotification(
            "turn/completed",
            types.SimpleNamespace(turn=types.SimpleNamespace(status="failed")),
        ),
    ]
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [event async for event in runtime.run_harness_events("hello")]

    import asyncio

    with pytest.raises(RuntimeError, match="turn status: failed"):
        asyncio.run(collect())


def test_successful_turn_with_no_error_is_unchanged(fake_codex_sdk, tmp_path):
    runtime = create_runtime("codex-sdk", config=_config(tmp_path))

    async def collect():
        return [chunk async for chunk in runtime.run_streaming("hello")]

    import asyncio

    assert asyncio.run(collect()) == ["hello"]
