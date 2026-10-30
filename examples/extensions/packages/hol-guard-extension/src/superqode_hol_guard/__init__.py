"""HOL Guard gate for SuperQode's native before-tool extension boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable

from superqode import Extension
from superqode.agent.hooks import ALLOW, DENY, HookDecision
from superqode.tools.validation import validate_working_dir_parameter


DEFAULT_TIMEOUT_SECONDS = 6.0

extension = Extension(
    "hol-guard",
    name="HOL Guard",
    version="0.1.0",
    description="Runs local shell tool requests through HOL Guard before execution.",
)


def _non_empty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _reject_duplicate_guard_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject conflicting machine verdicts, including nested classification fields."""
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate key in Guard JSON verdict")
        obj[key] = value
    return obj


def _last_json_object(stdout: str) -> dict[str, Any] | None:
    """Require exactly one JSON-object verdict, without mixed diagnostic output."""
    text = stdout.strip()
    if not text:
        return None
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_guard_keys)
    except (ValueError, RecursionError):
        # The CLI promises JSON on stdout. Any diagnostic prefix, suffix,
        # second object or echoed command makes the result non-authoritative.
        return None
    return value if isinstance(value, dict) else None


def _reason(payload: dict[str, Any] | None) -> str:
    if payload:
        classification = payload.get("classification")
        if isinstance(classification, dict):
            reason = _non_empty_text(classification.get("reason"))
            if reason:
                return reason
        for key in ("reason", "message"):
            reason = _non_empty_text(payload.get(key))
            if reason:
                return reason
    return "HOL Guard did not allow this command."


def decision_from_guard_payload(payload: dict[str, Any] | None) -> HookDecision:
    """Map Guard's command-test payload to SuperQode's gating decision."""
    if not isinstance(payload, dict):
        return HookDecision(action=DENY, message="HOL Guard returned an invalid response.")
    decision = payload.get("decision")
    hook_output = payload.get("hookSpecificOutput")
    if (
        ("continue" in payload and payload["continue"] is not True)
        or (
            "decision" in payload
            and (not isinstance(decision, str) or decision.strip().lower() != "allow")
        )
        or (
            "policy_action" in payload
            and (
                not isinstance(payload["policy_action"], str)
                or payload["policy_action"] not in {"allow", "not_run"}
            )
        )
        or (
            "hookSpecificOutput" in payload
            and (
                not isinstance(hook_output, dict)
                or hook_output.get("permissionDecision") != "allow"
                or hook_output.get("hookEventName") != "PreToolUse"
            )
        )
    ):
        return HookDecision(
            action=DENY,
            message="HOL Guard explicitly refused tool continuation.",
            reason="HOL Guard gate",
        )

    minimum_action = _non_empty_text(payload.get("minimum_action"))
    if minimum_action:
        minimum_action = minimum_action.lower()
    classification = payload.get("classification")
    explicitly_benign = (
        isinstance(classification, dict) and classification.get("explicitly_benign") is True
    )

    if minimum_action == "allow" and explicitly_benign:
        return HookDecision(action=ALLOW, reason="HOL Guard explicitly classified the command benign.")
    if minimum_action in {"allow", "monitor", "review", "block"}:
        return HookDecision(action=DENY, message=_reason(payload), reason="HOL Guard gate")
    return HookDecision(
        action=DENY,
        message="HOL Guard returned no recognized decision.",
        reason="HOL Guard gate",
    )


def evaluate_command(
    command: str,
    working_directory: Path,
    *,
    binary: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> HookDecision:
    """Run a shell command through the local HOL Guard CLI without invoking a shell."""
    guard_binary = _non_empty_text(binary) or _non_empty_text(os.environ.get("HOL_GUARD_BIN"))
    guard_binary = guard_binary or "hol-guard"
    # Resolve PATH and relative binaries in the caller's directory *before*
    # switching cwd. Otherwise a project-local executable can shadow Guard.
    resolved_binary = shutil.which(guard_binary)
    if not resolved_binary:
        return HookDecision(
            action=DENY,
            message="HOL Guard executable could not be resolved.",
            reason="HOL Guard gate launch failure",
        )
    selected_binary = os.path.abspath(resolved_binary)
    guard_binary = os.path.realpath(selected_binary)
    try:
        # Use the outermost Git root. A nested .git marker can be supplied by
        # an untrusted project, and a project-owned symlink can point outside.
        root = os.path.realpath(working_directory)
        current = root
        while True:
            if os.path.lexists(os.path.join(current, ".git")):
                root = current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        if any(
            os.path.commonpath((root, candidate)) == root
            for candidate in (selected_binary, guard_binary)
        ):
            return HookDecision(
                action=DENY,
                message="HOL Guard executable is controlled by the project worktree.",
                reason="HOL Guard gate untrusted executable",
            )
    except (OSError, ValueError):
        return HookDecision(
            action=DENY,
            message="HOL Guard executable location could not be verified.",
            reason="HOL Guard gate launch failure",
        )
    try:
        completed = runner(
            [guard_binary, "command", "test", "--json", "--", command],
            cwd=str(working_directory),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return HookDecision(
            action=DENY,
            message=f"HOL Guard did not return a decision within {timeout_seconds:g}s.",
            reason="HOL Guard gate timeout",
        )
    except OSError as exc:
        return HookDecision(
            action=DENY,
            message=f"HOL Guard could not start: {exc}",
            reason="HOL Guard gate launch failure",
        )
    except ValueError as exc:
        # subprocess may reject an argv with NUL or fail to decode CLI output.
        # Report a deny rather than raising out of the reusable evaluator.
        return HookDecision(
            action=DENY,
            message=f"HOL Guard returned invalid process data: {exc}",
            reason="HOL Guard gate process failure",
        )

    if completed.returncode != 0:
        return HookDecision(
            action=DENY,
            message=f"HOL Guard exited with code {completed.returncode}.",
            reason="HOL Guard gate process failure",
        )
    return decision_from_guard_payload(_last_json_object(completed.stdout))


@extension.before_tool
def hol_guard_before_tool(ctx, name: str = "", arguments=None):
    """Gate SuperQode's native bash tool immediately before execution."""
    # Missing or malformed tool names cannot prove an unrelated safe tool.
    # Do not silently abstain if the host loses a protected bash identity.
    if not isinstance(name, str) or not name.strip():
        return HookDecision(
            action=DENY,
            message="HOL Guard could not identify the tool being called.",
            reason="HOL Guard gate input failure",
        )
    if name != "bash":
        return None
    if not isinstance(arguments, dict):
        return HookDecision(
            action=DENY,
            message="HOL Guard could not inspect the bash tool arguments.",
            reason="HOL Guard gate input failure",
        )
    # Inspect exactly what the bash tool will run, including whitespace and newlines.
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        return HookDecision(
            action=DENY,
            message="HOL Guard could not inspect an empty bash command.",
            reason="HOL Guard gate input failure",
        )
    try:
        # Match the exact directory validated by the native BashTool before it
        # executes. A tool-level working_dir overrides the session directory.
        cwd = validate_working_dir_parameter(
            arguments.get("working_dir"), Path(ctx.working_directory)
        )
        return evaluate_command(command, cwd)
    except Exception:
        # SuperQode treats hook exceptions as abstentions. Convert any unexpected
        # adapter failure into an explicit deny so this security gate stays closed.
        return HookDecision(
            action=DENY,
            message="HOL Guard evaluation failed before the tool could run.",
            reason="HOL Guard gate internal failure",
        )
