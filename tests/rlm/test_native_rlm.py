"""Contract tests for SuperQode's native one-tool RLM harness."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from superqode.harness import list_harnesses, resolve_harness
from superqode.harness.discovery import load_harness_adapter
from superqode.harness.backends.registry import (
    create_harness_backend,
    known_harness_backend_names,
)
from superqode.harness.pipy_adapter import translate_event
from superqode.harness.protocol import HarnessCreateRequest, HarnessMessage
from superqode.harness.rlm_adapter import RLMHarnessProtocolAdapter
from superqode.harness.templates import rlm_template
from superqode.pipy import ToolCall, ToolResultMessage
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.coding_session import CodingSessionOptions
from superqode.pipy.events import AgentStartEvent
from superqode.pipy.stream import Model
from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
from superqode.rlm.kernel import PersistentPythonKernel
from superqode.rlm.policy import RLMPolicy, RLMPolicyStore, run_completion_gates
from superqode.rlm.supervisor import AgentRecord, AgentSupervisor
from superqode.rlm.worker_process import run_durable_child
from superqode.rlm.worker import _watch_control, run_worker

MODEL = Model(id="fake-rlm", provider="fake", api="fake-api")


def _options(tmp_path: Path, script=()) -> CodingSessionOptions:
    return CodingSessionOptions(
        cwd=tmp_path,
        model=MODEL,
        stream_fn=FakeStream(list(script)),
        session_root=tmp_path / ".rlm-sessions",
    )


def _factory(script, session_root: Path):
    async def factory(request, working_directory, session_path):
        options = CodingSessionOptions(
            cwd=working_directory,
            model=MODEL,
            stream_fn=FakeStream(list(script)),
            session_root=session_root,
        )
        if session_path and Path(session_path).is_file():
            return await RLMCodingSession.resume(options, session_path=session_path)
        return await RLMCodingSession.create(options)

    return factory


def test_rlm_is_a_first_class_selectable_harness(tmp_path):
    entries = {entry.id: entry for entry in list_harnesses(tmp_path)}

    assert entries["rlm"].display_name == "RLM"
    assert entries["rlm"].runtime == "rlm"
    assert entries["rlm"].tools == ("python",)
    assert entries["rlm"].recommended is True
    assert entries["rlm"].continuity == "context-replay"
    assert resolve_harness("rlm-native", root=tmp_path).id == "rlm"


def test_template_declares_exactly_one_model_tool():
    spec = rlm_template()

    assert spec.agents[0].tools == ("python",)
    assert spec.metadata["model_tool_count"] == 1
    assert spec.metadata["persistent_python"] is True
    assert spec.metadata["durable_children"] is True
    assert spec.runtime.config["durable_children"] is True
    assert spec.execution_policy.sandbox == "none"
    assert spec.metadata["pure_permissions"] is True


def test_backend_is_registered_without_prime_or_rlm_code_dependency():
    assert "rlm" in known_harness_backend_names()
    backend = create_harness_backend("rlm")

    assert backend.name == "rlm"
    assert backend.capabilities.event_detail == "rich"
    assert backend.capabilities.supports_streaming is True


def test_protocol_discovery_uses_the_native_rlm_adapter():
    descriptor = load_harness_adapter("rlm").descriptor

    assert descriptor.name == "RLM"
    assert descriptor.capabilities.steer is True
    assert descriptor.capabilities.cancel is True
    assert descriptor.capabilities.checkpoint is True
    assert descriptor.metadata["tools"] == ["python"]
    assert descriptor.metadata["durable_children"] is True


async def test_kernel_preserves_python_state(tmp_path):
    kernel = PersistentPythonKernel(tmp_path)

    assigned = await kernel.execute("value = 40")
    computed = await kernel.execute("value + 2")

    assert assigned.error is None
    assert computed.text == "42"


async def test_kernel_restores_serializable_state_after_process_boundary(tmp_path):
    checkpoint = tmp_path / "session.kernel.pkl"
    first = PersistentPythonKernel(tmp_path, checkpoint_path=checkpoint)

    await first.execute("answer = {'value': 42}\nimport threading\nlock = threading.Lock()")
    second = PersistentPythonKernel(tmp_path, checkpoint_path=checkpoint)

    restored = await second.execute("answer['value']")
    assert restored.text == "42"
    assert "answer" in second.restored_names
    assert "lock" not in second.restored_names
    assert "workspace" not in second.restored_names


async def test_kernel_ignores_a_corrupt_checkpoint(tmp_path):
    checkpoint = tmp_path / "session.kernel.pkl"
    checkpoint.write_bytes(b"not a pickle")

    kernel = PersistentPythonKernel(tmp_path, checkpoint_path=checkpoint)

    assert kernel.restored_names == ()
    assert (await kernel.execute("6 * 7")).text == "42"


async def test_kernel_checkpoints_state_mutated_before_an_execution_error(tmp_path):
    checkpoint = tmp_path / "session.kernel.pkl"
    first = PersistentPythonKernel(tmp_path, checkpoint_path=checkpoint)

    failed = await first.execute("kept = 42\nraise RuntimeError('later failure')")
    second = PersistentPythonKernel(tmp_path, checkpoint_path=checkpoint)

    assert "later failure" in str(failed.error)
    assert (await second.execute("kept")).text == "42"


async def test_python_namespace_can_read_edit_and_run_commands(tmp_path):
    (tmp_path / "answer.txt").write_text("before\n")
    kernel = PersistentPythonKernel(tmp_path)

    read = await kernel.execute("workspace.read('answer.txt')")
    edited = await kernel.execute("workspace.edit('answer.txt', 'before', 'after')")
    command = await kernel.execute("shell.run(['pwd']).ok")

    assert read.text == "'before'"
    assert "edited answer.txt" in edited.text
    assert (tmp_path / "answer.txt").read_text() == "after\n"
    assert command.text == "True"


async def test_session_advertises_only_python_and_executes_it(tmp_path):
    stream = FakeStream(
        [
            tool_response(ToolCall(id="p1", name="python", arguments={"code": "x = 40"})),
            tool_response(ToolCall(id="p2", name="python", arguments={"code": "x + 2"})),
            text_response("done"),
        ]
    )
    session = await RLMCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=stream,
            session_root=tmp_path / ".rlm-sessions",
        )
    )

    await session.prompt("compute the answer")

    assert [tool.name for tool in session.tools] == ["python"]
    assert all([tool.name for tool in call.tools or []] == ["python"] for call in stream.calls)
    assert "exactly one executable tool: python" in stream.calls[0].system_prompt
    context = await session.session.build_context()
    results = [message for message in context.messages if isinstance(message, ToolResultMessage)]
    assert results[-1].text == "42"


async def test_adapter_streams_rlm_runtime_events(tmp_path):
    adapter = RLMHarnessProtocolAdapter(
        session_factory=_factory([text_response("hello")], tmp_path / "sessions")
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="rlm", working_directory=tmp_path))

    events = [event async for event in adapter.send(ref, HarnessMessage("user", "hi"))]

    assert ref.metadata["model_tools"] == ["python"]
    assert events[0].type == "model.requested"
    assert any(event.type == "run_start" and event.data["runtime"] == "rlm" for event in events)
    assert any(event.type == "model_delta" and event.data["text"] == "hello" for event in events)


async def test_adapter_streams_recursive_child_lifecycle(tmp_path):
    script = [
        tool_response(
            ToolCall(
                id="spawn-1",
                name="python",
                arguments={"code": "child = rlm.run('child work'); child.wait()"},
            )
        ),
        text_response("child result"),
        text_response("root result"),
    ]
    adapter = RLMHarnessProtocolAdapter(session_factory=_factory(script, tmp_path / "sessions"))
    ref = await adapter.create(HarnessCreateRequest(harness_id="rlm", working_directory=tmp_path))

    events = [event async for event in adapter.send(ref, HarnessMessage("user", "delegate"))]

    starts = [event for event in events if event.type == "subagent_start"]
    results = [event for event in events if event.type == "subagent_result"]
    assert len(starts) == 1
    assert starts[0].data["parent_id"] == "root"
    assert starts[0].data["prompt"] == "child work"
    assert len(results) == 1
    assert results[0].data["status"] == "completed"
    assert results[0].data["result"] == "child result"


async def test_adapter_retries_until_autonomous_completion_gate_passes(tmp_path):
    adapter = RLMHarnessProtocolAdapter(
        session_factory=_factory(
            [text_response("first attempt"), text_response("second attempt")],
            tmp_path / "sessions",
        )
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="rlm", working_directory=tmp_path))
    marker = tmp_path / "gate-ready"
    session = adapter._sessions[ref.session_id]
    session.update_policy(
        autonomous=True,
        gates=(f"test -f {marker} || (touch {marker}; false)",),
        max_rounds=2,
    )

    events = [event async for event in adapter.send(ref, HarnessMessage("user", "finish it"))]

    assert [
        event.data["passed"] for event in events if event.type == "autonomous_gates_result"
    ] == [
        False,
        True,
    ]
    assert [event.data["text"] for event in events if event.type == "model_delta"] == [
        "first attempt",
        "second attempt",
    ]
    assert not any(event.type == "error" for event in events)


async def test_python_can_spawn_and_wait_for_a_child_rlm_session(tmp_path):
    stream = FakeStream(
        [
            tool_response(
                ToolCall(
                    id="spawn-1",
                    name="python",
                    arguments={"code": "child = rlm.run('inspect the child task'); child.wait()"},
                )
            ),
            text_response("child result"),
            text_response("root result"),
        ]
    )
    session = await RLMCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=stream,
            session_root=tmp_path / ".rlm-sessions",
        )
    )

    result = await session.prompt("delegate this")

    assert result.text == "root result"
    assert len(stream.calls) == 3
    assert all([tool.name for tool in call.tools or []] == ["python"] for call in stream.calls)
    context = await session.session.build_context()
    tool_results = [
        message for message in context.messages if isinstance(message, ToolResultMessage)
    ]
    assert tool_results[-1].text == "'child result'"


async def test_supervisor_tracks_batch_ancestry_results_and_deletion():
    events = []

    async def runner(record):
        await asyncio.sleep(0)
        return f"result:{record.prompt}"

    supervisor = AgentSupervisor(
        asyncio.get_running_loop(),
        runner,
        max_children=3,
        max_parallel=2,
        event_sink=events.append,
    )
    handles = supervisor.spawn_batch(["one", "two"], parent_id="root")

    results = await supervisor.wait_all([handle.id for handle in handles])

    assert results == ["result:one", "result:two"]
    assert {item["parent_id"] for item in supervisor.snapshots()} == {"root"}
    assert {event["type"] for event in events} >= {
        "agent.spawned",
        "agent.started",
        "agent.completed",
    }
    first_id = handles[0].id
    handles[0].delete()
    assert first_id not in {item["id"] for item in supervisor.snapshots()}


async def test_supervisor_queues_messages_until_child_session_attaches():
    release = asyncio.Event()

    class Session:
        def __init__(self):
            self.follow_ups = []
            self.steering = []

        async def info(self):
            return type("Info", (), {"id": "child-session"})()

        async def follow_up(self, message):
            self.follow_ups.append(message)

        async def steer(self, message):
            self.steering.append(message)

    session = Session()

    async def runner(record):
        await supervisor.attach_session(record.id, session)
        await release.wait()
        return "done"

    supervisor = AgentSupervisor(asyncio.get_running_loop(), runner)
    handle = supervisor.spawn("work")
    await supervisor.send(handle.id, "additional context")
    await supervisor.steer(handle.id, "change direction")
    await asyncio.sleep(0)
    release.set()

    assert await supervisor.wait(handle.id) == "done"
    assert session.follow_ups == ["additional context"]
    assert session.steering == ["change direction"]


async def test_supervisor_recovers_completed_children_from_journal(tmp_path):
    journal = tmp_path / "root.agents.jsonl"

    async def runner(record):
        return f"finished:{record.prompt}"

    supervisor = AgentSupervisor(asyncio.get_running_loop(), runner, journal_path=journal)
    handle = supervisor.spawn("inspect recovery")
    assert await supervisor.wait(handle.id) == "finished:inspect recovery"

    recovered = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)

    assert recovered.snapshot(handle.id)["status"] == "completed"
    assert await recovered.wait(handle.id) == "finished:inspect recovery"


async def test_supervisor_marks_active_children_interrupted_after_restart(tmp_path):
    journal = tmp_path / "root.agents.jsonl"
    release = asyncio.Event()

    async def runner(record):
        await release.wait()
        return "late result"

    supervisor = AgentSupervisor(asyncio.get_running_loop(), runner, journal_path=journal)
    handle = supervisor.spawn("long task")
    await asyncio.sleep(0)

    recovered = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)
    snapshot = recovered.snapshot(handle.id)

    assert snapshot["status"] == "interrupted"
    assert "process restart" in snapshot["error"]
    try:
        await recovered.wait(handle.id)
    except RuntimeError as exc:
        assert "process restart" in str(exc)
    else:
        raise AssertionError("Interrupted agents cannot produce a result")

    await supervisor.cancel(handle.id)


async def test_supervisor_reattaches_a_live_detached_worker(tmp_path):
    journal = tmp_path / "root.agents.jsonl"
    control = tmp_path / "control.jsonl"
    result = tmp_path / "result.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"agent_id": "agent-detached", "worker_pid": os.getpid()}),
        encoding="utf-8",
    )
    agent = {
        "id": "agent-detached",
        "prompt": "continue after restart",
        "parent_id": "root",
        "status": "running",
        "created_at": time.time(),
        "started_at": time.time(),
        "worker_pid": os.getpid(),
        "worker_request_path": str(request),
        "worker_result_path": str(result),
        "worker_control_path": str(control),
        "children": [],
    }
    journal.write_text(
        json.dumps({"type": "agent.detached", "timestamp": time.time(), "agent": agent}) + "\n",
        encoding="utf-8",
    )
    supervisor = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)

    async def resume_runner(record):
        assert record.worker_pid == os.getpid()
        return "reattached result"

    supervisor.set_runner(resume_runner)

    assert await supervisor.wait("agent-detached") == "reattached result"
    assert any(event["type"] == "agent.reattached" for event in supervisor.events_since(0)[0])


async def test_supervisor_rejects_a_recycled_worker_pid(tmp_path):
    journal = tmp_path / "root.agents.jsonl"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"agent_id": "some-other-agent", "worker_pid": os.getpid()}),
        encoding="utf-8",
    )
    agent = {
        "id": "agent-original",
        "prompt": "work",
        "parent_id": "root",
        "status": "running",
        "created_at": time.time(),
        "worker_pid": os.getpid(),
        "worker_request_path": str(request),
        "children": [],
    }
    journal.write_text(
        json.dumps({"type": "agent.detached", "timestamp": time.time(), "agent": agent}) + "\n",
        encoding="utf-8",
    )

    recovered = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)

    assert recovered.snapshot("agent-original")["status"] == "interrupted"


def test_zero_depth_disables_child_spawning():
    loop = asyncio.new_event_loop()
    supervisor = AgentSupervisor(loop, max_depth=0)

    try:
        supervisor.spawn("must not start")
    except RuntimeError as error:
        assert "depth limit" in str(error)
    else:
        raise AssertionError("max_depth=0 must disable recursive children")
    finally:
        loop.close()


async def test_durable_worker_preserves_model_override_and_remaining_depth(tmp_path, monkeypatch):
    journal = tmp_path / "root.agents.jsonl"
    supervisor = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal, max_depth=3)
    record = AgentRecord(
        id="agent-worker",
        prompt="work",
        parent_id="root",
        model="openai/gpt-5.2",
        status="running",
    )
    supervisor._records[record.id] = record

    class Process:
        pid = os.getpid()

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return None

    monkeypatch.setattr("superqode.rlm.worker_process.subprocess.Popen", lambda *a, **k: Process())
    monkeypatch.setattr(
        "superqode.rlm.worker_process._read_json",
        lambda path: {
            "status": "completed",
            "result": "worker result",
            "usage": {"total_tokens": 42},
        },
    )
    options = RLMCodingSessionOptions(cwd=tmp_path, model=MODEL)

    assert (
        await run_durable_child(record, options=options, supervisor=supervisor) == "worker result"
    )
    request = json.loads(Path(record.worker_request_path).read_text(encoding="utf-8"))
    assert request["provider"] == "openai"
    assert request["model"] == "gpt-5.2"
    assert request["max_depth"] == 2
    assert record.usage == {"total_tokens": 42}


async def test_worker_entrypoint_writes_atomic_result_and_usage(tmp_path, monkeypatch):
    result_path = tmp_path / "result.json"
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "agent_id": "agent-worker",
                "prompt": "work",
                "cwd": str(tmp_path),
                "provider": "fake",
                "model": "fake-rlm",
                "thinking_level": "off",
                "session_root": str(tmp_path / "sessions"),
                "result_path": str(result_path),
                "control_path": str(tmp_path / "control.jsonl"),
            }
        ),
        encoding="utf-8",
    )

    class Usage:
        input = 10
        output = 5
        cache_read = 0
        cache_write = 0
        total_tokens = 15
        cost = type("Cost", (), {"total": 0.01})()

    class Session:
        async def prompt(self, prompt):
            assert prompt == "work"
            return type("Message", (), {"text": "finished", "usage": Usage()})()

    async def fake_create(cls, options):
        return Session()

    monkeypatch.setattr(RLMCodingSession, "create", classmethod(fake_create))

    assert await run_worker(request_path) == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["result"] == "finished"
    assert result["usage"]["total_tokens"] == 15


async def test_worker_control_stream_delivers_follow_up_steer_and_cancel(tmp_path):
    control = tmp_path / "control.jsonl"
    blocked = asyncio.Event()

    class Session:
        def __init__(self):
            self.messages = []
            self.steering = []
            self.aborted = False

        async def follow_up(self, message):
            self.messages.append(message)

        async def steer(self, message):
            self.steering.append(message)

        async def abort(self):
            self.aborted = True

    async def prompt():
        await blocked.wait()

    session = Session()
    prompt_task = asyncio.create_task(prompt())
    watcher = asyncio.create_task(_watch_control(control, session, prompt_task))
    control.write_text(
        "\n".join(
            json.dumps({"operation": operation, "message": message})
            for operation, message in (
                ("follow_up", "more context"),
                ("steer", "change direction"),
                ("cancel", ""),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    await watcher

    assert session.messages == ["more context"]
    assert session.steering == ["change direction"]
    assert session.aborted is True
    assert prompt_task.cancelled()


async def test_supervisor_recovers_result_written_while_parent_was_detached(tmp_path):
    journal = tmp_path / "root.agents.jsonl"
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps({"status": "completed", "result": "finished elsewhere"}),
        encoding="utf-8",
    )
    agent = {
        "id": "agent-finished",
        "prompt": "work",
        "parent_id": "root",
        "status": "running",
        "created_at": time.time(),
        "worker_pid": 999_999_999,
        "worker_result_path": str(result),
        "children": [],
    }
    journal.write_text(
        json.dumps({"type": "agent.detached", "timestamp": time.time(), "agent": agent}) + "\n",
        encoding="utf-8",
    )

    recovered = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)

    assert await recovered.wait("agent-finished") == "finished elsewhere"


async def test_supervisor_routes_messages_to_detached_worker_control_file(tmp_path):
    journal = tmp_path / "root.agents.jsonl"
    control = tmp_path / "control.jsonl"
    supervisor = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)
    record = AgentRecord(id="agent-worker", prompt="work", parent_id="root", status="running")
    supervisor._records[record.id] = record
    supervisor.mark_worker(
        record.id,
        pid=os.getpid(),
        request_path=tmp_path / "request.json",
        result_path=tmp_path / "result.json",
        control_path=control,
    )

    await supervisor.send(record.id, "more context")
    await supervisor.steer(record.id, "change direction")

    commands = [json.loads(line) for line in control.read_text(encoding="utf-8").splitlines()]
    assert [command["operation"] for command in commands] == ["follow_up", "steer"]


async def test_supervisor_does_not_recover_deleted_children(tmp_path):
    journal = tmp_path / "root.agents.jsonl"

    async def runner(record):
        return "done"

    supervisor = AgentSupervisor(asyncio.get_running_loop(), runner, journal_path=journal)
    parent = supervisor.spawn("parent")
    assert await supervisor.wait(parent.id) == "done"
    child = supervisor.spawn("child", parent_id=parent.id)
    assert await supervisor.wait(child.id) == "done"
    child.delete()

    recovered = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)

    assert {item["id"] for item in recovered.snapshots()} == {parent.id}
    assert recovered.snapshot(parent.id)["children"] == []


def test_supervisor_skips_corrupt_journal_lines(tmp_path):
    journal = tmp_path / "root.agents.jsonl"
    journal.write_text("not-json\n{}\n", encoding="utf-8")

    recovered = AgentSupervisor(asyncio.new_event_loop(), journal_path=journal)

    assert recovered.snapshots() == []
    recovered.loop.close()


async def test_policy_store_persists_validated_goal_and_gates(tmp_path):
    store = RLMPolicyStore(tmp_path / "session.policy.json")
    saved = store.save(
        RLMPolicy(
            goal="Ship native RLM",
            autonomous=True,
            gates=("pytest -q",),
            max_rounds=4,
        )
    )

    assert store.load() == saved
    assert RLMPolicy.from_dict({"max_rounds": 100}).max_rounds == 20


async def test_completion_gates_return_bounded_structured_evidence(tmp_path):
    results = await run_completion_gates(
        ("printf pass", "printf failure >&2; exit 7"),
        cwd=tmp_path,
        timeout=5,
    )

    assert results[0].ok is True
    assert results[0].stdout == "pass"
    assert results[1].ok is False
    assert results[1].returncode == 7
    assert results[1].stderr == "failure"


def test_event_translation_keeps_pipy_default_and_accepts_rlm_runtime():
    event = AgentStartEvent()

    assert translate_event(event)[0].data["runtime"] == "pipy"
    assert translate_event(event, runtime="rlm")[0].data["runtime"] == "rlm"
