"""Read release-decision evidence out of SuperQode's existing stores.

The record fields that carry the most weight — who accepted the result, what to
revert to, and whether policy held — already exist in SuperQode. They live in
the promotion registry, the governance decision path and the harness protocol
ledger. This module reads them so `gauge run` reports what happened rather than
asking an operator to retype it.

Every reader here degrades to None or an empty result when its store is absent.
A record built without a promotion, or without a policy engine, is a weaker
record at a lower conformance level, which is the accurate outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_LEDGER_DIR = Path(".superqode") / "harness-protocol"


def promotion_evidence(
    *,
    base_spec: str | Path | None = None,
    candidate_id: str = "",
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    """Read the staged or activated promotion covering this spec.

    Returns the actor who moved it, the digest to revert to, and the recorded
    status. The rollback target is the *base* digest: the version in force
    before this candidate, which is what a reader needs when the candidate
    turns out to be wrong.
    """
    try:
        from superqode.harness.promotion import (
            DEFAULT_PROMOTION_REGISTRY,
            harness_promotion_state,
        )
    except ImportError:  # pragma: no cover - promotion is optional
        return {}

    registry = Path(registry_path or DEFAULT_PROMOTION_REGISTRY)
    if not registry.exists():
        return {}

    try:
        state = harness_promotion_state(candidate_id, base_spec=base_spec, registry_path=registry)
    except (ValueError, OSError):
        return {}

    evidence: dict[str, Any] = {}
    if state.get("actor"):
        evidence["actor"] = str(state["actor"])
    if state.get("base_digest"):
        evidence["rolls_back_to"] = _as_digest(state["base_digest"])
    if state.get("candidate_id"):
        evidence["candidate_id"] = str(state["candidate_id"])
    if state.get("status"):
        evidence["status"] = str(state["status"])
    if state.get("snapshot"):
        evidence["snapshot"] = str(state["snapshot"])

    audit = state.get("audit") or {}
    if isinstance(audit, dict) and audit.get("eval_gates"):
        evidence["eval_gates"] = audit["eval_gates"]
    return evidence


def _as_digest(value: str) -> str:
    """The promotion registry stores bare hex; the record wants a prefix."""
    text = str(value)
    return text if text.startswith("sha256:") else f"sha256:{text}"


def policy_decisions(
    *,
    repository: str | Path = ".",
    phases: tuple[str, ...] = ("request", "response", "tool_call", "tool_result"),
) -> list[dict[str, Any]]:
    """Report what the governance engine would decide for this repository.

    This reads the policy in force and records the default disposition per
    phase. It is an assertion about configuration, not a replay of a run: where
    a run's own decision log exists, prefer `policy_decisions_from_ledger`.
    """
    try:
        from superqode.governance import PolicyRequest, load_governance
    except ImportError:  # pragma: no cover
        return []

    try:
        bundle = load_governance(repository)
    except Exception:
        return []

    decisions: list[dict[str, Any]] = []
    for phase in phases:
        try:
            decision = bundle.engine.evaluate(PolicyRequest(phase=phase, arguments={}))
        except Exception:
            continue
        decisions.append(
            {
                "phase": phase,
                "action": getattr(decision, "action", "allow"),
                "reason": getattr(decision, "reason", ""),
            }
        )
    return decisions


def policy_decisions_from_ledger(
    ledger_dir: str | Path = DEFAULT_LEDGER_DIR,
) -> list[dict[str, Any]]:
    """Read the decisions a run actually produced, where the ledger kept them."""
    root = Path(ledger_dir)
    if not root.exists():
        return []

    decisions: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if str(event.get("type", "")).startswith("policy."):
                    payload = event.get("data") or event
                    decisions.append(
                        {
                            "phase": payload.get("phase", ""),
                            "action": payload.get("action", "allow"),
                            "reason": payload.get("reason", ""),
                        }
                    )
        except (OSError, json.JSONDecodeError):
            continue
    return decisions


def ledger_evidence(ledger_dir: str | Path = DEFAULT_LEDGER_DIR) -> dict[str, Any]:
    """Locate the event ledger and count what it holds.

    L4 asks for a referenced ledger with an event count, so that a third party
    knows what they are being invited to replay. A ledger that cannot be found
    is reported as absent rather than assumed.
    """
    root = Path(ledger_dir)
    if not root.exists():
        return {}

    events = 0
    for path in root.rglob("*.jsonl"):
        try:
            with open(path, encoding="utf-8") as handle:
                events += sum(1 for line in handle if line.strip())
        except OSError:
            continue

    if not events:
        for path in root.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, list):
                events += len(data)
            elif isinstance(data, dict) and isinstance(data.get("events"), list):
                events += len(data["events"])

    if not events:
        return {}
    return {
        "ledger": str(root),
        "format": "superqode.harness-protocol/1",
        "events": events,
        "replayable": True,
    }
