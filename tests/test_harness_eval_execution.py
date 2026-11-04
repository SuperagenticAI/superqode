"""Execution failures must not become grading or candidate adoption successes."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
import yaml

from superqode.agent.loop import AgentResponse
from superqode.harness import eval as evaluation
from superqode.harness.acceptance import heldout_acceptance
from superqode.harness.backends.base import HarnessBackendResult
from superqode.harness.loader import harness_spec_to_dict
from superqode.harness.templates import no_tool_template
from superqode.harness.spec import WorkflowMode


@pytest.mark.parametrize(
    "stop", ["error", "cancelled", "needs_approval", "max_iterations", "max_tokens", "unknown"]
)
@pytest.mark.asyncio
async def test_matching_failed_run_is_not_graded_or_accepted(tmp_path, monkeypatch, stop):
    class Backend:
        async def run(self, request):
            return HarnessBackendResult(
                response=AgentResponse(
                    content="EXPECTED",
                    messages=[],
                    tool_calls_made=0,
                    iterations=1,
                    stopped_reason=stop,
                    input_tokens=10,
                    output_tokens=2,
                    total_tokens=12,
                    cost_usd=0.01,
                ),
                backend="fixture",
                runtime="fixture",
            )

    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda _: Backend())

    async def grade(*args, **kwargs):
        raise AssertionError("Incomplete runs must not invoke a grader")

    monkeypatch.setattr(evaluation, "evaluate_content", grade)
    paths = []
    for name in ["baseline", "candidate"]:
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(harness_spec_to_dict(no_tool_template(name=name))))
        paths.append(path)
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "id": "case",
                        "split": "held-out",
                        "prompt": "fixture",
                        "expect_contains": "EXPECTED",
                    }
                ]
            }
        )
    )
    report = await evaluation.run_harness_eval(
        spec_paths=paths,
        tasks_path=tasks,
        provider="synthetic",
        model="passthrough",
        working_dir=tmp_path,
        live=True,
        eval_split="held-out",
    )
    assert report["status"] == "failed"
    assert not heldout_acceptance(report)["accepted"]
    for variant in report["variants"]:
        row = variant["tasks"][0]
        assert row["status"] == "error"
        assert row["evaluation"]["evaluator"] == "execution"
        assert row["score"] == 0
        assert row["total_tokens"] == 12
        assert row["cost_usd"] == 0.01
        assert row["run_id"]


@pytest.mark.parametrize(
    "field,value", [("error", "fixture failure"), ("schema_errors", ["invalid schema"])]
)
def test_error_metadata_blocks_even_complete_stop(field, value):
    response = AgentResponse(
        content="EXPECTED", messages=[], tool_calls_made=0, iterations=1, stopped_reason="complete"
    )
    setattr(response, field, value)
    assert evaluation._execution_error(SimpleNamespace(response=response))


@pytest.mark.asyncio
async def test_failed_workflow_does_not_grade_its_final_success_text(tmp_path, monkeypatch):
    spec = no_tool_template()
    spec = replace(spec, workflow=replace(spec.workflow, mode=WorkflowMode.CHAIN))
    response = AgentResponse(
        content="EXPECTED", messages=[], tool_calls_made=0, iterations=1, stopped_reason="complete"
    )
    workflow = SimpleNamespace(
        content="EXPECTED",
        run_id="workflow",
        results=(SimpleNamespace(response=response),),
        failures=({"error": "earlier step failed"},),
    )

    async def run(*args, **kwargs):
        return workflow

    monkeypatch.setattr(evaluation, "run_workflow", run)
    row = await evaluation._run_eval_task(
        spec=spec,
        kernel=None,
        task={
            "id": "case",
            "split": "held-out",
            "prompt": "fixture",
            "expect_contains": "EXPECTED",
        },
        provider="synthetic",
        model="passthrough",
        runtime=None,
        working_dir=tmp_path,
        sandbox_backend="local",
        live=True,
    )
    assert row["status"] == "error"
    assert "failed steps" in row["reason"]


def test_unknown_or_empty_workflow_is_not_proof_of_completion():
    assert evaluation._execution_error(SimpleNamespace(results=(), failures=()))
    assert evaluation._execution_error(SimpleNamespace(response=None))
