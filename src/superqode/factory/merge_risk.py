"""Deterministic, advisory 5-dimension Merge Risk assessment for Factory trials.

Evaluates Alignment, Impact, Verification, Rollback cost, and Error detection
strictly from recorded diff, touched paths, verification receipts, and proof
artifacts. Advisory only: never silently overrides SuperGauge SHIP/HOLD/REJECT.
"""

from __future__ import annotations

import re
from typing import Any

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

_SENSITIVE_PATH_TOKENS = (
    "auth",
    "oauth",
    "login",
    "session",
    "security",
    "permission",
    "secret",
    "credential",
    "keychain",
    "billing",
    "payment",
    "stripe",
    "migration",
    "migrations",
    "schema",
    "database",
    "sqlite",
    "governance",
    "release",
    ".github/workflows",
)

_ONE_WAY_DOOR_TOKENS = (
    "migration",
    "migrations",
    "schema",
    ".sql",
    "alembic",
    "storage",
    "persisted",
    "recovery",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "info.plist",
)

_UI_PATH_TOKENS = (
    "view.swift",
    "screen.swift",
    ".tsx",
    ".jsx",
    ".vue",
    ".svelte",
    ".css",
    "apps/macos/",
    "apps/ios/",
)

_TEST_PATH_TOKENS = (
    "test_",
    "_test.",
    "tests/",
    "Tests/",
    ".spec.",
    ".test.",
)

_SWALLOWED_ERROR_PATTERNS = (
    re.compile(r"^\+\s*except\b[^:]*:\s*(pass|\.\.\.)\s*$"),
    re.compile(r"^\+\s*catch\b[^{]*\{\s*\}\s*$"),
    re.compile(r"^\+\s*//\s*ignore\s+error", re.IGNORECASE),
)

_ERROR_REPORTING_PATTERNS = (
    re.compile(r"^\+.*\b(logger\.|logging\.|raise\s+|throw\s+|NSLog|os_log|failure\s*=)"),
)


def _extract_diff_files(diff_text: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null" and path not in seen:
                seen.add(path)
                files.append(path)
        elif line.startswith("diff --git a/"):
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                path = parts[1].strip()
                if path and path not in seen:
                    seen.add(path)
                    files.append(path)
    return files


def _top_area(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"src", "apps", "packages"}:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else "."


def _goal_tokens(goal: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", (goal or "").casefold())}


def _max_risk(*levels: str) -> str:
    best = "low"
    for level in levels:
        if _RISK_ORDER.get(level, 0) > _RISK_ORDER[best]:
            best = level
    return best


def assess_merge_risk(
    *,
    goal: str = "",
    diff_text: str = "",
    files: list[str] | None = None,
    verification: dict[str, Any] | None = None,
    visual_proof: dict[str, Any] | None = None,
    stage_statuses: list[str] | None = None,
) -> dict[str, Any]:
    """Compute a deterministic 5-dimension Merge Risk assessment."""
    changed_files = list(files) if files else _extract_diff_files(diff_text)
    added_lines = [
        line
        for line in (diff_text or "").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    removed_lines = [
        line
        for line in (diff_text or "").splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    total_churn = len(added_lines) + len(removed_lines)
    verification = verification or {}
    visual_proof = visual_proof or {}

    gaps: list[str] = []

    # 1. Alignment: scope coherence vs. stated goal
    areas = sorted({_top_area(p) for p in changed_files})
    tokens = _goal_tokens(goal)
    file_overlap = sum(1 for p in changed_files if any(tok in p.casefold() for tok in tokens))
    if not changed_files:
        align_risk = "low"
        align_summary = "No candidate file changes recorded yet."
    elif len(changed_files) > 16 or len(areas) > 4:
        align_risk = "high"
        align_summary = (
            f"Touches {len(changed_files)} files across {len(areas)} areas; "
            "verify no drive-by edits outside the goal."
        )
        gaps.append(
            "Large multi-area diff; confirm every touched file belongs to the requested goal."
        )
    elif len(changed_files) > 8 or (len(areas) > 2 and file_overlap == 0 and tokens):
        align_risk = "medium"
        align_summary = f"Touches {len(changed_files)} files across {len(areas)} areas ({', '.join(areas[:3])})."
    else:
        align_risk = "low"
        align_summary = (
            f"Focused scope: {len(changed_files)} file"
            f"{'' if len(changed_files) == 1 else 's'} ({total_churn} changed lines)."
        )

    # 2. Impact: blast radius & sensitive areas
    sensitive = [
        p for p in changed_files if any(tok in p.casefold() for tok in _SENSITIVE_PATH_TOKENS)
    ]
    if sensitive:
        impact_risk = "high" if len(sensitive) >= 2 or total_churn > 200 else "medium"
        impact_summary = (
            f"Touches sensitive surface ({', '.join(sensitive[:3])}"
            f"{'…' if len(sensitive) > 3 else ''})."
        )
        gaps.append(f"Sensitive files modified: {', '.join(sensitive[:3])}.")
    elif total_churn > 400 or len(changed_files) > 12:
        impact_risk = "medium"
        impact_summary = (
            f"Moderate blast radius ({total_churn} lines across {len(changed_files)} files)."
        )
    elif not changed_files:
        impact_risk = "low"
        impact_summary = "No repository mutations recorded yet."
    else:
        impact_risk = "low"
        impact_summary = "Isolated change outside auth, permissions, schema, and workflow paths."

    # 3. Verification: protected checks, tests, and UI visual proof
    verif_state = str(verification.get("state") or "").lower()
    touches_test = any(any(tok in p for tok in _TEST_PATH_TOKENS) for p in changed_files)
    touches_ui = any(any(tok in p.casefold() for tok in _UI_PATH_TOKENS) for p in changed_files)
    has_proof_media = bool(visual_proof.get("items")) or bool(visual_proof.get("summary"))
    if verif_state == "failed":
        verify_risk = "high"
        verify_summary = "Protected SuperGauge verification failed."
        gaps.append("Protected acceptance checks failed; fix failures before merging.")
    elif verif_state == "passed":
        if touches_ui and not has_proof_media:
            verify_risk = "medium"
            verify_summary = (
                "Protected checks passed, but UI files changed with no visual proof attached."
            )
            gaps.append(
                "UI files changed without visual proof; attach screenshots or walkthrough notes."
            )
        else:
            verify_risk = "low"
            parts = ["Protected checks passed"]
            if touches_test:
                parts.append("regression tests updated")
            if has_proof_media:
                parts.append("visual proof attached")
            verify_summary = ", ".join(parts) + "."
    else:
        if changed_files and not touches_test:
            verify_risk = "high"
            verify_summary = (
                "Protected verification has not run yet and no test files were updated."
            )
            gaps.append("Run SuperGauge verification and confirm test coverage before shipping.")
        elif changed_files:
            verify_risk = "medium"
            verify_summary = (
                "Tests were touched, but protected SuperGauge verification has not run yet."
            )
            gaps.append("Run protected SuperGauge verification to produce a deterministic verdict.")
        else:
            verify_risk = "low"
            verify_summary = "Pending implementation and verification."

    # 4. Rollback cost: two-way door vs. one-way door
    one_way = [p for p in changed_files if any(tok in p.casefold() for tok in _ONE_WAY_DOOR_TOKENS)]
    if any(
        tok in p.casefold() for p in one_way for tok in ("migration", "schema", ".sql", "alembic")
    ):
        rollback_risk = "high"
        rollback_summary = (
            f"Potential one-way door: schema or migration touched ({', '.join(one_way[:2])})."
        )
        gaps.append("Schema/migration change increases rollback cost; document downgrade steps.")
    elif one_way:
        rollback_risk = "medium"
        rollback_summary = (
            f"Persisted state or dependency metadata touched ({', '.join(one_way[:2])}); "
            "verify rollback path."
        )
    elif not changed_files:
        rollback_risk = "low"
        rollback_summary = "No persisted state or schema changes."
    else:
        rollback_risk = "low"
        rollback_summary = "Two-way door: reversible with a standard git revert."

    # 5. Error detection: swallowed exceptions vs. explicit reporting
    swallowed = sum(
        1
        for line in added_lines
        if any(pattern.search(line) for pattern in _SWALLOWED_ERROR_PATTERNS)
    )
    reporting = sum(
        1
        for line in added_lines
        if any(pattern.search(line) for pattern in _ERROR_REPORTING_PATTERNS)
    )
    if swallowed >= 2:
        error_risk = "high"
        error_summary = f"Detected {swallowed} added empty/silent exception handlers."
        gaps.append("Added code swallows exceptions silently; surface or log errors explicitly.")
    elif swallowed == 1:
        error_risk = "medium"
        error_summary = (
            "Detected 1 added silent exception handler; verify failures stay observable."
        )
        gaps.append("Review the silent exception handler to ensure production errors are visible.")
    elif not added_lines:
        error_risk = "low"
        error_summary = "No added error-handling issues detected."
    else:
        error_risk = "low"
        error_summary = (
            "No silent error swallowing detected; explicit error reporting present."
            if reporting > 0
            else "No silent error swallowing detected in added lines."
        )

    categories = [
        {"id": "alignment", "title": "Alignment", "risk": align_risk, "summary": align_summary},
        {"id": "impact", "title": "Impact", "risk": impact_risk, "summary": impact_summary},
        {
            "id": "verification",
            "title": "Verification",
            "risk": verify_risk,
            "summary": verify_summary,
        },
        {
            "id": "rollback",
            "title": "Rollback cost",
            "risk": rollback_risk,
            "summary": rollback_summary,
        },
        {
            "id": "error_detection",
            "title": "Error detection",
            "risk": error_risk,
            "summary": error_summary,
        },
    ]
    overall = _max_risk(*(row["risk"] for row in categories))

    lines = [
        f"## Merge Risk Assessment (**{overall.upper()}**)",
        "",
        "| Category | Verdict | Summary |",
        "| --- | --- | --- |",
    ]
    for row in categories:
        lines.append(f"| {row['title']} | **{row['risk'].upper()}** | {row['summary']} |")
    if gaps:
        lines.extend(["", "### Gaps to address", *[f"- {gap}" for gap in gaps]])

    return {
        "overall": overall,
        "advisory": True,
        "file_count": len(changed_files),
        "churn_lines": total_churn,
        "categories": categories,
        "gaps": gaps,
        "markdown": "\n".join(lines),
    }
