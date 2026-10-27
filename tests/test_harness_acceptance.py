from copy import deepcopy

import pytest

from superqode.harness.acceptance import heldout_acceptance


def report():
    tasks = [
        {
            "id": "gate",
            "split": "held-out",
            "status": "passed",
            "evaluation": {"status": "passed", "evaluator": "decision"},
        }
    ]
    return {
        "live": True,
        "split": "held-out",
        "task_count": 1,
        "variants": [{"tasks": deepcopy(tasks)}, {"tasks": deepcopy(tasks)}],
    }


def test_graded_matched_heldout_tasks_can_pass():
    assert heldout_acceptance(report())["accepted"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(live=False),
        lambda r: r.update(split="all"),
        lambda r: r.update(task_count=0),
        lambda r: r["variants"][1].update(tasks=[]),
        lambda r: r["variants"][1]["tasks"][0].update(status="error"),
        lambda r: r["variants"][1]["tasks"][0].update(id="other"),
        lambda r: r["variants"][1]["tasks"][0].update(
            evaluation={"status": "passed", "evaluator": "non_empty"}
        ),
        lambda r: r["variants"][1]["tasks"][0].update(
            evaluation={"status": "failed", "evaluator": "decision"}
        ),
        lambda r: r["variants"][1]["tasks"][0].update(
            evaluation={
                "status": "passed",
                "evaluator": "decision",
                "evidence": {"smoke_only": True},
            }
        ),
        lambda r: r["variants"][1]["tasks"][0].pop("evaluation"),
    ],
)
def test_aggregate_claims_cannot_override_missing_or_invalid_evidence(mutation):
    value = report()
    mutation(value)
    value["accepted"] = True
    value["variants"][1].update(score=1.0, regressed=False)
    assert heldout_acceptance(value)["accepted"] is False


def test_recomputes_regression_instead_of_trusting_summary():
    value = report()
    row = value["variants"][1]["tasks"][0]
    row["status"] = row["evaluation"]["status"] = "failed"
    gate = heldout_acceptance(value)
    assert gate["regressions"] == ["gate"]
    assert not gate["accepted"]


def test_duplicate_tasks_cannot_supply_missing_coverage():
    value = report()
    value["task_count"] = 2
    for variant in value["variants"]:
        variant["tasks"] *= 2
    assert not heldout_acceptance(value)["accepted"]
