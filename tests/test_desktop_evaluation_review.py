"""Native comparison uses actual evidence, not headline scores or claimed approval."""

from copy import deepcopy
import json

import pytest

from superqode.desktop_service.evaluation_review import (
    evaluation_comparison,
    review_artifact,
)
from test_desktop_service import desktop  # noqa: F401


def task(identity="case", status="passed", split="held-out"):
    return {"id": identity, "status": status, "split": split, "reason": status}


def report(before=None, after=None):
    return {
        "live": True,
        "baseline": "baseline",
        "tasks_hash": "suite-v1",
        "task_count": len(before) if before is not None else 1,
        "variants": [
            {
                "harness": "baseline",
                "tasks": [task()] if before is None else before,
                "cost_usd": 0.2,
                "duration_seconds": 2,
            },
            {
                "harness": "candidate",
                "tasks": [task()] if after is None else after,
                "cost_usd": 0.1,
                "duration_seconds": 3,
            },
        ],
    }


@pytest.mark.parametrize(
    "before", ["passed", "failed", "error", "skipped", "abstained", "ungraded", "unknown"]
)
@pytest.mark.parametrize(
    "after", ["passed", "failed", "error", "skipped", "abstained", "ungraded", "unknown"]
)
def test_outcomes_require_matching_graded_evidence(before, after):
    comparison = evaluation_comparison(report([task(status=before)], [task(status=after)]))
    candidate = comparison["candidates"][0]
    row = candidate["rows"][0]
    if before == "passed" and after in {"failed", "error", "skipped", "abstained", "ungraded"}:
        assert row["outcome"] == "regression"
        assert candidate["state"] == "regressed"
    elif before == "failed" and after == "passed":
        assert row["outcome"] == "improvement"
    elif before == after and before in {"passed", "failed"}:
        assert row["outcome"] == "unchanged"
    else:
        assert row["outcome"] == "unverified"
        assert candidate["state"] == "incomplete"
    assert "accepted" not in comparison and "accepted" not in candidate


def test_mixed_wins_regressions_and_unknowns_are_all_visible():
    data = report(
        [task("lost"), task("won", "failed"), task("same"), task("missing")],
        [task("won"), task("same"), task("lost", "failed"), task("extra")],
    )
    data["variants"][1]["score"] = 1  # A headline score cannot override task evidence.
    candidate = evaluation_comparison(data)["candidates"][0]
    assert candidate["counts"] == {
        "regression": 1,
        "improvement": 1,
        "unchanged": 1,
        "unverified": 2,
    }
    assert [row["id"] for row in candidate["rows"]] == ["lost", "won", "same", "missing", "extra"]
    assert candidate["cost_delta_usd"] == pytest.approx(-0.1)
    assert candidate["duration_delta_seconds"] == 1


@pytest.mark.parametrize("split", [None, "held-in", {}, []])
def test_missing_or_different_splits_cannot_claim_improvement(split):
    candidate = evaluation_comparison(report([task(status="failed")], [task(split=split)]))[
        "candidates"
    ][0]
    assert candidate["state"] == "incomplete"
    assert candidate["rows"][0]["outcome"] == "unverified"


def test_duplicate_ids_and_invalid_rows_are_not_silently_overwritten():
    candidate = evaluation_comparison(report([task(), task(), {}], [task(), task()]))["candidates"][
        0
    ]
    assert candidate["state"] == "incomplete"
    assert candidate["rows"][0]["outcome"] == "unverified"
    assert len(candidate["issues"]) == len(set(candidate["issues"])) == 3
    assert "Recorded tasks do not match the declared suite task count." in candidate["issues"]


@pytest.mark.parametrize(
    "cost", [None, True, False, -1, float("nan"), float("inf"), "0.1", 10**400]
)
def test_invalid_or_unknown_cost_never_becomes_zero(cost):
    data = report()
    data["variants"][1]["cost_usd"] = cost
    candidate = evaluation_comparison(data)["candidates"][0]
    assert candidate["candidate_cost_usd"] is None
    assert candidate["cost_delta_usd"] is None


def test_zero_cost_is_known_and_invalid_usage_objects_are_safe():
    data = report()
    data["variants"][1]["cost_usd"] = 0
    data["variants"][1]["usage"] = ["invalid"]
    candidate = evaluation_comparison(data)["candidates"][0]
    assert candidate["candidate_cost_usd"] == 0
    assert candidate["cost_delta_usd"] == -0.2


def test_multiple_candidates_are_compared_independently():
    data = report()
    data["variants"].append({"harness": "third", "tasks": [task(status="failed")]})
    comparison = evaluation_comparison(data)
    assert [row["state"] for row in comparison["candidates"]] == ["compared", "regressed"]


def test_setup_empty_and_malformed_results_are_explicit():
    data = report()
    data["live"] = False
    assert evaluation_comparison(data)["available"] is False
    for invalid in [
        None,
        {},
        {"heldout_eval": None},
        {"live": True},
        {"live": True, "variants": [{}, None]},
    ]:
        assert evaluation_comparison(invalid)["available"] is False
    data = report([], [])
    assert evaluation_comparison(data)["candidates"][0]["state"] == "incomplete"
    data["variants"][0]["tasks"] = None
    assert evaluation_comparison(data)["candidates"][0]["issues"]


def test_optimizer_requires_heldout_tasks_and_ignores_claimed_acceptance():
    data = {
        "accepted": True,
        "heldout_eval": report([task(split="held-in")], [task(split="held-in")]),
    }
    comparison = evaluation_comparison(data)
    assert comparison["scope"] == "held-out"
    assert comparison["candidates"][0]["state"] == "incomplete"
    data["heldout_eval"] = report([task()], [task(status="failed")])
    assert evaluation_comparison(data)["candidates"][0]["state"] == "regressed"


def test_smoke_only_checks_never_claim_task_quality_improvements():
    data = report([task(status="failed")], [task()])
    for variant in data["variants"]:
        row = variant["tasks"][0]
        row["evaluation"] = {
            "evaluator": "non_empty",
            "status": row["status"],
            "evidence": {"smoke_only": True},
        }
    candidate = evaluation_comparison(data)["candidates"][0]
    assert candidate["state"] == "incomplete"
    assert candidate["rows"][0]["outcome"] == "unverified"
    assert candidate["ungraded_pairs"] == 1
    assert "Smoke-only" in candidate["rows"][0]["reason"]


@pytest.mark.parametrize(
    "nested",
    [
        None,
        [],
        {"status": "ungraded"},
        {"status": "error"},
        {"status": "passed", "evaluator": "decision", "evidence": []},
    ],
)
def test_contradictory_or_malformed_evaluator_evidence_is_unverified(nested):
    data = report([task(status="failed")], [task()])
    data["variants"][1]["tasks"][0]["evaluation"] = nested
    row = evaluation_comparison(data)["candidates"][0]["rows"][0]
    assert row["outcome"] == "unverified"
    assert row["fully_graded"] is False


def test_real_evaluator_evidence_and_declared_task_coverage():
    data = report([task(status="failed")], [task()])
    for variant in data["variants"]:
        row = variant["tasks"][0]
        row["evaluation"] = {"status": row["status"], "evaluator": "decision", "evidence": {}}
    assert evaluation_comparison(data)["candidates"][0]["state"] == "compared"
    data["task_count"] = 100
    candidate = evaluation_comparison(data)["candidates"][0]
    assert candidate["state"] == "incomplete"
    assert "declared" in candidate["issues"][0]


def test_numeric_task_ids_preserve_type_and_avoid_string_collisions():
    identities = [42, "42", 3.5]
    data = report(
        [task(identity, "failed") for identity in identities],
        [task(identity) for identity in identities],
    )
    candidate = evaluation_comparison(data)["candidates"][0]
    assert candidate["counts"]["improvement"] == 3
    assert len({row["key"] for row in candidate["rows"]}) == 3
    assert [row["identity_type"] for row in candidate["rows"]] == ["integer", "string", "number"]


@pytest.mark.asyncio
async def test_actual_non_empty_evaluator_is_smoke_evidence():
    from superqode.harness.evaluators import evaluate_content

    before = await evaluate_content("", {"id": "case", "prompt": "Answer"})
    after = await evaluate_content("some text", {"id": "case", "prompt": "Answer"})
    data = report([task(status=before.status)], [task(status=after.status)])
    data["variants"][0]["tasks"][0]["evaluation"] = before.model_dump(mode="json")
    data["variants"][1]["tasks"][0]["evaluation"] = after.model_dump(mode="json")
    assert evaluation_comparison(data)["candidates"][0]["state"] == "incomplete"
    assert evaluation_comparison(data)["candidates"][0]["counts"]["improvement"] == 0


def test_actual_task_loader_preserves_supported_numeric_identities(tmp_path):
    from superqode.harness.eval import load_eval_tasks

    path = tmp_path / "tasks.yaml"
    path.write_text(
        'tasks:\n- {id: 42, prompt: Answer}\n- {id: "42", prompt: Answer}\n- {id: 3.5, prompt: Answer}\n'
    )
    identities = [row["id"] for row in load_eval_tasks(path)["tasks"]]
    data = report(
        [task(identity, "failed") for identity in identities],
        [task(identity) for identity in identities],
    )
    assert evaluation_comparison(data)["candidates"][0]["counts"]["improvement"] == 3


def test_inconsistent_baseline_and_excessive_projection_are_rejected():
    data = report()
    data["baseline"] = "other"
    assert evaluation_comparison(data)["available"] is False


def test_reason_previews_and_total_projection_are_bounded():
    data = report()
    data["variants"][0]["tasks"][0]["reason"] = "private detail " * 1000
    row = evaluation_comparison(data)["candidates"][0]["rows"][0]
    assert len(row["baseline_reason"]) == 1001
    data = report([task(str(i)) for i in range(10)], [task(str(i)) for i in range(10)])
    for row in data["variants"][0]["tasks"]:
        row["reason"] = "汉" * 1000
    data["variants"] += [deepcopy(data["variants"][1]) for _ in range(59)]
    assert len(data["variants"]) <= 64
    comparison = evaluation_comparison(data)
    assert comparison["available"] is False
    assert "too large" in comparison["message"]


def test_empty_candidate_overhead_is_also_bounded():
    data = report([], [])
    data["variants"] = [{"tasks": []}] * 65
    assert evaluation_comparison(data)["available"] is False


def test_native_execution_error_remains_a_regression_and_ungraded():
    data = report([task()], [task(status="error")])
    data["variants"][1]["tasks"][0]["evaluation"] = {
        "evaluator": "execution",
        "status": "error",
        "reason": "RuntimeError",
    }
    candidate = evaluation_comparison(data)["candidates"][0]
    assert candidate["state"] == "regressed"
    assert candidate["counts"]["regression"] == 1
    assert candidate["ungraded_pairs"] == 1


def test_optimizer_job_review_does_not_change_the_adoption_flag(desktop):
    service, project, _ = desktop
    original = {"accepted": True, "heldout_eval": report([task()], [task(status="failed")])}
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "optimizer",
            project["id"],
            "optimization",
            "optimizer",
            "completed",
            "{}",
            json.dumps(original),
            1,
            1,
        ),
    )
    result = service.dispatch("jobs.get", {"id": "optimizer"})["result"]
    assert result["accepted"] is True
    assert result["comparison"]["scope"] == "held-out"
    assert result["comparison"]["candidates"][0]["state"] == "regressed"
    data = report([task(str(i)) for i in range(5010)], [task()])
    data["variants"] *= 3
    assert evaluation_comparison(data)["available"] is False


@pytest.mark.parametrize(
    "wrapper",
    [
        lambda value: value,
        lambda value: {"result": value},
        lambda value: {"job": {"result": value}},
    ],
)
def test_imported_and_stored_results_get_the_same_review_without_mutation(desktop, wrapper):
    service, project, root = desktop
    original = report([task()], [task(status="failed")])
    artifact = wrapper(original)
    snapshot = deepcopy(artifact)
    path = root / "result.json"
    path.write_text(json.dumps(artifact))
    imported = service.dispatch("artifacts.read", {"project": project["id"], "path": str(path)})
    reviewed = imported.get("job", {}).get("result", imported.get("result", imported))
    assert reviewed["comparison"]["candidates"][0]["state"] == "regressed"
    assert json.loads(path.read_text()) == snapshot
    assert review_artifact(artifact) == imported
    assert artifact == snapshot
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "review",
            project["id"],
            "evaluation",
            "evaluation",
            "completed",
            "{}",
            json.dumps(original),
            1,
            1,
        ),
    )
    stored = service.dispatch("jobs.get", {"id": "review"})["result"]
    assert stored["comparison"] == reviewed["comparison"]
    assert (
        json.loads(service._all("SELECT result FROM jobs WHERE id='review'")[0]["result"])
        == original
    )
