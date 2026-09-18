"""Sanitized permission evidence and comparisons; execution is not a safety label."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import resolve_systemone
from .state import prepare_decision_state

logger = logging.getLogger(__name__)


def finish_trace(loop: Any, call_id: str | None, action: str, result: Any = None) -> None:
    settings = resolve_systemone(
        spec=getattr(loop.config, "harness_spec", None),
        explicit=getattr(loop.config, "systemone", None),
    )
    if not settings.enabled:
        return
    event = getattr(loop, "last_systemone_decision", None)
    if event is None:
        if result is None:
            return
        event = {
            "tool": result.metadata.get("tool"),
            "mode": settings.mode,
            "intendedAction": None,
            "policyAction": action,
            "evaluation": {"status": "skipped"},
            "reason": result.metadata.get("permission"),
        }
        loop.last_systemone_decision = event
    event.update(
        trace_id=uuid4().hex,
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=getattr(loop, "session_id", ""),
        tool_call_id=call_id,
        permissionAction=action,
    )
    if not settings.trace_dir:
        return
    try:
        # A separate file per decision avoids interleaved writes from simultaneous sessions.
        directory = Path(settings.trace_dir)
        directory.mkdir(parents=True, exist_ok=True)
        payload = prepare_decision_state(event)
        path = directory / f"{event['trace_id']}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
    except (OSError, ValueError):
        logger.warning("System One trace could not be recorded")


def disagreement_report(
    events: list[dict[str, Any]], reference: str = "policyAction"
) -> dict[str, Any]:
    """Compare only evaluated decisions with explicit labels; unknowns stay unknown."""
    if reference not in {"policyAction", "humanAction"}:
        raise ValueError("reference must be policyAction or humanAction")
    evaluated = [
        e
        for e in events
        if e.get("evaluation", {}).get("status") == "success"
        and e.get("intendedAction") in {"allow", "deny", "ask"}
    ]
    labelled = [e for e in evaluated if e.get(reference) in {"allow", "deny", "ask"}]
    matrix = Counter(f"{e[reference]}->{e['intendedAction']}" for e in labelled)
    latencies = sorted(
        e["evaluation"]["latency_ms"]
        for e in evaluated
        if isinstance(e["evaluation"].get("latency_ms"), (int, float))
    )
    buckets = {}
    for lower, upper in ((0.0, 0.5), (0.5, 0.75), (0.75, 0.9), (0.9, 1.01)):
        members = [
            e
            for e in labelled
            if isinstance(e.get("confidence"), (int, float)) and lower <= e["confidence"] < upper
        ]
        buckets[f"{lower:.2f}-{min(upper, 1.0):.2f}"] = {
            "labelled": len(members),
            "disagreements": sum(e[reference] != e["intendedAction"] for e in members),
            "allow_against_deny": sum(
                e[reference] == "deny" and e["intendedAction"] == "allow" for e in members
            ),
        }
    return {
        "confidence_buckets": buckets,
        "reference": reference,
        "total": len(events),
        "evaluated": len(evaluated),
        "labelled": len(labelled),
        "unlabelled": len(evaluated) - len(labelled),
        "errors": sum(e.get("evaluation", {}).get("status") == "error" for e in events),
        "skipped": len(events)
        - len(evaluated)
        - sum(e.get("evaluation", {}).get("status") == "error" for e in events),
        "disagreements": sum(e[reference] != e["intendedAction"] for e in labelled),
        "allow_against_deny": matrix["deny->allow"],
        "deny_against_allow": matrix["allow->deny"],
        "allow_against_ask": matrix["ask->allow"],
        "ask_rate": sum(e["intendedAction"] == "ask" for e in evaluated) / len(evaluated)
        if evaluated
        else None,
        "latency_p50_ms": latencies[(len(latencies) - 1) // 2] if latencies else None,
        "confusion_matrix": dict(sorted(matrix.items())),
    }


def distribution_diagnostics(probabilities: dict[str, float]) -> dict[str, float | None]:
    """Describe ties and spread without interpreting them as safety."""
    import math

    values = sorted(probabilities.values(), reverse=True)
    return {
        "top_probability": values[0] if values else None,
        "top_two_margin": values[0] - values[1] if len(values) > 1 else None,
        "entropy": -sum(p * math.log(p) for p in values if p > 0),
    }


def confidence_sweep(
    events: list[dict[str, Any]], thresholds: tuple[float, ...], reference: str
) -> list[dict[str, Any]]:
    """Recompose recorded answers offline; never change packs or runtime policy."""
    from .compose import compose_tool_gate
    from .pack import ToolGateThresholds
    from .types import Answers

    reports = []
    for threshold in thresholds:
        replayed = []
        for event in events:
            if event.get("evaluation", {}).get("status") != "success":
                continue
            if not event.get("answers") or not event.get("thresholds"):
                continue
            limits = ToolGateThresholds.model_validate(event["thresholds"])
            limits = limits.model_copy(update={"allow_confidence": threshold})
            answers = Answers.model_validate({"answers": event["answers"]})
            decision = compose_tool_gate(answers, thresholds=limits)
            replayed.append({**event, "intendedAction": decision.action.value})
        reports.append(
            {
                "allow_confidence": threshold,
                "excluded": len(events) - len(replayed),
                **disagreement_report(replayed, reference),
            }
        )
    return reports
