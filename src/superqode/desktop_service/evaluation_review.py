"""Read-only task comparisons for native evaluation and held-out optimizer review.

These projections summarize recorded evidence; they never authorize promotion.
"""

from __future__ import annotations

import math
import json
from collections import Counter


def _text(value, limit=1000):
    return (
        value
        if isinstance(value, str) and len(value) <= limit
        else value[:limit] + "…"
        if isinstance(value, str)
        else ""
    )


def _metric(record, key):
    usage = record.get("usage")
    value = record.get(key, usage.get(key) if isinstance(usage, dict) else None)
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def _identity(value):
    if isinstance(value, str) and value.strip() and len(value) <= 256:
        return ("string", value)
    if type(value) is int and value and value.bit_length() <= 840:
        return ("integer", value)
    if type(value) is float and value and math.isfinite(value):
        return ("number", value)
    return None


def _grading_issue(task):
    if not task or "evaluation" not in task:
        return ""  # Older scorecards only recorded outer task outcomes.
    evaluation = task["evaluation"]
    if not isinstance(evaluation, dict) or evaluation.get("status") != task.get("status"):
        return "Evaluator evidence is malformed or contradicts the recorded status."
    evidence = evaluation.get("evidence", {})
    if not isinstance(evidence, dict):
        return "Evaluator evidence is malformed."
    if evaluation.get("evaluator") == "non_empty" or evidence.get("smoke_only") is True:
        return "Smoke-only checks do not establish task quality."
    if "smoke_only" in evidence and type(evidence["smoke_only"]) is not bool:
        return "Evaluator evidence is malformed."
    method = evaluation.get("evaluator")
    if method == "execution" and task.get("status") == "error":
        return ""  # An operational failure is not graded, but loses a baseline success.
    if not isinstance(method, str) or method not in {"contains", "decision", "jev_rubric"}:
        return "The grading method is missing or unsupported."
    return ""


def _tasks(variant):
    rows = variant.get("tasks")
    if not isinstance(rows, list):
        return {}, set(), ["Task evidence is missing."]
    indexed, duplicates, issues = {}, set(), []
    for row in rows:
        identity = _identity(row.get("id")) if isinstance(row, dict) else None
        if identity is None:
            issues.append("A task is missing a valid identity.")
            continue
        if identity in indexed:
            duplicates.add(identity)
        indexed[identity] = row
    if duplicates:
        issues.append("Duplicate task identities prevent reliable matching.")
    return indexed, duplicates, issues


def evaluation_comparison(result):
    if not isinstance(result, dict):
        return {"available": False, "message": "No evaluation evidence recorded."}
    heldout = "heldout_eval" in result
    data = result.get("heldout_eval") if heldout else result
    if not isinstance(data, dict) or not data:
        return {"available": False, "message": "No held-out evaluation evidence recorded."}
    if data.get("live") is not True:
        return {"available": False, "message": "Setup checks do not measure task outcomes."}
    variants = data.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return {
            "available": False,
            "message": "Evaluate a baseline and a candidate to compare tasks.",
        }
    if not all(isinstance(variant, dict) for variant in variants):
        return {"available": False, "message": "Configuration evidence is malformed."}
    if len(variants) > 64:
        return {
            "available": False,
            "message": "This report has too many configurations for task comparison. Inspect full evidence.",
        }
    baseline = variants[0]

    def task_count(variant):
        return len(variant["tasks"]) if isinstance(variant.get("tasks"), list) else 0

    if sum(task_count(baseline) + task_count(candidate) for candidate in variants[1:]) > 10_000:
        return {
            "available": False,
            "message": "This report is too large for task comparison. Inspect full evidence.",
        }
    if data.get("baseline") and data["baseline"] != baseline.get("harness"):
        return {
            "available": False,
            "message": "The declared baseline does not match the recorded order.",
        }
    base_tasks, base_duplicates, base_issues = _tasks(baseline)
    candidates = []
    projected_bytes = 0
    for index, candidate in enumerate(variants[1:], 1):
        tasks, duplicates, issues = _tasks(candidate)
        issues = list(dict.fromkeys(base_issues + issues))
        declared = data.get("task_count")
        if type(declared) is not int or declared < 0:
            issues.append(
                "Suite task count is missing or invalid; completeness cannot be verified."
            )
        elif len(base_tasks) != declared or len(tasks) != declared:
            issues.append("Recorded tasks do not match the declared suite task count.")
        rows = []
        for identity in dict.fromkeys([*base_tasks, *tasks]):
            before, after = base_tasks.get(identity), tasks.get(identity)
            b_status = _text((before or {}).get("status"), 40) or "missing"
            c_status = _text((after or {}).get("status"), 40) or "missing"
            split = (before or after or {}).get("split")
            reason = ""
            grading_issue = _grading_issue(before) or _grading_issue(after)
            outcome = "unverified"
            matched = bool(before and after)
            if not matched:
                reason = "Task evidence is missing from one configuration."
            elif identity in base_duplicates or identity in duplicates:
                reason = "This task identity occurs more than once."
            elif (
                not isinstance(split, str)
                or split not in {"held-in", "held-out"}
                or split != after.get("split")
            ):
                reason = "Task splits are missing or different."
            elif heldout and split != "held-out":
                reason = "Optimizer validation must use held-out evidence."
            elif grading_issue:
                reason = grading_issue
            elif b_status == "passed" and c_status in {
                "failed",
                "error",
                "skipped",
                "abstained",
                "ungraded",
            }:
                outcome = "regression"
            elif b_status == "failed" and c_status == "passed":
                outcome = "improvement"
            elif b_status == c_status and b_status in {"passed", "failed"}:
                outcome = "unchanged"
            else:
                reason = "One or both task outcomes are ungraded or unknown."
            rows.append(
                {
                    "key": json.dumps(identity, ensure_ascii=True),
                    "id": str(identity[1]),
                    "identity_type": identity[0],
                    "split": split if isinstance(split, str) else "unknown",
                    "baseline_status": b_status,
                    "candidate_status": c_status,
                    "outcome": outcome,
                    "fully_graded": not grading_issue
                    and b_status in {"passed", "failed"}
                    and c_status in {"passed", "failed"},
                    "reason": reason,
                    "baseline_reason": _text((before or {}).get("reason")),
                    "candidate_reason": _text((after or {}).get("reason")),
                }
            )
            projected_bytes += len(json.dumps(rows[-1], ensure_ascii=True).encode())
            if projected_bytes > 2_000_000:
                return {
                    "available": False,
                    "message": "This report is too large for task comparison. Inspect full evidence.",
                }
        counts = Counter(row["outcome"] for row in rows)
        incomplete = (
            bool(issues)
            or not rows
            or any(not row["fully_graded"] for row in rows)
            or bool(counts["unverified"])
        )
        b_cost, c_cost = _metric(baseline, "cost_usd"), _metric(candidate, "cost_usd")
        b_time, c_time = (
            _metric(baseline, "duration_seconds"),
            _metric(candidate, "duration_seconds"),
        )
        candidates.append(
            {
                "index": index,
                "name": _text(candidate.get("harness"), 256) or f"Candidate {index}",
                "state": "regressed"
                if counts["regression"]
                else "incomplete"
                if incomplete
                else "compared",
                "counts": {
                    key: counts[key]
                    for key in ("regression", "improvement", "unchanged", "unverified")
                },
                "ungraded_pairs": sum(not row["fully_graded"] for row in rows),
                "issues": issues,
                "rows": rows,
                "baseline_cost_usd": b_cost,
                "candidate_cost_usd": c_cost,
                "cost_delta_usd": round(c_cost - b_cost, 8)
                if b_cost is not None and c_cost is not None
                else None,
                "baseline_duration_seconds": b_time,
                "candidate_duration_seconds": c_time,
                "duration_delta_seconds": round(c_time - b_time, 3)
                if b_time is not None and c_time is not None
                else None,
            }
        )
        projected_bytes += len(
            json.dumps(
                {key: value for key, value in candidates[-1].items() if key != "rows"},
                ensure_ascii=True,
            ).encode()
        )
        if projected_bytes > 2_000_000:
            return {
                "available": False,
                "message": "This report is too large for task comparison. Inspect full evidence.",
            }
    return {
        "available": True,
        "baseline": _text(baseline.get("harness"), 256) or "Baseline",
        "scope": "held-out" if heldout else "evaluation",
        "tasks_hash": data.get("tasks_hash") if isinstance(data.get("tasks_hash"), str) else None,
        "candidates": candidates,
        "message": "Observed task outcomes, not a promotion decision or a billing guarantee.",
    }


def with_evaluation_comparison(result):
    if not isinstance(result, dict):
        return result
    return {**result, "comparison": evaluation_comparison(result)}


def review_artifact(artifact):
    """Support the result shapes accepted by Open result without modifying the file."""
    if not isinstance(artifact, dict):
        return artifact
    if isinstance(artifact.get("job"), dict) and isinstance(artifact["job"].get("result"), dict):
        return {
            **artifact,
            "job": {
                **artifact["job"],
                "result": with_evaluation_comparison(artifact["job"]["result"]),
            },
        }
    if isinstance(artifact.get("result"), dict):
        return {**artifact, "result": with_evaluation_comparison(artifact["result"])}
    return with_evaluation_comparison(artifact)
