"""Apply the System One tool gate inside AgentLoop._check_tool_permission.

Hard YAML / manager denials never reach this module. Model ASK requires
approval; unavailable evaluations fall back visibly to the existing policy.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..tools.base import ToolResult
from .compose import GateAction, GateDecision, evaluate_tool_gate
from .config import build_client, resolve_systemone
from .pack import load_pack
from .state import ToolGateState

logger = logging.getLogger("superqode.systemone")


def _cache(loop: Any) -> dict[str, Any]:
    cached = getattr(loop, "_systemone_cache", None)
    if cached is None:
        cached = {}
        loop._systemone_cache = cached
    return cached


def _settings(loop: Any) -> Any:
    spec = getattr(getattr(loop, "config", None), "harness_spec", None)
    explicit = getattr(getattr(loop, "config", None), "systemone", None)
    return resolve_systemone(spec=spec, explicit=explicit)


def _pack(loop: Any, pack_id: str):
    cache = _cache(loop)
    if cache.get("pack_id") == pack_id and cache.get("pack") is not None:
        return cache["pack"]
    try:
        pack = load_pack(pack_id)
    except Exception as exc:
        if not cache.get("pack_warned"):
            logger.warning(
                "System One pack %r failed to load (%s); gate stays fail-open", pack_id, exc
            )
            cache["pack_warned"] = True
        return None
    cache["pack"] = pack
    cache["pack_id"] = pack_id
    return pack


def publish_decision(loop: Any, decision: GateDecision, tool: str) -> None:
    event = {
        "tool": tool,
        "action": decision.action.value,
        "message": decision.message,
        **decision.metadata(),
    }
    settings = _settings(loop)
    event.update(mode=settings.mode, intendedAction=decision.action.value)
    loop.last_systemone_decision = event
    callback = getattr(loop, "on_systemone", None)
    if callback:
        try:
            callback(event)
        except Exception:
            logger.warning("System One status callback failed")
    elif decision.reason == "client_error":
        logger.warning(
            "System One evaluation failed: %s; using existing permission policy", decision.message
        )
    else:
        logger.info(format_decision(event))


def format_decision(event: dict[str, Any]) -> str:
    evaluation = event.get("evaluation") or {}
    status = evaluation.get("status", "skipped")
    details = f"Jev {event.get('mode', 'enforce')} {status} · {event.get('tool', '')} · {event.get('action', 'ask').upper()}"
    if status == "success":
        details += f" · {evaluation.get('model', event.get('client', ''))} · {evaluation.get('latency_ms', 0)}ms"
        usage = evaluation.get("usage") or {}
        if usage:
            details += f" · {usage.get('input_tokens', 0)} input tokens"
    else:
        details += (
            f" · {event.get('message', event.get('reason', ''))} · using existing permission policy"
        )
    return details


async def apply_systemone_gate(
    loop: Any, name: str, arguments: dict[str, Any]
) -> tuple[Optional[ToolResult], bool, bool]:
    """Return ``(deny_result, preapprove, require_approval)``."""
    settings = _settings(loop)
    if not settings.enabled or settings.skip_client:
        if settings.skip_reason and not _cache(loop).get("skip_logged"):
            logger.warning(
                "System One gate skipped (%s); client=%s enabled=%s",
                settings.skip_reason,
                settings.client,
                settings.enabled,
            )
            _cache(loop)["skip_logged"] = True
        if settings.enabled:
            publish_decision(
                loop,
                GateDecision(
                    GateAction.ASK,
                    settings.skip_reason,
                    client=settings.client,
                    skipped_client=True,
                    message=settings.skip_reason,
                ),
                name,
            )
        return None, False, False
    try:
        client = build_client(settings, injected=getattr(loop, "_systemone_client", None))
    except Exception:
        publish_decision(
            loop,
            GateDecision(
                GateAction.ASK,
                "client_error",
                client=settings.client,
                message="Client configuration could not be loaded",
                evaluation={"status": "error"},
            ),
            name,
        )
        return None, False, False
    if client is None:
        publish_decision(
            loop,
            GateDecision(
                GateAction.ASK,
                "client_error",
                client=settings.client,
                message="No evaluation client is configured",
                evaluation={"status": "error"},
            ),
            name,
        )
        return None, False, False
    pack = _pack(loop, settings.pack)
    if pack is None or pack.id != "tool_gate":
        publish_decision(
            loop,
            GateDecision(
                GateAction.ASK,
                "client_error",
                client=settings.client,
                message="A valid tool_gate pack is required",
                evaluation={"status": "error"},
            ),
            name,
        )
        return None, False, False
    try:
        state = _tool_gate_state(loop, name, arguments)
        decision = await evaluate_tool_gate(client, state, pack)
    except Exception:
        publish_decision(
            loop,
            GateDecision(
                GateAction.ASK,
                "client_error",
                client=settings.client,
                message="Evaluation could not be completed",
                evaluation={"status": "error"},
            ),
            name,
        )
        return None, False, False
    publish_decision(loop, decision, name)
    event = loop.last_systemone_decision
    event["state"] = state.to_payload()
    event["model"] = settings.model
    event["thresholds"] = pack.thresholds.model_dump()
    from .audit import distribution_diagnostics

    disposition = event.get("answers", {}).get("disposition", {})
    event["distribution"] = distribution_diagnostics(disposition.get("probabilities", {}))
    if settings.mode == "shadow":
        return None, False, False
    if decision.action is GateAction.DENY:
        return (
            ToolResult(
                success=False,
                output="",
                error=decision.message or f"Permission denied for tool: {name}",
                metadata={**decision.metadata(), "tool": name},
            ),
            False,
            False,
        )
    if decision.action is GateAction.ALLOW:
        return None, True, False
    return None, False, decision.reason != "client_error"


def _tool_gate_state(loop: Any, name: str, arguments: dict[str, Any]) -> ToolGateState:
    spec = getattr(getattr(loop, "config", None), "harness_spec", None)
    execution = getattr(spec, "execution_policy", None)
    policy = str(getattr(execution, "approval_profile", "") or "")
    tools = getattr(loop, "tools", None)
    grant: list[str] = []
    if tools is not None and hasattr(tools, "list"):
        grant = [tool.name for tool in tools.list()]
    return ToolGateState(
        tool=name,
        arguments=dict(arguments or {}),
        grant=grant,
        policy=policy,
        task=_current_task(loop),
        last_diff=str(getattr(loop, "last_turn_diff", "") or "") or None,
    )


def _current_task(loop: Any) -> str:
    messages = getattr(loop, "_current_messages", None) or []
    for message in reversed(list(messages)):
        if getattr(message, "role", "") == "user":
            content = getattr(message, "content", "") or ""
            if str(content).strip():
                return str(content)
    return ""


__all__ = ["apply_systemone_gate"]
