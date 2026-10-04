"""Independent wire fixtures and crash/ownership/budget boundaries."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import pickle
import time

import httpx
import pytest

from superqode.a2a.billing import CreditLedger
from superqode.a2a.client import A2AClient, A2AClientError
from superqode.a2a.types import (
    AgentCard,
    Artifact,
    Message,
    MessageRole,
    Part,
    Task,
    TaskStatus,
    TaskStatusValue,
)
from superqode.rlm.delegation import DelegationManager
from superqode.rlm.delegation_policy import DelegationPolicy
from superqode.rlm.delegation_store import DelegationStore
from superqode.rlm.kernel_server import A2AProxy, DelegationProxy, _revive, rebind_delegations


def task(state="working", text=""):
    return Task(
        "remote-1",
        TaskStatus(TaskStatusValue(state)),
        context_id="conversation",
        artifacts=[Artifact([Part(text=text)], "findings", "findings")] if text else [],
    )


class Peer:
    _binding = "JSONRPC"
    _protocol_version = "1.0"
    _interface_url = "https://peer.example/rpc"

    def __init__(self):
        self.sent = []
        self.result = task()
        self.reads = 0
        self.uncertain = False

    async def get_agent_card(self):
        return AgentCard("peer", "", "https://peer.example/rpc", "1")

    async def send_message(self, text, **kwargs):
        self.sent.append((text, kwargs))
        if self.uncertain:
            raise TimeoutError("ack lost")
        return self.result

    async def get_task(self, identifier):
        assert identifier == "remote-1"
        self.reads += 1
        return self.result

    async def cancel_task(self, identifier):
        return self.result  # Cancellation rejection does not invent canceled.

    async def close(self):
        pass


@pytest.fixture
async def manager(tmp_path):
    peer = Peer()
    policy = DelegationPolicy.from_config(
        {
            "enabled": True,
            "peers": [{"name": "reviewer", "url": "https://peer.example"}],
            "poll_seconds": 1,
        }
    )
    instance = DelegationManager(
        root="root-session",
        store=DelegationStore(tmp_path / "state.sqlite"),
        policy=policy,
        client_factory=lambda _: peer,
    )
    yield instance, peer
    await instance.close()


async def test_disabled_and_key_only_routes_do_not_discover_or_reserve(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_API_KEY", "exists")
    peer = Peer()
    instance = DelegationManager(
        root="root",
        store=DelegationStore(tmp_path / "state"),
        policy=DelegationPolicy(),
        client_factory=lambda _: peer,
    )
    with pytest.raises(PermissionError, match="disabled"):
        await instance.start("root", peer="reviewer", task="hello")
    assert not peer.sent and not instance.store.records("root")


async def test_nonblocking_send_stable_identity_and_owner_fencing(manager):
    instance, peer = manager
    handle = await instance.start("child", peer="reviewer", task="review", request_id="tool-1")
    again = await instance.start("child", peer="reviewer", task="review", request_id="tool-1")
    assert handle["id"] == again["id"] and len(peer.sent) == 1
    assert peer.sent[0][1]["nonblocking"] is True
    with pytest.raises(PermissionError):
        instance.snapshot("sibling", handle["id"])
    with pytest.raises(ValueError, match="different work"):
        await instance.start("child", peer="reviewer", task="different", request_id="tool-1")


async def test_lost_ack_and_restart_never_resubmit(manager):
    instance, peer = manager
    peer.uncertain = True
    handle = await instance.start("root", peer="reviewer", task="review", request_id="stable")
    assert instance.snapshot("root", handle["id"])["state"] == "unknown"
    await instance.close()
    fresh = DelegationManager(
        root=instance.root,
        store=DelegationStore(instance.store.path),
        policy=instance.policy,
        client_factory=lambda _: peer,
    )
    await fresh.recover("root")
    again = await fresh.start("root", peer="reviewer", task="review", request_id="stable")
    assert handle["id"] == again["id"] and len(peer.sent) == 1
    assert fresh.completion_errors()
    await fresh.close()


async def test_known_task_recovers_by_read_and_preserves_artifact(manager):
    instance, peer = manager
    handle = await instance.start("root", peer="reviewer", task="review")
    await instance.close()
    peer.result = task("completed", "evidence\n" * 1000)
    fresh = DelegationManager(
        root=instance.root,
        store=DelegationStore(instance.store.path),
        policy=instance.policy,
        client_factory=lambda _: peer,
    )
    await fresh.recover("root")
    result = await fresh.wait("root", handle["id"], timeout=1)
    assert result["state"] == "completed" and len(peer.sent) == 1 and peer.reads
    assert fresh.read("root", handle["id"], "findings", 3, 5) == "dence"
    assert fresh.snapshot("root", handle["id"])["usage"] is None
    assert not fresh.completion_errors()
    await fresh.close()


async def test_direct_message_has_no_invented_remote_task(manager):
    instance, peer = manager
    peer.result = Message(MessageRole.AGENT, [Part(text="direct answer")], "message-id", "ctx")
    value = await instance.start("root", peer="reviewer", task="review")
    assert instance.snapshot("root", value["id"])["task_id"] is None
    assert instance.read("root", value["id"]) == "direct answer"
    assert not instance.completion_errors()


async def test_input_auth_and_unconfirmed_cancel_are_distinct(manager):
    instance, peer = manager
    peer.result = task("auth_required")
    value = await instance.start("root", peer="reviewer", task="review")
    assert (await instance.wait("root", value["id"], 0))["state"] == "auth_required"
    with pytest.raises(ValueError, match="awaiting input"):
        await instance.reply("root", value["id"], "hi")
    cancelled = await instance.cancel("root", value["id"])
    assert cancelled["state"] == "auth_required"
    peer.result = task("input_required")
    await instance.poll("root", value["id"])
    peer.result = task("completed", "clarified")
    await instance.reply("root", value["id"], "extra evidence")
    assert peer.sent[-1][1]["task_id"] == "remote-1"
    new = await instance.follow_up("root", value["id"], "another review")
    assert new["id"] != value["id"] and peer.sent[-1][1]["session_id"] == "conversation"


async def test_wait_timeout_and_optional_work_do_not_assert_cancel(manager):
    instance, peer = manager
    value = await instance.start("root", peer="reviewer", task="review", required=False)
    assert (await instance.wait("root", value["id"], 0))["state"] == "working"
    assert not instance.completion_errors()
    assert len(peer.sent) == 1


def test_hosted_opt_in_validation_and_durable_root_cap(tmp_path):
    raw = {
        "enabled": True,
        "hosted_enabled": True,
        "max_hosted_credits": 3,
        "peers": [
            {
                "name": "paid",
                "url": "https://peer.example",
                "hosted": True,
                "credential_env": "MY_KEY",
                "skill": "review",
                "credits": 2,
            }
        ],
    }
    policy = DelegationPolicy.from_config(raw)
    store = DelegationStore(tmp_path / "state")
    peer = policy.peer("paid")

    def admit(i):
        try:
            return store.admit("root", f"child-{i}", str(i), str(i), policy, peer, {"peer": "paid"})
        except PermissionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(admit, [1, 2]))
    assert sum(v is not None for v in values) == 1
    assert len(DelegationStore(store.path).records("root")) == 1
    raw["hosted_enabled"] = False
    with pytest.raises(PermissionError):
        DelegationPolicy.from_config(raw).peer("paid")
    for value in (
        {"enabled": "false"},
        {"paid_fallback": True},
        {
            "enabled": True,
            "peers": [{"name": "p", "url": "https://peer.example", "token": "secret"}],
        },
    ):
        with pytest.raises(ValueError):
            DelegationPolicy.from_config(value)


def test_account_reservations_are_atomic_across_instances_and_settle_once(tmp_path):
    ledger = CreditLedger(tmp_path / "credits")
    ledger.grant("trial", 3, skills=["review"], expires_at=time.time() + 60, max_parallel=2)

    def reserve(i):
        try:
            return CreditLedger(ledger.path).reserve(
                "trial", str(i), str(i), skill="review", credits=2
            )
        except PermissionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [1, 2]))
    assert sum(v is not None for v in results) == 1
    job = next(v[0]["id"] for v in results if v)
    assert ledger.account("trial")["available"] == 1
    assert ledger.reserve("trial", job, job, skill="review", credits=2)[1] is False
    assert ledger.settle("trial", job, 2)
    assert not CreditLedger(ledger.path).settle("trial", job, 2)
    assert ledger.account("trial")["balance"] == 1
    with pytest.raises(PermissionError):
        ledger.reserve("trial", "new", "new", skill="unentitled", credits=1)
    with pytest.raises(PermissionError):
        ledger.reserve("another", job, job, skill="review", credits=2)


def test_proxies_checkpoint_only_identity_and_rebind():
    calls = []

    def call(name, payload):
        calls.append((name, payload))
        return {"state": "completed"}

    proxy = DelegationProxy(call, "opaque", {"state": "completed"})
    carried = pickle.loads(pickle.dumps(proxy))
    assert carried.id == "opaque" and carried._call is None
    rebind_delegations({"nested": [carried]}, call)
    assert carried.status()["state"] == "completed"
    assert "opaque" in repr(carried)


@pytest.mark.parametrize("version", ["1.0", "0.3"])
async def test_independent_direct_message_wire_fixture(version):
    seen = []

    def respond(request):
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "name": "peer",
                    "url": "https://peer.example",
                    "skills": [],
                    "supportedInterfaces": [
                        {
                            "url": "https://peer.example",
                            "protocolBinding": "JSONRPC",
                            "protocolVersion": version,
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {
                    "messageId": "reply",
                    "role": "ROLE_AGENT" if version == "1.0" else "agent",
                    "parts": [
                        {"text": "answer"},
                        {"url": "https://peer.example/file", "filename": "report"},
                    ],
                    "contextId": "ctx",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = A2AClient("https://peer.example", http_client=http)
        response = await client.send_message("hello", message_id="stable", nonblocking=True)
        assert isinstance(response, Message) and response.parts[0].text == "answer"
        assert response.parts[1].file.url.endswith("/file")
        payload = json.loads(seen[-1].content)["params"]
        assert payload["message"]["messageId"] == "stable"
        assert payload["configuration"] == {
            "acceptedOutputModes": ["text/plain"],
            **({"returnImmediately": True} if version == "1.0" else {"blocking": False}),
        }


async def test_multiline_sse_normalizes_artifact_status_and_protocol_errors():
    text = 'data: {"jsonrpc":"2.0","result":{"statusUpdate":\ndata: {"taskId":"t","status":{"state":"TASK_STATE_AUTH_REQUIRED"}}}}\n\n'
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=text))
    ) as http:
        response = await http.get("https://peer.example")
        client = A2AClient("https://peer.example", http_client=http)
        events = [e async for e in client._events(response)]
        assert (
            events[0].type == "status_update"
            and events[0].data["status"].state == TaskStatusValue.AUTH_REQUIRED
        )
        assert (
            client._parse_event({"jsonrpc": "2.0", "error": {"code": -1, "message": "bad"}}).type
            == "error"
        )
        with pytest.raises(A2AClientError, match="Unknown"):
            client._parse_task({"id": "x", "status": {"state": "alien"}})
        old = client._parse_task(
            {
                "id": "x",
                "status": {"state": "input-required"},
                "artifacts": [
                    {
                        "artifactId": "a",
                        "parts": [{"kind": "file", "file": {"bytes": "YWJj", "name": "a"}}],
                    }
                ],
            }
        )
        assert (
            old.status.state == TaskStatusValue.INPUT_REQUIRED
            and old.artifacts[0].parts[0].file.raw == "YWJj"
        )


async def test_credentialed_peer_cannot_retarget_card_origin():
    def respond(_):
        return httpx.Response(
            200, json={"name": "peer", "url": "https://evil.example", "skills": []}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = A2AClient(
            "https://peer.example", http_client=http, bearer_token="private", strict_origin=True
        )
        with pytest.raises(A2AClientError, match="origin"):
            await client.get_agent_card()


@pytest.mark.parametrize("profile", ["host", "monty"])
async def test_native_one_tool_selects_context_and_delegates(profile, tmp_path, monkeypatch):
    from superqode.pipy.ai import FakeStream, text_response, tool_response
    from superqode.pipy import ToolCall
    from superqode.pipy.stream import Model
    from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
    from superqode.rlm.sandbox import RLMSandboxConfig

    peer = Peer()
    peer.result = Message(role=MessageRole.AGENT, parts=[Part(text="finding at evidence.txt:1")])
    monkeypatch.setattr(DelegationManager, "_client", lambda self, selected: peer)
    (tmp_path / "evidence.txt").write_text("PLANTED DEFECT\n")
    (tmp_path / "noise.txt").write_text("irrelevant\n" * 10000)
    code = 'selected = context.read("evidence.txt")\nreview = a2a.start(peer="review", task="Review selected evidence", context=selected, request_id="stable-review")\nreview.read(size=100)'
    stream = FakeStream(
        [
            tool_response(ToolCall("py", "python", {"code": code})),
            text_response("Reviewed the selected evidence."),
        ]
    )
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            session_root=tmp_path / "sessions",
            model=Model(id="fake", provider="fake"),
            stream_fn=stream,
            sandbox=RLMSandboxConfig.from_config({"sandbox": profile}),
            a2a_config={
                "enabled": True,
                "peers": [{"name": "review", "url": "https://peer.example"}],
            },
        )
    )
    try:
        response = await session.prompt("Audit evidence")
        assert response.text == "Reviewed the selected evidence."
        assert [t.name for t in session.harness.get_tools()] == ["python"]
        assert len(peer.sent) == 1 and "PLANTED DEFECT" in peer.sent[0][0]
        assert "irrelevant" not in peer.sent[0][0]
        assert not session.delegation_manager.completion_errors()
        assert session.delegation_manager.evidence()[0]["usage"] is None
        if profile == "monty":
            reference = await session.sandbox_backend.checkpoint("root")
            assert reference.ok
    finally:
        await session.delegation_manager.close()
        if session.sandbox_backend:
            await session.sandbox_backend.close()


async def test_required_remote_work_blocks_protocol_completion(tmp_path, monkeypatch):
    from superqode.pipy.ai import FakeStream, text_response, tool_response
    from superqode.pipy import ToolCall
    from superqode.pipy.stream import Model
    from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
    from superqode.harness.rlm_adapter import RLMHarnessProtocolAdapter
    from superqode.harness.protocol import HarnessCreateRequest, HarnessMessage

    peer = Peer()
    peer.result = task("working")
    monkeypatch.setattr(DelegationManager, "_client", lambda self, selected: peer)

    async def factory(request, cwd, path):
        return await RLMCodingSession.create(
            RLMCodingSessionOptions(
                cwd=cwd,
                session_root=tmp_path / "sessions",
                model=Model(id="fake", provider="fake"),
                stream_fn=FakeStream(
                    [
                        tool_response(
                            ToolCall(
                                "py",
                                "python",
                                {"code": 'a2a.start("review", "Review", request_id="r")'},
                            )
                        ),
                        text_response("done"),
                    ]
                ),
                a2a_config={
                    "enabled": True,
                    "peers": [{"name": "review", "url": "https://peer.example"}],
                },
            )
        )

    adapter = RLMHarnessProtocolAdapter(session_factory=factory)
    ref = await adapter.create(HarnessCreateRequest(harness_id="rlm", working_directory=tmp_path))
    try:
        events = [e async for e in adapter.send(ref, HarnessMessage("user", "audit"))]
        assert events[-1].type == "run.failed"
        assert not any(e.type in {"run.completed", "run_end"} for e in events)
        assert any(e.type == "artifact.created" for e in events)
    finally:
        await adapter.close(ref)


def test_mailbox_is_scoped_retained_and_idempotent(tmp_path):
    from superqode.rlm.mailbox import AgentMailbox

    store = DelegationStore(tmp_path / "state.sqlite3")
    box = AgentMailbox(store, "root-a")
    box.register("root")
    box.register("child", "root")
    box.register("sibling", "root")
    box.send("child", "root", "report", "delivery-1")
    box.send("child", "root", "report", "delivery-1")
    recovered = AgentMailbox(DelegationStore(store.path), "root-a")
    assert len(recovered.read("root")) == 1
    assert recovered.parent("child") == "root"
    with pytest.raises(PermissionError):
        recovered.acknowledge("sibling", "delivery-1")
    recovered.acknowledge("root", "delivery-1")
    assert recovered.read("root") == []
    recovered.send("child", "root", "report", "delivery-1")
    assert recovered.read("root") == []
    with pytest.raises(PermissionError):
        AgentMailbox(store, "root-b").send("child", "root", "wrong root")


async def test_root_semantic_quota_survives_children_and_restart(tmp_path):
    from superqode.rlm.subcall_ledger import SubcallLedger
    from superqode.rlm.subcalls import SubcallPolicy, SubcallExecutor, SubcallLimitError
    from superqode.pipy.ai import FakeStream, text_response
    from superqode.pipy.stream import Model

    path = tmp_path / "calls.sqlite3"

    def executor():
        return SubcallExecutor(
            model=Model(id="fake", provider="fake"),
            stream_fn=FakeStream([text_response("bounded answer")]),
            policy=SubcallPolicy(max_calls=1),
            ledger=SubcallLedger(path, "root"),
        )

    root, child = executor(), executor()
    assert (await root.query("selected context")).ok
    with pytest.raises(SubcallLimitError):
        await child.query("must not get a new allowance")
    with pytest.raises(SubcallLimitError):
        await executor().query("restart must not refresh allowance")
    assert root.snapshot()["root_usage"]["calls"] == 1


async def test_monty_timeout_revokes_late_callback_admission(tmp_path):
    from dataclasses import replace
    import asyncio
    from superqode.rlm.capabilities import check_admission
    from superqode.rlm.kernel_monty import MontyKernelBackend
    from superqode.rlm.sandbox import RLMSandboxConfig

    admitted = []

    async def host(name, payload):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
        check_admission()
        admitted.append(name)
        return []

    backend = MontyKernelBackend(
        tmp_path,
        config=replace(RLMSandboxConfig.from_config({"sandbox": "monty"}), python_timeout=0.1),
        session_id="timeout",
        state_dir=tmp_path / "state",
        host_call=host,
    )
    try:
        result = await backend.execute("root", "a2a.peers()")
        assert result.error
        await asyncio.sleep(0.2)
        assert admitted == []
        assert not backend._checkouts and not backend._sessions
        fresh = await backend.execute("new", "1 + 1")
        assert fresh.value_repr == "2"
    finally:
        await backend.close()


async def test_result_body_limit_is_enforced_before_parsing():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 10000))
    ) as http:
        client = A2AClient("https://peer.example", http_client=http, max_response_bytes=100)
        with pytest.raises(A2AClientError, match="size"):
            await client.get_agent_card()


async def test_docker_portable_kernel_uses_host_delegation_and_retains_opaque_handles(
    tmp_path, manager
):
    import asyncio
    from superqode.rlm.kernel_server import SandboxKernel

    instance, peer = manager
    peer.result = Message(role=MessageRole.AGENT, parts=[Part(text="artifact-only finding")])
    loop = asyncio.get_running_loop()

    class Channel:
        def send(self, message):
            value = asyncio.run_coroutine_threadsafe(
                instance.dispatch("root", message["name"], message["payload"]), loop
            ).result(5)
            self.response = {
                "type": "call_result",
                "call_id": message["call_id"],
                "ok": True,
                "value": value,
            }

        def receive(self):
            return self.response

    kernel = SandboxKernel(Channel(), tmp_path, "root")
    result = await asyncio.to_thread(
        kernel.execute,
        'review = a2a.start("reviewer", "inspect", request_id="docker-one")\nreview.read(size=20)',
    )
    assert not result["error"] and "artifact-only" in result["value_repr"]
    path = tmp_path / "isolated-state.pkl"
    await asyncio.to_thread(kernel.checkpoint, path)
    fresh = SandboxKernel(Channel(), tmp_path, "root")
    await asyncio.to_thread(fresh.restore, path)
    result = await asyncio.to_thread(fresh.execute, "review.read(size=20)")
    assert not result["error"] and len(peer.sent) == 1


async def test_fragmented_artifact_stream_preserves_append_and_chunk_flags():
    class Fragmented(httpx.AsyncByteStream):
        async def __aiter__(self):
            data = b'data: {"jsonrpc":"2.0","result":{"artifactUpdate":{"taskId":"t","artifact":{"artifactId":"a","parts":[{"text":"first"}]},"append":false,"lastChunk":false}}}\n\ndata: {"jsonrpc":"2.0","result":{"artifactUpdate":{"taskId":"t","artifact":{"artifactId":"a","parts":[{"text":"second"}]},"append":true,"lastChunk":true}}}\n\n'
            for i in range(0, len(data), 7):
                yield data[i : i + 7]

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Fragmented()))
    ) as http:
        client = A2AClient("https://peer.example", http_client=http)
        async with http.stream("GET", "https://peer.example") as response:
            events = [event async for event in client._events(response)]
    assert [event.type for event in events] == ["artifact_update", "artifact_update"]
    assert events[0].data["append"] is False
    assert (
        events[1].data["lastChunk"] is True and events[1].data["artifact"].parts[0].text == "second"
    )


async def test_completed_child_continuation_preserves_original_run(tmp_path):
    import asyncio
    from superqode.rlm.supervisor import AgentSupervisor
    from superqode.rlm.mailbox import AgentMailbox

    calls = []

    async def run(record):
        calls.append((record.id, record.resume_path))
        record.session_path = str(tmp_path / "retained.jsonl")
        return record.prompt

    supervisor = AgentSupervisor(
        asyncio.get_running_loop(), run, journal_path=tmp_path / "agents.jsonl"
    )
    supervisor.mailbox = AgentMailbox(DelegationStore(tmp_path / "state.sqlite3"), "root")
    supervisor.mailbox.register("root")
    original = supervisor.spawn("first")
    assert await supervisor.wait(original.id) == "first"
    continuation = supervisor.follow_up(original.id, "second")
    assert await supervisor.wait(continuation.id) == "second"
    assert supervisor.snapshot(original.id)["result"] == "first"
    assert supervisor.snapshot(original.id)["status"] == "completed"
    assert supervisor.snapshot(continuation.id)["continuation_of"] == original.id
    assert calls[-1][1].endswith("retained.jsonl")
    supervisor.mailbox.send("root", original.id, "retained after completion", "delivery")
    assert len(supervisor.mailbox.read(original.id)) == 1


async def test_monty_restore_refuses_changed_resource_policy(tmp_path):
    from dataclasses import replace
    from superqode.rlm.kernel_monty import MontyKernelBackend
    from superqode.rlm.sandbox import RLMSandboxConfig

    config = RLMSandboxConfig.from_config({"sandbox": "monty"})
    original = MontyKernelBackend(
        tmp_path, config=config, session_id="old", state_dir=tmp_path / "state"
    )
    changed = MontyKernelBackend(
        tmp_path,
        config=replace(config, monty_memory_bytes=config.monty_memory_bytes // 2),
        session_id="new",
        state_dir=tmp_path / "new",
    )
    try:
        await original.execute("root", "carried = 1")
        reference = await original.checkpoint("root")
        with pytest.raises(ValueError, match="resource policy"):
            await changed.restore("root", reference)
        assert not changed._checkouts
    finally:
        await original.close()
        await changed.close()


async def test_monty_completed_feed_restores_automatically_without_repeating_admission(tmp_path):
    from superqode.rlm.kernel_monty import MontyKernelBackend
    from superqode.rlm.sandbox import RLMSandboxConfig

    config = RLMSandboxConfig.from_config({"sandbox": "monty"})

    def backend():
        return MontyKernelBackend(
            tmp_path, config=config, session_id="persistent", state_dir=tmp_path / "state"
        )

    original = backend()
    try:
        result = await original.execute("root", "carried = 73")
        assert not result.error
    finally:
        await original.close()
    fresh = backend()
    try:
        result = await fresh.execute("root", "carried + 1")
        assert not result.error and result.value_repr == "74"
    finally:
        await fresh.close()


async def test_real_monty_child_continuation_keeps_heap_and_retained_inbox(tmp_path):
    from superqode.pipy.ai import FakeStream, tool_response, text_response
    from superqode.pipy import ToolCall
    from superqode.pipy.stream import Model
    from superqode.rlm.coding_session import (
        RLMCodingSession,
        RLMCodingSessionOptions,
        supervisor_for_session,
    )
    from superqode.rlm.sandbox import RLMSandboxConfig

    stream = FakeStream(
        [
            tool_response(ToolCall("py1", "python", {"code": "carried = 42"})),
            text_response("first result"),
            tool_response(
                ToolCall(
                    "py2",
                    "python",
                    {
                        "code": 'assert carried == 42\nassert rlm.inbox()[0]["message"] == "retained message"\nrlm.ack_inbox(rlm.inbox()[0]["id"])'
                    },
                )
            ),
            text_response("continued result"),
        ]
    )
    root = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            session_root=tmp_path / "sessions",
            model=Model(id="fake", provider="fake"),
            stream_fn=stream,
            durable_children=False,
            sandbox=RLMSandboxConfig.from_config({"sandbox": "monty"}),
        )
    )
    supervisor = supervisor_for_session(root.session_path)
    original = supervisor.spawn("first")
    assert await supervisor.wait(original.id) == "first result"
    supervisor.mailbox.send("root", original.id, "retained message", "retained-delivery")
    continuation = supervisor.follow_up(original.id, "continue")
    assert await supervisor.wait(continuation.id) == "continued result"
    assert supervisor.snapshot(original.id)["result"] == "first result"
    assert supervisor.mailbox.read(original.id) == []
    for context in stream.calls:
        for message in context.messages:
            if getattr(message, "role", "") == "toolResult":
                assert not getattr(message, "is_error", False)
    await root.delegation_manager.close()


async def test_bounded_peer_refuses_compression_before_body_consumption():
    class Unreadable(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("compressed response must not be consumed")
            yield b""

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Unreadable())
        )
    ) as http:
        client = A2AClient("https://peer.example", http_client=http, strict_origin=True)
        with pytest.raises(A2AClientError, match="Compressed"):
            await client.get_agent_card()
