"""Short, shared text summaries for the CLI and TUI.

Status emoji: ✅ passed, ⏸️ held, ❌ failed, ⛔ blocked, ➖ not run yet.
"""

from __future__ import annotations

import json
from pathlib import Path

EMOJI = {
    "passed": "✅",
    "covered": "✅",
    "ship": "✅",
    "succeeded": "✅",
    "merged": "✅",
    "held": "⏸️",
    "hold": "⏸️",
    "uncovered": "⏸️",
    "failed": "❌",
    "reject": "❌",
    "blocked": "⛔",
    "missing": "⛔",
    "never_ran": "➖",
    "not_run": "➖",
}


def mark(status) -> str:
    return EMOJI.get(str(status), "➖")


def overview(root) -> dict:
    """The saved FactorySpec, its release policy and recent runs."""
    from .definition import load_factory, project_path
    from .runtime import factory_store
    from .snapshot import resolve_factory

    root = Path(root).resolve()
    definition = load_factory(root=root)
    data = definition.data
    if "apiVersion" not in data:
        return {
            "path": str(definition.path),
            "legacy": True,
            "default_route": data.get("default_route"),
        }
    snapshot = resolve_factory(definition)
    checks = data["improvement"]["checks"]
    governance = data["governance"]
    runs = []
    if project_path(root, ".superqode/workorders/store.sqlite3").exists():
        for order in factory_store(root, read_only=True).list(limit=50):
            if "factory" not in order.metadata:
                continue
            record = next(
                (a for a in reversed(order.artifacts) if a.kind == "factory_quality_record"),
                None,
            )
            runs.append(
                {
                    "id": order.work_order_id,
                    "status": order.status.value,
                    "goal": order.goal.splitlines()[0][:80],
                    "verification": order.metadata.get("factory_verification", {}).get(
                        "state", "missing"
                    ),
                    "gauge": json.loads(record.content)["decision"]["verdict"] if record else None,
                    "current_revision": order.metadata["factory"]["snapshot_digest"]
                    == snapshot.digest,
                }
            )
            if len(runs) >= 5:
                break
    return {
        "path": str(definition.path),
        "legacy": False,
        "name": data["metadata"]["name"],
        "snapshot_digest": snapshot.digest,
        "stages": [
            {"id": s["id"], "role": s["role"], "human_gate": bool(s.get("human_gate"))}
            for s in data["orchestration"]["stages"]
        ],
        "acceptance_checks": [
            {
                "id": name,
                "category": checks[name].get("category", "test"),
                "evaluator": bool(checks[name].get("evaluator")),
            }
            for name in data["orchestration"]["acceptance_checks"]
        ],
        "signers": sorted((governance.get("release_authority") or {}).get("keys", {})),
        "release_gauge": {"level": "L2", **(governance.get("release_gauge") or {})},
        "interfaces": data.get("access", {}).get("interfaces", []),
        "runs": runs,
    }


def overview_lines(value) -> list[str]:
    if value.get("legacy"):
        return [
            f"⛔ {value['path']} is a route-only policy, not a FactorySpec.",
            "   Next: sq factory init --template fix-and-verify",
        ]
    lines = [
        f"🏭 {value['name']}  {value['snapshot_digest'][:19]}",
        "   Stages: "
        + " → ".join(
            s["id"] + (" (human gate)" if s["human_gate"] else "") for s in value["stages"]
        ),
    ]
    for check in value["acceptance_checks"]:
        state = "passed" if check["evaluator"] else "blocked"
        hint = "" if check["evaluator"] else "  needs protected evaluator probes"
        lines.append(f"   {mark(state)} check {check['id']} ({check['category']}){hint}")
    gauge = value["release_gauge"]
    lines.append(
        f"   Release: SuperGauge {gauge['level']} with ship, then a human signature"
        + (
            f" from {', '.join(value['signers'])}"
            if value["signers"]
            else " (no signer configured ⛔)"
        )
    )
    if value["runs"]:
        lines.append("   Recent runs:")
        for run in value["runs"]:
            verdict = run["gauge"] or "missing"
            lines.append(
                f"   {mark(run['verification'] if run['verification'] != 'missing' else 'never_ran')}"
                f" {run['id']}  {run['status']}  gauge {mark(verdict)} {verdict}  {run['goal']}"
            )
    else:
        lines.append('   No runs yet. Next: :factory trial "<goal>"')
    return lines


def readiness_lines(report) -> list[str]:
    lines = []
    for row in report["checks"]:
        state = "passed" if row["passed"] else "failed"
        lines.append(f"{mark(state)} host {row['id']}  [{row.get('label', 'configured')}]")
        if row.get("action"):
            lines.append(f"   → {row['action']}")
    for row in report.get("application", []):
        lines.append(f"{mark(row['status'])} {row['category']} {row['id']}  [{row['label']}]")
        if row.get("detail"):
            lines.append(f"   {row['detail']}")
        if row.get("action"):
            lines.append(f"   → {row['action']}")
    return lines


def trace_lines(value) -> list[str]:
    summary = value["summary"]
    checks, requirements = summary["checks"], summary["requirements"]
    lines = [
        "Checks: "
        + "  ".join(
            f"{mark(k)} {k.replace('_', ' ')} {checks[k]}"
            for k in ("passed", "failed", "blocked", "never_ran")
        ),
        "Requirements: "
        + "  ".join(
            f"{mark(k)} {k} {requirements[k]}"
            for k in ("covered", "failed", "blocked", "uncovered")
        ),
    ]
    for row in value["application_checks"]:
        lines.append(f"{mark(row['status'])} {row['check']}  {row['reason']}")
    for row in value["requirements"]:
        lines.append(f"{mark(row['status'])} requirement {row['id']}: {row['description'][:80]}")
    return lines


def decision_lines(status) -> list[str]:
    gauge = status.get("gauge") or {}
    verdict = gauge.get("verdict", "missing")
    lines = [
        f"Run {status['run']}  {status['status']}",
        f"{mark(status['verification'] if status['verification'] != 'missing' else 'never_ran')}"
        f" verification {status['verification']}",
        f"{mark(verdict)} SuperGauge {verdict}  (needs {gauge.get('required_level', 'L2')} + ship,"
        f" reached {gauge.get('highest_level') or 'none'})",
    ]
    if status["authorized"]:
        lines.append("✅ Signed by a human approver")
    if status["applied"]:
        lines.append("✅ Applied to the working tree")
    if status["blockers"]:
        lines.append("⛔ Release blocked:")
        lines.extend(f"   - {item}" for item in status["blockers"])
    elif not status["authorized"]:
        lines.append(
            "⏸️ Ready for a human signature: sq factory release-challenge "
            f"{status['run']} --key <signer>"
        )
    return lines
