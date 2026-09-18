"""Explicit task evaluators, including labelled decision outputs."""

from __future__ import annotations

import json
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
    if kind not in {"decision", "contains", "non_empty", "jev_rubric"}:
        raise ValueError(f"Unknown evaluator type: {kind}")
    if kind == "decision" and not (isinstance(config.get("expected"), dict) and config["expected"]):
        raise ValueError("decision evaluator requires non-empty expected outputs")
    if kind == "jev_rubric" and not str(config.get("rubric") or "").strip():
        raise ValueError("jev_rubric evaluator requires rubric")
    if kind == "contains" and not config.get("expected"):
        raise ValueError("contains evaluator requires expected text")


async def evaluate_content(content: str, task: dict[str, Any], *, spec=None) -> EvaluationResult:
    validate_evaluator(task)
    config = task.get("evaluator") or {}
    kind = config.get("type") or ("contains" if task.get("expect_contains") else "non_empty")
    if kind == "jev_rubric":
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
