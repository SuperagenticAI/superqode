"""Explicit task evaluators, including labelled decision outputs."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluator: str
    status: Literal["passed", "failed", "abstained", "error", "ungraded"]
    reason: str
    evidence: dict[str, Any] = {}


def validate_evaluator(task: dict[str, Any]) -> None:
    config = task.get("evaluator")
    if config is None:
        return
    if not isinstance(config, dict):
        raise ValueError("evaluator must be a mapping")
    kind = config.get("type")
    if kind not in {
        "decision",
        "review",
        "contains",
        "non_empty",
        "jev_rubric",
        "systemone_rubric",
        "repository",
    }:
        raise ValueError(f"Unknown evaluator type: {kind}")
    if kind == "repository":
        from .repository_grader import validate

        validate(config)
    if kind == "review":
        if config.get("expected_verdict") not in {"approved", "changes_requested"}:
            raise ValueError("review evaluator requires an explicit expected_verdict")
        issues = config.get("issue_contains", [])
        if (
            set(config)
            - {"type", "expected_verdict", "issue_contains", "output_names", "max_bytes"}
            or not isinstance(issues, list)
            or len(issues) > 8
            or any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in issues)
        ):
            raise ValueError("Invalid bounded review evaluator criteria")
        names = config.get("output_names", [])
        if (
            not isinstance(names, list)
            or len(names) > 16
            or any(
                not isinstance(n, str) or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", n) is None
                for n in names
            )
            or len(set(names)) != len(names)
        ):
            raise ValueError("Invalid named review outputs")
        maximum = config.get("max_bytes", 16000)
        if type(maximum) is not int or not 1 <= maximum <= 16000:
            raise ValueError("Invalid review output byte limit")
    if kind == "decision" and not (isinstance(config.get("expected"), dict) and config["expected"]):
        raise ValueError("decision evaluator requires non-empty expected outputs")
    if kind in {"jev_rubric", "systemone_rubric"} and not str(config.get("rubric") or "").strip():
        raise ValueError("jev_rubric evaluator requires rubric")
    if kind == "contains" and not config.get("expected"):
        raise ValueError("contains evaluator requires expected text")


async def evaluate_content(content: str, task: dict[str, Any], *, spec=None) -> EvaluationResult:
    validate_evaluator(task)
    config = task.get("evaluator") or {}
    kind = config.get("type") or ("contains" if task.get("expect_contains") else "non_empty")
    if kind == "review":
        from superqode.factory.contracts import check_value, parse_json

        try:
            lines = re.findall(r"^SUPERQODE_REVIEW:\s*(\{[^\n]*\})\s*$", content, re.MULTILINE)
            if len(lines) != 1:
                raise ValueError("Require exactly one typed review verdict")
            review = parse_json(lines[0])
            check_value({"type": "review", "max_bytes": config.get("max_bytes", 16000)}, review)
            outputs = re.findall(r"^SUPERQODE_OUTPUT:\s*(\{[^\n]*\})\s*$", content, re.MULTILINE)
            if config.get("output_names") or outputs:
                named = parse_json(outputs[0]) if len(outputs) == 1 else None
                if (
                    not isinstance(named, dict)
                    or not named
                    or any(v != review for v in named.values())
                    or (config.get("output_names") and set(named) != set(config["output_names"]))
                ):
                    raise ValueError("Missing or contradictory named review outputs")
        except (ValueError, TypeError, AttributeError):
            return EvaluationResult(
                evaluator=kind, status="error", reason="Malformed or contradictory typed review"
            )
        issues = "\n".join(review["issues"])
        passed = review["verdict"] == config["expected_verdict"] and all(
            v in issues for v in config.get("issue_contains", [])
        )
        return EvaluationResult(
            evaluator=kind,
            status="passed" if passed else "failed",
            reason="Matched labelled review" if passed else "Review differs from labelled criteria",
            evidence={"review": review},
        )
    if kind == "repository":
        return EvaluationResult(
            evaluator=kind,
            status="ungraded",
            reason="Repository grading requires an isolated live evaluation workspace",
        )
    if kind in {"jev_rubric", "systemone_rubric"}:
        from superqode.agent.rubric import evaluate_jev_rubric

        result = await evaluate_jev_rubric(config["rubric"], content, spec=spec)
        verdict = result.get("verdict")
        status = (
            "ungraded"
            if verdict == "ungraded"
            else ("passed" if verdict == "satisfied" else "failed")
        )
        return EvaluationResult(
            evaluator=kind, status=status, reason=result["reason"], evidence=result
        )
    if kind == "decision":
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError("Expected decision object")
            outputs = payload.get("outputs", payload)
            if not isinstance(outputs, dict):
                raise ValueError("Expected output object")
        except (ValueError, TypeError):
            return EvaluationResult(evaluator=kind, status="error", reason="Invalid decision JSON")
        evidence = {"expected": config["expected"], "decision": payload}
        if payload.get("status") == "abstain":
            return EvaluationResult(
                evaluator=kind, status="abstained", reason="Decision abstained", evidence=evidence
            )
        if "status" in payload and payload["status"] != "decided":
            return EvaluationResult(
                evaluator=kind,
                status="error",
                reason="Decision did not complete",
                evidence=evidence,
            )
        # JSON type equality matters: True must not satisfy a numeric label of 1.
        mismatches = [
            key
            for key, value in config["expected"].items()
            if key not in outputs or type(outputs[key]) is not type(value) or outputs[key] != value
        ]
        return EvaluationResult(
            evaluator=kind,
            status="failed" if mismatches else "passed",
            reason="Mismatched fields: " + ", ".join(mismatches)
            if mismatches
            else "Matched labelled outputs",
            evidence=evidence,
        )
    if kind == "contains":
        expected = config.get("expected", task.get("expect_contains"))
        values = expected if isinstance(expected, list) else [expected]
        passed = all(str(value) in content for value in values)
        reason = "matched expect_contains" if passed else "missing expected text"
    else:
        passed = bool(content.strip())
        reason = "non-empty response" if passed else "empty response"
    return EvaluationResult(
        evaluator=kind,
        status="passed" if passed else "failed",
        reason=reason,
        evidence={"smoke_only": kind == "non_empty"},
    )
