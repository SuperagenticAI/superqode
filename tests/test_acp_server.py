"""Tests for the agent-side ACP server (superqode serve acp)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from acp import PROTOCOL_VERSION, text_block
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    AllowedOutcome,
    RequestPermissionResponse,
    ToolCallProgress,
    ToolCallStart,
)

from superqode.acp.server import (
    SuperQodeAcpAgent,
    _AcpSessionState,
    _prompt_to_text,
    _tool_kind,
    discover_session_spec,
    resolve_provider_model,
)
from superqode.harness.events import HarnessEvent


class FakeClient:
    """Collects session updates and answers permission requests."""

    def __init__(self, permission_option: str = "allow_once"):
        self.updates: list = []
        self.permission_requests: list = []
        self.permission_option = permission_option

    async def session_update(self, session_id: str, update, **kwargs):
        self.updates.append(update)

    async def request_permission(self, options, session_id, tool_call, **kwargs):
        self.permission_requests.append(tool_call)
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=self.permission_option)
        )


class FakeSession:
    """Stands in for a HarnessSession: replays scripted events."""

    def __init__(self, events=(), pending=None, block_after_first=False):
        self.session_id = "sess-1"
        self._events = list(events)
        self._pending = list(pending or [])
        self._block_after_first = block_after_first
        self.approved: list = []
        self.rejected: list = []

    async def stream(self, prompt, **kwargs):
        for i, event in enumerate(self._events):
            yield event
            if self._block_after_first and i == 0:
                await asyncio.Event().wait()  # block until cancelled

    def pending_approvals(self):
        return tuple(dict(item) for item in self._pending)

    async def approve_pending(self, index=0, *, always=False):
        self.approved.append({"index": index, "always": always})
        self._pending = []
        return SimpleNamespace(content="approved and resumed")

    async def reject_pending(self, index=0, *, message=None, always=False):
        self.rejected.append({"index": index, "message": message})
        self._pending = []
        return SimpleNamespace(content="")


def make_agent_with_session(session) -> tuple[SuperQodeAcpAgent, FakeClient]:
    agent = SuperQodeAcpAgent()
    client = FakeClient()
    agent.on_connect(client)
    agent._sessions[session.session_id] = _AcpSessionState(
        session=session,
        spec=SimpleNamespace(execution_policy=SimpleNamespace(sandbox="local")),
        provider="ollama",
        model="qwen3-coder",
        cwd=Path.cwd(),
    )
    return agent, client


async def test_initialize_reports_capabilities_and_auth_methods():
    agent = SuperQodeAcpAgent()
    response = await agent.initialize(protocol_version=PROTOCOL_VERSION)
    assert response.protocol_version == PROTOCOL_VERSION
    # The ACP registry requires at least one terminal or agent auth method.
    assert len(response.auth_methods) == 1
    assert response.auth_methods[0].type == "terminal"
    assert response.auth_methods[0].id == "superqode-setup"
    assert response.agent_info.name == "superqode"
    assert response.agent_capabilities.load_session is False


async def test_initialize_caps_protocol_version():
    agent = SuperQodeAcpAgent()
    response = await agent.initialize(protocol_version=PROTOCOL_VERSION + 5)
    assert response.protocol_version == PROTOCOL_VERSION


def test_tool_kind_mapping():
    assert _tool_kind("read_file") == "read"
    assert _tool_kind("edit_file") == "edit"
    assert _tool_kind("grep") == "search"
    assert _tool_kind("bash") == "execute"
    assert _tool_kind("web_fetch") == "fetch"
    assert _tool_kind("mystery_tool") == "other"


def test_prompt_to_text_flattens_blocks():
    blocks = [
        text_block("Fix the failing test"),
        SimpleNamespace(
            type="resource",
            resource=SimpleNamespace(text="def foo(): ...", uri="file:///a.py"),
        ),
        SimpleNamespace(type="resource_link", uri="file:///b.py", name="b.py"),
    ]
    text = _prompt_to_text(blocks)
    assert "Fix the failing test" in text
    assert '<context uri="file:///a.py">' in text
    assert "[resource: b.py]" in text


def test_discover_session_spec_prefers_local_yaml(tmp_path):
    (tmp_path / "harness.yaml").write_text("name: h\n")
    (tmp_path / "superqode.local.yaml").write_text("name: local\n")
    assert discover_session_spec(tmp_path).name == "superqode.local.yaml"
    (tmp_path / "superqode.local.yaml").unlink()
    assert discover_session_spec(tmp_path).name == "harness.yaml"
    (tmp_path / "harness.yaml").unlink()
    assert discover_session_spec(tmp_path) is None


def test_discover_session_spec_checks_harness_dirs(tmp_path):
    harness_dir = tmp_path / ".superqode" / "harness"
    harness_dir.mkdir(parents=True)
    (harness_dir / "coder.yaml").write_text("name: coder\n")
    assert discover_session_spec(tmp_path).name == "coder.yaml"


def test_resolve_provider_model_from_primary():
    spec = SimpleNamespace(model_policy=SimpleNamespace(primary="ollama/qwen3-coder"))
    provider, model = resolve_provider_model(spec)
    assert provider == "ollama"
    assert model == "qwen3-coder"


def test_resolve_provider_model_explicit_wins():
    spec = SimpleNamespace(model_policy=SimpleNamespace(primary="ollama/qwen3-coder"))
    provider, model = resolve_provider_model(spec, provider="openai", model="gpt-4o-mini")
    assert provider == "openai"
    assert model == "gpt-4o-mini"


def test_resolve_provider_model_honors_harbor_requested_model(monkeypatch):
    monkeypatch.setenv("HARBOR_ACP_REQUESTED_MODEL", "ollama/gemma4:e4b")
    spec = SimpleNamespace(model_policy=SimpleNamespace(primary=None))
    provider, model = resolve_provider_model(spec)
    assert provider == "ollama"
    assert model == "gemma4:e4b"


def test_resolve_provider_model_harbor_beats_spec_primary(monkeypatch):
    # The benchmark's --model is the run contract: it must win over a spec default.
    monkeypatch.setenv("HARBOR_ACP_REQUESTED_MODEL", "openai/gpt-5")
    spec = SimpleNamespace(model_policy=SimpleNamespace(primary="ollama/qwen3-coder"))
    provider, model = resolve_provider_model(spec)
    assert provider == "openai"
    assert model == "gpt-5"


async def test_set_session_model_updates_state():
    session = FakeSession()
    agent, _ = make_agent_with_session(session)
    await agent.set_session_model(model_id="openrouter/qwen3-coder", session_id="sess-1")
    state = agent._sessions["sess-1"]
    assert state.provider == "openrouter"
    assert state.model == "qwen3-coder"


async def test_set_session_model_bare_model_keeps_provider():
    session = FakeSession()
    agent, _ = make_agent_with_session(session)
    await agent.set_session_model(model_id="gemma4:e4b", session_id="sess-1")
    state = agent._sessions["sess-1"]
    assert state.provider == "ollama"
    assert state.model == "gemma4:e4b"


async def test_set_session_model_unknown_session_raises():
    agent = SuperQodeAcpAgent()
    with pytest.raises(Exception):
        await agent.set_session_model(model_id="x/y", session_id="nope")


def test_load_spec_template_name_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERQODE_ACP_SPEC", "template:qwen-coding")
    agent = SuperQodeAcpAgent()
    spec = agent._load_spec(tmp_path)
    assert "qwen" in spec.name.lower()


def test_load_spec_unknown_template_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERQODE_ACP_SPEC", "template:not-a-real-template")
    agent = SuperQodeAcpAgent()
    with pytest.raises(Exception):
        agent._load_spec(tmp_path)


def test_benchmark_coding_template_is_autonomous():
    from superqode.harness.templates import get_harness_template

    spec = get_harness_template("benchmark-coding")
    assert spec.execution_policy.approval_profile == "yolo"
    assert spec.flavor.value == "coding"
    stance = spec.agents[0].system_prompt or ""
    assert "Never ask questions" in stance
    assert "git reflog" in stance


def test_benchmark_stance_reaches_agent_job_description():
    # The stance only matters if it lands in the compiled profile the loop runs with.
    from superqode.harness.compiler import compile_to_headless_profile
    from superqode.harness.templates import get_harness_template

    profile = compile_to_headless_profile(get_harness_template("benchmark-coding"))
    assert "headless benchmark environment" in (profile.job_description or "")


def test_load_spec_benchmark_template_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERQODE_ACP_SPEC", "template:benchmark-coding")
    agent = SuperQodeAcpAgent()
    spec = agent._load_spec(tmp_path)
    assert spec.name == "benchmark-coding"


async def test_prompt_streams_events_as_session_updates():
    session = FakeSession(
        events=[
            HarnessEvent(type="thinking", data={"text": "planning"}),
            HarnessEvent(
                type="tool_call", data={"tool_name": "read_file", "arguments": {"path": "a.py"}}
            ),
            HarnessEvent(
                type="tool_result",
                data={"tool_name": "read_file", "success": True, "output": "contents"},
            ),
            HarnessEvent(type="delta", data={"text": "Here is the fix."}),
            HarnessEvent(type="model_delta", data={"text": " Streamed by builtin."}),
            HarnessEvent(type="end", data={}),
        ]
    )
    agent, client = make_agent_with_session(session)
    response = await agent.prompt(prompt=[text_block("go")], session_id="sess-1")
    assert response.stop_reason == "end_turn"
    kinds = [type(u).__name__ for u in client.updates]
    assert "AgentThoughtChunk" in kinds
    assert "ToolCallStart" in kinds
    assert "ToolCallProgress" in kinds
    assert "AgentMessageChunk" in kinds
    start = next(u for u in client.updates if isinstance(u, ToolCallStart))
    progress = next(u for u in client.updates if isinstance(u, ToolCallProgress))
    assert start.tool_call_id == progress.tool_call_id
    assert start.kind == "read"
    assert progress.status == "completed"


async def test_prompt_failed_tool_result_marks_failed():
    session = FakeSession(
        events=[
            HarnessEvent(type="tool_call", data={"tool_name": "bash", "arguments": {}}),
            HarnessEvent(
                type="tool_result",
                data={"tool_name": "bash", "success": False, "error": "exit 1"},
            ),
        ]
    )
    agent, client = make_agent_with_session(session)
    await agent.prompt(prompt=[text_block("go")], session_id="sess-1")
    progress = next(u for u in client.updates if isinstance(u, ToolCallProgress))
    assert progress.status == "failed"


async def test_prompt_empty_input_ends_turn():
    session = FakeSession()
    agent, _ = make_agent_with_session(session)
    response = await agent.prompt(prompt=[], session_id="sess-1")
    assert response.stop_reason == "end_turn"


async def test_prompt_unknown_session_raises():
    agent = SuperQodeAcpAgent()
    with pytest.raises(Exception):
        await agent.prompt(prompt=[text_block("go")], session_id="nope")


async def test_cancel_stops_streaming_turn():
    session = FakeSession(
        events=[HarnessEvent(type="delta", data={"text": "working"})],
        block_after_first=True,
    )
    agent, client = make_agent_with_session(session)
    task = asyncio.create_task(agent.prompt(prompt=[text_block("go")], session_id="sess-1"))
    # Let the first delta flow, then cancel.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if client.updates:
            break
    await agent.cancel(session_id="sess-1")
    response = await asyncio.wait_for(task, timeout=5)
    assert response.stop_reason == "cancelled"


async def test_approval_flow_requests_permission_and_resumes():
    session = FakeSession(
        events=[HarnessEvent(type="delta", data={"text": "needs a tool"})],
        pending=[
            {
                "index": 0,
                "tool_name": "bash",
                "arguments": {"command": "ls"},
                "tool_call_id": "tc-9",
            }
        ],
    )
    agent, client = make_agent_with_session(session)
    response = await agent.prompt(prompt=[text_block("go")], session_id="sess-1")
    assert response.stop_reason == "end_turn"
    assert len(client.permission_requests) == 1
    assert client.permission_requests[0].tool_call_id == "tc-9"
    assert session.approved == [{"index": 0, "always": False}]
    texts = [
        u.content.text
        for u in client.updates
        if isinstance(u, AgentMessageChunk) and hasattr(u.content, "text")
    ]
    assert "approved and resumed" in texts


async def test_approval_flow_always_allow():
    session = FakeSession(
        pending=[{"index": 0, "tool_name": "bash", "arguments": {}, "tool_call_id": "tc-1"}],
    )
    agent, client = make_agent_with_session(session)
    client.permission_option = "allow_always"
    await agent.prompt(prompt=[text_block("go")], session_id="sess-1")
    assert session.approved == [{"index": 0, "always": True}]


async def test_approval_flow_reject():
    session = FakeSession(
        pending=[{"index": 0, "tool_name": "bash", "arguments": {}, "tool_call_id": "tc-1"}],
    )
    agent, client = make_agent_with_session(session)
    client.permission_option = "reject_once"
    response = await agent.prompt(prompt=[text_block("go")], session_id="sess-1")
    assert response.stop_reason == "end_turn"
    assert session.rejected
    assert not session.approved


async def test_close_session_drops_state():
    session = FakeSession()
    agent, _ = make_agent_with_session(session)
    await agent.close_session(session_id="sess-1")
    assert "sess-1" not in agent._sessions
