"""HarnessSpec backend for a Unified Harness Protocol server.

The TUI and the HarnessKernel run backends, not protocol adapters, so this
wraps :class:`UHPHarnessProtocolAdapter` for that route.

Two things differ from the controller path.  Nothing calls ``session_state``
here, so this backend persists the ids itself and feeds them back on the next
turn; without that, a conversation would silently restart between turns.  And
a first turn has nothing to resume, so resume is attempted rather than
required.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...agent.loop import AgentResponse
from ..events import HarnessEvent
from ..protocol import HarnessCapabilityError, HarnessMessage, HarnessSessionRef
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..uhp_adapter import UHPHarnessProtocolAdapter


def uhp_backend_status() -> tuple[bool, str]:
    """Return whether a UHP server and harness are configured."""
    from ...providers.uhp import resolve_settings, setup_hint

    settings = resolve_settings()
    if not settings.configured:
        return False, setup_hint()
    if not settings.harness_id:
        return False, (
            "No UHP harness is selected. List them with `:connect uhp <url>`, then "
            "choose one with `:connect uhp --harness <id>` (or the same "
            "`superqode connect uhp` commands in a shell)."
        )
    return True, ""


class UHPHarnessBackend:
    """Expose a UHP server through the normal HarnessSpec/TUI execution route."""

    name = "uhp"
    capabilities = HarnessBackendCapabilities(
        backend="uhp",
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=True,
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=False,
        supports_mcp=False,
        supports_typed_output=False,
        supports_workflow_children=False,
        event_detail="rich",
        notes=(
            "Tools, sandbox, and approvals belong to the UHP server, so a local "
            "HarnessSpec does not govern this route.",
        ),
    )

    def __init__(self, *, adapter: "UHPHarnessProtocolAdapter | None" = None) -> None:
        self._adapter = adapter

    @property
    def adapter(self) -> "UHPHarnessProtocolAdapter":
        """Build the adapter from the saved connection on first use."""
        if self._adapter is None:
            from ...providers.uhp import resolve_settings
            from ..uhp_adapter import UHPHarnessProtocolAdapter

            settings = resolve_settings()
            if not settings.configured:
                raise RuntimeError(uhp_backend_status()[1])
            self._adapter = UHPHarnessProtocolAdapter(
                settings.base_url,
                harness_id=settings.harness_id or None,
                api_key=settings.api_key or None,
                max_output_tokens=settings.max_output_tokens,
                name=f"UHP {settings.harness_id or 'harness'}",
            )
        return self._adapter

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        events: list[HarnessEvent] = []
        text: list[str] = []
        final_text = ""
        tool_calls = 0
        usage: dict[str, Any] = {}
        stopped_reason = "complete"
        error: str | None = None

        async for event in self._adapter_events(request):
            events.append(_backend_event(event))
            if event.type == "message.delta":
                text.append(str(event.data.get("text") or ""))
            elif event.type == "message.created" and event.data.get("role") == "assistant":
                final_text = str(event.data.get("content") or "")
            elif event.type == "tool.requested":
                tool_calls += 1
            elif event.type == "model.completed":
                raw_usage = event.data.get("usage")
                if isinstance(raw_usage, dict):
                    usage = dict(raw_usage)
            elif event.type == "run.failed":
                stopped_reason = "error"
                error = str(event.data.get("error") or "UHP run failed")

        response = AgentResponse(
            content=final_text or "".join(text),
            messages=[],
            tool_calls_made=tool_calls,
            iterations=1,
            stopped_reason=stopped_reason,
            error=error,
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            total_tokens=_optional_int(usage.get("total_tokens")),
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=self.name,
            metadata={"events": events, "policy_owner": "server"},
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        async for event in self._adapter_events(request):
            yield _backend_event(event)

    async def _adapter_events(
        self,
        request: HarnessBackendRequest,
    ) -> AsyncIterator[HarnessEvent]:
        adapter = self.adapter
        state_path = _state_path(request)
        ref = _session_ref(request, _load_state(state_path))
        try:
            ref = await adapter.resume(ref)
        except HarnessCapabilityError:
            # A first turn has nothing to resume, which is not a failure.
            pass
        try:
            async for event in adapter.send(ref, HarnessMessage("user", request.prompt)):
                yield event
                if event.type == "run.failed":
                    raise RuntimeError(str(event.data.get("error") or "UHP run failed"))
        finally:
            # Nothing calls session_state on this route, so the ids that let
            # the next turn continue the conversation are stored here.
            _save_state(state_path, adapter.session_state(ref))


def _state_path(request: HarnessBackendRequest) -> Path:
    session_id = request.session_id or "uhp-session"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-") or "session"
    return request.working_directory / ".superqode" / "uhp" / "sessions" / f"{safe}.json"


def _load_state(path: Path) -> dict[str, str]:
    """Return the persisted UHP ids, or nothing when this is a first turn."""
    from ..uhp_adapter import PREVIOUS_RESPONSE_KEY, SESSION_KEY

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: str(payload[key]) for key in (PREVIOUS_RESPONSE_KEY, SESSION_KEY) if payload.get(key)
    }


def _save_state(path: Path, state: dict[str, Any]) -> None:
    """Persist the ids for the next turn, without failing the run."""
    if not state:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        logger.warning(
            "Could not persist UHP session state at %s; resume will not survive a restart",
            path,
            exc_info=True,
        )


def _session_ref(request: HarnessBackendRequest, state: dict[str, str]) -> HarnessSessionRef:
    from ..uhp_adapter import SESSION_KEY

    session_id = request.session_id or "uhp-session"
    return HarnessSessionRef(
        session_id=session_id,
        harness_id="uhp",
        external_session_id=state.get(SESSION_KEY),
        metadata={
            **dict(request.metadata),
            **state,
            "provider": request.provider,
            "model": request.model,
            "working_directory": str(request.working_directory),
            "policy_owner": "server",
        },
    )


def _backend_event(event: HarnessEvent) -> HarnessEvent:
    """Translate canonical protocol events to the runtime event vocabulary."""
    event_type = event.type
    data = dict(event.data)
    if event_type == "message.delta":
        event_type = "model_delta"
    elif event_type == "model.thinking":
        event_type = "thinking"
    elif event_type == "tool.requested":
        event_type = "tool_call"
    elif event_type == "tool.completed":
        event_type = "tool_result"
    elif event_type == "model.requested":
        event_type = "model_request"
    elif event_type == "model.completed":
        event_type = "turn_complete"
    elif event_type == "run.failed":
        event_type = "error"
    return HarnessEvent(
        type=event_type,
        data=data,
        timestamp=event.timestamp,
        session_id=event.session_id,
        run_id=event.run_id,
        parent_event_id=event.parent_event_id,
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
