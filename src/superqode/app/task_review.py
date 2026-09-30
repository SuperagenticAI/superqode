"""Build reviewable task results from recorded edits and terminal tool events."""

from __future__ import annotations

import re
import shlex

from superqode.app.outcomes import Outcome, OutcomeSeverity, OutcomeAction


def _test_command(command: str) -> bool:
    for segment in re.split(r"\s*(?:&&|\|\||[;|])\s*", command):
        try:
            words = shlex.split(segment)
        except ValueError:
            continue
        while words and (
            "=" in words[0]
            or words[0] in {"env", "uv", "run", "exec", "npx"}
            or words[0].startswith("-")
        ):
            words.pop(0)
        if not words:
            continue
        executable = words[0].rsplit("/", 1)[-1]
        if executable in {"pytest", "py.test", "unittest", "vitest", "jest", "ctest"}:
            return True
        if executable.startswith("python") and words[1:3] in (["-m", "pytest"], ["-m", "unittest"]):
            return True
        if executable in {
            "npm",
            "pnpm",
            "yarn",
            "bun",
            "cargo",
            "go",
            "dotnet",
            "mvn",
            "gradle",
        } and (words[1:2] == ["test"] or words[1:3] == ["run", "test"]):
            return True
    return False


def task_review(summary: dict, calls: list[dict]) -> Outcome:
    """Use tool status/exit codes as evidence; never interpret model claims."""
    files = list(dict.fromkeys(summary.get("files_modified") or []))
    diffs = summary.get("file_diffs") or {}
    details = []
    if files:
        details.append("File Changes\n" + "\n".join(str(path) for path in files))
    tests = []
    failed = False
    for call in calls:
        if call.get("status") not in {"success", "error"}:
            continue
        command = str(call.get("command") or "")
        if not _test_command(command):
            continue
        metadata = call.get("metadata") or {}
        exit_code = metadata.get("exit_code")
        ok = call["status"] == "success" and exit_code in (None, 0, "0")
        failed |= not ok
        status = "Command succeeded" if ok else "Command failed"
        if exit_code is not None:
            status += f" · exit {exit_code}"
        tests.append(f"{command}\n{status}\n{str(call.get('output') or '')[:4000]}")
    details.append("Tests\n" + ("\n\n".join(tests) if tests else "Not recorded"))
    # Diffs belong to this turn, not the current repository working tree.
    for path in files:
        diff = str((diffs.get(path) or {}).get("diff_text") or "")
        if diff:
            details.append(
                f"{path}\n{diff[:16000]}"
                + ("\nDiff preview limited to 16,000 characters." if len(diff) > 16000 else "")
            )
    remaining = summary.get("remaining_work")
    if remaining:
        details.append("Remaining work\n" + str(remaining))
    return Outcome(
        title="Done",
        summary=f"{len(files)} files changed · Tests: "
        + ("Command failed" if failed else "Command succeeded" if tests else "Not recorded"),
        details=tuple(details),
        severity=OutcomeSeverity.WARNING if failed else OutcomeSeverity.INFORMATION,
        source="task",
        actions=(
            OutcomeAction(
                "review", "Review changes", f":diff task {summary['task_id']}", primary=True
            ),
        )
        if summary.get("task_id") and files
        else (),
    )
