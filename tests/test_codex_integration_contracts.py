"""Security and protocol regressions for the product-owned Codex integration."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.codex_capabilities import CodexCapabilities
from superqode.runtime.codex_cli import CodexCLIRuntime
from superqode.runtime.codex_events import CodexEvents
from superqode.runtime.codex_daemon import CodexDaemonTransport, local_codex_endpoint
from superqode.tools.base import Tool, ToolRegistry, ToolResult
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager
from superqode.tools.question_tool import Answer, get_question_handler, set_question_handler


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "superqode.runtime.codex_cli.codex_binary", lambda explicit=None: sys.executable
    )
    return CodexCLIRuntime(
        config=AgentConfig(
            provider="openai", model="", working_directory=tmp_path, enable_session_storage=False
        )
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "ws://remote.example:4500",
        "wss://127.0.0.1:4500",
        "ws://localhost:4500",
        "ws://127.0.0.1",
        "ws://127.0.0.1:4500/path",
        "ws://user:pass@127.0.0.1:4500",
        "ws://127.0.0.1:4500?token=secret",
        "ws://127.0.0.1:0",
    ],
)
def test_codex_daemon_rejects_nonlocal_or_credential_endpoints(endpoint):
    with pytest.raises(ValueError):
        local_codex_endpoint(endpoint)


@pytest.mark.asyncio
async def test_daemon_transport_uses_rpc_and_detaches_without_stopping_listener():
    from websockets.asyncio.server import serve

    connections = []

    async def handler(socket):
        connections.append(socket)
        async for data in socket:
            request = json.loads(data)
            if "id" in request:
                await socket.send(json.dumps({"id": request["id"], "result": {"ok": True}}))

    async with serve(handler, "127.0.0.1", 0) as server:
        endpoint = "ws://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
        for _ in range(2):
            transport = CodexDaemonTransport(
                lambda *args: None,
                lambda *args: None,
                lambda error: pytest.fail(str(error)),
                endpoint=endpoint,
            )
            await transport.start([], cwd=".", env={})
            assert await transport.request("test") == {"ok": True}
            await transport.close()
        assert len(connections) == 2


def test_strict_network_policy_blocks_unobserved_codex_execution(runtime, monkeypatch):
    monkeypatch.setenv("SUPERQODE_NET_STRICT", "1")
    with pytest.raises(RuntimeError, match="strict network policy"):
        runtime._preflight_policy()


@pytest.mark.asyncio
async def test_network_approval_displays_destination_and_obeys_strict_policy(runtime, monkeypatch):
    seen = []
    runtime._approval_callback = lambda tool, args: seen.append((tool, args)) or True
    request = {
        "networkApprovalContext": {"host": "github.com:443", "protocol": "https"},
        "itemId": "net",
    }
    assert await runtime._server_request("item/commandExecution/requestApproval", request) == {
        "decision": "accept"
    }
    assert seen[0][0] == "network"
    assert seen[0][1]["host"] == "github.com"
    assert seen[0][1]["port"] == 443
    monkeypatch.setenv("SUPERQODE_NET_STRICT", "1")
    request["networkApprovalContext"]["host"] = "github.com.evil.test"
    assert await runtime._server_request("item/commandExecution/requestApproval", request) == {
        "decision": "decline"
    }
    assert len(seen) == 1
    for host in ("github.com/path", "user@github.com", "github.com:99999"):
        request["networkApprovalContext"]["host"] = host
        assert (await runtime._server_request("item/commandExecution/requestApproval", request))[
            "decision"
        ] == "decline"


@pytest.mark.asyncio
async def test_session_consent_is_exact_scope_and_invalidates_on_policy_change(runtime):
    seen = []
    runtime._approval_callback = lambda *args: seen.append(args) or "acceptForSession"
    method = "item/commandExecution/requestApproval"
    params = {"command": "echo first", "cwd": "/project", "itemId": "a"}
    assert await runtime._server_request(method, params) == {"decision": "accept"}
    assert await runtime._server_request(method, {**params, "itemId": "b"}) == {
        "decision": "accept"
    }
    assert len(seen) == 1
    assert len(runtime.approval_receipts) == 2
    assert await runtime._server_request(method, {**params, "command": "echo second"}) == {
        "decision": "accept"
    }
    assert len(seen) == 2
    runtime._permission_manager.config.tools["bash"] = Permission.DENY
    assert await runtime._server_request(method, params) == {"decision": "decline"}
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_host_session_consent_cannot_spread_to_different_arguments(runtime):
    seen = []
    runtime._approval_callback = lambda *args: seen.append(args) or "acceptForSession"
    assert (
        await runtime._approval_choice("memory_remember", {"content": "first"}, Permission.ASK)
        == "accept"
    )
    assert (
        await runtime._approval_choice("memory_remember", {"content": "different"}, Permission.ASK)
        == "accept"
    )
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_decline_string_never_becomes_truthy_approval_and_cancel_is_preserved(runtime):
    runtime._approval_callback = lambda *args: "decline"
    method, params = "item/commandExecution/requestApproval", {"command": "echo ok"}
    assert await runtime._server_request(method, params) == {"decision": "decline"}
    runtime._approval_callback = lambda *args: "cancel"
    assert await runtime._server_request(method, params) == {"decision": "cancel"}
    params["availableDecisions"] = ["accept", "decline"]
    assert await runtime._server_request(method, params) == {"decision": "decline"}


@pytest.mark.asyncio
async def test_persistent_rule_requires_separate_confirmation(runtime):
    rule = {"acceptWithExecpolicyAmendment": {"execpolicy_amendment": ["git", "status"]}}
    runtime._approval_callback = lambda *args: rule
    previous = get_question_handler()
    try:
        set_question_handler(None)
        params = {"command": "git status", "availableDecisions": [rule, "decline"]}
        assert await runtime._server_request("item/commandExecution/requestApproval", params) == {
            "decision": "decline"
        }

        async def confirm(question):
            assert "persistent Codex rule" in question.question
            return Answer("Apply rule")

        set_question_handler(confirm)
        assert await runtime._server_request("item/commandExecution/requestApproval", params) == {
            "decision": rule
        }
    finally:
        set_question_handler(previous)


@pytest.mark.asyncio
async def test_mcp_form_validates_and_url_requires_manual_completion(runtime):
    old = get_question_handler()
    values = iter(["Continue", '{"count":2}', "Continue", '{"count":"invalid"}', "Completed"])
    seen = []

    async def answer(question):
        seen.append(question)
        return Answer(next(values))

    set_question_handler(answer)
    try:
        params = {
            "mode": "form",
            "serverName": "example",
            "message": "Count?",
            "requestedSchema": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        }
        assert await runtime._server_request("mcpServer/elicitation/request", params) == {
            "action": "accept",
            "content": {"count": 2},
        }
        assert (await runtime._server_request("mcpServer/elicitation/request", params))[
            "action"
        ] == "cancel"
        params = {"mode": "url", "url": "https://example.com/authorize", "serverName": "example"}
        assert (await runtime._server_request("mcpServer/elicitation/request", params))[
            "action"
        ] == "accept"
        assert "Open this URL yourself" in seen[-1].question
        params["url"] = "javascript:alert(1)"
        assert (await runtime._server_request("mcpServer/elicitation/request", params))[
            "action"
        ] == "cancel"
    finally:
        set_question_handler(old)


@pytest.mark.asyncio
async def test_unverified_schema_disables_experimental_controls(runtime, monkeypatch):
    async def started():
        pass

    monkeypatch.setattr(runtime, "_ensure_started", started)
    for operation in (
        lambda: runtime.set_plan_mode(True),
        runtime.background_terminals,
        lambda: runtime.select_permission_profile("test"),
    ):
        with pytest.raises(RuntimeError, match="does not advertise"):
            await operation()


@pytest.mark.asyncio
async def test_old_schema_rejects_unsupported_granular_policy_before_rpc(runtime):
    from unittest.mock import AsyncMock
    from jsonschema import ValidationError

    runtime.capabilities = CodexCapabilities(
        methods={
            "turn/start": {
                "properties": {"approvalPolicy": {"enum": ["on-request", "never"]}},
            }
        }
    )
    request = AsyncMock()
    runtime._transport = SimpleNamespace(request=request)
    with pytest.raises(ValidationError):
        await runtime._timed_request("turn/start", {"approvalPolicy": {"granular": {}}})
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_installed_schema_is_cached_by_binary_revision(tmp_path, monkeypatch):
    from superqode.runtime.codex_capabilities import probe_capabilities

    binary = tmp_path / "codex"
    binary.write_text("test")
    calls = []

    def generate(argv, **kwargs):
        if argv[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=b"codex-cli 0.160.0\n")
        calls.append(argv)
        from pathlib import Path

        root = Path(argv[-1])
        root.joinpath("ClientRequest.json").write_text(
            json.dumps(
                {
                    "oneOf": [
                        {
                            "properties": {
                                "method": {"enum": ["turn/start"]},
                                "params": {"$ref": "#/definitions/TurnStartParams"},
                            }
                        }
                    ],
                    "definitions": {"TurnStartParams": {"properties": {"collaborationMode": {}}}},
                }
            )
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("superqode.runtime.codex_capabilities.subprocess.run", generate)
    first = await asyncio.to_thread(probe_capabilities, str(binary))
    assert first.supports("turn/start", "collaborationMode")
    assert probe_capabilities(str(binary)) is first
    assert len(calls) == 1
    binary.write_text("new binary revision")
    assert probe_capabilities(str(binary)).verified
    assert len(calls) == 2


class MemoryTool(Tool):
    name = "memory_test"
    description = "Test governed host execution"
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    calls = []

    async def execute(self, args, ctx):
        self.calls.append((args, ctx))
        return ToolResult(True, args["value"])


@pytest.mark.asyncio
async def test_mcp_bridge_enforces_real_capability_identity(runtime, monkeypatch):
    calls = []
    tool = SimpleNamespace(
        description="Write fixture",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )

    async def execute(server, name, arguments):
        calls.append((server, name, arguments))
        return SimpleNamespace(is_error=False, content=[], structured_content={"ok": True})

    async def manager():
        return SimpleNamespace(get_tool=lambda server, name: tool, execute_tool=execute)

    monkeypatch.setattr(runtime._host_tools.get("mcp_execute"), "_get_mcp_manager", manager)
    runtime._permission_manager = PermissionManager(
        PermissionConfig(
            default=Permission.ALLOW,
            tools={"mcp_files_write": Permission.DENY},
        )
    )
    params = {
        "tool": "superqode_mcp_execute",
        "arguments": {
            "server": "files",
            "tool": "write",
            "arguments": {"path": "x"},
        },
        "callId": "mcp-denied",
    }
    assert not (await runtime._server_request("item/tool/call", params))["success"]
    assert not calls
    runtime._permission_manager.config.tools["mcp_files_write"] = Permission.ALLOW
    params["callId"] = "mcp-allowed"
    assert (await runtime._server_request("item/tool/call", params))["success"]
    assert calls == [("files", "write", {"path": "x"})]


@pytest.mark.asyncio
async def test_dynamic_tools_use_host_executor_and_validate_before_execution(runtime):
    tool = MemoryTool()
    tool.calls = []
    registry = ToolRegistry()
    registry.register(tool)
    runtime._init_host_tools(registry)
    runtime._permission_manager = PermissionManager(PermissionConfig(default=Permission.ASK))
    runtime._approval_callback = lambda *args: True
    params = {"tool": "superqode_memory_test", "arguments": {"value": "ok"}, "callId": "call1"}
    assert (await runtime._server_request("item/tool/call", params))["success"]
    assert len(tool.calls) == 1
    assert tool.calls[0][1].invocation_id == "call1"
    runtime._permission_manager.config.tools["memory_test"] = Permission.DENY
    params["callId"] = "call2"
    assert not (await runtime._server_request("item/tool/call", params))["success"]
    assert len(tool.calls) == 1
    params["arguments"] = {"value": 4}
    assert not (await runtime._server_request("item/tool/call", params))["success"]
    assert len(tool.calls) == 1
    params["tool"] = "bash"
    assert not (await runtime._server_request("item/tool/call", params))["success"]


@pytest.mark.asyncio
async def test_host_tools_obey_read_only_turn(runtime):
    registry = ToolRegistry()
    tool = MemoryTool()
    tool.calls = []
    registry.register(tool)
    runtime._init_host_tools(registry)
    runtime._turn_read_only = True
    runtime._permission_manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))
    assert not (
        await runtime._server_request(
            "item/tool/call",
            {"tool": "superqode_memory_test", "arguments": {"value": "no write"}, "callId": "plan"},
        )
    )["success"]
    assert not tool.calls


@pytest.mark.asyncio
async def test_composer_resolves_only_enabled_catalog_mentions(runtime, monkeypatch):
    runtime.capabilities = CodexCapabilities(methods={"skills/list": {}, "app/list": {}})

    async def catalog(topic, **kwargs):
        if topic == "skills":
            return {
                "data": [
                    {
                        "skills": [
                            {"name": "review", "path": "/skills/review/SKILL.md", "enabled": True}
                        ]
                    }
                ]
            }
        return {
            "data": [
                {"id": "drive", "name": "Team Drive", "isAccessible": True, "isEnabled": True},
                {"id": "disabled", "name": "Disabled", "isAccessible": True, "isEnabled": False},
            ]
        }

    monkeypatch.setattr(runtime, "inspect", catalog)
    inputs = await runtime._composer_input("$review inspect @team-drive and @disabled")
    assert inputs == [
        {"type": "text", "text": "$review inspect $team-drive and @disabled", "text_elements": []},
        {"type": "skill", "name": "review", "path": "/skills/review/SKILL.md"},
        {"type": "mention", "name": "Team Drive", "path": "app://drive"},
    ]


def test_typed_errors_hooks_and_context_status_remain_visible(runtime):
    mapper = CodexEvents()
    error = mapper.map(
        "error",
        {"error": {"message": "quota", "codexErrorInfo": "usageLimitExceeded"}, "willRetry": False},
    )[0]
    assert error.type == "error"
    assert error.data["error_info"] == "usageLimitExceeded"
    assert (
        mapper.map("hook/completed", {"run": {"eventName": "Stop", "status": "completed"}})[0].type
        == "hook"
    )
    runtime._thread_id = "ours"
    runtime._on_notification(
        "thread/status/changed", {"threadId": "other", "status": {"type": "active"}}
    )
    assert not runtime.run_status
    runtime._on_notification(
        "thread/status/changed", {"threadId": "ours", "status": {"type": "idle"}}
    )
    assert runtime.run_status == {"type": "idle"}
    runtime.token_usage = {"last": {"totalTokens": 100}, "modelContextWindow": 1000}
    assert runtime.context_usage == {"used": 100, "window": 1000, "percent": 10}


def test_approval_policy_supports_untrusted_and_validated_granular(runtime):
    runtime.set_approval_policy("untrusted")
    assert runtime._thread_params()["approvalPolicy"] == "untrusted"
    policy = {"granular": {"mcp_elicitations": True, "rules": True, "sandbox_approval": True}}
    runtime.set_approval_policy(policy)
    assert runtime._thread_params()["approvalPolicy"] == policy
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        runtime.set_approval_policy({"granular": {"sandbox_approval": "yes"}})


def test_reviewer_mismatch_fails_before_any_turn(runtime):
    with pytest.raises(RuntimeError, match="approval mediation"):
        runtime._accept_thread({"thread": {"id": "no"}, "approvalsReviewer": "auto_review"})
    assert runtime.thread_id is None


@pytest.mark.asyncio
async def test_detached_review_streams_separate_thread_and_restores_main(runtime, monkeypatch):
    from unittest.mock import AsyncMock

    runtime._thread_id = runtime.session_id = "main-thread"
    runtime.history = [{"id": "earlier-turn", "items": []}]
    runtime.token_usage = {"last": {"totalTokens": 42}}
    runtime._transport = SimpleNamespace(cancel_server_requests=AsyncMock())
    monkeypatch.setattr(runtime, "ensure_thread", AsyncMock(return_value=False))
    runtime.capabilities = CodexCapabilities(
        methods={"thread/fork": {"properties": {"deferGoalContinuation": {}}}}
    )

    async def request(method, params):
        if method == "thread/fork":
            assert params["threadId"] == "main-thread"
            assert params["sandbox"] == "read-only"
            assert params["deferGoalContinuation"] is True
            return {"thread": {"id": "review-thread"}, "approvalsReviewer": "user"}
        assert method == "review/start"
        assert params["threadId"] == "review-thread"
        assert params["target"] == {"type": "uncommittedChanges"}
        runtime._on_notification(
            "item/agentMessage/delta",
            {"threadId": "review-thread", "turnId": "review-turn", "delta": "review result"},
        )
        runtime._on_notification(
            "turn/completed",
            {"threadId": "review-thread", "turn": {"id": "review-turn", "status": "completed"}},
        )
        return {"turn": {"id": "review-turn"}}

    monkeypatch.setattr(runtime, "_timed_request", request)
    runtime.set_review(detached=True)
    response = await runtime.run("review")
    assert response.content == "review result"
    assert runtime.thread_id == runtime.session_id == "main-thread"
    assert runtime.history[0]["id"] == "earlier-turn"
    assert runtime.token_usage["last"]["totalTokens"] == 42
    assert runtime.last_review_thread_id == "review-thread"
    from superqode.session.codex import latest_thread

    assert (
        latest_thread(runtime.config.working_directory, runtime.billing_requested).session_id
        == "main-thread"
    )


@pytest.mark.asyncio
async def test_shared_listener_cannot_resume_unobserved_autonomous_goal(runtime, monkeypatch):
    from unittest.mock import AsyncMock

    runtime.codex_server = "ws://127.0.0.1:4500"
    runtime.capabilities = CodexCapabilities(methods={"thread/goal/get": {}})
    request = AsyncMock(return_value={"goal": {"status": "active"}})
    monkeypatch.setattr(runtime, "_timed_request", request)
    with pytest.raises(RuntimeError, match="Pause it in Codex"):
        await runtime._check_resume_goal("existing-thread")
    request.assert_awaited_once_with("thread/goal/get", {"threadId": "existing-thread"})
