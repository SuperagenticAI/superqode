"""Build an Agent Quality Record from SuperQode run state."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPERGAUGE_VERSION = "0.1"

# Measures graded by a model. The specification forbids these from backing a
# gate, and `gates_from_policy` refuses to emit one.
MODEL_GRADED = frozenset({"answer.grounded", "robustness.multi_turn"})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_id() -> str:
    return f"aqr_{secrets.token_hex(8)}"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def manifest_digest(tasks: list[dict[str, Any]], split: str = "held-out") -> str:
    """Fingerprint a task split by id and success condition.

    Ordering is normalised so two runs over the same split agree. Prompts are
    excluded: editing a prompt's wording without changing what it asserts should
    not invalidate a seal.
    """
    items = sorted(
        (
            str(task.get("id", "")),
            json.dumps(task.get("expect_contains") or task.get("expect") or [], sort_keys=True),
        )
        for task in tasks
        if str(task.get("split") or "held-in") == split
    )
    return sha256_bytes(json.dumps(items, sort_keys=True).encode())


@dataclass
class AgentQualityRecord:
    """A record under construction. `to_dict` emits the published shape."""

    profile: dict[str, Any]
    subject: dict[str, Any]
    task_set: dict[str, Any]
    measures: list[dict[str, Any]] = field(default_factory=list)
    gates: list[dict[str, Any]] = field(default_factory=list)
    assurance: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    record_id: str = field(default_factory=_record_id)
    emitted_at: str = field(default_factory=_now)

    def add_measure(self, measure_id: str, value: Any, **fields: Any) -> None:
        entry: dict[str, Any] = {"id": measure_id, "value": value}
        entry.update({k: v for k, v in fields.items() if v is not None})
        self.measures.append(entry)

    def add_gate(self, gate_id: str, result: str, **fields: Any) -> None:
        if gate_id in MODEL_GRADED:
            raise ValueError(
                f"{gate_id} is model-graded and cannot back a gate; report it as a measure"
            )
        entry: dict[str, Any] = {"id": gate_id, "result": result}
        entry.update({k: v for k, v in fields.items() if v is not None})
        self.gates.append(entry)

    def to_dict(self) -> dict[str, Any]:
        return {
            "supergauge": SUPERGAUGE_VERSION,
            "record_id": self.record_id,
            "emitted_at": self.emitted_at,
            "profile": self.profile,
            "subject": self.subject,
            "task_set": self.task_set,
            "measures": self.measures,
            "gates": self.gates,
            "assurance": self.assurance,
            "decision": self.decision,
        }


def _authority_from_spec(spec: Any) -> dict[str, Any]:
    """Read the execution policy that bounded the run.

    The specification requires this block because a record pinning what an agent
    is, and not what it was permitted to do, can be valid and wrong. Values are
    read from the spec in force; nothing here is defaulted optimistically.
    """
    authority: dict[str, Any] = {}
    policy = getattr(spec, "execution_policy", None)

    sandbox = getattr(policy, "sandbox", None) if policy else None
    if sandbox:
        authority["sandbox"] = str(sandbox)

    network = getattr(policy, "network", None) if policy else None
    if network is not None:
        allowed = getattr(network, "allow", None) or getattr(network, "allow_hosts", None)
        if allowed:
            authority["egress"] = "allow-list"
        elif getattr(network, "enabled", True) is False:
            authority["egress"] = "deny-by-default"
        else:
            authority["egress"] = "unrestricted"

    capabilities = sorted(
        {
            tool
            for agent in getattr(spec, "agents", []) or []
            for tool in getattr(agent, "tools", []) or []
        }
    )
    if capabilities:
        authority["capabilities"] = capabilities

    return authority


def _split_counts(tasks: list[dict[str, Any]]) -> tuple[int, int]:
    held_in = sum(1 for t in tasks if str(t.get("split") or "held-in") == "held-in")
    held_out = sum(1 for t in tasks if str(t.get("split") or "held-in") == "held-out")
    return held_in, held_out


def record_from_eval(
    *,
    eval_result: dict[str, Any],
    tasks: list[dict[str, Any]],
    spec: Any,
    spec_path: str | Path,
    profile_id: str = "sg/coding-agent",
    profile_version: str = "0.1",
    tier: str = "T1",
    sealed: bool = False,
    canary_ids: list[str] | None = None,
    policy_decisions: list[dict[str, Any]] | None = None,
    ledger: str | None = None,
    ledger_format: str = "superqode.harness-protocol/1",
    ledger_events: int | None = None,
    evaluator_independent: bool = False,
    actor: str | None = None,
) -> AgentQualityRecord:
    """Project one `harness eval` result into a record.

    The eval result is the baseline variant of `run_harness_eval`. Measures are
    emitted only where the underlying run produced them, so a record built from
    a run without repeats carries no reliability measure and stops at L2.
    """
    variant = (eval_result.get("variants") or [{}])[0]
    held_in, held_out = _split_counts(tasks)

    record = AgentQualityRecord(
        profile={"id": profile_id, "version": profile_version, "tier": tier},
        subject={
            "agent": getattr(spec, "name", "") or Path(spec_path).stem,
            "harness_digest": sha256_file(spec_path),
            "authority": _authority_from_spec(spec),
        },
        task_set={
            "manifest_digest": manifest_digest(tasks, "held-out"),
            "held_in": held_in,
            "held_out": held_out,
            "sealed": bool(sealed),
        },
    )

    model = getattr(spec, "model_policy", None)
    provider = getattr(model, "provider", None) if model else None
    model_id = getattr(model, "model", None) if model else None
    if provider and model_id:
        record.subject["model"] = {"provider": str(provider), "id": str(model_id)}

    if canary_ids:
        record.task_set["canary_ids"] = list(canary_ids)

    # --- Effectiveness -----------------------------------------------------
    task_results = variant.get("tasks") or []
    scored = [t for t in task_results if t.get("status") in {"passed", "failed"}]
    if scored:
        passed = sum(1 for t in scored if t.get("status") == "passed")
        record.add_measure(
            "task.completion",
            round(passed / len(scored), 3),
            split="held-out" if held_out and not held_in else None,
            n=len(scored),
        )

    # --- Efficiency --------------------------------------------------------
    # `harness eval` already reports these three per successful task.
    for measure_id, key, unit in (
        ("efficiency.cost_per_success", "cost_per_success", "usd"),
        ("efficiency.tokens_per_success", "tokens_per_success", None),
        ("efficiency.latency_per_success", "latency_ms_per_success", "seconds"),
    ):
        value = variant.get(key)
        if value:
            if measure_id.endswith("latency_per_success"):
                value = round(float(value) / 1000.0, 3)
            record.add_measure(measure_id, value, unit=unit)

    # --- Safety ------------------------------------------------------------
    if policy_decisions is not None:
        denials = [d for d in policy_decisions if str(d.get("action")) == "deny"]
        record.add_measure("policy.hard_rules", 1.0 if not denials else 0.0)
        record.add_gate(
            "policy.hard_rules",
            "pass" if not denials else "fail",
            source="acs",
        )

    # --- Assurance ---------------------------------------------------------
    evidence: dict[str, Any] = {"format": ledger_format, "replayable": bool(ledger)}
    if ledger:
        evidence["ledger"] = str(ledger)
    if ledger_events is not None:
        evidence["events"] = int(ledger_events)
    record.assurance = {
        "evidence": evidence,
        "evaluator_independent": bool(evaluator_independent),
    }

    record.decision = {
        "verdict": "hold",
        "actor": actor or os.environ.get("USER") or "unknown",
    }
    return record


def build_record(
    *,
    spec_path: str | Path,
    tasks_path: str | Path,
    eval_result: dict[str, Any],
    spec: Any,
    tasks: list[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience wrapper returning the emitted mapping."""
    record = record_from_eval(
        eval_result=eval_result, tasks=tasks, spec=spec, spec_path=spec_path, **kwargs
    )
    return record.to_dict()
