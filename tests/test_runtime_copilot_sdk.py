"""Contract tests for the optional GitHub Copilot SDK runtime."""

from __future__ import annotations

import asyncio
import sys
import threading
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
        # The real CopilotClient downloads the Copilot CLI from inside __init__
        # with a blocking urlopen, so record where SuperQode built it.
        self.built_on = threading.current_thread()
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


class _FakeRuntimeConnection:
    requested_path = None

    @classmethod
    def for_stdio(cls, *, path=None, **_kwargs):
        cls.requested_path = path
        return SimpleNamespace(kind="stdio", path=path)


@pytest.fixture
def fake_copilot_sdk(monkeypatch):
    module = types.ModuleType("copilot")
    module.__path__ = []
    module.CopilotClient = _FakeClient
    module.RuntimeConnection = _FakeRuntimeConnection
    rpc_module = types.ModuleType("copilot.rpc")
    rpc_module.PermissionDecisionApproveOnce = type(
        "PermissionDecisionApproveOnce", (_Decision,), {}
    )
    rpc_module.PermissionDecisionReject = type("PermissionDecisionReject", (_Decision,), {})
    monkeypatch.setitem(sys.modules, "copilot", module)
    monkeypatch.setitem(sys.modules, "copilot.rpc", rpc_module)
    _FakeClient.instances.clear()
    _FakeRuntimeConnection.requested_path = None
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


@pytest.mark.asyncio
async def test_client_is_built_off_the_event_loop(fake_copilot_sdk, tmp_path):
    """CopilotClient.__init__ downloads the CLI with a blocking urlopen.

    Constructing it inline froze the TUI for the whole download - seconds on a
    fast link, minutes behind a corporate proxy - so it must not run on the loop.
    """
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    runtime = CopilotSDKRuntime(config=_config(tmp_path))
    assert runtime.needs_start is True
    await runtime._ensure_started()
    assert runtime.needs_start is False

    client = _FakeClient.instances[-1]
    assert client.built_on is not threading.current_thread()
    await runtime.aclose()


@pytest.mark.asyncio
async def test_installed_cli_is_reused_instead_of_triggering_sdk_download(
    fake_copilot_sdk, tmp_path, monkeypatch
):
    from superqode.runtime import copilot_sdk
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    monkeypatch.setattr(
        copilot_sdk.shutil,
        "which",
        lambda name: "/opt/bin/copilot" if name == "copilot" else None,
    )
    runtime = CopilotSDKRuntime(config=_config(tmp_path))
    await runtime._ensure_started()

    assert _FakeRuntimeConnection.requested_path == "/opt/bin/copilot"
    assert _FakeClient.instances[-1].kwargs["connection"].path == "/opt/bin/copilot"
    await runtime.aclose()


@pytest.mark.asyncio
async def test_permission_bridge_never_blocks_the_event_loop(fake_copilot_sdk, tmp_path):
    """The TUI approval bridge blocks until the user answers the prompt.

    The SDK awaits the permission handler on the event loop, so deciding inline
    deadlocked: the approval card could not render and the keypress could not be
    read, leaving every request frozen until the bridge timed out and denied it.
    """
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    answered = threading.Event()

    def blocking_callback(_name, _args):
        # Stands in for `threading.Event.wait()` in the real TUI bridge.
        assert answered.wait(5), "loop never got to answer the prompt"
        return True

    runtime = CopilotSDKRuntime(
        config=_config(tmp_path),
        approval_callback=blocking_callback,
    )

    decision_task = asyncio.create_task(
        runtime._approval_handler(SimpleNamespace(fullCommandText="pwd"))
    )
    # A blocked loop could never reach this line, so answering here proves the
    # decision moved off the loop.
    await asyncio.sleep(0)
    answered.set()
    decision = await asyncio.wait_for(decision_task, timeout=5)
    assert type(decision).__name__ == "PermissionDecisionApproveOnce"


@pytest.mark.asyncio
async def test_only_an_explicit_copilot_token_reaches_the_sdk(
    fake_copilot_sdk, tmp_path, monkeypatch
):
    """GH_TOKEN/GITHUB_TOKEN are git PATs, not Copilot credentials.

    Forwarding one made the SDK start the CLI with --no-auto-login, so it
    ignored a working `copilot login` and stalled on an account that could not
    answer.
    """
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gho_git_only")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_git_only")

    runtime = CopilotSDKRuntime(config=_config(tmp_path))
    await runtime._ensure_started()
    assert "github_token" not in _FakeClient.instances[-1].kwargs
    assert "GH_TOKEN" not in _FakeClient.instances[-1].kwargs["env"]
    assert "GITHUB_TOKEN" not in _FakeClient.instances[-1].kwargs["env"]
    await runtime.aclose()

    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "gho_copilot")
    explicit = CopilotSDKRuntime(config=_config(tmp_path))
    await explicit._ensure_started()
    assert _FakeClient.instances[-1].kwargs["github_token"] == "gho_copilot"
    await explicit.aclose()


@pytest.mark.asyncio
async def test_turn_failure_is_reported_instead_of_raised(fake_copilot_sdk, tmp_path):
    """A Copilot turn that times out or errors must end the turn, not escape it."""
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    runtime = CopilotSDKRuntime(config=_config(tmp_path))
    await runtime._ensure_started()

    async def boom(_prompt, timeout=60.0):
        raise TimeoutError(f"Timeout after {timeout}s waiting for session.idle")

    runtime._session.send_and_wait = boom
    events = [event async for event in runtime.run_harness_events("anything")]

    complete = next(e for e in events if e.type == "turn_complete")
    assert complete.data["status"] == "error"
    assert "SUPERQODE_COPILOT_TIMEOUT" in complete.data["error"]
    assert events[-1].type == "model_result"
    await runtime.aclose()


@pytest.mark.asyncio
async def test_startup_failure_is_reported_instead_of_raised(fake_copilot_sdk, tmp_path):
    """An unauthenticated or undownloadable runtime ends the turn with guidance."""
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    runtime = CopilotSDKRuntime(config=_config(tmp_path))

    async def no_start() -> None:
        raise RuntimeError("Copilot CLI not found at /nope")

    runtime._ensure_started = no_start
    events = [event async for event in runtime.run_harness_events("anything")]

    complete = next(e for e in events if e.type == "turn_complete")
    assert complete.data["status"] == "error"
    assert "Copilot CLI not found" in complete.data["error"]
    assert ":copilot cli" in complete.data["error"]
    assert events[-1].type == "model_result"


@pytest.mark.asyncio
async def test_startup_has_a_hard_deadline_and_never_hangs(fake_copilot_sdk, tmp_path, monkeypatch):
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime

    monkeypatch.setenv("SUPERQODE_COPILOT_STARTUP_TIMEOUT", "0.01")
    runtime = CopilotSDKRuntime(config=_config(tmp_path))

    async def never_starts() -> None:
        await asyncio.Event().wait()

    runtime._ensure_started = never_starts
    events = await asyncio.wait_for(
        _collect_events(runtime, "anything"),
        timeout=1,
    )

    complete = next(e for e in events if e.type == "turn_complete")
    assert complete.data["status"] == "error"
    assert "startup exceeded 0.01s" in complete.data["error"]
    assert ":copilot cli" in complete.data["error"]


async def _collect_events(runtime, prompt):
    return [event async for event in runtime.run_harness_events(prompt)]


@pytest.mark.asyncio
async def test_pure_mode_streams_a_failed_turn_to_the_user(fake_copilot_sdk, tmp_path):
    """A turn_complete error must reach the transcript.

    PureMode used to read only the usage block off turn_complete, so a failed
    Copilot turn ended with an empty response and no explanation - which reads
    exactly like a hang.
    """
    from superqode.harness.events import HarnessEvent
    from superqode.pure_mode import PureMode

    pure = PureMode()
    failed = HarnessEvent(
        type="turn_complete",
        data={
            "status": "error",
            "error": "Could not start the GitHub Copilot runtime",
            "usage": {},
        },
    )
    assert "Could not start the GitHub Copilot runtime" in pure._handle_runtime_harness_event(
        failed
    )

    # A clean or cancelled turn stays quiet.
    for status in ("completed", "cancelled"):
        quiet = HarnessEvent(
            type="turn_complete", data={"status": status, "error": None, "usage": {}}
        )
        assert pure._handle_runtime_harness_event(quiet) == ""


@pytest.mark.asyncio
async def test_copilot_identity_cannot_enable_provider_override(
    fake_copilot_sdk, tmp_path, monkeypatch
):
    from superqode.runtime.copilot_sdk import CopilotSDKRuntime
    from superqode.providers.subscription_env import VENDOR_API_KEY_ENVS

    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "explicit-identity")
    for key in VENDOR_API_KEY_ENVS["copilot"]:
        monkeypatch.setenv(key, "redirect-value")
    runtime = CopilotSDKRuntime(config=_config(tmp_path))
    await runtime._ensure_started()
    launch = _FakeClient.instances[-1].kwargs
    assert launch["github_token"] == "explicit-identity"
    assert all(key not in launch["env"] for key in VENDOR_API_KEY_ENVS["copilot"])
    await runtime.aclose()
