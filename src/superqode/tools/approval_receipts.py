"""Host-owned, invocation-scoped consent for contextual ASK decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Mapping

from superqode.governance import active_governance


def argument_digest(arguments: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(arguments), sort_keys=True, default=str).encode()
    ).hexdigest()


def policy_revision() -> str:
    bundle = active_governance()
    return argument_digest(bundle.to_public_dict()) if bundle is not None else "ungoverned"


@dataclass(frozen=True)
class ApprovalReceipt:
    invocation_id: str
    tool_name: str
    arguments_sha256: str
    policy_revision: str
    _lock: Any = field(default_factory=Lock, compare=False, repr=False)
    _consumed: bool = field(default=False, compare=False, repr=False)

    def matches(self, invocation_id: str, tool_name: str, arguments: Mapping[str, Any]) -> bool:
        return (
            not self._consumed
            and bool(invocation_id)
            and (
                self.invocation_id == invocation_id
                and self.tool_name == tool_name
                and self.arguments_sha256 == argument_digest(arguments)
                and self.policy_revision == policy_revision()
            )
        )

    def consume(self, invocation_id: str, tool_name: str, arguments: Mapping[str, Any]) -> bool:
        with self._lock:
            if not self.matches(invocation_id, tool_name, arguments):
                return False
            object.__setattr__(self, "_consumed", True)
            return True


def issue_receipt(loop, pending: Mapping[str, Any]) -> ApprovalReceipt:
    """Called only by the host approval handler, never from model arguments."""
    receipt = ApprovalReceipt(
        str(pending.get("tool_call_id") or ""),
        str(pending.get("tool_name") or ""),
        argument_digest(pending.get("arguments") or {}),
        str(pending.get("policy_revision") or policy_revision()),
    )
    if not hasattr(loop, "_approval_receipts"):
        loop._approval_receipts = {}
    loop._approval_receipts[receipt.invocation_id] = receipt
    return receipt
