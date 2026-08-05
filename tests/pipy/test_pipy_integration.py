"""PiPy inside SuperQode: catalog, backend, protocol adapter (checklist I1 to I10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from superqode.harness import DEFAULT_HARNESS_ID, list_harnesses, resolve_harness
from superqode.harness.backends.registry import (
    create_harness_backend,
    known_harness_backend_names,
)
from superqode.harness.conformance import run_harness_conformance
from superqode.harness.pipy_adapter import PiPyHarnessProtocolAdapter, translate_event
from superqode.harness.protocol import HarnessCreateRequest, HarnessMessage
from superqode.harness.templates import pipy_template
from superqode.pipy import ToolCall
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
from superqode.pipy.stream import Model

MODEL = Model(id="fake-1", provider="fake", api="fake-api")


def make_factory(script, session_root: Path):
    """Build PiPy sessions with a scripted stream instead of a real provider."""

    async def factory(request, working_directory, session_path):
        options = CodingSessionOptions(
            cwd=working_directory,
            model=MODEL,
            stream_fn=FakeStream(list(script)),
            session_root=session_root,
        )
        if session_path and Path(session_path).is_file():
            return await PiPyCodingSession.resume(options, session_path=session_path)
        return await PiPyCodingSession.create(options)

    return factory


# -- catalog ----------------------------------------------------------------- #


def test_pipy_is_selectable(tmp_path):
    entries = {entry.id: entry for entry in list_harnesses(tmp_path)}

    assert "pipy" in entries
    assert entries["pipy"].runtime == "pipy"
    assert entries["pipy"].recommended is True
    assert entries["pipy"].continuity == "exact-resume"


@pytest.mark.parametrize("alias", ["pipy", "pi", "pi-python"])
def test_pipy_aliases_resolve(alias):
    assert resolve_harness(alias).id == "pipy"


def test_core_remains_the_default():
    """PiPy is opt in. Nothing changes for anyone who does not ask for it."""
    assert DEFAULT_HARNESS_ID == "core"
    entries = {entry.id: entry for entry in list_harnesses(".")}
    assert entries["core"].default is True
    assert entries["pipy"].default is False


def test_existing_harnesses_are_untouched():
    entries = {entry.id: entry for entry in list_harnesses(".")}

    assert entries["core"].runtime == "builtin"
    assert entries["core"].tools == ("read", "write", "edit", "bash")
    assert entries["workbench"].runtime == "builtin"
    assert entries["tau"].runtime == "tau"


def test_template_declares_pure_permissions():
    spec = pipy_template()

    assert spec.execution_policy.approval_profile == "none"
    assert spec.execution_policy.sandbox == "none"
    assert spec.metadata["pure_permissions"] is True
    assert spec.metadata["rich_stream_events"] is True


def test_backend_is_registered():
    assert "pipy" in known_harness_backend_names()
    backend = create_harness_backend("pipy")
    assert backend.name == "pipy"
    assert backend.capabilities.supports_approvals is False
    assert backend.capabilities.supports_sandbox is False
    assert backend.capabilities.event_detail == "rich"


# -- adapter ----------------------------------------------------------------- #


def test_descriptor_declares_no_approvals():
    descriptor = PiPyHarnessProtocolAdapter().descriptor

    assert descriptor.id == "pipy"
    assert descriptor.capabilities.approvals is False
    assert descriptor.capabilities.steer is True
    assert descriptor.capabilities.resume is True
    assert descriptor.capabilities.checkpoint is True


async def test_create_opens_a_session_file(tmp_path):
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory([text_response("ok")], tmp_path / "sessions")
    )

    ref = await adapter.create(HarnessCreateRequest(harness_id="pipy", working_directory=tmp_path))

    assert ref.harness_id == "pipy"
    assert Path(ref.metadata["session_path"]).is_file()
    assert ref.metadata["pure_permissions"] is True


async def test_send_streams_a_turn(tmp_path):
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory([text_response("hello")], tmp_path / "sessions")
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="pipy", working_directory=tmp_path))

    events = [event async for event in adapter.send(ref, HarnessMessage("user", "hi"))]
    kinds = [event.type for event in events]

    assert kinds[0] == "model.requested"
    assert "run_start" in kinds
    assert "model_delta" in kinds
    assert "run_end" in kinds
    text = "".join(
        str(event.data.get("text") or "") for event in events if event.type == "model_delta"
    )
    assert text == "hello"


async def test_send_reports_tool_calls_and_results(tmp_path):
    (tmp_path / "a.txt").write_text("body\n")
    script = [
        tool_response(ToolCall(id="c1", name="read", arguments={"path": "a.txt"})),
        text_response("done"),
    ]
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory(script, tmp_path / "sessions")
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="pipy", working_directory=tmp_path))

    events = [event async for event in adapter.send(ref, HarnessMessage("user", "read it"))]

    calls = [e for e in events if e.type == "tool_call"]
    results = [e for e in events if e.type == "tool_result"]
    assert [e.data["tool_name"] for e in calls] == ["read"]
    assert calls[0].data["args"] == {"path": "a.txt"}
    assert results[0].data["success"] is True
    assert "body" in results[0].data["output"]


async def test_no_approval_events_are_ever_emitted(tmp_path):
    """The whole point of PiPy: nothing pauses for permission."""
    (tmp_path / "a.txt").write_text("body\n")
    script = [
        tool_response(ToolCall(id="c1", name="write", arguments={"path": "b.txt", "content": "x"})),
        text_response("written"),
    ]
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory(script, tmp_path / "sessions")
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="pipy", working_directory=tmp_path))

    events = [event async for event in adapter.send(ref, HarnessMessage("user", "write it"))]

    assert not any("approval" in event.type for event in events)
    assert (tmp_path / "b.txt").read_text() == "x"


async def test_resume_reuses_the_same_session_file(tmp_path):
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory([text_response("one")], tmp_path / "sessions")
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="pipy", working_directory=tmp_path))
    await anext(adapter.send(ref, HarnessMessage("user", "hi")).__aiter__())

    fresh = PiPyHarnessProtocolAdapter(
        session_factory=make_factory([text_response("two")], tmp_path / "sessions")
    )
    resumed = await fresh.resume(ref)

    assert resumed.metadata["session_path"] == ref.metadata["session_path"]


async def test_checkpoint_records_the_leaf(tmp_path):
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory([text_response("ok")], tmp_path / "sessions")
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="pipy", working_directory=tmp_path))
    async for _ in adapter.send(ref, HarnessMessage("user", "hi")):
        pass

    checkpoint = await adapter.checkpoint(ref)

    assert checkpoint.harness_id == "pipy"
    assert checkpoint.external_checkpoint_id
    assert checkpoint.state["session_path"].endswith(".jsonl")


async def test_adapter_rejects_another_harness_id(tmp_path):
    adapter = PiPyHarnessProtocolAdapter()

    with pytest.raises(ValueError, match="cannot create harness"):
        await adapter.create(HarnessCreateRequest(harness_id="core", working_directory=tmp_path))


# -- event translation ------------------------------------------------------- #


def test_translation_of_each_event_kind():
    from superqode.pipy.events import (
        AgentEndEvent,
        AgentStartEvent,
        ToolExecutionEndEvent,
        ToolExecutionStartEvent,
    )
    from superqode.pipy.tools import AgentToolResult

    assert translate_event(AgentStartEvent())[0].type == "run_start"
    assert translate_event(AgentEndEvent())[0].type == "run_end"

    started = translate_event(
        ToolExecutionStartEvent(tool_call_id="c1", tool_name="read", args={"path": "a"})
    )
    assert started[0].data["tool_call_id"] == "c1"

    from superqode.pipy import TextContent

    ended = translate_event(
        ToolExecutionEndEvent(
            tool_call_id="c1",
            tool_name="read",
            result=AgentToolResult(content=[TextContent(text="out")]),
            is_error=True,
        )
    )
    assert ended[0].data["success"] is False
    assert ended[0].data["error"] == "out"


def test_unknown_events_translate_to_nothing():
    class Odd:
        type = "something_else"

    assert translate_event(Odd()) == []


# -- protocol conformance ---------------------------------------------------- #


async def test_protocol_conformance(tmp_path):
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory([text_response("ok")], tmp_path / "sessions")
    )

    report = await run_harness_conformance(adapter, working_directory=tmp_path)

    failed = [check.name for check in report.checks if not check.passed]
    assert report.passed, f"failed checks: {failed}"


# -- session isolation ------------------------------------------------------- #


async def test_pipy_sessions_do_not_collide_with_other_harnesses(tmp_path):
    """Switching harnesses must leave each store intact."""
    adapter = PiPyHarnessProtocolAdapter(
        session_factory=make_factory([text_response("ok")], tmp_path / "sessions")
    )
    ref = await adapter.create(HarnessCreateRequest(harness_id="pipy", working_directory=tmp_path))
    async for _ in adapter.send(ref, HarnessMessage("user", "hi")):
        pass

    session_file = Path(ref.metadata["session_path"])
    assert session_file.is_file()
    # PiPy writes only under its own root, never into .superqode/tau or the
    # workbench session directory.
    assert "sessions" in session_file.parts
    assert "tau" not in session_file.parts


def test_tau_integration_is_untouched():
    """Phase 8 must not change Tau's behaviour in any way."""
    import subprocess

    diff = subprocess.run(
        ["git", "diff", "main", "--name-only", "--", "*tau*"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert diff.stdout.strip() == "", f"tau files changed: {diff.stdout}"


async def test_a_second_turn_continues_the_same_session(tmp_path, monkeypatch):
    """The catalog advertises exact resume, so turn two must not start over."""
    from superqode.harness.backends.base import HarnessBackendRequest
    from superqode.harness.backends.pipy import PiPyHarnessBackend

    sessions = tmp_path / "sessions"
    monkeypatch.setenv("SUPERQODE_PIPY_SESSION_DIR", str(sessions))
    spec = pipy_template()

    async def turn(prompt: str) -> None:
        backend = PiPyHarnessBackend(
            adapter=PiPyHarnessProtocolAdapter(
                session_factory=make_factory([text_response(prompt)], sessions)
            )
        )
        request = HarnessBackendRequest(
            spec=spec,
            prompt=prompt,
            provider="fake",
            model="fake",
            working_directory=tmp_path,
            session_id="tui-session-1",
        )
        async for _event in backend.stream(request):
            pass

    await turn("first")
    await turn("second")

    files = sorted(sessions.rglob("*.jsonl"))
    assert len(files) == 1, f"expected one session across two turns, got {len(files)}"
    body = files[0].read_text(encoding="utf-8")
    assert "first" in body and "second" in body


async def test_a_deleted_session_starts_a_new_one_instead_of_failing(tmp_path, monkeypatch):
    """A stale index entry must not turn into a resume error."""
    from superqode.harness.pipy_adapter import _indexed_session_path, _record_session_path

    sessions = tmp_path / "sessions"
    monkeypatch.setenv("SUPERQODE_PIPY_SESSION_DIR", str(sessions))
    from superqode.pipy.config import session_dir_for

    session_file = session_dir_for(tmp_path) / "2026-01-01T00-00-00-000Z_deadbeef.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("{}\n", encoding="utf-8")
    _record_session_path("gone", session_file)
    assert _indexed_session_path("gone", tmp_path) == str(session_file)

    session_file.unlink()
    assert _indexed_session_path("gone", tmp_path) == ""
