"""HarnessSpec backend for SuperQode's native RLM harness."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from ...agent.loop import AgentResponse
from ..events import HarnessEvent
from ..protocol import HarnessMessage, HarnessSessionRef
from ..rlm_adapter import RLMHarnessProtocolAdapter
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult


class RLMHarnessBackend:
    name = "rlm"
    capabilities = HarnessBackendCapabilities(
        backend="rlm",
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=True,
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=True,
        supports_mcp=False,
        supports_typed_output=False,
        supports_workflow_children=False,
        event_detail="rich",
        notes=(
            "The initial native RLM kernel executes persistent Python with the permissions "
            "of the SuperQode process.",
        ),
    )

    def __init__(self, *, adapter: RLMHarnessProtocolAdapter | None = None) -> None:
        self.adapter = adapter or RLMHarnessProtocolAdapter()

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        events: list[HarnessEvent] = []
        text: list[str] = []
        tool_calls = 0
        turns = 0
        usage: dict[str, Any] = {}
        stopped_reason = "complete"
        error: str | None = None
        async for event in self._events(request):
            events.append(event)
            if event.type == "model_delta":
                text.append(str(event.data.get("text") or ""))
            elif event.type == "tool_call":
                tool_calls += 1
            elif event.type == "turn_complete":
                turns += 1
                raw = event.data.get("usage")
                if isinstance(raw, dict):
                    usage = _accumulate(usage, raw)
            elif event.type == "error":
                stopped_reason = "error"
                error = str(event.data.get("error") or "RLM run failed")
        response = AgentResponse(
            content="".join(text),
            messages=[],
            tool_calls_made=tool_calls,
            iterations=max(1, turns),
            stopped_reason=stopped_reason,
            error=error,
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            total_tokens=_optional_int(usage.get("total_tokens")),
            cost_usd=_optional_float(usage.get("cost_usd")),
            cost_currency="USD" if usage.get("cost_usd") is not None else None,
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=self.name,
            metadata={
                "events": events,
                "model_tools": ["python"],
                "persistent_python": True,
                "pure_permissions": True,
            },
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        async for event in self._events(request):
            yield event

    async def _events(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        ref = await self.adapter.resume(_session_ref(request))
        async for event in self.adapter.send(ref, HarnessMessage("user", request.prompt)):
            yield event


def _session_ref(request: HarnessBackendRequest) -> HarnessSessionRef:
    session_id = request.session_id or "rlm-session"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-") or "session"
    return HarnessSessionRef(
        session_id=safe,
        harness_id="rlm",
        external_session_id=session_id,
        metadata={
            **dict(request.metadata),
            "provider": request.provider,
            "model": request.model,
            "working_directory": str(request.working_directory),
            "rlm_config": dict(request.spec.runtime.config),
        },
    )


def _accumulate(totals: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    merged = dict(totals)
    for key, value in raw.items():
        if isinstance(value, (int, float)):
            merged[key] = merged.get(key, 0) + value
    return merged


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


__all__ = ["RLMHarnessBackend"]
