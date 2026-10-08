"""Exercise the native transport against a real, scripted stdio subprocess."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.codex_cli import CodexCLIRuntime
from superqode.runtime.codex_transport import CodexTransport
from superqode.tools.question_tool import Answer, get_question_handler, set_question_handler


SERVER = r"""
import json, sys
def send(message):
    print(json.dumps(message), flush=True)
def event(method, **params):
    send({"method": method, "params": params})
def result(rid, **value):
    send({"id": rid, "result": value})
turn = 0
waiting = None
for line in sys.stdin:
    msg = json.loads(line)
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        result(rid, userAgent="codex/0.160.0", serverInfo={"version": "0.160.0"})
    elif method == "account/read":
        result(rid, account={"type": "chatgpt", "planType": "plus"}, requiresOpenaiAuth=True)
    elif method == "model/list":
        result(rid, data=[{"model": "test-model", "displayName": "Test model",
                          "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}])
    elif method in ("thread/start", "thread/resume", "thread/fork"):
        result(rid, thread={"id": "thread-1"}, modelProvider="openai", model="test-model")
    elif method == "thread/read":
        result(rid, thread={"id": "thread-1", "name": "Test thread"})
    elif method == "thread/list":
        result(rid, data=[{"id": "thread-1", "name": "Test thread"}])
    elif method in ("turn/start", "review/start"):
        turn += 1
        tid = f"turn-{turn}"
        prompt = msg["params"].get("input", [{}])[0].get("text", "review")
        if prompt == "eof":
            sys.exit(0)
        if prompt == "malformed":
            print("not json", flush=True)
            continue
        if prompt == "rpc-fail":
            send({"id": rid, "error": {"code": -32602, "message": "unsupported model"}})
            continue
        # Deliberately emit an event before acknowledging turn/start.
        event("item/agentMessage/delta", threadId="thread-1", turnId=tid, itemId="message", delta="hello ")
        result(rid, turn={"id": tid, "status": "inProgress"})
        if prompt in ("approval", "question", "wait"):
            waiting = tid
            if prompt == "approval":
                send({"id": "approve-1", "method": "item/commandExecution/requestApproval",
                      "params": {"threadId": "thread-1", "turnId": tid, "command": "echo ok"}})
            elif prompt == "question":
                send({"id": "question-1", "method": "item/tool/requestUserInput",
                      "params": {"threadId": "thread-1", "turnId": tid, "questions": [
                          {"id": "choice", "question": "Choose?", "options": [{"label": "A"}, {"label": "B"}]}]}})
            continue
        if prompt == "failed":
            event("turn/completed", threadId="thread-1", turn={"id": tid, "status": "failed",
                "error": {"message": "usage limit reached"}})
            continue
        if prompt == "sandbox":
            assert msg["params"]["sandboxPolicy"]["type"] == "workspaceWrite"
            assert msg["params"]["sandboxPolicy"]["writableRoots"]
        event("item/reasoning/summaryTextDelta", threadId="thread-1", turnId=tid, delta="Checking files")
        event("item/started", threadId="thread-1", turnId=tid,
              item={"id": "command", "type": "commandExecution", "command": "echo ok", "status": "inProgress"})
        event("item/completed", threadId="thread-1", turnId=tid,
              item={"id": "command", "type": "commandExecution", "command": "echo ok", "status": "completed", "exitCode": 0, "aggregatedOutput": "ok"})
        event("item/agentMessage/delta", threadId="thread-1", turnId=tid, itemId="message", delta="world")
        event("item/completed", threadId="thread-1", turnId=tid,
              item={"id": "message", "type": "agentMessage", "text": "hello world"})
        event("thread/tokenUsage/updated", threadId="thread-1", tokenUsage={"last": {"inputTokens": 12, "outputTokens": 3}})
        event("account/rateLimits/updated", rateLimits={"primary": {"usedPercent": 10}})
        event("turn/completed", threadId="thread-1", turn={"id": tid, "status": "completed"})
    elif method == "turn/interrupt":
        result(rid)
        event("turn/completed", threadId="thread-1", turn={"id": waiting, "status": "interrupted"})
        waiting = None
    elif method == "turn/steer":
        result(rid, turnId=waiting)
        event("item/agentMessage/delta", threadId="thread-1", turnId=waiting, itemId="steered", delta="steered")
        event("turn/completed", threadId="thread-1", turn={"id": waiting, "status": "completed"})
        waiting = None
    elif rid in ("approve-1", "question-1"):
        if rid == "question-1":
            assert msg["result"] == {"answers": {"choice": {"answers": ["B"]}}}
        else:
            assert msg["result"]["decision"] in ("accept", "decline")
        event("item/agentMessage/delta", threadId="thread-1", turnId=waiting, itemId="answer", delta="answered")
        event("turn/completed", threadId="thread-1", turn={"id": waiting, "status": "completed"})
        waiting = None
    elif rid is not None:
        result(rid)
"""


@pytest.fixture
def native_runtime(tmp_path, monkeypatch):
    import superqode.runtime.codex_cli as cli

    script = tmp_path / "app_server.py"
    script.write_text(SERVER)
    original_spawn = asyncio.create_subprocess_exec
    launches = []

    async def spawn(*argv, **kwargs):
        launches.append((argv, kwargs["env"]))
        return await original_spawn(sys.executable, "-u", str(script), **kwargs)

    monkeypatch.setattr(cli, "codex_binary", lambda explicit=None: sys.executable)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    runtime = CodexCLIRuntime(
        config=AgentConfig(provider="openai", model="", working_directory=tmp_path),
        billing_requested="subscription",
        request_timeout=2,
    )
    return runtime, launches


@pytest.mark.asyncio
async def test_reuses_process_streams_early_events_and_preserves_usage(native_runtime):
    runtime, launches = native_runtime
    try:
        response = await runtime.run("hello")
        assert response.content == "hello world"
        assert response.tool_calls_made == 1
        assert response.usage["input_tokens"] == 12
        assert runtime.subscription_status["billing_verified"] == "chatgpt-account"
        assert runtime.rate_limits == {"primary": {"usedPercent": 10}}
        assert runtime.timings["first_text"] >= 0
        assert (await runtime.run("again")).content == "hello world"
        assert len(launches) == 1
        assert runtime._active_turn is None
        proc = runtime._transport.process
    finally:
        await runtime.aclose()
    assert proc.returncode is not None


@pytest.mark.asyncio
async def test_metadata_does_not_create_thread_or_require_sdk(native_runtime, monkeypatch):
    runtime, launches = native_runtime
    monkeypatch.setitem(sys.modules, "openai_codex", None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("CODEX_API_KEY", "test-codex-key")
    monkeypatch.setenv("HERDR_TOKEN", "test-pane-authority")
    monkeypatch.setenv("CODEX_HOME", "/custom/codex")
    try:
        assert (await runtime.models())["data"][0]["model"] == "test-model"
        assert runtime.thread_id is None
        argv, env = launches[0]
        assert "app-server" in argv and "stdio://" in argv
        assert 'forced_login_method="chatgpt"' in argv
        assert not {"OPENAI_API_KEY", "CODEX_API_KEY", "HERDR_TOKEN"} & env.keys()
        assert env["CODEX_HOME"] == "/custom/codex"
        assert runtime.codex_sessions_dir == "/custom/codex/sessions"
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_refuses_api_account_before_thread_start(native_runtime, monkeypatch):
    runtime, _ = native_runtime

    async def account(**kwargs):
        return {"account": {"type": "apiKey"}, "requiresOpenaiAuth": True}

    monkeypatch.setattr(runtime, "account", account)
    try:
        with pytest.raises(RuntimeError, match="No API billing fallback"):
            await runtime.run("must not run")
        assert runtime.thread_id is None
        assert runtime._active_turn is None
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_reader_keeps_routing_while_approval_waits(native_runtime):
    runtime, _ = native_runtime
    reached, release = asyncio.Event(), asyncio.Event()

    async def approval(tool, args):
        assert tool == "bash" and args["command"] == "echo ok"
        reached.set()
        await release.wait()
        return True

    runtime._approval_callback = approval
    running = asyncio.create_task(runtime.run("approval"))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        # The RPC reader must remain responsive while the UI has not decided.
        assert (await asyncio.wait_for(runtime.models(), 1))["data"]
        release.set()
        assert (await running).content == "hello answered"
    finally:
        release.set()
        await runtime.aclose()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_question_answer_bridge(native_runtime):
    runtime, _ = native_runtime
    old = get_question_handler()

    async def answer(question):
        assert question.options == ["A", "B"]
        return Answer("B")

    set_question_handler(answer)
    try:
        assert (await runtime.run("question")).content == "hello answered"
    finally:
        set_question_handler(old)
        await runtime.aclose()


@pytest.mark.asyncio
async def test_cancel_and_steer_use_live_turn(native_runtime):
    runtime, launches = native_runtime

    async def active():
        for _ in range(200):
            if runtime._active_turn:
                return
            await asyncio.sleep(0.005)
        raise AssertionError("turn did not start")

    try:
        running = asyncio.create_task(runtime.run("wait"))
        await active()
        assert await runtime.steer("continue")
        assert (await running).content == "hello steered"
        running = asyncio.create_task(runtime.run("wait"))
        await active()
        runtime.cancel()
        assert (await asyncio.wait_for(running, 2)).stopped_reason == "interrupted"
        assert len(launches) == 1
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt, message",
    [
        ("eof", "closed stdout"),
        ("malformed", "Expecting value"),
        ("rpc-fail", "unsupported model"),
        ("failed", "usage limit reached"),
    ],
)
async def test_failures_surface_without_replay(native_runtime, prompt, message):
    runtime, launches = native_runtime
    try:
        with pytest.raises(Exception, match=message):
            await asyncio.wait_for(runtime.run(prompt), 3)
        assert len(launches) == 1
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_concurrent_turns_serialize_and_review_is_native(native_runtime):
    runtime, launches = native_runtime
    try:
        results = await asyncio.gather(runtime.run("first"), runtime.run("second"))
        assert [result.content for result in results] == ["hello world", "hello world"]
        runtime.set_review()
        await runtime.run("ignored by native review")
        assert "review/start" in runtime.timings
        runtime.set_sandbox_backend("workspace-write")
        await runtime.run("sandbox")
        assert len(launches) == 1
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_transport_timeout_is_bounded_and_not_replayed(tmp_path):
    script = tmp_path / "silent.py"
    script.write_text("import sys,time\nfor line in sys.stdin: time.sleep(10)\n")
    transport = CodexTransport(
        lambda *_: None, lambda *_: None, lambda *_: None, request_timeout=0.03
    )
    try:
        await transport.start([sys.executable, str(script)], cwd=str(tmp_path), env={})
        with pytest.raises(RuntimeError, match="not replayed"):
            await transport.request("turn/start", {})
        assert not transport._pending
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_closing_stream_interrupts_before_reusing_thread(native_runtime):
    runtime, launches = native_runtime
    events = runtime.run_harness_events("wait")
    try:
        while (await anext(events)).type != "model_delta":
            pass
        assert runtime._active_turn
        await events.aclose()
        assert runtime._active_turn is None
        assert (await runtime.run("next")).content == "hello world"
        assert len(launches) == 1
    finally:
        await events.aclose()
        await runtime.aclose()


@pytest.mark.asyncio
async def test_cancelling_task_cleans_unanswered_question(native_runtime):
    runtime, _ = native_runtime
    old = get_question_handler()
    reached, cancelled = asyncio.Event(), asyncio.Event()

    async def answer(question):
        reached.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    set_question_handler(answer)
    running = asyncio.create_task(runtime.run("question"))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert cancelled.is_set()
        assert not runtime._transport._server_tasks
        assert (await runtime.run("next")).content == "hello world"
    finally:
        set_question_handler(old)
        await runtime.aclose()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_subscription_rejects_non_openai_thread(native_runtime, monkeypatch):
    runtime, _ = native_runtime
    original = runtime._timed_request
    methods = []

    async def request(method, params=None):
        methods.append(method)
        value = await original(method, params)
        if method == "thread/start":
            value["modelProvider"] = "other"
        return value

    monkeypatch.setattr(runtime, "_timed_request", request)
    try:
        with pytest.raises(RuntimeError, match="different provider"):
            await runtime.run("must not run")
        assert "turn/start" not in methods
        assert runtime.subscription_status["billing_verified"] == "unknown"
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_user_skip_answers_rpc_and_unsupported_requests_are_explicit(native_runtime):
    runtime, _ = native_runtime
    old = get_question_handler()

    async def skipped(question):
        raise asyncio.CancelledError

    set_question_handler(skipped)
    try:
        assert await runtime._server_request(
            "item/tool/requestUserInput", {"questions": [{"id": "q", "question": "Skip?"}]}
        ) == {"answers": {}}
        assert await runtime._server_request("item/commandExecution/requestApproval", {}) == {
            "decision": "decline"
        }
        assert await runtime._server_request("item/permissions/requestApproval", {}) == {
            "permissions": {},
            "scope": "turn",
        }
        assert (await runtime._server_request("mcpServer/elicitation/request", {}))[
            "action"
        ] == "cancel"
        with pytest.raises(RuntimeError, match="does not support"):
            await runtime._server_request("future/method", {})
    finally:
        set_question_handler(old)
        await runtime.aclose()


def test_remote_tool_arguments_cannot_overwrite_event_fields():
    from superqode.runtime.codex_events import CodexEvents

    mapper = CodexEvents()
    item = {
        "type": "mcpToolCall",
        "id": "m1",
        "server": "test",
        "tool": "echo",
        "status": "completed",
        "arguments": {"output": "argument", "success": False, "tool_name": "argument"},
        "result": "actual result",
    }
    result = mapper.map("item/completed", {"item": item})[0]
    assert result.data["output"] == "actual result"
    assert result.data["success"] is True
    assert result.data["tool_name"] == "mcp:test/echo"
    assert result.data["arguments"]["output"] == "argument"
    item["arguments"] = ["valid", "JSON", "array"]
    assert (
        mapper.map("item/completed", {"item": item})[0].data["arguments"]["input"]
        == item["arguments"]
    )
    assert mapper.map("item/reasoning/textDelta", {"delta": "hidden"}) == []


@pytest.mark.asyncio
async def test_closing_at_terminal_event_keeps_connection_reusable(native_runtime):
    runtime, launches = native_runtime
    events = runtime.run_harness_events("hello")
    try:
        while (await anext(events)).type != "turn_complete":
            pass
        await events.aclose()
        assert (await runtime.run("next")).content == "hello world"
        assert len(launches) == 1
    finally:
        await events.aclose()
        await runtime.aclose()
