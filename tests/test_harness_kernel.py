"""Tests for the minimal v2 HarnessKernel."""

from dataclasses import replace
from pathlib import Path

from pydantic import BaseModel
import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import (
    FileHarnessStore,
    HarnessBackendResult,
    HarnessFlavor,
    ModelPolicySpec,
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

    async def run_streaming(self, prompt: str):
        yield f"{prompt}-"
        yield "streamed"

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


class FakeApprovalRuntime:
    def __init__(self):
        self.approved = []
        self.rejected = []
        self._pending = [{"index": 0, "tool_name": "bash", "arguments": {"command": "ls"}}]

    def get_pending_approvals(self):
        return list(self._pending)

    async def approve_and_resume(self, index: int = 0, always: bool = False):
        self.approved.append((index, always))
        self._pending = []
        return AgentResponse(
            content="approved",
            messages=[],
            tool_calls_made=1,
            iterations=2,
            stopped_reason="complete",
        )

    async def reject_and_resume(
        self, index: int = 0, message: str | None = None, always: bool = False
    ):
        self.rejected.append((index, message, always))
        self._pending = []
        return AgentResponse(
            content="rejected",
            messages=[],
            tool_calls_made=0,
            iterations=2,
            stopped_reason="complete",
        )


class FakeStreamingApprovalRuntime(FakeApprovalRuntime):
    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs

    async def run_streaming(self, prompt: str):
        yield f"{prompt}:paused"

    async def run(self, prompt: str) -> AgentResponse:
        return AgentResponse(
            content="",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="needs_approval",
        )

    def cancel(self) -> None:
        pass

    def reset_cancellation(self) -> None:
        pass


class FakeApprovalBackend(FakeBackend):
    def __init__(self, runtime: FakeApprovalRuntime):
        super().__init__(content="")
        self.runtime = runtime

    async def run(self, request):
        self.requests.append(request)
        response = AgentResponse(
            content="",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="needs_approval",
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime="openai-agents",
            metadata={
                "pending_approvals": self.runtime.get_pending_approvals(),
                "pending_runtime": self.runtime,
            },
        )


class FakeModelDeltaBackend:
    async def stream(self, request):
        from superqode.harness import HarnessEvent

        yield HarnessEvent(type="model_request", data={"runtime": "fake"})
        yield HarnessEvent(type="model_delta", data={"text": "hello"})
        yield HarnessEvent(type="model_delta", data={"text": "-streamed"})
        yield HarnessEvent(type="end", data={"runtime": "fake"})


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
    assert isinstance(events[1].data["latency_ms"], int)
    assert events[1].data["tokens_in"] is None
    assert events[1].data["tokens_out"] is None
    stored_run = store.get_run(result.run_id)
    assert stored_run is not None
    assert stored_run.status == "succeeded"
    assert isinstance(stored_run.metadata["latency_ms"], int)
    assert stored_run.metadata["tokens_in"] is None
    assert stored_run.metadata["tokens_out"] is None
    assert [event.type for event in stored_run.events] == ["run_start", "run_end"]


@pytest.mark.asyncio
async def test_kernel_surfaces_and_resumes_pending_approval(monkeypatch, tmp_path: Path):
    runtime = FakeApprovalRuntime()
    backend = FakeApprovalBackend(runtime)
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    events = []
    store = FileHarnessStore(tmp_path / "approval-store")
    kernel = await init_harness(
        get_harness_template("coding"), event_callback=events.append, store=store
    )
    session = await kernel.session("approval-session")

    result = await session.prompt(
        "run ls",
        provider="openai",
        model="gpt-5",
        working_directory=tmp_path,
    )

    assert result.response.stopped_reason == "needs_approval"
    assert session.pending_approvals() == (
        {"index": 0, "tool_name": "bash", "arguments": {"command": "ls"}},
    )
    assert [event.type for event in events] == ["run_start", "approval_required", "run_end"]
    assert events[1].data["pending_approvals"][0]["tool_name"] == "bash"
    stored_run = store.get_run(result.run_id)
    assert stored_run is not None
    assert stored_run.status == "needs_approval"
    assert stored_run.metadata["pending_approvals"][0]["arguments"] == {"command": "ls"}

    resumed = await session.approve_pending(always=True)

    assert resumed.content == "approved"
    assert runtime.approved == [(0, True)]
    assert session.pending_approvals() == ()
    assert events[-2].type == "approval_decision"
    assert events[-1].type == "approval_resumed"


@pytest.mark.asyncio
async def test_coding_kernel_uses_template_tools(monkeypatch, tmp_path: Path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        created["name"] = name
        created["kwargs"] = kwargs
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    kernel = await init_harness(
        get_harness_template("coding"), store=FileHarnessStore(tmp_path / "store")
    )
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
async def test_kernel_stream_emits_delta_events(monkeypatch, tmp_path: Path):
    def fake_create_runtime(name, **kwargs):
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    store = FileHarnessStore(tmp_path / "stream-store")
    kernel = await init_harness(get_harness_template("no-tool"), store=store)
    session = await kernel.session("stream-session")

    events = [
        event
        async for event in session.stream(
            "hello",
            provider="test",
            model="model",
            working_directory=tmp_path,
        )
    ]

    assert [event.type for event in events] == ["delta", "delta", "end"]
    assert "".join(event.data.get("text", "") for event in events) == "hello-streamed"


@pytest.mark.asyncio
async def test_pure_mode_can_stream_through_harness_spec(monkeypatch, tmp_path: Path):
    from superqode.pure_mode import PureMode

    def fake_create_runtime(name, **kwargs):
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    spec = get_harness_template("no-tool")
    pure = PureMode()
    pure.set_harness(spec)
    assert pure.connect("test", "model", working_directory=tmp_path)

    chunks = [chunk async for chunk in pure.run_streaming("hello")]

    assert "".join(chunks) == "hello-streamed"
    status = pure.get_status()
    assert status["harness"]["enabled"] is True
    assert status["harness"]["name"] == spec.name


@pytest.mark.asyncio
async def test_pure_mode_harness_primary_overrides_active_connection(monkeypatch, tmp_path: Path):
    from superqode.pure_mode import PureMode

    created = {}

    def fake_create_runtime(name, **kwargs):
        created["config"] = kwargs["config"]
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    spec = replace(
        get_harness_template("no-tool"),
        model_policy=ModelPolicySpec(primary="mlx/qwen3.6:35b-mlx"),
    )
    pure = PureMode()
    pure.set_harness(spec)
    assert pure.connect("ollama", "qwen3.6:35b-a3b", working_directory=tmp_path)

    chunks = [chunk async for chunk in pure.run_streaming("hello")]

    assert "".join(chunks) == "hello-streamed"
    assert created["config"].provider == "mlx"
    assert created["config"].model == "qwen3.6:35b-mlx"


def test_pure_mode_harness_allows_ollama_mlx_tagged_model(tmp_path: Path):
    from superqode.pure_mode import PureMode

    pure = PureMode()
    pure.set_harness(get_harness_template("no-tool"))
    assert pure.connect("ollama", "qwen3.6:35b-mlx", working_directory=tmp_path)

    provider, model = pure._resolve_harness_route()

    assert provider == "ollama"
    assert model == "qwen3.6:35b-mlx"


def test_pure_mode_set_harness_updates_visible_status(tmp_path: Path):
    from superqode.pure_mode import PureMode

    spec = get_harness_template("qwen-coding")
    pure = PureMode()
    pure.set_harness(spec, path=tmp_path / "harness.yaml")

    status = pure.get_status()["harness"]
    assert status["enabled"] is True
    assert status["name"] == "qwen-coding"
    assert status["path"].endswith("harness.yaml")
    assert status["flavor"] == "coding"
    assert status["runtime"] == "builtin"


def test_pure_mode_disconnect_preserves_loaded_harness_status(tmp_path: Path):
    from superqode.pure_mode import PureMode

    spec = get_harness_template("qwen-coding")
    pure = PureMode()
    pure.set_harness(spec, path=tmp_path / "harness.yaml")
    assert pure.connect("ollama", "qwen3-coder", working_directory=tmp_path)

    pure.disconnect()

    status = pure.get_status()["harness"]
    assert status["enabled"] is True
    assert status["name"] == "qwen-coding"
    assert status["path"].endswith("harness.yaml")


@pytest.mark.asyncio
async def test_pure_mode_harness_stream_forwards_model_delta_events(monkeypatch, tmp_path: Path):
    from superqode.pure_mode import PureMode

    monkeypatch.setattr(
        "superqode.harness.kernel.create_harness_backend",
        lambda name: FakeModelDeltaBackend(),
    )
    pure = PureMode()
    pure.set_harness(get_harness_template("qwen-coding"), path=tmp_path / "harness.yaml")
    assert pure.connect("ollama", "qwen3-coder", working_directory=tmp_path)

    chunks = [chunk async for chunk in pure.run_streaming("hello")]

    assert chunks == ["hello", "-streamed"]


@pytest.mark.asyncio
async def test_pure_mode_resumes_harness_approval(monkeypatch, tmp_path: Path):
    from superqode.pure_mode import PureMode

    runtime = FakeApprovalRuntime()
    backend = FakeApprovalBackend(runtime)
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    pure = PureMode()
    pure.set_harness(get_harness_template("coding"))
    assert pure.connect("openai", "gpt-5", working_directory=tmp_path)

    response = await pure.run("run ls")

    assert response.stopped_reason == "needs_approval"
    assert pure.get_pending_approvals()[0]["tool_name"] == "bash"
    resumed = await pure.approve_and_resume(always=True)
    assert resumed.content == "approved"
    assert runtime.approved == [(0, True)]
    assert pure.get_pending_approvals() == []


@pytest.mark.asyncio
async def test_harness_stream_preserves_pending_approval_state(monkeypatch, tmp_path: Path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        runtime = FakeStreamingApprovalRuntime(**kwargs)
        created["runtime"] = runtime
        return runtime

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    store = FileHarnessStore(tmp_path / "stream-approval-store")
    kernel = await init_harness(get_harness_template("coding"), store=store)
    session = await kernel.session("stream-approval-session")

    events = [
        event
        async for event in session.stream(
            "hello",
            provider="openai",
            model="gpt-5",
            working_directory=tmp_path,
        )
    ]

    assert [event.type for event in events] == [
        "delta",
        "approval_required",
        "end",
    ]
    assert events[1].data["pending_approvals"][0]["tool_name"] == "bash"
    assert "pending_runtime" not in events[1].data
    assert session.pending_approvals()[0]["arguments"] == {"command": "ls"}
    resumed = await session.reject_pending(message="not now")
    assert resumed.content == "rejected"
    assert created["runtime"].rejected == [(0, "not now", False)]
    stored_run = store.get_run(events[0].run_id or "")
    assert stored_run is not None
    assert stored_run.status == "needs_approval"
    assert stored_run.metadata["pending_approvals"][0]["tool_name"] == "bash"


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
    kernel = await init_harness(
        get_harness_template("no-tool"), event_callback=events.append, store=store
    )
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
