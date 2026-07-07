"""Self-improvement helpers for SuperQode harnesses.

This module keeps the self-improvement loop local and auditable: mine
structured failures, maintain persistent logbook memory, audit candidates,
and preserve accepted/rejected attempts in a JSONL ledger.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SELF_IMPROVE_SCHEMA_VERSION = 1
DEFAULT_SELF_IMPROVE_DIR = Path(".superqode") / "self-improve"
DEFAULT_LOGBOOK_DIR = DEFAULT_SELF_IMPROVE_DIR / "logbook"
DEFAULT_CANDIDATE_LEDGER_PATH = DEFAULT_SELF_IMPROVE_DIR / "candidates.jsonl"
FAILURE_PATTERNS_FILE = "failure_patterns.yaml"


def mine_harness_failures(
    *,
    test_result_paths: tuple[str | Path, ...] = (),
    eval_result_paths: tuple[str | Path, ...] = (),
    harbor_run_paths: tuple[str | Path, ...] = (),
) -> dict[str, Any]:
    """Mine structured failure records from harness test/eval JSON payloads."""
    records: list[dict[str, Any]] = []
    for path in test_result_paths:
        source = Path(path).expanduser().resolve()
        payload = _read_json_mapping(source)
        records.extend(_records_from_test_result(payload, source))
    for path in eval_result_paths:
        source = Path(path).expanduser().resolve()
        payload = _read_json_mapping(source)
        records.extend(_records_from_eval_result(payload, source))
    for path in harbor_run_paths:
        source = Path(path).expanduser().resolve()
        records.extend(_records_from_benchmark_run(source))
    for index, record in enumerate(records, start=1):
        record["failure_id"] = f"fail_{index:04d}"
    return {
        "schema_version": SELF_IMPROVE_SCHEMA_VERSION,
        "failure_count": len(records),
        "failures": records,
    }


def write_failure_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write a mined failure report as JSON."""
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_failure_report(report: dict[str, Any]) -> str:
    """Render a compact human-readable failure report."""
    failures = report.get("failures") or []
    lines = [f"Failure mining: {len(failures)} failure(s)"]
    if not failures:
        return "\n".join(lines)
    by_dimension: dict[str, int] = {}
    for failure in failures:
        dimension = failure.get("dimension") or {}
        key = dimension.get("id") or "unclassified"
        by_dimension[key] = by_dimension.get(key, 0) + 1
    lines.append(
        "Dimensions: "
        + ", ".join(f"{key}={value}" for key, value in sorted(by_dimension.items()))
    )
    for failure in failures[:10]:
        dimension = failure.get("dimension") or {}
        lines.append(
            f"  {failure.get('failure_id')}: "
            f"{failure.get('task_id') or failure.get('check_name') or '-'} "
            f"{dimension.get('id') or '-'}:{dimension.get('field') or '-'} "
            f"{failure.get('symptom') or '-'}"
        )
    if len(failures) > 10:
        lines.append(f"  ... {len(failures) - 10} more")
    return "\n".join(lines)


def update_logbook_from_failures(
    *,
    failure_report_paths: tuple[str | Path, ...],
    logbook_dir: str | Path = DEFAULT_LOGBOOK_DIR,
) -> dict[str, Any]:
    """Merge mined failure reports into the file-backed self-improvement logbook."""
    root = Path(logbook_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    patterns_path = root / FAILURE_PATTERNS_FILE
    patterns = _read_yaml_list(patterns_path)
    by_fingerprint = {
        str(item.get("fingerprint") or ""): item
        for item in patterns
        if isinstance(item, dict) and item.get("fingerprint")
    }
    now = _now_iso()
    added = 0
    updated = 0
    for report_path in failure_report_paths:
        report = _read_json_mapping(Path(report_path).expanduser().resolve())
        for failure in report.get("failures") or []:
            if not isinstance(failure, dict):
                continue
            fingerprint = _failure_fingerprint(failure)
            source_refs = _dedupe_strings(failure.get("evidence") or [])
            existing = by_fingerprint.get(fingerprint)
            if existing:
                existing["count"] = int(existing.get("count") or 0) + 1
                existing.setdefault("first_seen_at", now)
                existing["last_seen_at"] = now
                existing["status"] = str(existing.get("status") or "active")
                existing["confidence"] = _pattern_confidence(int(existing.get("count") or 0))
                existing.setdefault("negative_results", [])
                existing.setdefault("superseded_by", "")
                existing["source_refs"] = _dedupe_strings(
                    [*(existing.get("source_refs") or []), *source_refs]
                )
                existing["last_failure_id"] = failure.get("failure_id") or ""
                updated += 1
                continue
            entry = {
                "id": f"fp_{len(patterns) + 1:04d}",
                "kind": "failure_pattern",
                "fingerprint": fingerprint,
                "summary": failure.get("symptom") or "Harness failure",
                "failure_category": failure.get("failure_category") or "",
                "dimension": failure.get("dimension") or {},
                "suggested_surfaces": failure.get("suggested_surfaces") or [],
                "count": 1,
                "confidence": _pattern_confidence(1),
                "status": "active",
                "first_seen_at": now,
                "last_seen_at": now,
                "negative_results": [],
                "superseded_by": "",
                "source_refs": source_refs,
                "last_failure_id": failure.get("failure_id") or "",
            }
            patterns.append(entry)
            by_fingerprint[fingerprint] = entry
            added += 1
    patterns_path.write_text(yaml.safe_dump(patterns, sort_keys=False), encoding="utf-8")
    return {
        "logbook_dir": str(root),
        "failure_patterns_path": str(patterns_path),
        "patterns": len(patterns),
        "added": added,
        "updated": updated,
    }


def read_logbook(logbook_dir: str | Path = DEFAULT_LOGBOOK_DIR) -> dict[str, Any]:
    """Read the self-improvement logbook."""
    root = Path(logbook_dir).expanduser()
    patterns = _read_yaml_list(root / FAILURE_PATTERNS_FILE)
    return {
        "schema_version": SELF_IMPROVE_SCHEMA_VERSION,
        "logbook_dir": str(root),
        "failure_patterns": patterns,
    }


def render_logbook(logbook: dict[str, Any]) -> str:
    patterns = logbook.get("failure_patterns") or []
    lines = [f"Self-improvement logbook: {len(patterns)} failure pattern(s)"]
    for item in patterns[:10]:
        dimension = item.get("dimension") or {}
        lines.append(
            f"  {item.get('id')}: count={item.get('count') or 0} "
            f"confidence={item.get('confidence') or '-'} "
            f"status={item.get('status') or 'active'} "
            f"{dimension.get('id') or '-'}:{dimension.get('field') or '-'} "
            f"{item.get('summary') or '-'}"
        )
    if len(patterns) > 10:
        lines.append(f"  ... {len(patterns) - 10} more")
    return "\n".join(lines)


def logbook_to_markdown(logbook: dict[str, Any]) -> str:
    """Render logbook contents as trace-evidence markdown."""
    patterns = logbook.get("failure_patterns") or []
    lines = ["## Self-Improvement Logbook", ""]
    if not patterns:
        lines.append("- No failure patterns recorded yet.")
        return "\n".join(lines) + "\n"
    for item in patterns:
        dimension = item.get("dimension") or {}
        lines.append(f"- {item.get('id')}: {item.get('summary') or '-'}")
        lines.append(f"  - count: {item.get('count') or 0}")
        lines.append(f"  - confidence: {item.get('confidence') or '-'}")
        lines.append(f"  - status: {item.get('status') or 'active'}")
        lines.append(f"  - category: {item.get('failure_category') or '-'}")
        lines.append(
            f"  - dimension: {dimension.get('id') or '-'} "
            f"{dimension.get('field') or '-'}"
        )
        surfaces = item.get("suggested_surfaces") or []
        if surfaces:
            lines.append(f"  - suggested_surfaces: {', '.join(map(str, surfaces))}")
        if item.get("superseded_by"):
            lines.append(f"  - superseded_by: {item['superseded_by']}")
        negative_results = item.get("negative_results") or []
        if negative_results:
            lines.append(f"  - negative_results: {len(negative_results)}")
        for source in (item.get("source_refs") or [])[:3]:
            lines.append(f"  - source: {source}")
    return "\n".join(lines) + "\n"


def prune_logbook(
    *,
    logbook_dir: str | Path = DEFAULT_LOGBOOK_DIR,
    min_count: int = 1,
    max_patterns: int | None = None,
    keep_statuses: tuple[str, ...] = ("active", "pinned"),
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prune stale low-signal logbook entries with deterministic retention."""
    if min_count < 1:
        raise ValueError("min_count must be at least 1")
    if max_patterns is not None and max_patterns < 1:
        raise ValueError("max_patterns must be at least 1")

    root = Path(logbook_dir).expanduser()
    patterns_path = root / FAILURE_PATTERNS_FILE
    patterns = _read_yaml_list(patterns_path)
    keep_status_set = {status.strip() for status in keep_statuses if status.strip()}
    retained = [
        item
        for item in patterns
        if str(item.get("status") or "active") in keep_status_set
        and int(item.get("count") or 0) >= min_count
    ]
    retained = sorted(
        retained,
        key=lambda item: (
            str(item.get("status") or "") != "pinned",
            -int(item.get("count") or 0),
            -_iso_timestamp(str(item.get("last_seen_at") or "")),
            str(item.get("id") or ""),
        ),
    )
    if max_patterns is not None:
        retained = retained[:max_patterns]
    retained_ids = {str(item.get("id") or "") for item in retained}
    pruned = [item for item in patterns if str(item.get("id") or "") not in retained_ids]
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        patterns_path.write_text(yaml.safe_dump(retained, sort_keys=False), encoding="utf-8")
    return {
        "logbook_dir": str(root),
        "failure_patterns_path": str(patterns_path),
        "dry_run": dry_run,
        "before": len(patterns),
        "after": len(retained),
        "pruned": len(pruned),
        "pruned_ids": [str(item.get("id") or "") for item in pruned],
    }


def audit_harness_candidate(
    *,
    base_spec_path: str | Path,
    candidate_spec_path: str | Path,
    tasks_path: str | Path | None = None,
    eval_result_paths: tuple[str | Path, ...] = (),
    editable_surfaces: tuple[str, ...] = (),
    protected_surfaces: tuple[str, ...] = (),
    max_candidate_edits: int | None = None,
    ledger_path: str | Path = DEFAULT_CANDIDATE_LEDGER_PATH,
    require_heldout: bool = False,
    allow_protected_changes: bool = False,
    allow_ungated: bool = False,
) -> dict[str, Any]:
    """Audit a proposed harness against self-improvement safety gates."""
    from .eval import load_eval_tasks
    from .loader import harness_spec_to_dict, load_harness_spec

    base_path = Path(base_spec_path).expanduser().resolve()
    candidate_path = Path(candidate_spec_path).expanduser().resolve()
    base_spec = load_harness_spec(base_path)
    candidate_spec = load_harness_spec(candidate_path)
    base_data = harness_spec_to_dict(base_spec)
    candidate_data = harness_spec_to_dict(candidate_spec)
    diffs = _diff_values(base_data, candidate_data)
    for item in diffs:
        item["surface"] = _surface_for_path(str(item.get("path") or ""))

    optimization = base_spec.optimization
    editable = editable_surfaces or optimization.editable_surfaces
    protected = protected_surfaces or optimization.protected_surfaces
    edit_limit = max_candidate_edits
    if edit_limit is None:
        edit_limit = optimization.max_candidate_edits

    task_split_counts: dict[str, int] = {}
    required_splits: list[str] = []
    if tasks_path:
        task_file = load_eval_tasks(tasks_path)
        task_split_counts = task_file.get("split_counts") or {}
        if require_heldout and int(task_split_counts.get("held-out") or 0) > 0:
            required_splits.append("held-out")
    elif require_heldout:
        required_splits.append("held-out")

    changed_surfaces = sorted({str(item["surface"]) for item in diffs if item.get("surface")})
    protected_changes = [
        item
        for item in diffs
        if any(_surface_matches(item["surface"], item["path"], surface) for surface in protected)
    ]
    out_of_scope_changes = [
        item
        for item in diffs
        if editable
        and not any(
            _surface_matches(item["surface"], item["path"], surface)
            for surface in (*editable, *protected)
        )
    ]
    permission_risks = _permission_widening_risks(base_data, candidate_data)
    check_risks = _check_weakening_risks(base_data, candidate_data)
    eval_gates = _candidate_eval_gates(
        eval_result_paths=eval_result_paths,
        candidate_spec_path=candidate_path,
        candidate_name=candidate_spec.name,
        required_splits=tuple(required_splits),
        allow_ungated=allow_ungated,
    )
    diff_fingerprint = _hash_json(
        {
            "changed": [
                {"path": item["path"], "before": item["before"], "after": item["after"]}
                for item in diffs
            ]
        }
    )
    novelty = _candidate_novelty(
        ledger_path=ledger_path,
        diff_fingerprint=diff_fingerprint,
        changed_surfaces=tuple(changed_surfaces),
    )

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if protected_changes:
        violations.append(
            _violation(
                "protected_surface_change",
                "Candidate edits protected harness surfaces that require external review.",
                blocking=not allow_protected_changes,
                paths=[item["path"] for item in protected_changes],
                surfaces=protected,
            )
        )
    if out_of_scope_changes:
        violations.append(
            _violation(
                "out_of_scope_change",
                "Candidate edits surfaces outside the bounded proposal context.",
                paths=[item["path"] for item in out_of_scope_changes],
                surfaces=editable,
            )
        )
    if edit_limit is not None and len(diffs) > edit_limit:
        violations.append(
            _violation(
                "candidate_edit_limit",
                f"Candidate changed {len(diffs)} fields; limit is {edit_limit}.",
                paths=[item["path"] for item in diffs],
            )
        )
    for risk in permission_risks:
        violations.append(
            _violation(
                "permission_widening",
                risk["message"],
                paths=[risk["path"]],
                surfaces=[risk["surface"]],
            )
        )
    for risk in check_risks:
        violations.append(
            _violation(
                "check_weakening",
                risk["message"],
                paths=[risk["path"]],
                surfaces=[risk["surface"]],
            )
        )
    if eval_gates["regressed"]:
        violations.append(
            _violation(
                "eval_regression",
                "Candidate regressed tasks the baseline previously solved.",
                paths=eval_gates.get("regression_refs") or [],
            )
        )
    if eval_gates["missing_required_splits"] and not allow_ungated:
        violations.append(
            _violation(
                "missing_heldout_gate",
                "Candidate is missing a passing held-out validation gate.",
                paths=eval_gates["missing_required_splits"],
            )
        )
    if novelty.get("duplicate_rejected"):
        violations.append(
            _violation(
                "duplicate_rejected_candidate",
                "Candidate repeats a previously rejected edit pattern.",
                paths=[novelty["duplicate_rejected"]],
            )
        )
    elif novelty.get("max_surface_similarity", 0) >= 0.8 and novelty.get("nearest_candidate_id"):
        warnings.append(
            _violation(
                "low_candidate_diversity",
                "Candidate changes the same surface set as a previous attempt.",
                blocking=False,
                paths=[str(novelty.get("nearest_candidate_id") or "")],
            )
        )

    accepted = not any(item.get("blocking", True) for item in violations)
    return {
        "schema_version": SELF_IMPROVE_SCHEMA_VERSION,
        "audited_at": _now_iso(),
        "candidate_id": f"cand_{diff_fingerprint[:12]}",
        "diff_fingerprint": diff_fingerprint,
        "base_spec": str(base_path),
        "candidate_spec": str(candidate_path),
        "tasks_file": str(Path(tasks_path).expanduser().resolve()) if tasks_path else "",
        "candidate_name": candidate_spec.name,
        "changed_fields": len(diffs),
        "changed_surfaces": changed_surfaces,
        "diffs": diffs,
        "editable_surfaces": list(editable),
        "protected_surfaces": list(protected),
        "task_split_counts": task_split_counts,
        "eval_gates": eval_gates,
        "novelty": novelty,
        "violations": violations,
        "warnings": warnings,
        "accepted": accepted,
        "decision": "accepted" if accepted else "rejected",
    }


def record_candidate_audit(
    audit: dict[str, Any],
    *,
    ledger_path: str | Path = DEFAULT_CANDIDATE_LEDGER_PATH,
    notes: str = "",
) -> dict[str, Any]:
    """Append an accepted/rejected candidate decision to the JSONL ledger."""
    path = Path(ledger_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    recorded_at = _now_iso()
    attempt_id = "attempt_" + _hash_json(
        {
            "candidate_id": audit.get("candidate_id"),
            "recorded_at": recorded_at,
            "ledger_path": str(path),
        }
    )[:12]
    record = {
        "schema_version": SELF_IMPROVE_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "recorded_at": recorded_at,
        "candidate_id": audit.get("candidate_id") or "",
        "candidate_spec": audit.get("candidate_spec") or "",
        "base_spec": audit.get("base_spec") or "",
        "decision": audit.get("decision") or "rejected",
        "accepted": bool(audit.get("accepted")),
        "changed_surfaces": audit.get("changed_surfaces") or [],
        "diff_fingerprint": audit.get("diff_fingerprint") or "",
        "violations": audit.get("violations") or [],
        "warnings": audit.get("warnings") or [],
        "eval_gates": audit.get("eval_gates") or {},
        "notes": notes,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return {"ledger_path": str(path), "record": record}


def read_candidate_ledger(
    ledger_path: str | Path = DEFAULT_CANDIDATE_LEDGER_PATH,
) -> dict[str, Any]:
    """Read the native self-improvement candidate ledger."""
    path = Path(ledger_path).expanduser()
    records: list[dict[str, Any]] = []
    if path.is_file():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}:{line_number}")
            records.append(payload)
    return {
        "schema_version": SELF_IMPROVE_SCHEMA_VERSION,
        "ledger_path": str(path),
        "candidates": records,
        "candidate_count": len(records),
        "accepted": sum(1 for item in records if item.get("accepted")),
        "rejected": sum(1 for item in records if not item.get("accepted")),
    }


def render_candidate_audit(audit: dict[str, Any]) -> str:
    """Render a compact candidate audit."""
    lines = [
        f"Candidate audit: {audit.get('candidate_id') or '-'}",
        f"Decision: {audit.get('decision') or '-'}",
        f"Changed fields: {audit.get('changed_fields') or 0}",
        f"Changed surfaces: {', '.join(audit.get('changed_surfaces') or []) or '-'}",
    ]
    violations = audit.get("violations") or []
    warnings = audit.get("warnings") or []
    if violations:
        lines.append("Violations:")
        for item in violations:
            lines.append(f"  - {item.get('code')}: {item.get('message')}")
    if warnings:
        lines.append("Warnings:")
        for item in warnings:
            lines.append(f"  - {item.get('code')}: {item.get('message')}")
    gates = audit.get("eval_gates") or {}
    if gates.get("gates"):
        lines.append("Eval gates:")
        for gate in gates["gates"]:
            lines.append(
                f"  - {gate.get('split') or '-'} {gate.get('status') or '-'} "
                f"{gate.get('candidate') or '-'}"
            )
    return "\n".join(lines)


def render_candidate_ledger(ledger: dict[str, Any]) -> str:
    """Render the candidate ledger."""
    records = ledger.get("candidates") or []
    if not records:
        return "No self-improvement candidates recorded."
    lines = ["candidate       decision  surfaces  violations"]
    for item in records:
        surfaces = ",".join(str(value) for value in item.get("changed_surfaces") or [])
        violations = ",".join(
            str(value.get("code") or "") for value in item.get("violations") or []
        )
        lines.append(
            f"{str(item.get('candidate_id') or '-'):<15} "
            f"{str(item.get('decision') or '-'):<9} "
            f"{surfaces or '-'}  {violations or '-'}"
        )
    return "\n".join(lines)


def candidate_ledger_to_markdown(
    ledger: dict[str, Any],
    *,
    limit: int = 12,
) -> str:
    """Render previous candidate attempts as bounded proposal context."""
    records = ledger.get("candidates") or []
    lines = ["## Previous Harness Edit Attempts", ""]
    if not records:
        lines.append("- No previous candidate attempts are recorded.")
        return "\n".join(lines) + "\n"
    for item in records[-limit:]:
        lines.append(
            f"- {item.get('candidate_id') or '-'}: "
            f"{item.get('decision') or '-'} "
            f"surfaces={', '.join(item.get('changed_surfaces') or []) or '-'}"
        )
        for violation in (item.get("violations") or [])[:3]:
            lines.append(f"  - rejected_for: {violation.get('code') or '-'}")
        if item.get("notes"):
            lines.append(f"  - notes: {_compact(str(item['notes']), limit=160)}")
    return "\n".join(lines) + "\n"


def append_self_improve_evidence(
    *,
    evidence_path: str | Path,
    failure_report_paths: tuple[str | Path, ...] = (),
    logbook_dir: str | Path = DEFAULT_LOGBOOK_DIR,
    candidate_ledger_path: str | Path = DEFAULT_CANDIDATE_LEDGER_PATH,
    editable_surfaces: tuple[str, ...] = (),
    protected_surfaces: tuple[str, ...] = (),
    optimization_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append failure/logbook guidance to an existing trace-evidence file."""
    path = Path(evidence_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Trace evidence file not found: {path}")
    failure_reports = [_read_json_mapping(Path(item).expanduser().resolve()) for item in failure_report_paths]
    logbook = read_logbook(logbook_dir)
    sections = [
        "",
        "## Self-Improvement Guidance",
        "",
        "Use these records to improve the harness mechanism, not to overfit a single answer.",
    ]
    if editable_surfaces:
        sections.append(f"- Editable surfaces: {', '.join(editable_surfaces)}")
    if protected_surfaces:
        sections.append(f"- Protected surfaces: {', '.join(protected_surfaces)}")
    if optimization_policy:
        sections.append(
            f"- Require human apply: {bool(optimization_policy.get('require_human_apply', True))}"
        )
        if optimization_policy.get("heldout_fraction") is not None:
            sections.append(f"- Heldout fraction: {optimization_policy['heldout_fraction']}")
        if optimization_policy.get("max_candidate_edits") is not None:
            sections.append(f"- Max candidate edits: {optimization_policy['max_candidate_edits']}")
    sections.extend(["", "### Mined Failures", ""])
    failure_count = 0
    for report in failure_reports:
        for failure in report.get("failures") or []:
            if not isinstance(failure, dict):
                continue
            failure_count += 1
            dimension = failure.get("dimension") or {}
            sections.append(
                f"- {failure.get('failure_id') or '-'}: "
                f"{failure.get('symptom') or '-'}"
            )
            sections.append(f"  - source_type: {failure.get('source_type') or '-'}")
            sections.append(f"  - task_id: {failure.get('task_id') or '-'}")
            sections.append(f"  - category: {failure.get('failure_category') or '-'}")
            sections.append(
                f"  - dimension: {dimension.get('id') or '-'} "
                f"{dimension.get('field') or '-'}"
            )
            surfaces = failure.get("suggested_surfaces") or []
            if surfaces:
                sections.append(f"  - suggested_surfaces: {', '.join(map(str, surfaces))}")
    if failure_count == 0:
        sections.append("- No mined failures were supplied.")
    candidate_ledger = read_candidate_ledger(candidate_ledger_path)
    sections.extend(
        [
            "",
            logbook_to_markdown(logbook).rstrip(),
            "",
            candidate_ledger_to_markdown(candidate_ledger).rstrip(),
            "",
        ]
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(sections))
        handle.write("\n")
    return {
        "trace_evidence_path": str(path),
        "failure_reports": [str(Path(item).expanduser()) for item in failure_report_paths],
        "failure_count": failure_count,
        "logbook_patterns": len(logbook.get("failure_patterns") or []),
        "candidate_attempts": len(candidate_ledger.get("candidates") or []),
        "candidate_ledger_path": str(Path(candidate_ledger_path).expanduser()),
        "editable_surfaces": list(editable_surfaces),
        "protected_surfaces": list(protected_surfaces),
        "optimization_policy": dict(optimization_policy or {}),
    }


def _records_from_test_result(payload: dict[str, Any], source: Path) -> list[dict[str, Any]]:
    digest = payload.get("failure_digest") or {}
    if payload.get("status") != "failed" and not digest.get("failure_category"):
        return []
    failed_checks = [
        (index, item)
        for index, item in enumerate(payload.get("checks") or [])
        if isinstance(item, dict) and item.get("status") == "failed"
    ]
    if not failed_checks:
        failed_checks = [(-1, {})]
    records = []
    for index, check in failed_checks:
        symptom = check.get("error") or _first_string(digest.get("evidence")) or "Harness test failed"
        records.append(
            _failure_record(
                source_type="harness_test",
                source=source,
                source_ref=f"{source}#checks/{index}" if index >= 0 else str(source),
                harness=str(payload.get("spec") or ""),
                spec=str(payload.get("spec") or ""),
                task_id="",
                check_name=str(check.get("name") or ""),
                status="failed",
                symptom=symptom,
                reason=symptom,
                digest=digest,
            )
        )
    return records


def _records_from_eval_result(payload: dict[str, Any], source: Path) -> list[dict[str, Any]]:
    records = []
    for variant_index, variant in enumerate(payload.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        regressions = set(str(item) for item in (variant.get("regressions_vs_baseline") or []))
        for task_index, task in enumerate(variant.get("tasks") or []):
            if not isinstance(task, dict) or task.get("status") != "failed":
                continue
            task_id = str(task.get("id") or "")
            digest = task.get("failure_digest") or {}
            reason = str(task.get("reason") or _first_string(digest.get("evidence")) or "")
            records.append(
                _failure_record(
                    source_type="harness_eval",
                    source=source,
                    source_ref=f"{source}#variants/{variant_index}/tasks/{task_index}",
                    harness=str(variant.get("harness") or ""),
                    spec=str(variant.get("spec") or ""),
                    task_id=task_id,
                    check_name="eval_task",
                    status="failed",
                    symptom=reason or "Eval task failed",
                    reason=reason,
                    digest=digest,
                    regressed=task_id in regressions,
                )
            )
    return records


def _records_from_benchmark_run(source: Path) -> list[dict[str, Any]]:
    paths: list[Path]
    if source.is_file():
        paths = [source]
    elif source.is_dir():
        paths = [
            *sorted(source.rglob("*.json")),
            *sorted(source.rglob("*.jsonl")),
        ][:500]
    else:
        raise FileNotFoundError(f"Benchmark run path not found: {source}")

    records: list[dict[str, Any]] = []
    for path in paths:
        if path.suffix.lower() == ".jsonl":
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    records.extend(
                        _records_from_benchmark_payload(
                            payload,
                            path,
                            source_ref=f"{path}#L{line_number}",
                        )
                    )
            continue
        try:
            payload = _read_json_mapping(path)
        except (json.JSONDecodeError, ValueError):
            continue
        records.extend(_records_from_benchmark_payload(payload, path, source_ref=str(path)))
    return records


def _records_from_benchmark_payload(
    payload: dict[str, Any],
    source: Path,
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    rows = payload.get("tasks") or payload.get("results") or payload.get("runs")
    if isinstance(rows, list):
        records: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not _payload_failed(row):
                continue
            records.extend(
                _records_from_benchmark_payload(
                    row,
                    source,
                    source_ref=f"{source_ref}/items/{index}",
                )
            )
        return records
    if not _payload_failed(payload):
        return []
    task_id = str(
        payload.get("task_id")
        or payload.get("id")
        or payload.get("name")
        or payload.get("instance_id")
        or ""
    )
    reason = str(
        payload.get("reason")
        or payload.get("error")
        or payload.get("failure")
        or payload.get("message")
        or payload.get("stderr")
        or "Benchmark task failed"
    )
    return [
        _failure_record(
            source_type="benchmark_run",
            source=source,
            source_ref=source_ref,
            harness=str(payload.get("harness") or payload.get("agent") or ""),
            spec=str(payload.get("spec") or ""),
            task_id=task_id,
            check_name=str(payload.get("check") or payload.get("verifier") or "benchmark"),
            status="failed",
            symptom=reason,
            reason=reason,
            digest={
                "failure_category": str(payload.get("failure_category") or "benchmark_failure"),
                "dimension": {
                    "id": str(payload.get("dimension_id") or "D5"),
                    "label": "evaluation and verification",
                    "field": str(payload.get("surface") or "checks"),
                },
                "evidence": _dedupe_strings(
                    [
                        source_ref,
                        payload.get("trace"),
                        payload.get("trajectory"),
                        payload.get("log"),
                    ]
                ),
            },
            regressed=bool(payload.get("regressed")),
        )
    ]


def _failure_record(
    *,
    source_type: str,
    source: Path,
    source_ref: str,
    harness: str,
    spec: str,
    task_id: str,
    check_name: str,
    status: str,
    symptom: str,
    reason: str,
    digest: dict[str, Any],
    regressed: bool = False,
) -> dict[str, Any]:
    dimension = digest.get("dimension") if isinstance(digest.get("dimension"), dict) else {}
    failure_category = str(digest.get("failure_category") or "")
    evidence = _dedupe_strings([source_ref, *list(digest.get("evidence") or [])])
    return {
        "failure_id": "",
        "source_type": source_type,
        "source": str(source),
        "source_ref": source_ref,
        "harness": harness,
        "spec": spec,
        "task_id": task_id,
        "check_name": check_name,
        "status": status,
        "failure_category": failure_category,
        "dimension": {
            "id": str(dimension.get("id") or ""),
            "label": str(dimension.get("label") or ""),
            "field": str(dimension.get("field") or ""),
        },
        "symptom": _compact(symptom),
        "reason": _compact(reason),
        "regressed": bool(regressed),
        "evidence": evidence,
        "terminal_cause": failure_category or _compact(reason, limit=120),
        "agent_behavior_status": "regressed" if regressed else "failed",
        "mechanism": str(dimension.get("field") or "unknown"),
        "addressable": bool(_suggested_surfaces(dimension)),
        "suggested_surfaces": _suggested_surfaces(dimension),
    }


def _suggested_surfaces(dimension: dict[str, Any]) -> list[str]:
    field = str(dimension.get("field") or "")
    if not field:
        return []
    if field == "model_policy":
        return ["model_policy"]
    if field == "context":
        return ["context", "workflow"]
    if field == "context.memory":
        return ["context.memory", "context"]
    if field == "agents.tools":
        return ["agents.tools", "tools"]
    if field == "execution_policy.sandbox":
        return ["execution_policy.sandbox", "runtime"]
    if field == "checks":
        return ["checks", "evals"]
    if field == "execution_policy":
        return ["execution_policy", "agents.tools"]
    return [field]


def _failure_fingerprint(failure: dict[str, Any]) -> str:
    dimension = failure.get("dimension") or {}
    raw = "|".join(
        [
            str(failure.get("failure_category") or ""),
            str(dimension.get("field") or ""),
            str(failure.get("symptom") or ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _read_json_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _read_yaml_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(payload, list):
        raise ValueError(f"Expected YAML list in {path}")
    return [item for item in payload if isinstance(item, dict)]


def _first_string(values: Any) -> str:
    if isinstance(values, list) and values:
        return str(values[0])
    if values:
        return str(values)
    return ""


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _compact(text: str, limit: int = 240) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _payload_failed(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or payload.get("outcome") or "").lower()
    if status in {"failed", "fail", "failure", "error", "timeout", "regressed"}:
        return True
    if payload.get("passed") is False or payload.get("success") is False:
        return True
    if payload.get("failed") and _to_int(payload.get("failed")) > 0:
        return True
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pattern_confidence(count: int) -> str:
    if count >= 5:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


def _diff_values(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        diffs: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left:
                diffs.append({"path": child_path, "before": None, "after": _json_value(right[key])})
            elif key not in right:
                diffs.append({"path": child_path, "before": _json_value(left[key]), "after": None})
            else:
                diffs.extend(_diff_values(left[key], right[key], child_path))
        return diffs
    if isinstance(left, list) and isinstance(right, list):
        if left == right:
            return []
        return [{"path": path, "before": _json_value(left), "after": _json_value(right)}]
    if left == right:
        return []
    return [{"path": path, "before": _json_value(left), "after": _json_value(right)}]


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _surface_for_path(path: str) -> str:
    if path.startswith("execution_policy.sandbox"):
        return "sandbox"
    if path.startswith("execution_policy.approval") or path.startswith(
        "execution_policy.permission_rules"
    ):
        return "approvals"
    if path.startswith("execution_policy"):
        return "execution_policy"
    if path.startswith("checks"):
        return "checks"
    if path.startswith("agents") and ".tools" in path:
        return "agents.tools"
    if path.startswith("agents"):
        return "agents"
    if path.startswith("context.memory"):
        return "context.memory"
    top = path.split(".", 1)[0]
    return top or "root"


def _surface_matches(surface: str, path: str, pattern: str) -> bool:
    target = pattern.strip()
    if not target:
        return False
    if target == surface or surface.startswith(f"{target}."):
        return True
    if target == path or path.startswith(f"{target}."):
        return True
    aliases = {
        "sandbox": ("execution_policy.sandbox",),
        "approvals": ("execution_policy.approval_profile", "execution_policy.permission_rules"),
        "tools": ("agents.tools",),
    }
    return any(path.startswith(alias) or surface == alias for alias in aliases.get(target, ()))


def _permission_widening_risks(
    base_data: dict[str, Any],
    candidate_data: dict[str, Any],
) -> list[dict[str, str]]:
    base = base_data.get("execution_policy") or {}
    candidate = candidate_data.get("execution_policy") or {}
    risks: list[dict[str, str]] = []
    for key in ("allow_write", "allow_shell", "allow_network"):
        if not bool(base.get(key)) and bool(candidate.get(key)):
            risks.append(
                {
                    "path": f"execution_policy.{key}",
                    "surface": "execution_policy",
                    "message": f"Candidate widens {key} from false to true.",
                }
            )
    base_commands = set(base.get("allowed_commands") or [])
    candidate_commands = set(candidate.get("allowed_commands") or [])
    added_commands = sorted(candidate_commands - base_commands)
    if added_commands:
        risks.append(
            {
                "path": "execution_policy.allowed_commands",
                "surface": "execution_policy",
                "message": "Candidate adds allowed commands: " + ", ".join(added_commands),
            }
        )
    base_blocked = set(base.get("blocked_categories") or [])
    candidate_blocked = set(candidate.get("blocked_categories") or [])
    removed_blocks = sorted(base_blocked - candidate_blocked)
    if removed_blocks:
        risks.append(
            {
                "path": "execution_policy.blocked_categories",
                "surface": "execution_policy",
                "message": "Candidate removes blocked categories: " + ", ".join(removed_blocks),
            }
        )
    if _approval_rank(str(candidate.get("approval_profile") or "")) < _approval_rank(
        str(base.get("approval_profile") or "")
    ):
        risks.append(
            {
                "path": "execution_policy.approval_profile",
                "surface": "approvals",
                "message": "Candidate weakens approval profile.",
            }
        )
    if _sandbox_rank(str(candidate.get("sandbox") or "")) < _sandbox_rank(
        str(base.get("sandbox") or "")
    ):
        risks.append(
            {
                "path": "execution_policy.sandbox",
                "surface": "sandbox",
                "message": "Candidate moves to a less restrictive sandbox.",
            }
        )
    return risks


def _check_weakening_risks(
    base_data: dict[str, Any],
    candidate_data: dict[str, Any],
) -> list[dict[str, str]]:
    base = base_data.get("checks") or {}
    candidate = candidate_data.get("checks") or {}
    risks: list[dict[str, str]] = []
    if bool(base.get("enabled")) and not bool(candidate.get("enabled")):
        risks.append(
            {
                "path": "checks.enabled",
                "surface": "checks",
                "message": "Candidate disables checks.",
            }
        )
    if bool(base.get("fail_on_error")) and not bool(candidate.get("fail_on_error")):
        risks.append(
            {
                "path": "checks.fail_on_error",
                "surface": "checks",
                "message": "Candidate stops failing on check errors.",
            }
        )
    base_steps = {
        str(item.get("name") or index): item
        for index, item in enumerate(base.get("custom_steps") or [])
        if isinstance(item, dict)
    }
    candidate_steps = {
        str(item.get("name") or index): item
        for index, item in enumerate(candidate.get("custom_steps") or [])
        if isinstance(item, dict)
    }
    removed = sorted(set(base_steps) - set(candidate_steps))
    if removed:
        risks.append(
            {
                "path": "checks.custom_steps",
                "surface": "checks",
                "message": "Candidate removes check steps: " + ", ".join(removed),
            }
        )
    disabled = [
        name
        for name, step in candidate_steps.items()
        if name in base_steps
        and bool(base_steps[name].get("enabled", True))
        and not bool(step.get("enabled", True))
    ]
    if disabled:
        risks.append(
            {
                "path": "checks.custom_steps.enabled",
                "surface": "checks",
                "message": "Candidate disables check steps: " + ", ".join(disabled),
            }
        )
    return risks


def _candidate_eval_gates(
    *,
    eval_result_paths: tuple[str | Path, ...],
    candidate_spec_path: Path,
    candidate_name: str,
    required_splits: tuple[str, ...],
    allow_ungated: bool,
) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    regression_refs: list[str] = []
    passed_splits: set[str] = set()
    for item in eval_result_paths:
        path = Path(item).expanduser().resolve()
        payload = _read_json_mapping(path)
        split = str(payload.get("split") or "all")
        variant = _select_candidate_variant(payload, candidate_spec_path, candidate_name)
        if not variant:
            gates.append(
                {
                    "path": str(path),
                    "split": split,
                    "status": "missing_candidate",
                    "candidate": "",
                    "passed": False,
                    "regressions": [],
                }
            )
            continue
        regressions = [str(value) for value in variant.get("regressions_vs_baseline") or []]
        skipped = _to_int(variant.get("skipped"))
        total_tasks = len(variant.get("tasks") or [])
        not_executed = not bool(payload.get("live")) or (total_tasks > 0 and skipped == total_tasks)
        status = "passed"
        passed = True
        if not_executed:
            status = "not_executed"
            passed = bool(allow_ungated)
        elif bool(variant.get("regressed")) or regressions:
            status = "failed"
            passed = False
            regression_refs.extend(f"{path}#{task_id}" for task_id in regressions)
        if passed and status == "passed":
            passed_splits.add(split)
        gates.append(
            {
                "path": str(path),
                "split": split,
                "status": status,
                "candidate": variant.get("harness") or "",
                "score": variant.get("score"),
                "passed": passed,
                "regressions": regressions,
                "live": bool(payload.get("live")),
            }
        )
    missing_required = [
        split for split in required_splits if split not in passed_splits and "all" not in passed_splits
    ]
    return {
        "required_splits": list(required_splits),
        "missing_required_splits": [] if allow_ungated else missing_required,
        "gates": gates,
        "regressed": any(gate.get("status") == "failed" for gate in gates),
        "regression_refs": regression_refs,
        "passed": not any(gate.get("status") == "failed" for gate in gates)
        and (allow_ungated or not missing_required),
    }


def _select_candidate_variant(
    payload: dict[str, Any],
    candidate_spec_path: Path,
    candidate_name: str,
) -> dict[str, Any] | None:
    variants = [item for item in payload.get("variants") or [] if isinstance(item, dict)]
    if not variants:
        return None
    candidate_path = str(candidate_spec_path)
    for variant in variants:
        spec = str(variant.get("spec") or "")
        if spec and (spec == candidate_path or Path(spec).name == candidate_spec_path.name):
            return variant
    for variant in variants[1:]:
        if str(variant.get("harness") or "") == candidate_name:
            return variant
    if len(variants) == 2:
        return variants[1]
    return next((item for item in variants[1:] if not item.get("regressed")), variants[-1])


def _candidate_novelty(
    *,
    ledger_path: str | Path,
    diff_fingerprint: str,
    changed_surfaces: tuple[str, ...],
) -> dict[str, Any]:
    ledger = read_candidate_ledger(ledger_path)
    records = ledger.get("candidates") or []
    changed = set(changed_surfaces)
    nearest_id = ""
    max_similarity = 0.0
    duplicate_rejected = ""
    for record in records:
        if record.get("diff_fingerprint") == diff_fingerprint and not record.get("accepted"):
            duplicate_rejected = str(record.get("candidate_id") or "")
        previous = set(str(value) for value in record.get("changed_surfaces") or [])
        if not changed and not previous:
            similarity = 1.0
        elif not changed or not previous:
            similarity = 0.0
        else:
            similarity = len(changed & previous) / len(changed | previous)
        if similarity > max_similarity:
            max_similarity = similarity
            nearest_id = str(record.get("candidate_id") or "")
    return {
        "ledger_path": str(Path(ledger_path).expanduser()),
        "previous_candidates": len(records),
        "nearest_candidate_id": nearest_id,
        "max_surface_similarity": round(max_similarity, 3),
        "duplicate_rejected": duplicate_rejected,
    }


def _violation(
    code: str,
    message: str,
    *,
    blocking: bool = True,
    paths: list[str] | None = None,
    surfaces: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "blocking": blocking,
        "paths": list(paths or []),
        "surfaces": list(surfaces or []),
    }


def _approval_rank(value: str) -> int:
    ranks = {
        "permissive": 0,
        "auto": 0,
        "balanced": 1,
        "ask": 1,
        "strict": 2,
        "locked": 3,
    }
    return ranks.get(value.lower(), 1)


def _sandbox_rank(value: str) -> int:
    ranks = {
        "local": 0,
        "workspace-write": 1,
        "git-worktree": 1,
        "docker": 2,
        "e2b": 2,
        "daytona": 2,
        "no-shell": 3,
        "read-only": 4,
    }
    return ranks.get(value.lower(), 1)


def _hash_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _iso_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0
