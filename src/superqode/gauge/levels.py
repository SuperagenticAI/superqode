"""Conformance level checks for an Agent Quality Record.

Mirrors `conformance/check.py` in the SuperGauge repository. Kept here so
`sq gauge gate` can decide in CI without a second dependency, and so a record
SuperQode emits is checked by the same rules a third party would apply.
"""

from __future__ import annotations

import re
from typing import Any

LEVELS = ("L1", "L2", "L3", "L4")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
MODEL_GRADED = frozenset({"answer.grounded", "robustness.multi_turn"})

REQUIRED_BLOCKS = (
    "supergauge",
    "record_id",
    "emitted_at",
    "profile",
    "subject",
    "task_set",
    "measures",
    "gates",
    "assurance",
    "decision",
)


def _l1(record: dict[str, Any]) -> list[str]:
    problems = [f"missing required block: {k}" for k in REQUIRED_BLOCKS if k not in record]

    subject = record.get("subject") or {}
    task_set = record.get("task_set") or {}
    for label, value in (
        ("subject.harness_digest", subject.get("harness_digest")),
        ("task_set.manifest_digest", task_set.get("manifest_digest")),
    ):
        if not value or not DIGEST.match(str(value)):
            problems.append(f"{label} is not a full sha256 digest")

    if not (subject.get("authority") or {}):
        problems.append("subject.authority is empty; the record cannot say what the agent could do")

    profile = record.get("profile") or {}
    tier = profile.get("tier")
    if tier not in {"T0", "T1", "T2"}:
        problems.append("profile.tier must be T0, T1 or T2")
    if not profile.get("version"):
        problems.append("profile.version is unset, so the governing rules are unpinned")

    # SPEC 4.1. The published schema encodes these, so a record breaking one is
    # malformed and never reaches L1.
    decision = record.get("decision") or {}
    if decision.get("verdict") == "ship":
        failed = [str(g.get("id")) for g in record.get("gates") or [] if g.get("result") != "pass"]
        if failed:
            problems.append(f"ship verdict with failing gates: {', '.join(failed)}")
        if not task_set.get("sealed"):
            problems.append("ship verdict over an unsealed held-out split")

    # SPEC 4.4. Tier T2 records a decision, not only an approval.
    if tier == "T2":
        for required in ("question", "options", "rationale", "signature"):
            if not decision.get(required):
                problems.append(f"tier T2 requires decision.{required}")

    return problems


def _l2(record: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    task_set = record.get("task_set") or {}
    gates = record.get("gates") or []
    decision = record.get("decision") or {}
    reported = {m.get("id") for m in record.get("measures") or []}

    if not gates:
        problems.append("no gates recorded")
    for gate in gates:
        if gate.get("id") in MODEL_GRADED:
            problems.append(f"gate {gate.get('id')} is model-graded and cannot back a gate")
        if gate.get("floor") is not None and gate.get("id") not in reported:
            problems.append(f"gate {gate.get('id')} sets a floor but no such measure is reported")

    if not task_set.get("sealed"):
        problems.append("held-out split is not sealed")
    if not task_set.get("held_out"):
        problems.append("no held-out split recorded")
    if not task_set.get("canary_ids"):
        problems.append("no contamination probes recorded")

    return problems


def _l3(record: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    measures = record.get("measures") or []
    assurance = record.get("assurance") or {}
    by_id = {m.get("id"): m for m in measures}

    pass_hat_k = by_id.get("reliability.pass_hat_k")
    if pass_hat_k is None:
        problems.append("reliability.pass_hat_k not reported")
    elif not pass_hat_k.get("k"):
        problems.append("reliability.pass_hat_k reported without k")
    elif int(pass_hat_k["k"]) < 2:
        problems.append("reliability.pass_hat_k requires k of at least 2")

    if not assurance.get("evaluator_independent"):
        problems.append("assurance.evaluator_independent is not asserted")

    if any(m.get("id") in MODEL_GRADED for m in measures):
        judge = assurance.get("judge") or {}
        if not judge:
            problems.append("model-graded measures reported without a judge record")
        else:
            if not judge.get("id") or not judge.get("model"):
                problems.append("judge record does not pin an id and a model")
            if judge.get("human_agreement_kappa") is None:
                problems.append("judge record carries no human agreement statistic")

    return problems


def _l4(record: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    decision = record.get("decision") or {}
    evidence = (record.get("assurance") or {}).get("evidence") or {}

    if not decision.get("signature"):
        problems.append("record is unsigned")
    if not decision.get("rolls_back_to"):
        problems.append("no rollback target recorded")
    if not evidence.get("ledger"):
        problems.append("no ledger referenced")
    if not evidence.get("replayable"):
        problems.append("evidence is not marked replayable")
    if not evidence.get("events"):
        problems.append("ledger referenced without an event count")

    return problems


def check_levels(record: dict[str, Any]) -> dict[str, list[str]]:
    """Return the failures at each level. An empty list means the level is met."""
    return {"L1": _l1(record), "L2": _l2(record), "L3": _l3(record), "L4": _l4(record)}


def highest_level(record: dict[str, Any]) -> str | None:
    """The highest cumulative level met, or None."""
    failures = check_levels(record)
    reached: str | None = None
    for level in LEVELS:
        if failures[level]:
            break
        reached = level
    return reached
