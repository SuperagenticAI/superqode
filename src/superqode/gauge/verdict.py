"""Verdicts and release bindings for Agent Quality Records.

Deterministic gates decide whether a record may say ``ship``. Model judges are
advisory reviewers: they may hold or reject a candidate, never approve it. A
``ship`` verdict is a quality recommendation only; a named human still signs the
release.
"""

from __future__ import annotations

from typing import Any, Iterable

from .levels import LEVELS, check_levels, release_failures

VERDICTS = ("ship", "hold", "reject")
JUDGE_VERDICTS = frozenset({"hold", "reject", "no_objection"})
_APPROVALS = frozenset({"ship", "approve", "approved", "pass", "accept", "accepted", "release"})


def judge_effect(judge: dict[str, Any]) -> str:
    """Validate one model judge result. Judges can only hold, reject or not object."""
    verdict = str((judge or {}).get("verdict", "")).strip().lower()
    if verdict in _APPROVALS:
        raise ValueError("Model judges may hold or reject a release but never approve it")
    if verdict not in JUDGE_VERDICTS:
        raise ValueError("Model judge verdict must be hold, reject or no_objection")
    if not (judge.get("id") and judge.get("model")):
        raise ValueError("Model judge results must name the judge id and model")
    return verdict


def decide(
    *,
    gates: Iterable[dict[str, Any]],
    reject_reasons: Iterable[str] = (),
    hold_reasons: Iterable[str] = (),
    judges: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Combine deterministic evidence and advisory judges into ship, hold or reject.

    Ship needs every deterministic gate to pass and no hold or reject reason.
    A judge can only make the verdict stricter.
    """
    gates = list(gates)
    reject = list(reject_reasons)
    hold = list(hold_reasons)
    judge_rows = []
    for judge in judges:
        effect = judge_effect(judge)
        judge_rows.append({"id": judge["id"], "model": judge["model"], "verdict": effect})
        if effect == "reject":
            reject.append(f"model judge {judge['id']} rejected the candidate")
        elif effect == "hold":
            hold.append(f"model judge {judge['id']} asked for a hold")
    if not gates:
        hold.append("no deterministic gates were recorded")
    failing = [str(g.get("id")) for g in gates if g.get("result") != "pass"]
    if failing and not reject:
        hold.append("gates not passing: " + ", ".join(failing))
    verdict = "reject" if reject else "hold" if hold else "ship"
    return {
        "verdict": verdict,
        "reasons": reject + hold if verdict != "ship" else ["all deterministic gates passed"],
        "judges": judge_rows,
        "judge_policy": "Model judges may hold or reject; they never approve.",
    }


def binding_failures(
    record: dict[str, Any],
    *,
    factory_digest: str = "",
    candidate_id: str = "",
    candidate_digest: str = "",
) -> list[str]:
    """Check that a record describes the exact factory revision and candidate."""
    subject = record.get("subject") or {}
    candidate = subject.get("candidate") or {}
    problems = []
    if factory_digest and subject.get("factory_digest") != factory_digest:
        problems.append("SuperGauge record is stale: it is bound to a different factory revision")
    if candidate_id and candidate.get("id") != candidate_id:
        problems.append("SuperGauge record is stale: it is bound to a different candidate")
    if candidate_digest and candidate.get("digest") != candidate_digest:
        problems.append("SuperGauge record is stale: the candidate digest changed")
    return problems


def release_check(
    record: dict[str, Any] | None,
    *,
    level: str = "L2",
    require_ship: bool = True,
    factory_digest: str = "",
    candidate_id: str = "",
    candidate_digest: str = "",
) -> list[str]:
    """Every reason this record cannot back a release. Empty means the record may.

    A clean result does not approve anything; a human signature is still required.
    """
    if not record:
        return ["No SuperGauge record exists for the current candidate; run verification"]
    if level not in LEVELS:
        raise ValueError("Gauge release level must be L1, L2, L3 or L4")
    problems = binding_failures(
        record,
        factory_digest=factory_digest,
        candidate_id=candidate_id,
        candidate_digest=candidate_digest,
    )
    failures = check_levels(record)
    for lv in LEVELS[: LEVELS.index(level) + 1]:
        problems.extend(f"SuperGauge {lv} not met: {item}" for item in failures[lv])
    if require_ship:
        decision = record.get("decision") or {}
        if decision.get("verdict") != "ship":
            reasons = "; ".join(decision.get("reasons") or []) or "no reason recorded"
            problems.append(
                f"SuperGauge verdict is {decision.get('verdict') or 'missing'}: {reasons}"
            )
        problems.extend(
            f"SuperGauge release check: {item}"
            for item in release_failures(record)
            if "verdict" not in item
        )
    return list(dict.fromkeys(problems))
