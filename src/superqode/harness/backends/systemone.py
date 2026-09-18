"""Harness backend that evaluates a frozen System One pack over state."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ...agent.loop import AgentResponse
from ...systemone.compose import evaluate_tool_gate
from ...systemone.config import build_client, resolve_systemone
from ...systemone.pack import load_pack
from ...systemone.decision import evaluate_decision, parse_state
from ...systemone.state import ToolGateState
from ..events import HarnessEvent
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult


class SystemOneHarnessBackend:
    """Run a decision pack. Not a coding loop."""

    name = "systemone"
    capabilities = HarnessBackendCapabilities(
        backend="systemone",
        supports_coding=False,
        supports_no_tool=True,
        supports_streaming=False,
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=False,
        supports_mcp=False,
        supports_typed_output=True,
        supports_workflow_children=False,
        supports_decision=True,
        event_detail="coarse",
        availability="ready",
        notes=("Evaluates a frozen question pack over structured state.",),
    )

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        settings = resolve_systemone(spec=request.spec)
        pack = load_pack(settings.pack)
        client = build_client(settings)
        if client is None:
            if settings.skip_reason == "live_unavailable":
                raise RuntimeError(
                    f"System One live client needs {settings.api_key_env} in this process"
                )
            if settings.skip_reason == "airplane":
                raise RuntimeError("System One skipped: harness is in airplane mode")
            raise RuntimeError(
                "System One client is unavailable "
                f"(enabled={settings.enabled} client={settings.client} skip={settings.skip_reason or 'none'})"
            )
        if pack.id == "tool_gate":
            state = _state_from_prompt(request.prompt)
            decision = await evaluate_tool_gate(client, state, pack)
            if decision.reason == "client_error":
                raise RuntimeError(f"System One evaluation failed: {decision.message}")
            payload = {
                "action": decision.action.value,
                "reason": decision.reason,
                "metadata": decision.metadata(),
            }
        else:
            result = await evaluate_decision(client, parse_state(request.prompt, pack), pack)
            payload = result.model_dump(mode="json")
        evaluation = (payload.get("metadata") or {}).get("evaluation") or {}
        usage = evaluation.get("usage") or {}
        response = AgentResponse(
            content=json.dumps(payload, indent=2),
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
            structured_output=payload,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=self.name,
            metadata=payload,
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        result = await self.run(request)
        yield HarnessEvent(
            type="model_delta",
            data={"text": result.response.content},
        )


def _state_from_prompt(prompt: str) -> ToolGateState:
    text = (prompt or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return ToolGateState(
                tool=str(data.get("tool") or "unknown"),
                arguments=dict(data.get("arguments") or {})
                if isinstance(data.get("arguments"), dict)
                else {},
                grant=list(data.get("grant") or []) if isinstance(data.get("grant"), list) else [],
                policy=str(data.get("policy") or ""),
                task=str(data.get("task") or ""),
                last_diff=str(data["last_diff"]) if data.get("last_diff") else None,
            )
    return ToolGateState(tool="unknown", task=text)
