"""ACP Preview lifecycle contracts and model-free, real stdio interoperability."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from superqode.acp.client import ACPClient, cancel_prompt_with_grace
from superqode.acp.ledger import SessionLedger
from superqode.acp.outbox import SubmissionOutbox
from superqode.acp.protocol import (
    ProtocolError,
    capability,
    select_version,
    validate_envelope,
    validate_v2,
)
from superqode.acp.state import SessionRegistry
from superqode.acp.transport import RpcConnection

FIXTURE = Path(__file__).parent / "fixtures" / "acp_v2_agent.py"


def client(tmp_path, *, version=2, v1_only=False, **kwargs):
    argv = [sys.executable, str(FIXTURE), str(tmp_path / "agent.sqlite3")]
    if v1_only:
        argv.append("--v1-only")
    return ACPClient(
        tmp_path,
        "fixture",
        protocol_version=version,
        launch_argv=argv,
        startup_timeout=5,
        prompt_timeout=5,
        **kwargs,
    )


@pytest.mark.parametrize("version,expected", [(1, 1), (2, 2), (3, 2), (65535, 2)])
def test_version_negotiation(version, expected):
    assert select_version(version) == expected


@pytest.mark.parametrize(
    "version,code",
    [(0, -32022), (-1, -32602), (True, -32602), (None, -32602), ("2", -32602), (65536, -32602)],
)
def test_invalid_version(version, code):
    with pytest.raises(ProtocolError) as error:
        select_version(version)
    assert error.value.code == code


def test_empty_capabilities_and_strict_envelopes():
    assert capability({"session": {}}, "session")
    assert not capability({"session": None}, "session")
    for value in [
        [],
        {"jsonrpc": "2.0", "method": "x", "id": None},
        {"jsonrpc": "2.0", "method": "x", "id": True},
    ]:
        with pytest.raises(ProtocolError):
            validate_envelope(value)


async def test_v1_router_does_not_open_v2_storage_or_lose_buffered_messages():
    initial = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}\n'
    following = b'{"jsonrpc":"2.0","id":2,"method":"session/list","params":{}}\n'
    reader = asyncio.StreamReader()
    reader.feed_data(initial + following)
    reader.feed_eof()

    def unavailable_storage():
        raise AssertionError("V1 must not instantiate v2 storage")

    connection = RpcConnection(reader, SimpleNamespace(), agent_factory=unavailable_storage)
    await connection.run()
    assert connection.switch_to_v1 == initial
    assert await reader.readline() == following


def test_message_replacement_children_and_metadata():
    registry = SessionRegistry()
    registry.apply(
        "p",
        {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "m",
            "content": {"type": "text", "text": "old"},
        },
    )
    registry.apply(
        "p",
        {
            "sessionUpdate": "agent_message",
            "messageId": "m",
            "content": [{"type": "text", "text": "new"}],
        },
    )
    registry.apply(
        "p", {"sessionUpdate": "subagent_update", "sessionId": "c", "capabilities": {"cancel": {}}}
    )
    registry.apply(
        "c",
        {
            "sessionUpdate": "agent_message",
            "messageId": "m",
            "content": [{"type": "text", "text": "child"}],
        },
    )
    assert registry.get("p").text() == "new"
    assert registry.get("c").text() == "child"
    registry.check_child_method("c", "session/cancel")
    for method in [
        "session/prompt",
        "session/resume",
        "session/close",
        "session/set_config_option",
    ]:
        with pytest.raises(ProtocolError):
            registry.check_child_method("c", method)
    registry.apply(
        "p",
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "t",
            "title": "old",
            "_meta": {"a": 1, "b": 2},
        },
    )
    registry.apply(
        "p",
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "t",
            "title": None,
            "_meta": {"a": None, "c": 3},
        },
    )
    assert registry.get("p").tools["t"]["title"] is None
    assert registry.get("p").tools["t"]["_meta"] == {"b": 2, "c": 3}


def test_terminal_snapshot_replaces_and_tool_chunks_append():
    registry = SessionRegistry()
    for kind, data in [
        ("terminal_update", {"output": {"data": base64.b64encode(b"old").decode()}}),
        ("terminal_output_chunk", {"data": base64.b64encode(b" chunk").decode()}),
        ("terminal_update", {"output": {"data": base64.b64encode(b"new").decode()}}),
    ]:
        registry.apply("p", {"sessionUpdate": kind, "terminalId": "t", **data})
    assert registry.get("p").terminals["t"]["bytes"] == b"new"
    content = {"type": "content", "content": {"type": "text", "text": "output"}}
    registry.apply(
        "p", {"sessionUpdate": "tool_call_content_chunk", "toolCallId": "a", "content": content}
    )
    registry.apply(
        "p", {"sessionUpdate": "tool_call_content_chunk", "toolCallId": "a", "content": content}
    )
    assert registry.get("p").tools["a"]["content"] == [content, content]


def test_chunk_metadata_and_mirrored_child_state_do_not_invent_completions():
    registry = SessionRegistry()
    registry.apply("s", {"sessionUpdate": "agent_message", "messageId": "m", "_meta": {"a": 1}})
    registry.apply(
        "s",
        {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "m",
            "content": {"type": "text", "text": "x"},
            "_meta": {"a": 2},
        },
    )
    assert registry.get("s").messages["m"]["_meta"] == {"a": 1}
    for state in ["running", "unknown", "idle"]:
        registry.apply(
            "s", {"sessionUpdate": "subagent_update", "sessionId": "c", "state": {"state": state}}
        )
    assert registry.get("c").state == "idle"
    assert registry.get("c").uncertain
    assert registry.get("c").completed == 0
    registry.apply("c", {"sessionUpdate": "state_update", "state": "running"})
    registry.apply(
        "s", {"sessionUpdate": "subagent_update", "sessionId": "c", "state": {"state": "idle"}}
    )
    registry.apply("c", {"sessionUpdate": "state_update", "state": "idle"})
    assert registry.get("c").completed == 1
    registry.apply("s", {"sessionUpdate": "subagent_update", "sessionId": "c", "state": None})
    assert registry.get("c").state == "unknown"


def test_durable_atomic_insertion_and_outbox(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = SessionLedger(path)
    ledger.create("s", str(tmp_path), {})
    prompt = [{"type": "text", "text": "do work"}]
    identity, _ = ledger.insert("s", prompt, "key")
    ledger.close()
    ledger = SessionLedger(path)
    assert ledger.insert("s", prompt, "key") == (identity, None)
    assert len(ledger.history("s")) == 1
    with pytest.raises(ProtocolError):
        ledger.insert("s", [{"type": "text", "text": "other"}], "key")
    ledger.close()
    outbox = SubmissionOutbox(tmp_path / "outbox.sqlite", scope="agent/project")
    outbox.put("key", {"session_id": "s", "prompt": prompt, "status": "pending"})
    assert (
        SubmissionOutbox(tmp_path / "outbox.sqlite", scope="agent/project").pending()["key"][
            "prompt"
        ]
        == prompt
    )
    assert not SubmissionOutbox(tmp_path / "outbox.sqlite", scope="other").pending()


async def test_stdio_v2_completion_and_v1_same_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    for version in [2, 1]:
        instance = client(tmp_path, version=version)
        try:
            assert await instance.start(), instance.last_startup_error
            assert instance.negotiated_version == version
            assert await instance.send_prompt("hello") == "end_turn"
            assert instance.get_message_buffer() == "answer:hello"
        finally:
            await instance.stop()


@pytest.mark.parametrize("version", [1, 2])
async def test_production_cli_with_synthetic_harness(tmp_path, monkeypatch, version):
    import yaml
    from superqode.harness.loader import harness_spec_to_dict
    from superqode.harness.templates import coding_template

    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    spec = harness_spec_to_dict(coding_template())
    spec["runtime"] = {"backend": "builtin", "fallback_backends": []}
    spec["model_policy"]["primary"] = "synthetic/passthrough"
    path = tmp_path / "harness.yaml"
    path.write_text(yaml.safe_dump(spec))
    instance = ACPClient(
        tmp_path,
        "superqode",
        protocol_version=version,
        launch_argv=[sys.executable, "-m", "superqode.main", "serve", "acp", "--spec", str(path)],
        startup_timeout=10,
        prompt_timeout=10,
    )
    try:
        assert await instance.start(), instance.last_startup_error
        assert instance.negotiated_version == version
        assert await instance.send_prompt("entry point check") == "end_turn"
        assert instance.get_message_buffer() == "entry point check"
        if version == 2:
            session_id = instance.get_session_id()
            assert await instance.reconnect(), instance.last_startup_error
            assert instance.get_session_id() == session_id
            assert await instance.send_prompt("resumed check") == "end_turn"
            assert instance.get_message_buffer() == "resumed check"
            await instance.close_session()
    finally:
        await instance.stop()


async def test_v1_fallback_reopens_once(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    instance = client(tmp_path, v1_only=True, terminal_auth_supported=True)
    try:
        assert await instance.start(), instance.last_startup_error
        assert instance.negotiated_version == 1
        assert instance._v1_fallback
        assert instance.get_auth_methods()[0]["id"] == "superqode-setup"
        assert await instance.send_prompt("hello") == "end_turn"
    finally:
        await instance.stop()


async def test_fresh_connection_can_negotiate_v2_after_earlier_v1_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    instance = client(tmp_path, v1_only=True, initialize_only=True)
    try:
        assert await instance.start(), instance.last_startup_error
        assert instance.negotiated_version == 1
        await instance.stop()
        instance.launch_argv = instance.launch_argv[:-1]
        assert await instance.start(), instance.last_startup_error
        assert instance.negotiated_version == 2
    finally:
        await instance.stop()


async def test_wire_notifications_and_invalid_peer_errors_never_receive_responses(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(FIXTURE),
        str(tmp_path / "wire.sqlite"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def send(payload):
        process.stdin.write(json.dumps({"jsonrpc": "2.0", **payload}).encode() + b"\n")
        await process.stdin.drain()

    try:
        await send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 2,
                    "info": {"name": "test", "version": "1"},
                    "capabilities": {},
                },
            }
        )
        async with asyncio.timeout(5):
            assert json.loads(await process.stdout.readline())["result"]["protocolVersion"] == 2
            await send({"method": "session/cancel", "params": []})
            await send({"id": "unknown-peer-response", "error": None})
            await send({"id": 2, "method": "session/list", "params": {}})
            assert json.loads(await process.stdout.readline()) == {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"sessions": []},
            }
    finally:
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 5)


async def test_ack_is_not_completion_and_cancellation_preserves_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    instance = client(tmp_path)
    try:
        assert await instance.start(), instance.last_startup_error
        task = asyncio.create_task(instance.send_prompt("slow"))
        async with asyncio.timeout(5):
            while not instance.get_message_buffer():
                await asyncio.sleep(0.01)
        assert not task.done()
        assert await cancel_prompt_with_grace(instance, task, timeout=3)
        assert task.result() == "cancelled"
        assert await instance.send_prompt("next") == "end_turn"
        assert instance.get_message_buffer() == "answer:next"
    finally:
        await instance.stop()


async def test_restart_resume_replay_and_idempotent_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    instance = client(tmp_path)
    try:
        assert await instance.start(), instance.last_startup_error
        assert await instance.send_prompt("hello", idempotency_key="durable") == "end_turn"
        identity = instance.outbox.entries["durable"]["message_id"]
        session_id = instance.get_session_id()
        assert await instance.reconnect(), instance.last_startup_error
        assert instance.get_session_id() == session_id
        assert instance.sessions.get(session_id).replay_complete
        assert (await instance.retry_submission("durable"))["messageId"] == identity
        assert await instance.send_prompt("hello", idempotency_key="durable") == "end_turn"
        assert instance.get_message_buffer() == "answer:hello"
        history = instance.sessions.get(session_id)
        assert len([m for m in history.messages.values() if m["role"] == "user_message"]) == 1
        assert await instance.send_prompt("another") == "end_turn"
    finally:
        await instance.stop()


async def test_child_output_is_separate_and_errors_are_semantic(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    updates = []

    async def record(params):
        updates.append(params)

    instance = client(tmp_path, on_session_update=record)
    try:
        assert await instance.start(), instance.last_startup_error
        assert await instance.send_prompt("child") == "end_turn"
        assert instance.get_message_buffer() == "answer:child"
        children = instance.sessions.get(instance.get_session_id()).children
        assert len(children) == 1
        assert instance.sessions.get(next(iter(children))).text() == "child result"
        assert await instance.send_prompt("error") == "error"
        assert instance.sessions.get(instance.get_session_id()).error["code"] == -32603
    finally:
        await instance.stop()


async def test_typed_configuration_and_no_legacy_probes(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    instance = client(tmp_path)
    try:
        assert await instance.start(), instance.last_startup_error
        assert await instance.set_config_option("thoughts", False)
        option = next(
            o for o in instance.get_session_config_options() if o["configId"] == "thoughts"
        )
        assert option["currentValue"] is False
        call = instance._call_method
        instance._call_method = AsyncMock(side_effect=AssertionError("No v1 probes on v2"))
        await instance.get_available_models()
        await instance.get_available_modes()
        await instance.get_current_model()
        await instance.get_current_mode()
        instance._call_method = call
    finally:
        await instance.stop()


async def test_permission_subject_keying_and_dismissal(tmp_path):
    from superqode.acp.permission_store import ACPPermissionStore

    instance = ACPClient(
        tmp_path,
        "unused",
        protocol_version=2,
        permission_store=ACPPermissionStore(tmp_path / "permissions.md"),
        permission_scope="agent",
    )
    instance.negotiated_version = 2
    instance.sessions.get("s")
    instance.on_permission_request = AsyncMock(return_value="yes")
    params = {
        "sessionId": "s",
        "title": "Run?",
        "subject": {"type": "command", "command": "test", "cwd": str(tmp_path)},
        "options": [{"optionId": "yes", "name": "Always", "kind": "allow_always"}],
    }
    assert (await instance._permission_v2(params))["outcome"]["optionId"] == "yes"
    assert (await instance._permission_v2(params))["outcome"]["optionId"] == "yes"
    assert instance.on_permission_request.await_count == 1
    params["subject"]["command"] = "different"
    instance.on_permission_request.return_value = ""
    assert (await instance._permission_v2(params))["outcome"]["outcome"] == "cancelled"
    assert instance.on_permission_request.await_count == 2


async def test_completion_before_rpc_response_and_resume_snapshot_not_completion(tmp_path):
    instance = ACPClient(tmp_path, "unused", protocol_version=2)
    instance.negotiated_version = 2
    instance._session_id = "s"

    async def update(kind, **fields):
        await instance._handle_v2_update(
            {"sessionId": "s", "update": {"sessionUpdate": kind, **fields}}
        )

    async def submit(method, **kwargs):
        await update("user_message", messageId="u", content=kwargs["prompt"])
        await update("state_update", state="running", background=[])
        await update("agent_message", messageId="a", content=[{"type": "text", "text": "done"}])
        await update("state_update", state="idle", stopReason="end_turn", background=[])
        return {"messageId": "u"}

    instance._call_method = submit
    await update("state_update", state="idle", background=[])
    assert instance.sessions.get("s").completed == 0
    assert await instance.send_prompt("hello") == "end_turn"


async def test_child_resume_and_config_are_rejected_before_any_rpc(tmp_path):
    instance = ACPClient(tmp_path, "unused", protocol_version=2)
    instance.negotiated_version = 2
    instance.sessions.apply("root", {"sessionUpdate": "subagent_update", "sessionId": "child"})
    instance._session_id = "child"
    instance._call_method = AsyncMock()
    with pytest.raises(ProtocolError):
        await instance._resume_session_v2("child")
    assert not await instance.set_config_option("example", False)
    instance._call_method.assert_not_called()


async def test_rpc_timeout_withdraws_request_without_resubmitting(tmp_path):
    instance = ACPClient(tmp_path, "unused", protocol_version=2)
    instance.negotiated_version = 2
    instance._send_json = AsyncMock()
    instance._send_notification = AsyncMock()
    with pytest.raises(TimeoutError):
        await instance._call_method("session/prompt", timeout=0.01, sessionId="s", prompt=[])
    assert instance._send_json.await_count == 1
    instance._send_notification.assert_awaited_once_with("$/cancel_request", requestId=1)


async def test_interactive_manager_permission_can_be_dismissed(tmp_path, monkeypatch):
    from superqode.agents.client import ACPAgentManager
    from prompt_toolkit import PromptSession

    monkeypatch.setenv("SUPERQODE_ACP_PROTOCOL_VERSION", "2")
    monkeypatch.setattr(ACPClient, "start", AsyncMock(return_value=True))
    monkeypatch.setattr(
        PromptSession, "prompt_async", AsyncMock(side_effect=asyncio.CancelledError)
    )
    manager = ACPAgentManager()
    assert await manager.connect_to_agent("unused", str(tmp_path))
    instance = manager._primary
    instance.negotiated_version = 2
    instance.sessions.get("s")
    response = await instance._permission_v2(
        {
            "sessionId": "s",
            "title": "Allow?",
            "options": [{"optionId": "allow", "kind": "allow_once", "name": "Allow once"}],
        }
    )
    assert response == {"outcome": {"outcome": "cancelled"}}
