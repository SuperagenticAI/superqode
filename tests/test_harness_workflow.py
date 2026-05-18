"""Tests for harness workflow execution."""

from dataclasses import replace

import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import (
    FileHarnessStore,
    HarnessBackendResult,
    WorkflowMode,
    WorkflowSpec,
    WorkflowStep,
    get_harness_template,
    init_harness,
    run_workflow,
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
