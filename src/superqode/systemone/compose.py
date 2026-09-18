"""Compose tool_gate answers into ALLOW / DENY / ASK.

Code owns this, not the model. Hard deterministic denials never call the
client. A client error, timeout, or missing client fail-opens to ASK.
"""

from __future__ import annotations

import time

from enum import Enum
from typing import Any

from .client import SystemOneClient, SystemOneError
from .pack import QuestionPack, ToolGateThresholds, load_pack
from .state import ToolGateState
from .types import Answers, ChoiceAnswer, SchemaViolation


class GateAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class GateDecision:
    """Composed tool-gate verdict plus the audit fields a ToolResult stores."""

    def __init__(
        self,
        action: GateAction,
        reason: str,
        *,
        skipped_client: bool = False,
        pack_id: str = "",
        pack_version: str = "",
        pack_hash: str = "",
        client: str = "stub",
        nouls: dict[str, float] | None = None,
        choice: str | None = None,
        confidence: float | None = None,
        message: str = "",
        evaluation: dict[str, Any] | None = None,
    ) -> None:
        self.evaluation = dict(evaluation or {})
        self.action = action
        self.reason = reason
        self.skipped_client = skipped_client
        self.pack_id = pack_id
        self.pack_version = pack_version
        self.pack_hash = pack_hash
        self.client = client
        self.nouls = dict(nouls or {})
        self.choice = choice
        self.confidence = confidence
        self.message = message or reason

    def metadata(self) -> dict[str, Any]:
        pack = f"{self.pack_id}@{self.pack_version}" if self.pack_id else ""
        return {
            "permission": "systemone",
            "answers": getattr(self, "answers", {}),
            "evaluation": self.evaluation,
            "pack": pack,
            "pack_hash": self.pack_hash,
            "client": self.client,
            "nouls": dict(self.nouls),
            "choice": self.choice,
            "confidence": self.confidence,
            "reason": self.reason,
            "skipped_client": self.skipped_client,
        }


def _pack_fields(pack: QuestionPack | None) -> dict[str, str]:
    if pack is None:
        return {}
    return {
        "pack_id": pack.id,
        "pack_version": pack.version,
        "pack_hash": pack.content_hash(),
    }


def compose_tool_gate(
    answers: Answers,
    pack: QuestionPack | None = None,
    *,
    thresholds: ToolGateThresholds | None = None,
    client_name: str = "stub",
) -> GateDecision:
    """Turn one pack of answers into a gate action.

    Order:
    1. destructive / exfil Noul at or above ``deny_noul`` → DENY
    2. confident ``disposition=deny`` → DENY
    3. ``disposition=allow`` with in_grant, args_plausible, on_task, and
       confidence all at or above allow thresholds, and no uncertain
       safety Noul → ALLOW
    4. everything else → ASK
    """
    pack = pack or load_pack("tool_gate")
    limits = thresholds or pack.thresholds
    fields = _pack_fields(pack)
    nouls = answers.noul_map()
    disposition = answers.get("disposition")
    choice = disposition.choice if isinstance(disposition, ChoiceAnswer) else None
    confidence = disposition.confidence if isinstance(disposition, ChoiceAnswer) else None

    def decide(action: GateAction, reason: str, message: str = "") -> GateDecision:
        return GateDecision(
            action,
            reason,
            client=client_name,
            nouls=nouls,
            choice=choice,
            confidence=confidence,
            message=message,
            **fields,
        )

    destructive = nouls.get("destructive", 0.5)
    exfil = nouls.get("exfil_risk", 0.5)
    if destructive >= limits.deny_noul:
        return decide(GateAction.DENY, "destructive", "Tool call looks destructive")
    if exfil >= limits.deny_noul:
        return decide(GateAction.DENY, "exfil_risk", "Tool call looks like data exfil")

    if (
        isinstance(disposition, ChoiceAnswer)
        and disposition.choice == "deny"
        and disposition.confidence >= limits.allow_confidence
    ):
        return decide(GateAction.DENY, "disposition_deny", "System One disposition is deny")

    in_grant = nouls.get("in_grant", 0.5)
    args_plausible = nouls.get("args_plausible", 0.5)
    on_task = nouls.get("on_task", 0.5)
    if (
        isinstance(disposition, ChoiceAnswer)
        and disposition.choice == "allow"
        and disposition.confidence >= limits.allow_confidence
        and in_grant >= limits.allow_noul
        and args_plausible >= limits.allow_noul
        and on_task >= limits.allow_noul
    ):
        if any(noul > limits.allow_risk_max for noul in (destructive, exfil)):
            return decide(GateAction.ASK, "risk_above_allow", "Risk is too high to auto-approve")
        return decide(GateAction.ALLOW, "allow", "System One allow with confidence")
    return decide(GateAction.ASK, "ask", "Not confident enough to auto-allow")


async def evaluate_tool_gate(
    client: SystemOneClient,
    state: ToolGateState,
    pack: QuestionPack | None = None,
    *,
    hard_deny: bool = False,
    skipped: bool = False,
    skip_reason: str = "skipped",
) -> GateDecision:
    """Run the tool_gate pack, or skip the client when a hard deny already won.

    ``hard_deny`` is the YAML / manager deny: never call the client.
    ``skipped`` is airplane mode / no client: fail-open to ASK.
    """
    pack = pack or load_pack("tool_gate")
    client_name = getattr(client, "name", "unknown")
    fields = _pack_fields(pack)
    if hard_deny:
        return GateDecision(
            GateAction.DENY,
            "hard_deny",
            skipped_client=True,
            client=client_name,
            message="Denied by deterministic policy before System One",
            **fields,
        )
    if skipped:
        return GateDecision(
            GateAction.ASK,
            skip_reason,
            skipped_client=True,
            client=client_name,
            message="System One client unavailable; fail-open to ASK",
            **fields,
        )
    started = time.monotonic()
    try:
        answers = await client.evaluate(state.to_payload(), pack.wire_questions())
    except (SystemOneError, SchemaViolation) as exc:
        return GateDecision(
            GateAction.ASK,
            "client_error",
            client=client_name,
            evaluation={
                "status": "error",
                "latency_ms": round((time.monotonic() - started) * 1000),
            },
            message=str(exc) or "System One client error; fail-open to ASK",
            **fields,
        )
    except Exception as exc:
        return GateDecision(
            GateAction.ASK,
            "client_error",
            client=client_name,
            evaluation={
                "status": "error",
                "latency_ms": round((time.monotonic() - started) * 1000),
            },
            message=str(exc) or "System One client error; fail-open to ASK",
            **fields,
        )
    decision = compose_tool_gate(answers, pack=pack, client_name=client_name)
    decision.answers = answers.model_dump(mode="json")["answers"]
    decision.evaluation = {
        "status": "success",
        "latency_ms": round((time.monotonic() - started) * 1000),
        **answers.metadata,
    }
    return decision


__all__ = [
    "GateAction",
    "GateDecision",
    "compose_tool_gate",
    "evaluate_tool_gate",
]
