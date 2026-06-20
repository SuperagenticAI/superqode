import asyncio
from typing import Any

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.harness import AgentSpec, HarnessSpec, compile_to_headless_profile
from superqode.providers.gateway.base import GatewayInterface, GatewayResponse, StreamChunk
from superqode.tools import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.harness_agent_session import AgentSessionTool
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output=str(args.get("text", "")))


class RecordingGateway(GatewayInterface):
    def __init__(self):
        self.calls = []

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append({"messages": list(messages), "model": model, "provider": provider})
        last_user = next((item for item in reversed(messages) if item.role == "user"), None)
        return GatewayResponse(content=f"{model}: {last_user.content if last_user else ''}")

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        yield StreamChunk(content="ok")

    async def test_connection(self, provider, model=None) -> dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider, model) -> str:
        return f"{provider}/{model}"


class ScriptedGateway(RecordingGateway):
    def __init__(self, responses: list[GatewayResponse]):
        super().__init__()
        self.responses = responses

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append({"messages": list(messages), "model": model, "provider": provider})
        if self.responses:
            return self.responses.pop(0)
        return GatewayResponse(content="done")


def _spec() -> HarnessSpec:
    return HarnessSpec(
        name="team",
        agents=(
            AgentSpec(
                id="lead",
                role="Coordinate.",
                tools=("read_file",),
                delegates_to=("reviewer",),
            ),
            AgentSpec(
                id="reviewer",
                role="Review correctness.",
                model="child-model",
                system_prompt="You are the reviewer.",
                tools=("grep",),
                max_iterations=3,
            ),
        ),
    )


def _loop(gateway: RecordingGateway, tmp_path) -> AgentLoop:
    return AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.coding(),
        config=AgentConfig(
            provider="test",
            model="parent-model",
            harness_spec=_spec(),
            session_id="parent",
            session_storage_dir=str(tmp_path / "sessions"),
        ),
    )


def _approval_loop(gateway: RecordingGateway, tmp_path) -> AgentLoop:
    spec = HarnessSpec(
        name="team",
        agents=(
            AgentSpec(id="lead", role="Coordinate.", tools=("agent_session",), delegates_to=("echoer",)),
            AgentSpec(
                id="echoer",
                role="Echo after approval.",
                model="child-model",
                tools=("echo",),
            ),
        ),
    )
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(AgentSessionTool())
    return AgentLoop(
        gateway=gateway,
        tools=registry,
        config=AgentConfig(
            provider="test",
            model="parent-model",
            harness_spec=spec,
            session_id="parent",
            session_storage_dir=str(tmp_path / "sessions"),
        ),
        permission_manager=PermissionManager(PermissionConfig(default=Permission.ASK)),
    )


def _ctx(loop: AgentLoop, tmp_path) -> ToolContext:
    return ToolContext(
        session_id="parent",
        working_directory=tmp_path,
        harness_spec=loop.config.harness_spec,
        peer_manager=loop._get_peer_manager(),
    )


def test_delegated_specs_auto_include_agent_session_tool():
    profile = compile_to_headless_profile(_spec())

    assert profile.tools is not None
    assert "read_file" in profile.tools
    assert "agent_session" in profile.tools


@pytest.mark.asyncio
async def test_agent_session_runs_declared_child_with_own_model_and_prompt(tmp_path):
    gateway = RecordingGateway()
    loop = _loop(gateway, tmp_path)
    ctx = _ctx(loop, tmp_path)
    tool = AgentSessionTool()

    started = await tool.execute(
        {"action": "start", "agent": "reviewer", "message": "check the diff"},
        ctx,
    )
    assert started.success, started.error
    waited = await tool.execute(
        {"action": "wait", "agent": "reviewer", "timeout_s": 10},
        ctx,
    )

    assert waited.success, waited.error
    assert "child-model: check the diff" in waited.output
    assert gateway.calls[0]["model"] == "child-model"
    assert any("You are the reviewer." in item.content for item in gateway.calls[0]["messages"])
    peer = loop._get_peer_manager().resolve("reviewer")
    assert peer is not None
    assert [tool.name for tool in peer.loop.tools.list()] == ["grep"]
    await loop._get_peer_manager().close_all()


@pytest.mark.asyncio
async def test_agent_session_reuses_child_context_for_followup(tmp_path):
    gateway = RecordingGateway()
    loop = _loop(gateway, tmp_path)
    ctx = _ctx(loop, tmp_path)
    tool = AgentSessionTool()

    await tool.execute({"action": "start", "agent": "reviewer", "message": "first"}, ctx)
    await tool.execute({"action": "wait", "agent": "reviewer", "timeout_s": 10}, ctx)
    sent = await tool.execute(
        {"action": "send", "agent": "reviewer", "message": "second"},
        ctx,
    )
    waited = await tool.execute(
        {"action": "wait", "agent": "reviewer", "timeout_s": 10},
        ctx,
    )

    assert sent.success
    assert sent.metadata["delivery"] == "queued"
    assert "child-model: second" in waited.output
    assert len(gateway.calls) == 2
    second_messages = gateway.calls[1]["messages"]
    assert any(item.role == "user" and item.content == "first" for item in second_messages)
    assert any(item.role == "user" and item.content == "second" for item in second_messages)
    await loop._get_peer_manager().close_all()


@pytest.mark.asyncio
async def test_agent_session_resumes_child_context_across_parent_loops(tmp_path):
    first_gateway = RecordingGateway()
    first_loop = _loop(first_gateway, tmp_path)
    first_ctx = _ctx(first_loop, tmp_path)
    tool = AgentSessionTool()

    started = await tool.execute(
        {
            "action": "start",
            "agent": "reviewer",
            "message": "first",
            "session_id": "reviewer-resume",
        },
        first_ctx,
    )
    await tool.execute({"action": "wait", "agent": "reviewer", "timeout_s": 10}, first_ctx)
    await first_loop._get_peer_manager().close_all()

    second_gateway = RecordingGateway()
    second_loop = _loop(second_gateway, tmp_path)
    second_ctx = _ctx(second_loop, tmp_path)
    resumed = await tool.execute(
        {
            "action": "resume",
            "agent": "reviewer",
            "session_id": started.metadata["session_id"],
        },
        second_ctx,
    )
    sent = await tool.execute(
        {"action": "send", "agent": "reviewer-resume", "message": "second"},
        second_ctx,
    )
    waited = await tool.execute(
        {"action": "wait", "agent": "reviewer-resume", "timeout_s": 10},
        second_ctx,
    )

    assert resumed.success, resumed.error
    assert resumed.metadata["session_id"] == "reviewer-resume"
    assert sent.success
    assert "child-model: second" in waited.output
    second_messages = second_gateway.calls[0]["messages"]
    assert any(item.role == "user" and item.content == "first" for item in second_messages)
    assert any(item.role == "user" and item.content == "second" for item in second_messages)
    await second_loop._get_peer_manager().close_all()


@pytest.mark.asyncio
async def test_agent_session_rejects_undeclared_child(tmp_path):
    gateway = RecordingGateway()
    loop = _loop(gateway, tmp_path)
    ctx = _ctx(loop, tmp_path)

    result = await AgentSessionTool().execute(
        {"action": "start", "agent": "unknown", "message": "work"},
        ctx,
    )

    assert result.success is False
    assert "Available: reviewer" in (result.error or "")


@pytest.mark.asyncio
async def test_agent_session_list_reports_declared_agents(tmp_path):
    gateway = RecordingGateway()
    loop = _loop(gateway, tmp_path)
    ctx = _ctx(loop, tmp_path)

    result = await AgentSessionTool().execute({"action": "list"}, ctx)

    assert result.success
    assert result.metadata["declared_agents"] == ["reviewer"]
    assert "Declared child agents: reviewer" in result.output


@pytest.mark.asyncio
async def test_agent_session_surfaces_and_approves_child_approval(tmp_path):
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {"name": "echo", "arguments": '{"text": "approved"}'},
                    }
                ],
            )
        ]
    )
    loop = _approval_loop(gateway, tmp_path)
    ctx = _ctx(loop, tmp_path)
    tool = AgentSessionTool()

    started = await tool.execute(
        {"action": "start", "agent": "echoer", "message": "use echo"},
        ctx,
    )
    waited = await tool.execute({"action": "wait", "agent": "echoer", "timeout_s": 10}, ctx)
    approved = await tool.execute({"action": "approve", "agent": "echoer"}, ctx)

    assert started.success
    assert waited.success
    assert waited.metadata["status"] == "needs_approval"
    assert waited.metadata["pending_approvals"][0]["tool_name"] == "echo"
    assert approved.success, approved.error
    assert approved.metadata["status"] == "idle"
    assert approved.metadata["result"] == "approved"
    await loop._get_peer_manager().close_all()


@pytest.mark.asyncio
async def test_agent_session_rejects_child_approval(tmp_path):
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {"name": "echo", "arguments": '{"text": "blocked"}'},
                    }
                ],
            )
        ]
    )
    loop = _approval_loop(gateway, tmp_path)
    ctx = _ctx(loop, tmp_path)
    tool = AgentSessionTool()

    await tool.execute({"action": "start", "agent": "echoer", "message": "use echo"}, ctx)
    await tool.execute({"action": "wait", "agent": "echoer", "timeout_s": 10}, ctx)
    rejected = await tool.execute(
        {"action": "reject", "agent": "echoer", "message": "not now"},
        ctx,
    )

    assert rejected.success
    assert rejected.metadata["status"] == "idle"
    assert rejected.metadata["result"] == "not now"
    await loop._get_peer_manager().close_all()
