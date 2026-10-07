"""Small projections for run supervision; execution stores retain ownership."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from superqode.systemone.state import redact_evidence
from superqode.tools.approval_receipts import argument_digest


@dataclass(frozen=True)
class SupervisionEntry:
    id: str
    label: str
    state: str
    detail: str
    source: str = ""
    target: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    store: str = ""


@dataclass(frozen=True)
class SupervisionSnapshot:
    runs: tuple[SupervisionEntry, ...] = ()
    approvals: tuple[SupervisionEntry, ...] = ()
    delivery: tuple[SupervisionEntry, ...] = ()
    notice: str = ""

    def entries(self, section: str) -> tuple[SupervisionEntry, ...]:
        return getattr(self, section)


def request_identity(source: str, target: str, request: dict) -> str:
    """Bind selection to owner, request identity and exact effective arguments."""
    content = {key: value for key, value in request.items() if key != "index"}
    return argument_digest({"source": source, "target": target, "request": content})


def evidence_text(value: Any, limit: int = 16000) -> str:
    value = redact_evidence(value)
    text = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)
    return text[:limit] + ("\n[Preview limited]" if len(text) > limit else "")


def approval_entry(source: str, target: str, owner: str, request: dict) -> SupervisionEntry:
    identity = request_identity(source, target, request)
    arguments = request.get("arguments") or {}
    argument_lines = "\n".join(f"{key}: {evidence_text(value)}" for key, value in arguments.items())
    detail = (
        f"{owner} · {request.get('tool_name') or 'unknown'}\n"
        + (argument_lines or "Arguments: none")
        + "\nScope: this request only\n"
        + f"Reason: {request.get('reason') or 'Not reported'}\n"
        + f"Risk: {request.get('risk') or 'Not reported'}\n"
        + f"Invocation: {request.get('tool_call_id') or request.get('approval_id') or 'not reported'}\n"
        + "\nApprove once or reject. A changed request must be inspected again.\n\n"
        + evidence_text(request)
    )
    return SupervisionEntry(
        identity,
        f"{owner} · {request.get('tool_name') or 'approval'}",
        "Waiting for approval",
        detail,
        source,
        target,
        dict(request),
    )


def display_state(state: str) -> str:
    return {
        "running": "Running",
        "starting": "Starting",
        "needs_approval": "Waiting for approval",
        "succeeded": "Completed",
        "failed": "Failed",
        "error": "Failed",
        "cancelled": "Cancelled",
        "closed": "Closed",
        "idle": "Idle",
        "pending": "Pending",
        "ready": "Ready",
        "queued": "Queued",
        "blocked": "Blocked",
        "ready_to_merge": "Ready for review",
        "merged": "Merged",
        "rolled_back": "Rolled back",
    }.get(state, state.replace("_", " ").capitalize() or "Not reported")
