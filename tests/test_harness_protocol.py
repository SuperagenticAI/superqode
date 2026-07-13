"""Harness Protocol v1 contracts, adapters, persistence, and conformance."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from superqode.agent.loop import AgentResponse
from superqode.harness import (
    ACPHarnessProtocolAdapter,
    CoreHarnessProtocolAdapter,
    DirectPythonHarnessAdapter,
    FileHarnessStore,
    HarnessBackendResult,
    HarnessCapabilityError,
    HarnessCreateRequest,
    HarnessEvent,
    HarnessMessage,
    HarnessProtocolController,
    MemoryHarnessStore,
    PythonHarnessResult,
    SQLiteHarnessStore,
    get_harness_template,
    run_harness_conformance,
)
from superqode.main import cli_main


class FakeCoreBackend:
    name = "fake-core"

    async def run(self, request):
        return HarnessBackendResult(
            response=AgentResponse(
                content=f"core:{request.prompt}",
                messages=[],
                tool_calls_made=0,
                iterations=1,
                stopped_reason="complete",
                input_tokens=4,
                output_tokens=2,
                total_tokens=6,
            ),
            backend=self.name,
            runtime="fake",
            metadata={
                "events": [
                    HarnessEvent(type="model_request", data={"runtime": "fake"}),
                    HarnessEvent(
                        type="tool_call",
                        data={"tool_name": "read_file", "arguments": {"path": "README.md"}},
                    ),
                    HarnessEvent(
                        type="tool_result",
                        data={"tool_name": "read_file", "success": True},
                    ),
                ]
            },
        )


class FakeACPClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.external_session_id = kwargs.get("resume_session_id") or "external-acp-session"
        self.stopped = False

    async def start(self):
        return True

    async def stop(self):
        self.stopped = True

    async def send_prompt(self, prompt):
        await self.kwargs["on_thinking"]("checking")
        await self.kwargs["on_tool_call"](
            {"toolCallId": "tool-1", "title": "read", "status": "in_progress"}
        )
        await self.kwargs["on_tool_update"](
            {"toolCallId": "tool-1", "title": "read", "status": "completed"}
        )
        await self.kwargs["on_message"](f"acp:{prompt}")
        return "end_turn"

    async def cancel(self):
        return True

    def get_session_id(self):
        return self.external_session_id

    def supports_resume(self):
        return True

    def get_message_buffer(self):
        return "acp:hello"

    def get_stats(self):
        return SimpleNamespace(
            prompt_tokens=3,
            completion_tokens=2,
            thinking_tokens=1,
            cost=0.01,
            tool_count=1,
            files_modified=[],
            files_read=["README.md"],
        )


class FakeHarnessEntryPoint:
    def __init__(self, name, value, *, target=None, error=None):
        self.name = name
        self.value = value
        self._target = target
        self._error = error
        self.dist = SimpleNamespace(name=f"example-{name}")

    def load(self):
        if self._error is not None:
            raise self._error
        return self._target


@pytest.mark.parametrize(
    "store_factory",
    [MemoryHarnessStore, FileHarnessStore, SQLiteHarnessStore],
)
def test_protocol_event_envelope_is_persisted_by_every_store(tmp_path, store_factory):
    if store_factory is MemoryHarnessStore:
        store = store_factory()
    elif store_factory is FileHarnessStore:
        store = store_factory(tmp_path / "events")
    else:
        store = store_factory(tmp_path / "events.sqlite3")
    spec = get_harness_template("coding")
    store.open_session("protocol-session", spec)
    run = store.start_run(
        session_id="protocol-session",
        spec=spec,
        provider="test",
        model="model",
        runtime="test",
        prompt="hello",
    )
    first = store.append_event(run.run_id, HarnessEvent(type="run.started")).events[-1]
    second = store.append_event(run.run_id, HarnessEvent(type="run.completed")).events[-1]

    reloaded = store.get_run(run.run_id)
    assert reloaded is not None
    assert [event.sequence for event in reloaded.events] == [1, 2]
    assert all(event.event_id for event in reloaded.events)
    assert reloaded.events[0].harness_id == spec.name
    assert reloaded.events[1].parent_event_id == first.event_id
    assert second.sequence == 2


@pytest.mark.asyncio
async def test_one_controller_runs_core_python_and_acp(monkeypatch, tmp_path):
    import superqode.harness.kernel as kernel_module

    monkeypatch.setattr(kernel_module, "create_harness_backend", lambda _name: FakeCoreBackend())

    async def python_handler(message, session):
        del session
        return PythonHarnessResult(
            content=f"python:{message.content}",
            usage={"input_tokens": 2, "output_tokens": 2},
        )

    adapters = [
        CoreHarnessProtocolAdapter(get_harness_template("coding")),
        DirectPythonHarnessAdapter("python", python_handler),
        ACPHarnessProtocolAdapter("fake acp", client_factory=FakeACPClient),
    ]
    controller = HarnessProtocolController(adapters, store=MemoryHarnessStore())
    final_content = {}
    for adapter in adapters:
        session = await controller.create(
            HarnessCreateRequest(
                harness_id=adapter.descriptor.id,
                provider="test",
                model="model",
                working_directory=tmp_path,
            )
        )
        events = [event async for event in controller.send(session, "hello")]
        assert events[0].type == "run.started"
        assert events[-1].type == "run.completed"
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assistant = [
            event
            for event in events
            if event.type == "message.created" and event.data.get("role") == "assistant"
        ]
        assert len(assistant) == 1
        final_content[adapter.descriptor.id] = assistant[0].data["content"]
        bundle = controller.export(session)
        assert bundle.session.session_id == session.session_id
        assert bundle.runs[0]["status"] == "succeeded"

    assert final_content == {
        "core": "core:hello",
        "python": "python:hello",
        "acp": "acp:hello",
    }


@pytest.mark.asyncio
async def test_file_ledger_can_resume_with_a_fresh_controller(tmp_path):
    async def handler(message, session):
        del session
        return f"reply:{message.content}"

    root = tmp_path / "ledger"
    first_controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("package-harness", handler)],
        store=FileHarnessStore(root),
    )
    session = await first_controller.create(
        HarnessCreateRequest(
            harness_id="package-harness",
            provider="test",
            model="model",
            working_directory=Path(tmp_path),
        )
    )
    first_events = [event async for event in first_controller.send(session, "one")]

    fresh_controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("package-harness", handler)],
        store=FileHarnessStore(root),
    )
    resumed = await fresh_controller.resume(session.session_id)
    second_events = [event async for event in fresh_controller.send(resumed, "two")]
    bundle = fresh_controller.export(resumed)

    assert resumed.session_id == session.session_id
    assert len(bundle.runs) == 2
    assert len(bundle.events) == len(first_events) + len(second_events)
    assert bundle.events[-1].type == "run.completed"


@pytest.mark.asyncio
async def test_unsupported_capabilities_fail_explicitly(monkeypatch):
    import superqode.harness.kernel as kernel_module

    monkeypatch.setattr(kernel_module, "create_harness_backend", lambda _name: FakeCoreBackend())
    adapter = CoreHarnessProtocolAdapter(get_harness_template("coding"))
    controller = HarnessProtocolController([adapter])
    session = await controller.create(
        HarnessCreateRequest(harness_id="core", provider="test", model="model")
    )

    with pytest.raises(HarnessCapabilityError, match="steer"):
        await controller.steer(session, HarnessMessage("user", "change course"))
    with pytest.raises(HarnessCapabilityError, match="checkpoint"):
        await controller.checkpoint(session)
    with pytest.raises(HarnessCapabilityError, match="cancel"):
        await controller.cancel(session)


@pytest.mark.asyncio
async def test_shared_conformance_suite_passes_direct_python_and_acp(tmp_path):
    async def handler(message, session):
        del session
        return f"python:{message.content}"

    python_report = await run_harness_conformance(
        DirectPythonHarnessAdapter("python", handler),
        working_directory=tmp_path,
    )
    acp_report = await run_harness_conformance(
        ACPHarnessProtocolAdapter("fake acp", client_factory=FakeACPClient),
        working_directory=tmp_path,
    )

    assert python_report.passed
    assert acp_report.passed


@pytest.mark.asyncio
async def test_shared_conformance_suite_passes_core(monkeypatch, tmp_path):
    import superqode.harness.kernel as kernel_module

    monkeypatch.setattr(kernel_module, "create_harness_backend", lambda _name: FakeCoreBackend())
    report = await run_harness_conformance(
        CoreHarnessProtocolAdapter(get_harness_template("coding")),
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    assert report.passed


@pytest.mark.asyncio
async def test_direct_python_cancellation_records_one_terminal_event():
    entered = asyncio.Event()

    async def handler(message, session):
        del message, session
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    controller = HarnessProtocolController([DirectPythonHarnessAdapter("cancellable", handler)])
    session = await controller.create(HarnessCreateRequest(harness_id="cancellable"))

    async def consume():
        return [event async for event in controller.send(session, "wait")]

    task = asyncio.create_task(consume())
    await entered.wait()
    await controller.cancel(session)
    with pytest.raises(asyncio.CancelledError):
        await task

    run = controller.store.list_runs(session_id=session.session_id)[0]
    assert run.status == "cancelled"
    assert [event.type for event in run.events].count("run.cancelled") == 1


def test_installed_handler_discovery_is_minimal_and_isolates_failures(monkeypatch):
    from superqode.harness import discover_harness_adapters, load_harness_adapter

    async def run(message, session):
        del session
        return f"package:{message.content}"

    points = [
        FakeHarnessEntryPoint("simple", "example_simple:run", target=run),
        FakeHarnessEntryPoint(
            "broken",
            "example_broken:run",
            error=RuntimeError("broken package"),
        ),
    ]
    monkeypatch.setattr("superqode.harness.discovery._harness_entry_points", lambda: points)

    entries = discover_harness_adapters(include_builtins=False)
    simple = next(entry for entry in entries if entry.id == "simple")
    broken = next(entry for entry in entries if entry.id == "broken")

    assert simple.available
    assert simple.source == "package:example-simple"
    assert not broken.available
    assert broken.issue == "broken package"
    assert load_harness_adapter("simple").descriptor.id == "simple"


def test_installed_harness_has_simple_list_show_run_and_check_flow(monkeypatch):
    async def run(message, session):
        del session
        return f"package:{message.content}"

    points = [FakeHarnessEntryPoint("simple", "example_simple:run", target=run)]
    monkeypatch.setattr("superqode.harness.discovery._harness_entry_points", lambda: points)
    runner = CliRunner()

    with runner.isolated_filesystem():
        listed = runner.invoke(cli_main, ["harness", "list", "--json"])
        shown = runner.invoke(cli_main, ["harness", "show", "simple", "--json"])
        executed = runner.invoke(
            cli_main,
            [
                "harness",
                "run",
                "simple",
                "hello",
                "--provider",
                "test",
                "--model",
                "model",
                "--json",
            ],
        )
        checked = runner.invoke(
            cli_main,
            ["harness", "protocol", "conformance", "simple", "--json"],
        )

    assert listed.exit_code == 0, listed.output
    assert (
        next(row for row in json.loads(listed.output) if row["id"] == "simple")["kind"] == "python"
    )
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["id"] == "simple"
    assert executed.exit_code == 0, executed.output
    payload = json.loads(executed.output)
    assert payload["content"] == "package:hello"
    assert payload["harness"] == "simple"
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["passed"] is True
