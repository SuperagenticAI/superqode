"""Guarded HarnessSpec staging, canary routing, activation, and rollback."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

from superqode.governance import PolicyRequest, load_governance

from .loader import load_harness_spec


PROMOTION_SCHEMA_VERSION = 1
DEFAULT_PROMOTION_REGISTRY = Path(".superqode") / "harnesses" / "promotions.jsonl"


def stage_harness_promotion(
    *,
    base_spec: str | Path,
    candidate_spec: str | Path,
    audit: dict[str, Any],
    registry_path: str | Path = DEFAULT_PROMOTION_REGISTRY,
    actor: str,
    reason: str = "",
) -> dict[str, Any]:
    """Stage one already-audited candidate and preserve a rollback snapshot."""
    if not actor.strip():
        raise ValueError("promotion actor is required")
    if not audit.get("accepted"):
        raise ValueError("candidate must pass the harness audit before staging")
    base = Path(base_spec).expanduser().resolve()
    candidate = Path(candidate_spec).expanduser().resolve()
    base_loaded = load_harness_spec(base)
    candidate_loaded = load_harness_spec(candidate)
    base_digest = _sha256_file(base)
    candidate_digest = _sha256_file(candidate)
    expected_candidate = Path(str(audit.get("candidate_spec") or "")).expanduser().resolve()
    expected_base = Path(str(audit.get("base_spec") or "")).expanduser().resolve()
    if expected_candidate != candidate or expected_base != base:
        raise ValueError("candidate audit does not describe the supplied base and candidate specs")
    registry = Path(registry_path).expanduser().resolve()
    snapshot_dir = registry.parent / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"{base_digest}.yaml"
    if not snapshot.exists():
        shutil.copyfile(base, snapshot)
    event = {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "event": "staged",
        "recorded_at": _now_iso(),
        "candidate_id": str(audit.get("candidate_id") or f"cand_{candidate_digest[:12]}"),
        "actor": actor.strip(),
        "reason": reason,
        "base_spec": str(base),
        "base_name": base_loaded.name,
        "base_digest": base_digest,
        "candidate_spec": str(candidate),
        "candidate_name": candidate_loaded.name,
        "candidate_digest": candidate_digest,
        "snapshot": str(snapshot),
        "audit": {
            "diff_fingerprint": audit.get("diff_fingerprint") or "",
            "changed_surfaces": audit.get("changed_surfaces") or [],
            "eval_gates": audit.get("eval_gates") or {},
            "warnings": audit.get("warnings") or [],
        },
    }
    _append_event(registry, event)
    return event


def start_harness_canary(
    candidate_id: str,
    *,
    percent: int,
    registry_path: str | Path = DEFAULT_PROMOTION_REGISTRY,
    actor: str,
    reason: str = "",
) -> dict[str, Any]:
    if not 1 <= percent <= 99:
        raise ValueError("canary percent must be between 1 and 99")
    state = harness_promotion_state(candidate_id, registry_path=registry_path)
    if state["status"] not in {"staged", "canary"}:
        raise ValueError(f"cannot start canary from {state['status']}")
    event = {
        **_event_identity(state),
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "event": "canary",
        "recorded_at": _now_iso(),
        "actor": actor.strip(),
        "reason": reason,
        "canary_percent": percent,
    }
    _append_event(Path(registry_path).expanduser().resolve(), event)
    return event


def activate_harness_promotion(
    candidate_id: str,
    *,
    evidence_paths: Iterable[str | Path],
    registry_path: str | Path = DEFAULT_PROMOTION_REGISTRY,
    actor: str,
    repository: str | Path = ".",
    reason: str = "",
) -> dict[str, Any]:
    """Activate a canary only after live held-out evidence and policy approval."""
    registry = Path(registry_path).expanduser().resolve()
    state = harness_promotion_state(candidate_id, registry_path=registry)
    if state["status"] != "canary":
        raise ValueError("candidate must be in canary state before activation")
    evidence = _validate_promotion_evidence(state, evidence_paths)
    bundle = load_governance(repository)
    decision = bundle.engine.evaluate(
        PolicyRequest(
            phase="promotion",
            arguments={
                "candidate_id": candidate_id,
                "base_spec": state["base_spec"],
                "candidate_spec": state["candidate_spec"],
                "canary_percent": state["canary_percent"],
            },
        )
    )
    if decision.action != "allow":
        raise PermissionError(f"promotion policy {decision.action}: {decision.reason}")
    base = Path(state["base_spec"])
    candidate = Path(state["candidate_spec"])
    if _sha256_file(base) != state["base_digest"]:
        raise ValueError("base HarnessSpec changed after staging; restage the candidate")
    if _sha256_file(candidate) != state["candidate_digest"]:
        raise ValueError("candidate HarnessSpec changed after staging; restage the candidate")
    _atomic_copy(candidate, base)
    activated_digest = _sha256_file(base)
    event = {
        **_event_identity(state),
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "event": "activated",
        "recorded_at": _now_iso(),
        "actor": actor.strip(),
        "reason": reason,
        "activated_digest": activated_digest,
        "canary_percent": state["canary_percent"],
        "evidence": evidence,
        "policy_decision": decision.to_dict(),
    }
    _append_event(registry, event)
    return event


def rollback_harness_promotion(
    candidate_id: str,
    *,
    registry_path: str | Path = DEFAULT_PROMOTION_REGISTRY,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Stop a canary or restore the exact pre-activation HarnessSpec snapshot."""
    if not reason.strip():
        raise ValueError("rollback reason is required")
    registry = Path(registry_path).expanduser().resolve()
    state = harness_promotion_state(candidate_id, registry_path=registry)
    if state["status"] not in {"canary", "active"}:
        raise ValueError(f"cannot roll back candidate from {state['status']}")
    restored = False
    if state["status"] == "active":
        base = Path(state["base_spec"])
        activated_digest = str(state.get("activated_digest") or "")
        if not activated_digest or _sha256_file(base) != activated_digest:
            raise ValueError("active HarnessSpec changed after promotion; refusing to overwrite it")
        snapshot = Path(state["snapshot"])
        if not snapshot.is_file() or _sha256_file(snapshot) != state["base_digest"]:
            raise ValueError("verified rollback snapshot is unavailable")
        _atomic_copy(snapshot, base)
        restored = True
    event = {
        **_event_identity(state),
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "event": "rolled_back",
        "recorded_at": _now_iso(),
        "actor": actor.strip(),
        "reason": reason.strip(),
        "restored": restored,
        "restored_digest": _sha256_file(Path(state["base_spec"])),
    }
    _append_event(registry, event)
    return event


def harness_promotion_state(
    candidate_id: str = "",
    *,
    base_spec: str | Path | None = None,
    registry_path: str | Path = DEFAULT_PROMOTION_REGISTRY,
) -> dict[str, Any]:
    records = read_promotion_registry(registry_path)
    matching = [
        item
        for item in records
        if (
            base_spec is None
            or Path(str(item.get("base_spec") or "")).resolve()
            == Path(base_spec).expanduser().resolve()
        )
    ]
    resolved_candidate = candidate_id or (
        str(matching[-1].get("candidate_id") or "") if matching else ""
    )
    selected = [item for item in matching if item.get("candidate_id") == resolved_candidate]
    if not selected:
        label = candidate_id or str(base_spec or "")
        raise ValueError(f"harness promotion not found: {label}")
    state: dict[str, Any] = {}
    for event in selected:
        state.update(event)
        state["status"] = {
            "staged": "staged",
            "canary": "canary",
            "activated": "active",
            "rolled_back": "rolled_back",
        }.get(str(event.get("event") or ""), str(event.get("event") or "unknown"))
    state["history"] = selected
    return state


def read_promotion_registry(
    registry_path: str | Path = DEFAULT_PROMOTION_REGISTRY,
) -> list[dict[str, Any]]:
    path = Path(registry_path).expanduser().resolve()
    if not path.is_file():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"invalid promotion event at {path}:{line_number}")
        rows.append(payload)
    return rows


def select_harness_promotion(
    base_spec: str | Path,
    *,
    key: str,
    registry_path: str | Path = DEFAULT_PROMOTION_REGISTRY,
) -> dict[str, Any]:
    """Choose base/candidate deterministically for a canary routing key."""
    try:
        state = harness_promotion_state(base_spec=base_spec, registry_path=registry_path)
    except ValueError:
        return {"selected_spec": str(Path(base_spec).expanduser().resolve()), "status": "stable"}
    selected = state["base_spec"]
    bucket = _canary_bucket(key)
    if state["status"] == "active":
        selected = state["base_spec"]
    elif state["status"] == "canary" and bucket < int(state.get("canary_percent") or 0):
        selected = state["candidate_spec"]
    return {
        "candidate_id": state["candidate_id"],
        "status": state["status"],
        "bucket": bucket,
        "canary_percent": int(state.get("canary_percent") or 0),
        "selected_spec": selected,
        "selected": "candidate" if selected == state["candidate_spec"] else "base",
    }


def _validate_promotion_evidence(
    state: dict[str, Any], paths: Iterable[str | Path]
) -> list[dict[str, Any]]:
    rows = []
    for value in paths:
        path = Path(value).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"promotion evidence must be a JSON object: {path}")
        rows.append((path, payload))
    held_out = [(path, item) for path, item in rows if item.get("split") == "held-out"]
    if not held_out:
        raise ValueError("activation requires a held-out HarnessBench scorecard")
    accepted = []
    for path, scorecard in held_out:
        if scorecard.get("status") != "passed" or not scorecard.get("live"):
            raise ValueError(f"promotion evidence must be a passing live scorecard: {path}")
        sources = scorecard.get("sources") or {}
        spec_digests = sources.get("specs") or {}
        if spec_digests.get(state["base_spec"]) != state["base_digest"]:
            raise ValueError(f"scorecard base digest does not match staged base: {path}")
        if spec_digests.get(state["candidate_spec"]) != state["candidate_digest"]:
            raise ValueError(f"scorecard candidate digest does not match staged candidate: {path}")
        by_spec = {
            str(Path(str(item.get("spec") or "")).expanduser().resolve()): item
            for item in scorecard.get("variants") or ()
            if item.get("spec")
        }
        base = by_spec.get(state["base_spec"])
        candidate = by_spec.get(state["candidate_spec"])
        if not base or not candidate:
            raise ValueError(f"scorecard does not include staged base and candidate: {path}")
        if int(candidate.get("regression_runs") or 0):
            raise ValueError(f"candidate has held-out regression runs: {path}")
        candidate_score = (candidate.get("score") or {}).get("mean")
        base_score = (base.get("score") or {}).get("mean")
        if candidate_score is None or base_score is None or candidate_score < base_score:
            raise ValueError(f"candidate does not meet the baseline held-out score: {path}")
        accepted.append(
            {
                "path": str(path),
                "fingerprint": scorecard.get("fingerprint") or "",
                "candidate_score": candidate_score,
                "base_score": base_score,
                "repetitions": scorecard.get("repetitions") or 0,
            }
        )
    return accepted


def _event_identity(state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "candidate_id",
        "base_spec",
        "base_name",
        "base_digest",
        "candidate_spec",
        "candidate_name",
        "candidate_digest",
        "snapshot",
    )
    return {key: state[key] for key in keys}


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        with _file_lock(handle):
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


@contextlib.contextmanager
def _file_lock(handle: Any) -> Iterator[None]:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except ImportError:  # pragma: no cover - Windows fallback
        yield


def _atomic_copy(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.superqode-{os.getpid()}-{time.time_ns()}")
    shutil.copyfile(source, temporary)
    os.replace(temporary, target)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canary_bucket(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 100


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DEFAULT_PROMOTION_REGISTRY",
    "PROMOTION_SCHEMA_VERSION",
    "activate_harness_promotion",
    "harness_promotion_state",
    "read_promotion_registry",
    "rollback_harness_promotion",
    "select_harness_promotion",
    "stage_harness_promotion",
    "start_harness_canary",
]
