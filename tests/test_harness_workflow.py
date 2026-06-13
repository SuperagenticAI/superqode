"""Tests for harness workflow execution."""

import sys
from dataclasses import replace

import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import (
    AgentSpec,
    FileHarnessStore,
    HarnessBackendResult,
    WorkflowMode,
    WorkflowSpec,
    WorkflowStep,
    ChecksSpec,
    CheckStepSpec,
    get_harness_template,
    init_harness,
    run_workflow,
    workflow_steps_from_spec,
)


class RecordingBackend:
    name = "recording"

    def __init__(self, responses=None):
        self.requests = []
        self.responses = list(responses or [])

    async def run(self, request):
        self.requests.append(request)
        content = (
            self.responses.pop(0)
            if self.responses
            else f"response:{len(self.requests)}:{request.prompt}"
        )
        response = AgentResponse(
            content=content,
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )
        return HarnessBackendResult(response=response, backend=self.name, runtime="fake")


class FlakyBackend:
    name = "flaky"

    def __init__(self, outcomes):
        self.requests = []
        self.outcomes = list(outcomes)

    async def run(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        response = AgentResponse(
            content=str(outcome),
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )
        return HarnessBackendResult(response=response, backend=self.name, runtime="fake")


def test_workflow_steps_from_spec_carries_agent_policy():
    spec = replace(
        get_harness_template("coding"),
        agents=(
            AgentSpec(
                id="planner",
                role="Plan.",
                model="ollama/qwen3:4b",
                tools=("read_file",),
                max_iterations=2,
                config={"runtime": "builtin"},
            ),
        ),
    )

    steps = workflow_steps_from_spec(spec, "ship it")

    assert len(steps) == 1
    assert steps[0].id == "planner"
    assert steps[0].metadata["agent_id"] == "planner"
    assert steps[0].metadata["agent_model"] == "ollama/qwen3:4b"
    assert steps[0].metadata["agent_tools"] == ["read_file"]
    assert steps[0].metadata["agent_max_iterations"] == 2
    assert steps[0].metadata["agent_runtime"] == "builtin"


@pytest.mark.asyncio
async def test_single_workflow_runs_first_step(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(get_harness_template("no-tool"), workflow=WorkflowSpec(mode=WorkflowMode.SINGLE))
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [WorkflowStep("first"), WorkflowStep("second")],
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    assert result.mode == WorkflowMode.SINGLE
    assert len(result.results) == 1
    assert backend.requests[0].prompt == "first"
    assert result.content == "response:1:first"


@pytest.mark.asyncio
async def test_chain_workflow_passes_previous_result(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(get_harness_template("no-tool"), workflow=WorkflowSpec(mode=WorkflowMode.CHAIN))
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [WorkflowStep("inspect", id="a"), WorkflowStep("summarize", id="b")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="chain-session",
    )

    assert len(result.results) == 2
    assert backend.requests[0].prompt == "inspect"
    assert backend.requests[1].prompt.startswith("summarize")
    assert "Previous step result:" in backend.requests[1].prompt
    assert "response:1:inspect" in backend.requests[1].prompt
    assert result.content.startswith("response:2:summarize")


@pytest.mark.asyncio
async def test_workflow_retries_failed_step(monkeypatch, tmp_path):
    backend = FlakyBackend([RuntimeError("temporary"), "recovered"])
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(mode=WorkflowMode.SINGLE, config={"max_retries": 1}),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))
    progress = []

    result = await run_workflow(
        kernel,
        [WorkflowStep("try", id="unstable")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        progress_callback=progress.append,
    )

    assert result.content == "recovered"
    assert len(backend.requests) == 2
    assert ("unstable", "retrying") in [(event.step_id, event.status) for event in progress]


@pytest.mark.asyncio
async def test_chain_workflow_continue_on_error_records_failure(monkeypatch, tmp_path):
    backend = FlakyBackend([RuntimeError("boom"), "after failure"])
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = FileHarnessStore(tmp_path / "store")
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(
            mode=WorkflowMode.CHAIN,
            config={"continue_on_error": True},
        ),
    )
    kernel = await init_harness(spec, store=store)

    result = await run_workflow(
        kernel,
        [WorkflowStep("bad", id="bad"), WorkflowStep("next", id="next")],
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    assert result.content == "after failure"
    assert result.failures[0]["step_id"] == "bad"
    assert "Previous step failed: boom" in backend.requests[1].prompt
    run = store.get_run(result.run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.metadata["failures"][0]["step_id"] == "bad"


@pytest.mark.asyncio
async def test_workflow_fallback_prompt_recovers_failed_step(monkeypatch, tmp_path):
    backend = FlakyBackend([RuntimeError("primary failed"), "fallback result"])
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(
            mode=WorkflowMode.SINGLE,
            config={
                "fallback_prompt": "Recover with a simpler response.",
                "fallback_step_id": "recover",
            },
        ),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [WorkflowStep("hard task", id="primary")],
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    assert result.content == "fallback result"
    assert len(backend.requests) == 2
    assert backend.requests[1].metadata["workflow_step"] == "recover"
    assert "Recover with a simpler response." in backend.requests[1].prompt


@pytest.mark.asyncio
async def test_workflow_honors_per_agent_model_runtime_and_policy(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("coding"),
        workflow=WorkflowSpec(mode=WorkflowMode.CHAIN),
        agents=(
            AgentSpec(
                id="planner",
                role="Plan with small model.",
                model="ollama/qwen3:4b",
                tools=("read_file",),
                max_iterations=2,
                config={"runtime": "builtin"},
            ),
            AgentSpec(
                id="reviewer",
                role="Review with hosted model.",
                model="gpt-5.5",
                tools=("grep", "read_file"),
                max_iterations=4,
                config={"provider": "openai", "runtime": "openai-agents"},
            ),
        ),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    await run_workflow(
        kernel,
        [
            WorkflowStep(
                "plan",
                id="planner",
                metadata={
                    "agent_id": "planner",
                    "agent_model": "ollama/qwen3:4b",
                    "agent_tools": ["read_file"],
                    "agent_max_iterations": 2,
                    "agent_runtime": "builtin",
                },
            ),
            WorkflowStep(
                "review",
                id="reviewer",
                metadata={
                    "agent_id": "reviewer",
                    "agent_provider": "openai",
                    "agent_model": "gpt-5.5",
                    "agent_tools": ["grep", "read_file"],
                    "agent_max_iterations": 4,
                    "agent_runtime": "openai-agents",
                },
            ),
        ],
        provider="default",
        model="default-model",
        working_directory=tmp_path,
        session_id="agent-policy",
    )

    assert backend.requests[0].provider == "ollama"
    assert backend.requests[0].model == "qwen3:4b"
    assert backend.requests[0].runtime == "builtin"
    assert backend.requests[0].metadata["agent_tools"] == ["read_file"]
    assert backend.requests[0].metadata["agent_max_iterations"] == 2

    assert backend.requests[1].provider == "openai"
    assert backend.requests[1].model == "gpt-5.5"
    assert backend.requests[1].runtime == "openai-agents"
    assert backend.requests[1].metadata["agent_tools"] == ["grep", "read_file"]
    assert backend.requests[1].metadata["agent_max_iterations"] == 4


@pytest.mark.asyncio
async def test_workflow_emits_step_progress(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(get_harness_template("no-tool"), workflow=WorkflowSpec(mode=WorkflowMode.CHAIN))
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))
    events = []

    await run_workflow(
        kernel,
        [WorkflowStep("inspect", id="inspect"), WorkflowStep("summarize", id="summarize")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        progress_callback=events.append,
    )

    assert [(event.step_id, event.status) for event in events] == [
        ("inspect", "running"),
        ("inspect", "done"),
        ("summarize", "running"),
        ("summarize", "done"),
    ]
    assert events[-1].detail == "1 iteration(s)"


@pytest.mark.asyncio
async def test_workflow_persists_parent_run_graph(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = FileHarnessStore(tmp_path / "store")
    spec = replace(get_harness_template("no-tool"), workflow=WorkflowSpec(mode=WorkflowMode.CHAIN))
    kernel = await init_harness(spec, store=store)

    result = await run_workflow(
        kernel,
        [WorkflowStep("inspect", id="inspect"), WorkflowStep("summarize", id="summarize")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="workflow-parent",
    )

    assert result.run_id.startswith("run_")
    assert result.session_id == "workflow-parent"
    run = store.get_run(result.run_id)
    assert run is not None
    assert run.status == "succeeded"
    assert run.metadata["workflow"] is True
    assert [event.type for event in run.events] == [
        "workflow.run.started",
        "workflow.step.started",
        "workflow.step.completed",
        "workflow.step.started",
        "workflow.step.completed",
        "workspace.changes.captured",
        "workflow.result",
        "workflow.run.completed",
    ]
    assert run.events[2].data["child_run_id"] == result.results[0].run_id
    graph = store.get_event_graph(result.run_id)
    assert [node.type for node in graph.nodes] == [
        "workflow",
        "workflow",
        "workflow",
        "workflow",
        "workflow",
        "evidence",
        "workflow",
        "workflow",
    ]
    assert graph.nodes[-1].label == "workflow.run.completed"


@pytest.mark.asyncio
async def test_workflow_persists_checks_and_evidence(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = FileHarnessStore(tmp_path / "store")
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(mode=WorkflowMode.SINGLE),
        checks=ChecksSpec(
            enabled=True,
            fail_on_error=True,
            custom_steps=(
                CheckStepSpec(
                    name="smoke",
                    command=f"{sys.executable} -c \"print('checks ok')\"",
                ),
            ),
        ),
    )
    kernel = await init_harness(spec, store=store)

    result = await run_workflow(
        kernel,
        [WorkflowStep("inspect", id="inspect")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="workflow-checks",
    )

    run = store.get_run(result.run_id)
    assert run is not None
    assert run.status == "succeeded"
    event_types = [event.type for event in run.events]
    assert "workspace.changes.captured" in event_types
    assert "checks.step.started" in event_types
    assert "checks.step.completed" in event_types
    assert "workflow.result" in event_types
    assert run.metadata["checks"]["status"] == "passed"
    assert run.metadata["changed_files"]["file_count"] == 0
    graph = store.get_event_graph(result.run_id)
    assert "checks" in {node.type for node in graph.nodes}
    assert "evidence" in {node.type for node in graph.nodes}


@pytest.mark.asyncio
async def test_workflow_marks_run_failed_when_required_checks_fails(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = FileHarnessStore(tmp_path / "store")
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(mode=WorkflowMode.SINGLE),
        checks=ChecksSpec(
            enabled=True,
            fail_on_error=True,
            custom_steps=(
                CheckStepSpec(
                    name="fail",
                    command=f'{sys.executable} -c "import sys; sys.exit(7)"',
                ),
            ),
        ),
    )
    kernel = await init_harness(spec, store=store)

    result = await run_workflow(
        kernel,
        [WorkflowStep("inspect", id="inspect")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="workflow-checks-fail",
    )

    run = store.get_run(result.run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.metadata["checks"]["status"] == "failed"
    assert run.metadata["checks"]["steps"][0]["returncode"] == 7


@pytest.mark.asyncio
async def test_parallel_workflow_runs_all_steps_in_separate_sessions(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(mode=WorkflowMode.PARALLEL, parallelism=2),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [WorkflowStep("one", id="x"), WorkflowStep("two", id="y"), WorkflowStep("three", id="z")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="parallel",
    )

    assert result.mode == WorkflowMode.PARALLEL
    assert len(result.results) == 3
    assert {request.prompt for request in backend.requests} == {"one", "two", "three"}
    assert {request.session_id for request in backend.requests} == {
        "parallel:x",
        "parallel:y",
        "parallel:z",
    }


@pytest.mark.asyncio
async def test_router_workflow_uses_explicit_route_to(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(mode=WorkflowMode.ROUTER, config={"route_to": "backend"}),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [WorkflowStep("frontend task", id="frontend"), WorkflowStep("backend task", id="backend")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="router",
    )

    assert result.mode == WorkflowMode.ROUTER
    assert len(result.results) == 1
    assert backend.requests[0].prompt == "backend task"
    assert backend.requests[0].session_id == "router:backend"


@pytest.mark.asyncio
async def test_router_workflow_can_route_from_router_output(monkeypatch, tmp_path):
    backend = RecordingBackend(responses=["route:api", "api answer"])
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(get_harness_template("no-tool"), workflow=WorkflowSpec(mode=WorkflowMode.ROUTER))
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [
            WorkflowStep("choose route", id="router"),
            WorkflowStep("web task", id="web"),
            WorkflowStep("api task", id="api"),
        ],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="router-dynamic",
    )

    assert len(result.results) == 2
    assert "Choose exactly one route" in backend.requests[0].prompt
    assert backend.requests[1].prompt == "api task"
    assert result.content == "api answer"


@pytest.mark.asyncio
async def test_orchestrator_workflow_runs_workers_then_synthesis(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(
            mode=WorkflowMode.ORCHESTRATOR,
            parallelism=2,
            config={"synthesis_prompt": "merge findings"},
        ),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [WorkflowStep("worker one", id="one"), WorkflowStep("worker two", id="two")],
        provider="test",
        model="model",
        working_directory=tmp_path,
        session_id="orch",
    )

    assert result.mode == WorkflowMode.ORCHESTRATOR
    assert len(result.results) == 3
    assert backend.requests[-1].session_id == "orch:synthesis"
    assert backend.requests[-1].prompt.startswith("merge findings")
    assert "Worker results:" in backend.requests[-1].prompt


@pytest.mark.asyncio
async def test_evaluator_optimizer_stops_on_pass(monkeypatch, tmp_path):
    backend = RecordingBackend(responses=["candidate", "PASS"])
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(mode=WorkflowMode.EVALUATOR_OPTIMIZER),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [
            WorkflowStep("draft", id="candidate"),
            WorkflowStep("judge", id="evaluator"),
            WorkflowStep("improve", id="optimizer"),
        ],
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    assert result.mode == WorkflowMode.EVALUATOR_OPTIMIZER
    assert len(result.results) == 2
    assert result.content == "PASS"


@pytest.mark.asyncio
async def test_evaluator_optimizer_runs_optimizer_on_failure(monkeypatch, tmp_path):
    backend = RecordingBackend(responses=["candidate", "needs work", "optimized"])
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec = replace(
        get_harness_template("no-tool"),
        workflow=WorkflowSpec(mode=WorkflowMode.EVALUATOR_OPTIMIZER),
    )
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))

    result = await run_workflow(
        kernel,
        [
            WorkflowStep("draft", id="candidate"),
            WorkflowStep("judge", id="evaluator"),
            WorkflowStep("improve", id="optimizer"),
        ],
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    assert len(result.results) == 3
    assert result.content == "optimized"
    assert "Evaluator feedback:" in backend.requests[2].prompt
