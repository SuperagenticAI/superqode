"""Muse's protocol lifecycle, without billing or a real account."""

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.muse import MuseRuntime, _command_id


HOST = r"""
import json, sys, uuid, os
assert "META_API_KEY" not in os.environ
assert os.environ["MUSE_UPDATE_INTERVAL_SECONDS"] == "disabled"
session = "muse-session"
turn = None
pending = None
def send(value):
    print(json.dumps(value), flush=True)
def reply(frame, result):
    send({"jsonrpc":"2.0", "id":frame["id"], "result":result})
def event(method, params):
    send({"jsonrpc":"2.0", "method":method, "params":{"sessionId":session, **params}})
def finish(text="hello"):
    item={"itemId":"message", "kind":"agentMessage", "status":"inProgress", "revision":1, "turnId":turn}
    event("item/started", {"item":item})
    event("item/delta", {"itemId":"message", "delta":text[:2]})
    event("item/completed", {"item":{**item,"status":"completed","revision":2,"text":text}})
    event("turn/completed", {"turnId":turn,"terminal":"completed"})
for line in sys.stdin:
    frame=json.loads(line)
    method=frame.get("method")
    p=frame.get("params",{})
    if not method or method=="initialized":
        continue
    if method!="initialize":
        assert uuid.UUID(p["commandId"]).version==7
    if method=="initialize":
        assert p["clientInfo"]["name"]=="superqode"
        reply(frame,{"serverInfo":{"version":"1.4.0"}})
    elif method in {"session/start","session/resume"}:
        if method=="session/start":
            assert p["approvalMode"]=="onRequest"
        reply(frame,{"session":{"sessionId":session,"modelId":"muse-spark"}})
    elif method=="turn/start":
        turn=p["commandId"]
        assert p["sessionId"]==session
        text=p["input"][0]["text"]
        reply(frame,{"status":"accepted","turnId":turn})
        if text=="approve":
            pending={"approvalId":"a", "currentRequirementId":{"approvalId":"a","sourceIndex":0},
                     "toolName":"shell", "rawArgs":"{\"command\":\"echo hi\"}",
                     "availableChoices":[{"choiceId":"allow_once","decision":"approved","scope":"once"},
                                         {"choiceId":"deny","decision":"denied","scope":"once"}]}
            send({"jsonrpc":"2.0","id":"server-approval","method":"approval/request","params":{"sessionId":session,**pending}})
            event("approval/requested",pending)
        elif text=="fail":
            event("turn/completed", {"turnId":turn,"terminal":"failed","error":{"message":"not logged in"}})
        elif text=="wait":
            event("turn/started", {"turnId":turn})
        else:
            finish(text)
    elif method=="approval/decide":
        assert p["requirementId"]==pending["currentRequirementId"]
        reply(frame,{"terminal":True})
        finish(p["choiceId"])
    elif method=="turn/cancel":
        reply(frame,{})
        event("turn/completed", {"turnId":turn,"terminal":"cancelled"})
"""


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    host = tmp_path / "muse"
    host.write_text(f"#!{sys.executable}\n" + HOST)
    host.chmod(0o755)
    monkeypatch.setattr("superqode.runtime.muse.shutil.which", lambda _: str(host))
    return MuseRuntime(config=AgentConfig(provider="meta", model="", working_directory=tmp_path))


def test_command_ids_are_uuid7():
    assert uuid.UUID(_command_id()).version == 7


async def test_three_turns_reuse_one_host_and_complete_final_text(runtime):
    try:
        responses = []
        for text in ["hello", "second", "third"]:
            responses.append((await runtime.run(text)).content)
        assert responses == ["hello", "second", "third"]
        assert runtime.session_id == "muse-session"
        assert runtime.metadata["model"] == "muse-spark"
        process = runtime._process
    finally:
        await runtime.aclose()
    assert process.returncode == 0


@pytest.mark.parametrize("allowed", [True, False])
async def test_approval_is_answered_once_off_the_event_loop(runtime, allowed):
    decisions = []

    def approve(name, args):
        decisions.append((name, args))
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return allowed

    runtime._approval_callback = approve
    try:
        result = await asyncio.wait_for(runtime.run("approve"), timeout=5)
        assert result.content == ("allow_once" if allowed else "deny")
        assert decisions == [("shell", {"command": "echo hi"})]
    finally:
        await runtime.aclose()


async def test_auth_failure_is_visible_not_an_empty_success(runtime):
    try:
        with pytest.raises(RuntimeError, match="Muse Code rejected its saved login"):
            await runtime.run("fail")
    finally:
        await runtime.aclose()


async def test_cancel_settles_without_killing_the_session(runtime):
    task = asyncio.create_task(runtime.run("wait"))
    try:
        for _ in range(100):
            if runtime._turn_id:
                break
            await asyncio.sleep(0.01)
        runtime.cancel()
        result = await asyncio.wait_for(task, timeout=5)
        assert result.stopped_reason == "cancelled"
        assert runtime._process.returncode is None
    finally:
        await runtime.aclose()


async def test_account_route_strips_api_key_and_disables_update_worker(runtime, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key")
    try:
        await runtime.run("hello")
        assert runtime.stripped_api_keys == ["META_API_KEY"]
    finally:
        await runtime.aclose()


async def test_closed_host_resumes_same_session(runtime):
    assert (await runtime.run("first")).content == "first"
    session = runtime.session_id
    await runtime.aclose()
    try:
        assert (await runtime.run("second")).content == "second"
        assert runtime.session_id == session
    finally:
        await runtime.aclose()


async def test_external_task_cancellation_closes_host(runtime):
    task = asyncio.create_task(runtime.run("wait"))
    try:
        for _ in range(100):
            if runtime._turn_id:
                break
            await asyncio.sleep(0.01)
        process = runtime._process
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.returncode is not None
        assert runtime._process is None
        assert not runtime._pending
    finally:
        await runtime.aclose()
