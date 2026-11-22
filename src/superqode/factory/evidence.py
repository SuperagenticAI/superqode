"""Requirement coverage and observed outcomes over pinned Factory runs."""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from .runtime import factory_store, _pinned_plan
from .snapshot import canonical, digest
from .operations import ownership
from .maintenance import execution
from superqode.workorders.models import TERMINAL_WORK_ORDER_STATUSES
from superqode.workorders.usage import usage_from_artifacts


def _plan(root, order):
    if order.repository != str(Path(root).resolve()):
        raise ValueError("Factory run belongs to a different project")
    return _pinned_plan(order)


def trace(root, reference):
    """Read historical bindings; this report never grants release authority."""
    order = factory_store(root, read_only=True).get(reference)
    plan = _plan(root, order)
    definition = plan.snapshot.payload["definition"]
    receipt = order.metadata.get("factory_verification", {})
    artifact = next(
        (a for a in order.artifacts if a.artifact_id == receipt.get("artifact_id")), None
    )
    report = json.loads(artifact.content) if artifact else {}
    binding = report.get("binding", {})
    candidate = next(
        (a for a in reversed(order.artifacts) if a.kind == "integration_candidate"), None
    )
    evidence_bound = bool(
        artifact
        and artifact.kind == "factory_verification"
        and artifact.digest == digest(artifact.content)
        and binding == receipt.get("binding")
        and binding.get("factory_digest") == plan.snapshot.digest
        and candidate is not None
        and candidate.artifact_id == binding.get("candidate_id")
        and report.get("isolation_applied")
        and not report.get("missing_evidence")
    )
    check_rows = []
    from .verification import evaluator_contract

    try:
        expected, _ = evaluator_contract(plan)
    except ValueError:
        expected = {}
    for check in definition["orchestration"]["acceptance_checks"]:
        results = [r for r in report.get("results", []) if r.get("check") == check]
        ids = [r.get("id") for r in results]
        expected_ids = [r["id"] for r in expected.get(check, [])]
        complete = evidence_bound and bool(expected_ids) and sorted(ids) == sorted(expected_ids)
        check_rows.append(
            {
                "check": check,
                "category": definition["improvement"]["checks"][check].get("category", "test"),
                "status": (
                    "passed" if all(r.get("status") == "passed" for r in results) else "failed"
                )
                if complete
                else "missing",
                "verification_artifact": artifact.artifact_id if artifact else None,
                "cases": ids,
            }
        )
    rows = []
    for name, requirement in definition["data_context"].get("requirements", {}).items():
        stages = []
        for stage in requirement["stages"]:
            tasks = [t for t in order.tasks if t.metadata.get("factory_stage") == stage]
            stages.append(
                {
                    "stage": stage,
                    "tasks": [{"id": t.task_id, "status": t.status.value} for t in tasks],
                    "artifacts": [
                        a.artifact_id
                        for a in order.artifacts
                        if a.task_id in {t.task_id for t in tasks}
                    ],
                    "completed": any(t.status.value == "succeeded" for t in tasks)
                    and all(t.status.value in {"succeeded", "skipped"} for t in tasks),
                }
            )
        checks = [c for c in check_rows if c["check"] in requirement["checks"]]
        rows.append(
            {
                "id": name,
                "description": requirement["description"],
                "stages": stages,
                "checks": checks,
                "status": "covered"
                if all(s["completed"] for s in stages)
                and all(c["status"] == "passed" for c in checks)
                else "uncovered",
            }
        )
    return {
        "format": "superqode.factory-trace/1",
        "run": reference,
        "snapshot_digest": plan.snapshot.digest,
        "candidate": {
            key: binding.get(key) for key in ("candidate_id", "candidate_digest", "candidate_tree")
        },
        "historical_evidence_only": True,
        "requirements": rows,
        "application_checks": check_rows,
        "requirements_declared": bool(rows),
        "covered": sum(r["status"] == "covered" for r in rows),
        "release_authorized": False,
    }


def _usage(order):
    usage = usage_from_artifacts(order.artifacts).to_dict()
    for field, missing in (
        ("total_tokens", "unknown_token_runs"),
        ("cost_usd", "unknown_cost_runs"),
    ):
        if not usage["run_count"] or usage[missing]:
            usage[field] = None
    return usage


def record_outcome(root, reference, *, observation, outcome, human_minutes=None, actor):
    """Record an attributed business observation, distinct from verifier evidence."""
    if not isinstance(observation, str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", observation
    ):
        raise ValueError("Choose a bounded stable observation id")
    if outcome not in {"met", "not_met", "unknown"}:
        raise ValueError("Outcome must be met, not_met or unknown")
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise ValueError("Outcome needs bounded operator attribution")
    if human_minutes is not None and (
        type(human_minutes) not in {int, float}
        or not math.isfinite(human_minutes)
        or not 0 <= human_minutes <= 525600
    ):
        raise ValueError("Human minutes must be finite and nonnegative, or unknown")
    with execution(root), ownership(root):
        store = factory_store(root)
        order = store.get(reference)
        plan = _plan(root, order)
        if order.status not in TERMINAL_WORK_ORDER_STATUSES:
            raise ValueError("Observe an outcome after the run has finished")
        value = {
            "format": "superqode.factory-outcome/1",
            "run": reference,
            "observation": observation,
            "outcome": outcome,
            "human_minutes": human_minutes,
            "actor": actor,
            "snapshot_digest": plan.snapshot.digest,
            "application_revision": order.metadata["factory"]["repository_commit"],
        }
        for artifact in order.artifacts:
            if artifact.kind != "factory_outcome":
                continue
            if artifact.digest != digest(artifact.content):
                raise ValueError("Outcome evidence digest changed")
            old = json.loads(artifact.content)
            if old["observation"] != observation:
                raise ValueError("A run already has an outcome; do not count it twice")
            if any(old[k] != v for k, v in value.items()):
                raise ValueError("Observation id already binds a different outcome")
            return old
        value.update(
            observed_at=time.time(),
            usage=_usage(order),
            verification=order.metadata.get("factory_verification", {}).get("state", "missing"),
            operator_reported=True,
            cost_scope="Recorded run usage; optimization experiments and infrastructure are separate",
            release_authorized=False,
        )
        store.add_artifact(
            reference,
            kind="factory_outcome",
            content=canonical(value),
            digest=digest(canonical(value)),
            actor=actor,
        )
        return json.loads(canonical(value))


def outcomes(root):
    """Group observed outcomes by actual factory revision, without claiming causality."""
    store = factory_store(root, read_only=True)
    groups = {}
    orders = store.list(limit=1001)
    if len(orders) > 1000:
        raise ValueError("Select a project with at most 1000 runs for outcome reporting")
    for order in orders:
        for artifact in order.artifacts:
            if artifact.kind != "factory_outcome":
                continue
            if artifact.digest != digest(artifact.content):
                raise ValueError("Outcome evidence digest changed")
            value = json.loads(artifact.content)
            plan = _plan(root, order)
            if (
                value["snapshot_digest"] != plan.snapshot.digest
                or value["run"] != order.work_order_id
            ):
                raise ValueError("Outcome evidence differs from its pinned run")
            groups.setdefault(plan.snapshot.digest, []).append(value)
    rows = []
    for revision, observations in groups.items():

        def total(field):
            values = [
                v["human_minutes"] if field == "human_minutes" else v["usage"][field]
                for v in observations
            ]
            return sum(values) if all(v is not None for v in values) else None

        rows.append(
            {
                "snapshot_digest": revision,
                "runs": len(observations),
                "outcomes": {
                    k: sum(v["outcome"] == k for v in observations)
                    for k in ("met", "not_met", "unknown")
                },
                "human_minutes": total("human_minutes"),
                "cost_usd": total("cost_usd"),
                "total_tokens": total("total_tokens"),
                "observations": observations,
            }
        )
    return {
        "format": "superqode.factory-outcomes/1",
        "revisions": rows,
        "causal_improvement_established": False,
        "release_authorized": False,
    }
