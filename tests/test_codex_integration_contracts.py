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
    params = {
        "command": "echo first",
        "cwd": "/project",
        "itemId": "a",
        "startedAtMs": 1,
        "reason": "Check the workspace",
    }
    assert await runtime._server_request(method, params) == {"decision": "accept"}
    assert await runtime._server_request(
        method, {**params, "itemId": "b", "startedAtMs": 2, "reason": "Inspect the project"}
    ) == {"decision": "accept"}
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
@pytest.mark.parametrize(
    "method,scope,changed",
    [
        ("item/fileChange/requestApproval", {"path": "/project/a.txt"}, {"path": "/project/b.txt"}),
        (
            "item/commandExecution/requestApproval",
            {"networkApprovalContext": {"host": "github.com:443", "protocol": "https"}},
            {"networkApprovalContext": {"host": "example.com:443", "protocol": "https"}},
        ),
    ],
)
async def test_session_consent_ignores_explanation_but_retains_paths_and_destinations(
    runtime, method, scope, changed
):
    seen = []
    runtime._approval_callback = lambda *args: seen.append(args) or "acceptForSession"
    for reason in ("First explanation", "Reworded explanation"):
        assert await runtime._server_request(method, {**scope, "reason": reason}) == {
            "decision": "accept"
        }
    assert len(seen) == 1
    assert await runtime._server_request(method, {**changed, "reason": "Reworded explanation"}) == {
        "decision": "accept"
    }
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_host_tool_reason_argument_still_changes_consent_scope(runtime):
    seen = []
    runtime._approval_callback = lambda *args: seen.append(args) or "acceptForSession"
    for reason in ("First argument", "Different argument"):
        assert (
            await runtime._approval_choice(
                "mcp_example_tool", {"arguments": {"reason": reason}}, Permission.ASK
            )
            == "accept"
        )
    assert len(seen) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("properties", [None, {}, {"ancestorThreadId": {}}])
async def test_descendants_refuse_missing_schema_fields_without_sending_rpc(
    runtime, monkeypatch, properties
):
    from unittest.mock import AsyncMock

    runtime._thread_id = "parent"
    runtime.capabilities = CodexCapabilities(
        methods={} if properties is None else {"thread/list": {"properties": properties}}
    )
    monkeypatch.setattr(runtime, "_ensure_started", AsyncMock())
    request = AsyncMock(return_value={"data": []})
    monkeypatch.setattr(runtime, "_timed_request", request)
    with pytest.raises(RuntimeError, match="does not advertise thread/list"):
        await runtime.list_threads(descendants=True)
    request.assert_not_awaited()
    # The baseline session list remains available on older schemas.
    assert await runtime.list_threads() == {"data": []}


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
@pytest.mark.parametrize("persisted", [True, False])
async def test_detached_review_streams_separate_thread_and_restores_main(
    runtime, monkeypatch, persisted
):
    from unittest.mock import AsyncMock

    runtime._thread_id = runtime.session_id = "main-thread"
    runtime._thread_persisted = persisted
    runtime.history = [{"id": "earlier-turn", "items": []}]
    runtime.token_usage = {"last": {"totalTokens": 42}}
    runtime._transport = SimpleNamespace(cancel_server_requests=AsyncMock())
    monkeypatch.setattr(runtime, "ensure_thread", AsyncMock(return_value=False))
    runtime.capabilities = CodexCapabilities(
        methods={"thread/fork": {"properties": {"deferGoalContinuation": {}}}}
    )

    async def request(method, params):
        if method in {"thread/fork", "thread/start"}:
            assert method == ("thread/fork" if persisted else "thread/start")
            assert params.get("threadId") == ("main-thread" if persisted else None)
            assert params["sandbox"] == "read-only"
            assert params.get("deferGoalContinuation") is (True if persisted else None)
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

    assert latest_thread(
        runtime.config.working_directory, runtime.billing_requested
    ).session_id == ("main-thread" if persisted else "review-thread")
    from superqode.session.codex import saved_thread

    assert (
        saved_thread(runtime.config.working_directory, "main-thread").backend_resume_ready
        == persisted
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


@pytest.mark.asyncio
async def test_history_falls_back_only_for_unimplemented_paging(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    from superqode.runtime.codex_transport import CodexRPCError

    runtime._thread_id = "saved"
    runtime.capabilities = CodexCapabilities(methods={"thread/items/list": {}})
    monkeypatch.setattr(runtime, "ensure_thread", AsyncMock())
    request = AsyncMock(
        side_effect=CodexRPCError(
            "thread/items/list",
            {
                "code": -32600,
                "message": "not supported yet",
            },
        )
    )
    monkeypatch.setattr(runtime, "_timed_request", request)
    fallback = AsyncMock(return_value={"thread": {"turns": [{"id": "old"}]}})
    monkeypatch.setattr(runtime, "read_thread", fallback)
    for _ in range(2):
        assert (await runtime.thread_history())["thread"]["turns"][0]["id"] == "old"
    assert request.await_count == 1
    with pytest.raises(ValueError, match="paginated"):
        await runtime.thread_history(cursor="old-page")
    runtime._history_paging_unavailable = False
    request.side_effect = CodexRPCError(
        "thread/items/list", {"code": -32000, "message": "disconnected"}
    )
    with pytest.raises(CodexRPCError, match="disconnected"):
        await runtime.thread_history()


@pytest.mark.asyncio
@pytest.mark.parametrize("paged", [True, False])
@pytest.mark.parametrize("error", [True, False])
async def test_empty_history_handles_only_unmaterialized_thread_errors(
    runtime, monkeypatch, paged, error
):
    from unittest.mock import AsyncMock
    from superqode.runtime.codex_transport import CodexRPCError

    monkeypatch.setattr(runtime, "ensure_thread", AsyncMock())
    runtime.capabilities = CodexCapabilities(methods={"thread/items/list": {}} if paged else {})
    response = (
        {"data": [], "nextCursor": None, "backwardsCursor": "previous"}
        if paged
        else {"thread": {"id": "fresh", "turns": []}}
    )
    request = AsyncMock(return_value=response)
    monkeypatch.setattr(runtime, "_timed_request" if paged else "read_thread", request)
    if error:
        request.side_effect = CodexRPCError(
            "thread/read",
            {
                "code": -32600,
                "message": "thread fresh is not materialized yet; includeTurns is unavailable before first user message",
            },
        )
    result = await runtime.thread_history()
    assert result["data"] == []
    assert "No messages or tool history" in result["message"]
    if paged and not error:
        assert result["backwardsCursor"] == "previous"
    request.side_effect = CodexRPCError(
        "thread/read", {"code": -32000, "message": "permission denied"}
    )
    with pytest.raises(CodexRPCError, match="permission denied"):
        await runtime.thread_history()


@pytest.mark.asyncio
async def test_fresh_history_handles_codex_0160_list_turns_limitation(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    from superqode.runtime.codex_transport import CodexRPCError

    monkeypatch.setattr(runtime, "ensure_thread", AsyncMock())
    monkeypatch.setattr(
        runtime,
        "read_thread",
        AsyncMock(
            side_effect=CodexRPCError(
                "thread/read",
                {"code": -32601, "message": "list_turns is not supported yet"},
            )
        ),
    )
    assert (await runtime.thread_history())["data"] == []
    runtime._thread_persisted = True
    with pytest.raises(CodexRPCError, match="list_turns"):
        await runtime.thread_history()


@pytest.mark.asyncio
async def test_optional_mention_catalog_failure_is_cached_and_does_not_fail_turn(
    runtime, monkeypatch
):
    from unittest.mock import AsyncMock

    runtime.capabilities = CodexCapabilities(methods={"skills/list": {}, "app/list": {}})
    inspect = AsyncMock(side_effect=RuntimeError("catalog offline"))
    monkeypatch.setattr(runtime, "inspect", inspect)
    for _ in range(2):
        assert await runtime._composer_input("$review @drive") == [
            {"type": "text", "text": "$review @drive", "text_elements": []}
        ]
    assert inspect.await_count == 2


@pytest.mark.asyncio
async def test_fresh_detached_review_never_forks_or_marks_origin_resumable(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    from superqode.session.codex import saved_thread, latest_thread

    runtime._accept_thread({"thread": {"id": "unsaved"}, "approvalsReviewer": "user"})
    runtime._transport = SimpleNamespace(cancel_server_requests=AsyncMock())
    monkeypatch.setattr(runtime, "ensure_thread", AsyncMock(return_value=False))

    async def request(method, params):
        assert method == "thread/start"
        assert "threadId" not in params
        raise RuntimeError("review creation failed")

    monkeypatch.setattr(runtime, "_timed_request", request)
    runtime.set_review(detached=True)
    with pytest.raises(RuntimeError, match="review creation failed"):
        await runtime.run("review")
    assert runtime.thread_id == "unsaved"
    saved = saved_thread(runtime.config.working_directory, "unsaved")
    assert not saved.backend_resume_ready
    from superqode.session.harness_bridge import probe_session_availability

    assert (
        probe_session_availability(saved, cwd=runtime.config.working_directory).status
        == "missing_transcript"
    )
    assert latest_thread(runtime.config.working_directory, runtime.billing_requested) is None


def test_native_identity_and_limit_pools_are_preserved(runtime):
    from superqode.session.codex import saved_thread

    runtime._accept_thread(
        {
            "thread": {
                "id": "child",
                "sessionId": "native-session",
                "forkedFromId": "parent",
            },
            "approvalsReviewer": "user",
        },
        persisted=True,
    )
    saved = saved_thread(runtime.config.working_directory, "child")
    assert saved.backend_native_session_id == runtime.native_session_id == "native-session"
    assert saved.backend_forked_from_id == runtime.forked_from_id == "parent"
    runtime._on_notification(
        "account/rateLimits/updated",
        {
            "rateLimits": {"primary": {}},
            "rateLimitsByLimitId": {"codex": {"limitId": "codex"}},
        },
    )
    assert runtime.rate_limits_by_limit_id["codex"]["limitId"] == "codex"


@pytest.mark.asyncio
async def test_mediated_profile_clears_full_access_and_named_profile(runtime, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(runtime, "_ensure_started", AsyncMock())
    runtime.capabilities = CodexCapabilities(
        methods={"turn/start": {"properties": {"approvalsReviewer": {}}}}
    )
    runtime._permission_profile = "unsafe-profile"
    runtime.sandbox_backend = runtime._next_turn_sandbox = "danger-full-access"
    runtime._approval_policy = "never"
    assert (await runtime.set_mediated_profile())["sandbox"] == "workspace-write"
    assert runtime._permission_profile is None
    assert runtime._next_turn_sandbox is None
    assert runtime._approval_policy == "on-request"


@pytest.mark.asyncio
async def test_turn_options_are_validated_and_sent_once(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    from jsonschema import ValidationError, SchemaError

    runtime._thread_id = runtime.session_id = "main-thread"
    runtime._transport = SimpleNamespace(cancel_server_requests=AsyncMock())
    monkeypatch.setattr(runtime, "_ensure_started", AsyncMock())
    monkeypatch.setattr(runtime, "ensure_thread", AsyncMock(return_value=False))
    runtime.capabilities = CodexCapabilities(
        methods={
            "turn/start": {
                "properties": {
                    "outputSchema": {},
                    "summary": {"enum": ["concise", "detailed", "none", "auto"]},
                    "serviceTier": {"type": ["string", "null"]},
                    "clientUserMessageId": {"type": ["string", "null"]},
                }
            }
        }
    )
    options = {
        "outputSchema": {"type": "object"},
        "summary": "concise",
        "serviceTier": None,
        "clientUserMessageId": "message-1",
    }
    await runtime.set_turn_options(options)
    with pytest.raises(ValidationError):
        await runtime.set_turn_options({"summary": "invalid"})
    with pytest.raises(SchemaError):
        await runtime.set_turn_options({"outputSchema": {"type": "invalid"}})
    with pytest.raises(ValueError):
        await runtime.set_turn_options({"unknown": True})
    seen = []

    async def request(method, params):
        assert method == "turn/start"
        seen.append(params)
        runtime._on_notification(
            "turn/completed",
            {
                "threadId": "main-thread",
                "turn": {"id": "turn", "status": "completed"},
            },
        )
        return {"turn": {"id": "turn"}}

    monkeypatch.setattr(runtime, "_timed_request", request)
    await runtime.run("first")
    await runtime.run("second")
    assert all(seen[0][key] == value for key, value in options.items())
    assert not options.keys() & seen[1].keys()


@pytest.mark.asyncio
async def test_turn_options_refuse_fields_absent_from_selected_binary(runtime, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(runtime, "_ensure_started", AsyncMock())
    runtime.capabilities = CodexCapabilities(methods={"turn/start": {"properties": {}}})
    with pytest.raises(RuntimeError, match="outputSchema"):
        await runtime.set_turn_options({"outputSchema": {"type": "object"}})
    assert runtime._next_turn_options == {}
