"""Fail-closed acceptance of a candidate against sealed, graded held-out tasks."""

from __future__ import annotations


def heldout_acceptance(report: dict) -> dict:
    if not isinstance(report, dict):
        report = {}
    issues = []
    variants = report.get("variants")
    count = report.get("task_count")
    if report.get("live") is not True or report.get("split") != "held-out":
        issues.append("A live held-out evaluation is required.")
    if type(count) is not int or count < 1:
        issues.append("A non-empty held-out task count is required.")
    if not isinstance(variants, list) or len(variants) < 2:
        return {
            "accepted": False,
            "issues": issues + ["Baseline and candidate are required."],
            "baseline_score": 0.0,
            "candidate_score": 0.0,
            "regressions": [],
        }
    indexed = []
    for variant in variants[:2]:
        tasks = variant.get("tasks") if isinstance(variant, dict) else None
        rows = {}
        if not isinstance(tasks, list) or len(tasks) != count:
            issues.append("Held-out task coverage is incomplete.")
        for row in tasks if isinstance(tasks, list) else []:
            if not isinstance(row, dict):
                issues.append("Malformed task evidence.")
                continue
            identity = row.get("id")
            if (
                not isinstance(identity, (str, int))
                or isinstance(identity, bool)
                or not str(identity)
            ):
                issues.append("Invalid task identity.")
                continue
            if identity in rows:
                issues.append("Duplicate task identity.")
            rows[identity] = row
            evaluation = row.get("evaluation")
            evidence = evaluation.get("evidence", {}) if isinstance(evaluation, dict) else {}
            if (
                row.get("split") != "held-out"
                or row.get("status") not in ("passed", "failed")
                or not isinstance(evaluation, dict)
                or evaluation.get("status") != row.get("status")
                or evaluation.get("evaluator") not in ("contains", "decision", "jev_rubric")
                or not isinstance(evidence, dict)
                or evidence.get("smoke_only", False) is not False
            ):
                issues.append("Every held-out task needs consistent, non-smoke grading evidence.")
        indexed.append(rows)
    before, after = indexed
    if set(before) != set(after):
        issues.append("Baseline and candidate task identities differ.")
    regressions = [
        key
        for key in before.keys() & after.keys()
        if before[key].get("status") == "passed" and after[key].get("status") != "passed"
    ]
    if regressions:
        issues.append("The candidate regresses on baseline successes.")
    baseline_score = sum(row.get("status") == "passed" for row in before.values()) / max(
        len(before), 1
    )
    candidate_score = sum(row.get("status") == "passed" for row in after.values()) / max(
        len(after), 1
    )
    if candidate_score < baseline_score:
        issues.append("The candidate score is below the baseline.")
    return {
        "accepted": not issues,
        "issues": list(dict.fromkeys(issues)),
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "regressions": regressions,
    }
