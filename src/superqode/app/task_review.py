"""Build reviewable task results from recorded edits and terminal tool events."""

from __future__ import annotations

from superqode.app.outcomes import Outcome, OutcomeSeverity, OutcomeAction
from superqode.workspace_evidence import is_test_command as _test_command, matching_states


def task_review(summary: dict, calls: list[dict]) -> Outcome:
    """Use tool status/exit codes as evidence; never interpret model claims."""
    files = list(dict.fromkeys(summary.get("files_modified") or []))
    diffs = summary.get("file_diffs") or {}
    details = []
    if files:
        details.append("File Changes\n" + "\n".join(str(path) for path in files))
    tests = []
    failed = False
    unknown = False
    last_check = -1
    check_evidence = {}
    last_mutation = -1
    for index, call in enumerate(calls):
        name = str(call.get("name") or "").lower()
        if call.get("status") in {"success", "error"} and (
            call.get("diff_text")
            or name
            in {
                "write",
                "write_file",
                "edit",
                "edit_file",
                "create_file",
                "insert_text",
                "apply_patch",
                "patch",
                "multi_edit",
                "bash",
                "shell",
                "python",
            }
        ):
            last_mutation = index
        if call.get("status") not in {"success", "error"}:
            continue
        command = str(call.get("command") or "")
        if not _test_command(command):
            continue
        metadata = call.get("metadata") or {}
        exit_code = metadata.get("exit_code")
        # A shell chain can mask the test process exit code (pytest || true).
        compound = any(token in command for token in ("||", "|", ";", "&&", "\n"))
        ok = call["status"] == "success" and exit_code in (0, "0") and not compound
        is_failure = call["status"] == "error" or exit_code not in (None, 0, "0")
        failed |= is_failure
        unknown |= not ok and not is_failure
        if ok:
            last_check = index
            check_evidence[command] = metadata.get("workspace_evidence") or {}
        status = (
            "Command succeeded"
            if ok
            else "Command failed"
            if is_failure
            else "Exit status unverified"
        )
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
    stale = last_check >= 0 and last_mutation > last_check
    if stale:
        details.append(
            "Verification\nChanges or commands ran after the last check. Run checks again on the final changes."
        )
    elif tests:
        details.append(
            "Verification\nRecorded command evidence covers this turn. External edits and test coverage are not independently certified."
        )
    final_state = summary.get("workspace_state") or {}
    bound = bool(check_evidence) and all(
        matching_states(evidence.get("before", {}), evidence.get("after", {}), final_state)
        for evidence in check_evidence.values()
    )
    if any(check_evidence.values()) and final_state and not bound:
        stale = True
        details.append(
            "Workspace verification\nThe check and final workspace snapshots do not match, or capture was incomplete. Run checks again."
        )
    if bound and not stale:
        details.append(
            "Workspace verification\nChecks matched the final Git-visible file snapshot at "
            + final_state.get("captured_at", "")
            + ". Ignored files, external dependencies and subsequent changes are outside this evidence."
        )
    remaining = summary.get("remaining_work")
    if remaining:
        details.append("Remaining work\n" + str(remaining))
    return Outcome(
        title="Checks failed"
        if failed
        else "Unverified"
        if unknown or stale or not tests or remaining
        else "Checks matched final snapshot"
        if bound
        else "Checks recorded",
        summary=f"{len(files)} files changed · Tests: "
        + (
            "Command failed"
            if failed
            else "Outdated"
            if stale
            else "Unverified"
            if unknown
            else "Command succeeded"
            if tests
            else "Not recorded"
        ),
        details=tuple(details),
        severity=OutcomeSeverity.WARNING
        if failed or stale or unknown
        else OutcomeSeverity.INFORMATION,
        source="task",
        actions=(
            OutcomeAction(
                "review", "Review changes", f":diff task {summary['task_id']}", primary=True
            ),
        )
        if summary.get("task_id") and files
        else (),
    )
