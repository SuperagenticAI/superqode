"""HarnessSpec backend for the native PiPy harness."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from ...agent.loop import AgentResponse
from ..events import HarnessEvent
from ..pipy_adapter import PiPyHarnessProtocolAdapter
from ..protocol import HarnessMessage, HarnessSessionRef
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult


class PiPyHarnessBackend:
    """Expose PiPy through the normal HarnessSpec and TUI execution route."""

    name = "pipy"
    capabilities = HarnessBackendCapabilities(
        backend="pipy",
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=True,
        # PiPy runs with the permissions of the process, matching pi. There is
        # no approval or sandbox path on this harness.
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=True,
        supports_mcp=True,
        supports_typed_output=False,
        supports_workflow_children=False,
        event_detail="rich",
        notes=(
            "PiPy executes tools with the permissions of the process that "
            "launched SuperQode. Hosted contextual policy is enforced; use core "
            "or workbench for approval and sandbox support.",
        ),
    )

    def __init__(self, *, adapter: PiPyHarnessProtocolAdapter | None = None) -> None:
        self.adapter = adapter or PiPyHarnessProtocolAdapter()
        self._active_ref: HarnessSessionRef | None = None

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
                if isinstance(raw, dict) and raw:
                    usage = _accumulate(usage, raw)
            elif event.type == "error":
                stopped_reason = (
                    "recovery_required" if event.data.get("recovery_required") else "error"
                )
                error = str(event.data.get("error") or "PiPy run failed")

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
            metadata={"events": events, "pure_permissions": True},
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        async for event in self._events(request):
            yield event

    async def cancel(self, session_id: str | None = None) -> None:
        """Abort the coding session that ``stream`` or ``run`` is driving."""
        ref = self._active_ref
        if ref is None:
            return
        if session_id and session_id not in {ref.session_id, ref.external_session_id}:
            safe = _safe_session_id(session_id)
            if ref.session_id != safe:
                return
        await self.adapter.cancel(ref)

    async def _events(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        ref = await self.adapter.resume(_session_ref(request))
        self._active_ref = ref
        try:
            message = HarnessMessage(
                "user",
                request.prompt,
                metadata={
                    "images": [
                        {"data": image.data, "mime_type": image.mime_type}
                        for image in request.images
                    ]
                }
                if request.images
                else {},
            )
            async for event in self.adapter.send(ref, message):
                yield event
        except Exception as exc:
            from ..pipy_recovery import PiPyRecoveryRequired

            if not isinstance(exc, PiPyRecoveryRequired):
                raise
            yield HarnessEvent(type="error", data={"error": str(exc), "recovery_required": True})
        finally:
            close = getattr(self.adapter, "close", None)
            if close is not None:
                await close(ref)
            if self._active_ref is ref:
                self._active_ref = None


def _safe_session_id(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-") or "session"


def _session_ref(request: HarnessBackendRequest) -> HarnessSessionRef:
    session_id = request.session_id or "pipy-session"
    safe = _safe_session_id(session_id)
    return HarnessSessionRef(
        session_id=safe,
        harness_id="pipy",
        external_session_id=session_id,
        metadata={
            **dict(request.metadata),
            "provider": request.provider,
            "model": request.model,
            "working_directory": str(request.working_directory),
            "runtime_config": dict(request.spec.runtime.config),
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


__all__ = ["PiPyHarnessBackend"]
