"""Tests for the minimal v2 HarnessKernel."""

from pathlib import Path

from pydantic import BaseModel
import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import (
    FileHarnessStore,
    HarnessBackendResult,
    HarnessFlavor,
    get_harness_template,
    init_harness,
)


class TriageResult(BaseModel):
    fix_applied: bool
    summary: str


class FakeRuntime:
    name = "fake"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def run(self, prompt: str) -> AgentResponse:
        tools = self.kwargs["tools"]
        config = self.kwargs["config"]
        tool_names = [tool.name for tool in tools.list()]
        return AgentResponse(
            content=f"{prompt}|tools={','.join(tool_names)}|level={config.system_prompt_level.value}",
            messages=[],
            tool_calls_made=len(tool_names),
            iterations=1,
            stopped_reason="complete",
        )

    def run_streaming(self, prompt: str):
        raise NotImplementedError

    def cancel(self) -> None:
        pass

    def reset_cancellation(self) -> None:
        pass


class FakeBackend:
    name = "fake-backend"

    def __init__(self, content: str | None = None):
        self.requests = []
        self.content = content

    async def run(self, request):
        self.requests.append(request)
        response = AgentResponse(
            content=self.content or f"{request.prompt}|backend={self.name}",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )
        return HarnessBackendResult(response=response, backend=self.name, runtime="fake-runtime")


@pytest.mark.asyncio
async def test_no_tool_kernel_runs_with_empty_registry(monkeypatch, tmp_path: Path):
    backend = FakeBackend()

    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    events = []
    store = FileHarnessStore(tmp_path / "harness-store")
    kernel = await init_harness(
        get_harness_template("no-tool"), event_callback=events.append, store=store
    )
    session = await kernel.session("session-1")

    result = await session.prompt(
        "reason only",
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    assert result.spec.flavor == HarnessFlavor.NO_TOOL
    assert result.content == "reason only|backend=fake-backend"
    assert result.tool_calls_made == 0
    assert backend.requests[0].spec.flavor == HarnessFlavor.NO_TOOL
    assert backend.requests[0].runtime is None
    assert [event.type for event in events] == ["run_start", "run_end"]
    assert events[0].data["flavor"] == "no_tool"
    assert events[1].data["status"] == "succeeded"
    assert events[1].data["backend"] == "fake-backend"
    assert events[1].data["runtime"] == "fake-runtime"
    stored_run = store.get_run(result.run_id)
    assert stored_run is not None
    assert stored_run.status == "succeeded"
    assert [event.type for event in stored_run.events] == ["run_start", "run_end"]


@pytest.mark.asyncio
async def test_coding_kernel_uses_template_tools(monkeypatch, tmp_path: Path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        created["name"] = name
        created["kwargs"] = kwargs
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    kernel = await init_harness(get_harness_template("coding"), store=FileHarnessStore(tmp_path / "store"))
    session = await kernel.session("session-2")

    result = await session.prompt(
        "code",
        provider="test",
        model="model",
        working_directory=tmp_path,
        runtime="builtin",
    )

    tool_names = [tool.name for tool in created["kwargs"]["tools"].list()]
    assert result.spec.flavor == HarnessFlavor.CODING
    assert "read_file" in tool_names
    assert "patch" in tool_names
    assert "bash" in tool_names
    assert created["kwargs"]["config"].tools_enabled is True
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_kernel_typed_output_returns_parsed_data(monkeypatch, tmp_path: Path):
    backend = FakeBackend(
        content='done\n---RESULT_START---\n{"fix_applied": true, "summary": "ok"}\n---RESULT_END---'
    )
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = FileHarnessStore(tmp_path / "typed-store")
    kernel = await init_harness(get_harness_template("no-tool"), store=store)
    session = await kernel.session("typed-session")

    result = await session.prompt(
        "triage",
        provider="test",
        model="model",
        working_directory=tmp_path,
        result=TriageResult,
    )

    assert isinstance(result.data, TriageResult)
    assert result.data.fix_applied is True
    assert result.data.summary == "ok"
    assert "---RESULT_START---" in backend.requests[0].prompt
    stored_run = store.get_run(result.run_id)
    assert stored_run is not None
    assert stored_run.metadata["typed_output"] is True


@pytest.mark.asyncio
async def test_kernel_typed_output_validation_failure_marks_run_failed(monkeypatch, tmp_path: Path):
    backend = FakeBackend(content="not json")
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = FileHarnessStore(tmp_path / "typed-fail-store")
    events = []
    kernel = await init_harness(get_harness_template("no-tool"), event_callback=events.append, store=store)
    session = await kernel.session("typed-fail-session")

    with pytest.raises(ValueError, match="Typed output"):
        await session.prompt(
            "triage",
            provider="test",
            model="model",
            working_directory=tmp_path,
            result=TriageResult,
        )

    assert events[-1].type == "run_end"
    assert events[-1].data["status"] == "failed"
    run_id = events[-1].run_id
    assert run_id is not None
    stored_run = store.get_run(run_id)
    assert stored_run is not None
    assert stored_run.status == "failed"
    assert stored_run.metadata["error_type"] == "TypedOutputError"
