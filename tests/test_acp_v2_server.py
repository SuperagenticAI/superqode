"""Server lifecycle races, held-input deduplication, replay and owned background work."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.acp.server import _AcpSessionState
from superqode.acp.server_v2 import SuperQodeAcpV2Agent, LiveSession
from superqode.acp.protocol import ProtocolError, validate_v2
from superqode.harness.events import HarnessEvent
from superqode.harness.loader import harness_spec_to_dict
from superqode.harness.templates import coding_template


class Connection:
    def __init__(self):
        self.events = []
        self.approval = asyncio.Event()
        self.approval_cancelled = False

    async def notify(self, method, **params):
        if method == "session/update":
            validate_v2("UpdateSessionNotification", params)
        self.events.append((method, params))

    async def request(self, method, **params):
        self.approval.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.approval_cancelled = True
            raise


class Harness:
    session_id = "s"

    def __init__(self):
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.inputs = []
        self.approvals = []

    async def stream(self, prompt, **kwargs):
        self.inputs.append(prompt)
        self.started.set()
        yield HarnessEvent(type="model_delta", data={"text": prompt})
        if prompt == "slow":
            await self.release.wait()

    def pending_approvals(self):
        return self.approvals

    async def cancel(self):
        pass


def setup(tmp_path):
    agent = SuperQodeAcpV2Agent(ledger_path=tmp_path / "ledger.sqlite")
    agent.connection = Connection()
    harness = Harness()
    spec = coding_template()
    state = _AcpSessionState(harness, spec, "test", "test-model", tmp_path)
    agent.live["s"] = LiveSession(state)
    agent.registry.get("s").background = []
    agent.ledger.create(
        "s",
        str(tmp_path),
        {"spec": harness_spec_to_dict(spec), "provider": "test", "model": "test-model"},
    )
    return agent, harness


def prompt(text, key):
    return {"sessionId": "s", "prompt": [{"type": "text", "text": text}], "idempotencyKey": key}


async def test_held_prompts_coalesce_and_insert_in_receive_order(tmp_path):
    agent, harness = setup(tmp_path)
    try:
        await agent.handle("session/prompt", prompt("slow", "one"))
        await harness.started.wait()
        second = asyncio.create_task(agent.handle("session/prompt", prompt("second", "two")))
        duplicate = asyncio.create_task(agent.handle("session/prompt", prompt("second", "two")))
        third = asyncio.create_task(agent.handle("session/prompt", prompt("third", "three")))
        await asyncio.sleep(0)
        assert not second.done() and len(agent.live["s"].queue) == 2
        harness.release.set()
        assert await second == await duplicate
        await third
        await agent.live["s"].runner
        assert harness.inputs == ["slow", "second", "third"]
        users = [u for u in agent.ledger.history("s") if u["sessionUpdate"] == "user_message"]
        assert len(users) == 3
    finally:
        await agent.shutdown()


async def test_cancel_before_execution_coroutine_starts_reports_completion(tmp_path):
    agent, harness = setup(tmp_path)
    notify = agent.connection.notify

    async def cancel_before_start(method, **params):
        await notify(method, **params)
        if params.get("update", {}).get("state") == "running":
            asyncio.get_running_loop().call_soon(lambda: agent.live["s"].work.cancel())

    agent.connection.notify = cancel_before_start
    try:
        result = await agent.handle("session/prompt", prompt("work", "one"))
        await asyncio.wait_for(agent.live["s"].runner, 2)
        assert result["messageId"] == agent.ledger.lookup("s", "one")["messageId"]
        assert not harness.inputs
        assert agent.registry.get("s").state == "idle"
        assert agent.registry.get("s").stop_reason == "cancelled"
    finally:
        await agent.shutdown()


async def test_cancel_drops_all_held_copies_and_closes_active_work(tmp_path):
    agent, harness = setup(tmp_path)
    try:
        await agent.handle("session/prompt", prompt("slow", "one"))
        await harness.started.wait()
        second = asyncio.create_task(agent.handle("session/prompt", prompt("held", "two")))
        duplicate = asyncio.create_task(agent.handle("session/prompt", prompt("held", "two")))
        await asyncio.sleep(0)
        await agent.handle("session/close", {"sessionId": "s"})
        for task in [second, duplicate]:
            with pytest.raises(ProtocolError) as error:
                await task
            assert error.value.code == -32800
        assert harness.inputs == ["slow"]
        assert agent.registry.get("s").state == "idle"
        assert agent.registry.get("s").stop_reason == "cancelled"
        with pytest.raises(ProtocolError) as error:
            await agent.handle("session/prompt", prompt("new", "three"))
        assert error.value.code == -32002
    finally:
        await agent.shutdown()


async def test_close_cancels_permission_wait_before_response(tmp_path):
    agent, harness = setup(tmp_path)
    harness.approvals = [{"tool_name": "write", "arguments": {"path": "x"}}]
    try:
        await agent.handle("session/prompt", prompt("approval", "one"))
        await asyncio.wait_for(agent.connection.approval.wait(), 2)
        await agent.handle("session/close", {"sessionId": "s"})
        assert agent.connection.approval_cancelled
        assert agent.registry.get("s").stop_reason == "cancelled"
    finally:
        await agent.shutdown()


@pytest.mark.parametrize("closing", [False, True])
async def test_later_prompt_during_backend_cancellation_is_serialized(tmp_path, closing):
    agent, harness = setup(tmp_path)
    cancelling, release = asyncio.Event(), asyncio.Event()

    async def slow_cancel():
        cancelling.set()
        await release.wait()

    harness.cancel = slow_cancel
    try:
        await agent.handle("session/prompt", prompt("slow", "one"))
        await harness.started.wait()
        method = "session/close" if closing else "session/cancel"
        stop = asyncio.create_task(agent.handle(method, {"sessionId": "s"}))
        await asyncio.wait_for(cancelling.wait(), 2)
        later = asyncio.create_task(agent.handle("session/prompt", prompt("later", "two")))
        await asyncio.sleep(0)
        if closing:
            with pytest.raises(ProtocolError) as error:
                await later
            assert error.value.code == -32002
        else:
            assert not later.done()
        assert harness.inputs == ["slow"]
        release.set()
        await stop
        if not closing:
            await later
            await agent.live["s"].runner
            assert harness.inputs == ["slow", "later"]
    finally:
        release.set()
        await agent.shutdown()


async def test_foreground_cancel_preserves_background_and_item_cancel_is_scoped(tmp_path):
    agent, harness = setup(tmp_path)
    try:
        first = asyncio.create_task(asyncio.Event().wait())
        second = asyncio.create_task(asyncio.Event().wait())
        await agent.register_background("s", "one", first)
        await agent.register_background("s", "two", second, terminal=True)
        await agent.handle("session/cancel", {"sessionId": "s"})
        assert not first.done() and not second.done()
        await agent.handle("tool_call/cancel", {"sessionId": "s", "toolCallId": "one"})
        assert first.cancelled() and not second.done()
        assert agent.registry.get("s").background == [{"type": "terminal", "terminalId": "two"}]
        await agent.handle("session/close", {"sessionId": "s"})
        assert second.cancelled()
    finally:
        await agent.shutdown()


async def test_empty_replay_and_resume_snapshot_order(tmp_path):
    agent, harness = setup(tmp_path)
    try:
        await agent.resume(
            {"sessionId": "s", "cwd": str(tmp_path), "replayFrom": {"type": "start"}}
        )
        kinds = [data["update"]["sessionUpdate"] for _, data in agent.connection.events]
        assert kinds == ["replay_complete", "state_update", "session_info_update"]
        agent.connection.events.clear()
        await agent.resume({"sessionId": "s", "cwd": str(tmp_path)})
        assert [data["update"]["sessionUpdate"] for _, data in agent.connection.events] == [
            "state_update",
            "session_info_update",
        ]
    finally:
        await agent.shutdown()


async def test_invalid_inputs_and_unadvertised_operations_do_not_insert(tmp_path):
    agent, harness = setup(tmp_path)
    try:
        bad = [
            prompt("text", ""),
            {"sessionId": "s", "prompt": []},
            {"sessionId": "s", "prompt": [{"type": "image", "data": "x", "mimeType": "image/png"}]},
        ]
        for params in bad:
            with pytest.raises(ProtocolError) as error:
                await agent.handle("session/prompt", params)
            assert error.value.code == -32602
        with pytest.raises(ProtocolError) as error:
            await agent.handle("session/set_mode", {"sessionId": "s", "modeId": "x"})
        assert error.value.code == -32601
        assert agent.ledger.history("s") == []
    finally:
        await agent.shutdown()


async def test_nested_children_replay_and_close_preserve_immediate_ownership(tmp_path):
    agent, _ = setup(tmp_path)
    try:
        await agent.subagent_event("s", "subagent_start", {"agent_id": "parent"})
        await agent.subagent_event(
            "s", "subagent_start", {"agent_id": "nested", "parent_id": "parent"}
        )
        parent = agent.child_ids["s", "parent"]
        child = agent.child_ids["s", "nested"]
        assert agent.registry.get(child).parent_id == parent
        assert child not in agent.registry.get("s").children
        await agent.subagent_event("s", "subagent_result", {"agent_id": "parent", "result": "done"})
        assert agent.registry.get(parent).state == "idle"
        assert agent.registry.get("s").background == [{"type": "subagent", "sessionId": parent}]
        assert agent.registry.get(parent).background == [{"type": "subagent", "sessionId": child}]
        await agent.handle("session/close", {"sessionId": "s"})
        assert agent.registry.get(parent).state == agent.registry.get(child).state == "idle"
        agent.connection.events.clear()
        await agent.resume(
            {"sessionId": "s", "cwd": str(tmp_path), "replayFrom": {"type": "start"}}
        )
        markers = [
            p["sessionId"]
            for _, p in agent.connection.events
            if p["update"]["sessionUpdate"] == "replay_complete"
        ]
        assert markers == [child, parent, "s"]
        for method in ["session/prompt", "session/close"]:
            params = (
                prompt("no", "child") | {"sessionId": child}
                if method.endswith("prompt")
                else {"sessionId": child}
            )
            with pytest.raises(ProtocolError):
                await agent.handle(method, params)
    finally:
        await agent.shutdown()
