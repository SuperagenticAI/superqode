"""Reviewer experiments grade structured judgments, never string 'approved'."""
# ruff: noqa: F811

import asyncio
import json

import pytest
import yaml

from test_factory_definition import project, rewrite  # noqa: F401
from test_factory_improvement import prepared, fake_eval  # noqa: F401
from test_factory_trials import suite_project  # noqa: F401
from superqode.factory import improvement, workflow, load_factory, resolve_factory, trials
from superqode.harness.evaluators import evaluate_content


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"verdict": "approved", "summary": "Reviewed exact candidate", "issues": []}, "passed"),
        (
            {"verdict": "changes_requested", "summary": "Wrong value", "issues": ["wrong total"]},
            "failed",
        ),
        ({"verdict": "approved", "summary": "Contradiction", "issues": ["wrong total"]}, "error"),
        ({"verdict": "approved"}, "error"),
    ],
)
def test_typed_reviewer_grading(payload, status):
    task = {"evaluator": {"type": "review", "expected_verdict": "approved"}}
    result = asyncio.run(evaluate_content("SUPERQODE_REVIEW: " + json.dumps(payload), task))
    assert result.status == status


@pytest.mark.parametrize("extra", ["missing", "empty", "different", "duplicate"])
def test_review_grader_requires_exact_named_outputs(extra):
    review = {"verdict": "approved", "summary": "Checked candidate", "issues": []}
    content = "SUPERQODE_REVIEW: " + json.dumps(review)
    if extra == "empty":
        content += "\nSUPERQODE_OUTPUT: {}"
    elif extra == "different":
        content += "\nSUPERQODE_OUTPUT: " + json.dumps({"other": review})
    elif extra == "duplicate":
        content = 'SUPERQODE_REVIEW: {"verdict":"approved","verdict":"changes_requested","summary":"Ambiguous","issues":[]}'
    task = {
        "evaluator": {
            "type": "review",
            "expected_verdict": "approved",
            "output_names": ["decision"],
        }
    }
    assert asyncio.run(evaluate_content(content, task)).status == "error"


def test_named_review_output_matches_full_contract():
    review = {
        "verdict": "changes_requested",
        "summary": "Wrong behavior",
        "issues": ["Repeated categories overwrite values"],
    }
    task = {
        "evaluator": {
            "type": "review",
            "expected_verdict": "changes_requested",
            "issue_contains": ["overwrite"],
            "output_names": ["decision"],
        }
    }
    content = (
        "SUPERQODE_OUTPUT: "
        + json.dumps({"decision": review})
        + "\nSUPERQODE_REVIEW: "
        + json.dumps(review)
    )
    assert asyncio.run(evaluate_content(content, task)).status == "passed"


def test_review_grader_keeps_declared_byte_limit():
    review = {"verdict": "approved", "summary": "Evidence " * 100, "issues": []}
    task = {"evaluator": {"type": "review", "expected_verdict": "approved", "max_bytes": 128}}
    assert (
        asyncio.run(evaluate_content("SUPERQODE_REVIEW: " + json.dumps(review), task)).status
        == "error"
    )


def test_reviewer_goal_comparison_requires_typed_labels(prepared, fake_eval):
    root, _ = prepared
    rewrite(root, lambda d: d["orchestration"]["stages"][0].update(role="reviewer"))
    params = {
        "binding": "coder",
        "tasks": ".superqode/evals/output.yaml",
        "fixture": "fixture",
        "target_kind": "workflow",
        "stage": "investigate",
        "max_seconds": 60,
    }
    with pytest.raises(ValueError, match="typed-review graders"):
        improvement.prepare(root, **params)
    path = root / params["tasks"]
    suite = yaml.safe_load(path.read_text())
    for task in suite["tasks"]:
        task.pop("expect_contains", None)
        task["evaluator"] = {"type": "review", "expected_verdict": "approved"}
    path.write_text(yaml.safe_dump(suite))
    plan = improvement.prepare(root, **params)
    assert plan["stage"] == "investigate"
    proposed = improvement.stage(
        root,
        plan["id"],
        "stage: investigate\ngoal: Review the exact candidate and report concrete findings.\n",
    )
    asyncio.run(improvement.compare(root, plan["id"], proposed["candidate"]))
    prompts = list(fake_eval[0]["task_prompts"].values())
    assert all("SUPERQODE_REVIEW" in values["gate"] for values in prompts)
    assert fake_eval[0]["readonly_workspace"]


def test_dependent_reviewer_export_pins_entire_workflow(suite_project):
    root, _ = suite_project
    rewrite(
        root,
        lambda d: d["orchestration"]["stages"][2].update(
            role="reviewer", outputs={"decision": {"type": "review"}}
        ),
    )
    snapshot = resolve_factory(load_factory(root=root))
    result = workflow.experiment(
        root,
        stage="verify",
        goal="Review the candidate for correctness and emit a typed decision.",
        work_goal="Make app.py print 43",
        expected_snapshot=snapshot.digest,
    )
    assert not result["promotion_authority"] and result["model_calls"] == 0
    plan = trials.prepare(root, suite_text=result["suite_yaml"])
    assert len(plan["entries"]) == 2
    assert (
        result["id"]
        == workflow.experiment(
            root,
            stage="verify",
            goal="Review the candidate for correctness and emit a typed decision.",
            work_goal="Make app.py print 43",
            expected_snapshot=snapshot.digest,
        )["id"]
    )
    with pytest.raises(ValueError, match="Save the reviewed"):
        workflow.experiment(
            root, stage="verify", goal="Another goal", work_goal="Task", expected_snapshot="stale"
        )
