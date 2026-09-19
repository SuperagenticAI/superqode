"""HOL Guard gate for SuperQode's native before-tool extension boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

from superqode import Extension
from superqode.agent.hooks import ALLOW, DENY, HookDecision


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


def _last_json_object(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


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
    try:
        completed = runner(
            [guard_binary, "command", "test", command, "--json"],
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
    if name != "bash":
        return None
    if not isinstance(arguments, dict):
        return HookDecision(
            action=DENY,
            message="HOL Guard could not inspect the bash tool arguments.",
            reason="HOL Guard gate input failure",
        )
    command = _non_empty_text(arguments.get("command"))
    if not command:
        return HookDecision(
            action=DENY,
            message="HOL Guard could not inspect an empty bash command.",
            reason="HOL Guard gate input failure",
        )
    try:
        return evaluate_command(command, Path(ctx.working_directory))
    except Exception:
        # SuperQode treats hook exceptions as abstentions. Convert any unexpected
        # adapter failure into an explicit deny so this security gate stays closed.
        return HookDecision(
            action=DENY,
            message="HOL Guard evaluation failed before the tool could run.",
            reason="HOL Guard gate internal failure",
        )
