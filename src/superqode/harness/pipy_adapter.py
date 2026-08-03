"""Harness Protocol v1 adapter for the native PiPy harness.

PiPy lives in ``superqode.pipy``. This module is the only
place that knows both PiPy's event vocabulary and SuperQode's, translating one
into the other so PiPy runs through the normal catalog, kernel and TUI route.

PiPy is imported lazily: the harness package should stay importable without
pulling the whole agent brain in.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from .events import HarnessEvent
from .protocol import (
    HarnessCapabilities,
    HarnessCheckpoint,
    HarnessCreateRequest,
    HarnessDescriptor,
    HarnessMessage,
    HarnessSessionRef,
)

#: PiPy tool names, in pi's own order.
DEFAULT_TOOLS: tuple[str, ...] = ("read", "bash", "edit", "write")


class PiPyHarnessProtocolAdapter:
    """Run a :class:`~superqode.pipy.PiPyCodingSession` behind the portable lifecycle."""

    def __init__(self, *, session_factory: Any | None = None) -> None:
        self.descriptor = HarnessDescriptor(
            id="pipy",
            name="PiPy",
            description=(
                "A Python harness inspired by pi: event-first loop, parallel "
                "tools, session tree, and a small tool surface. Runs with the "
                "permissions of the process, as pi does."
            ),
            adapter_version="1.0",
            capabilities=HarnessCapabilities(
                streaming=True,
                resume=True,
                steer=True,
                cancel=True,
                checkpoint=True,
                # Deliberate. PiPy has no approval path; that is the point of it.
                approvals=False,
                tools=True,
                usage=True,
            ),
            metadata={
                "pure_permissions": True,
                "tools": list(DEFAULT_TOOLS),
                "session_format": "pi-jsonl-v3",
            },
        )
        self._session_factory = session_factory
        self._sessions: dict[str, Any] = {}
        self._refs: dict[str, HarnessSessionRef] = {}

    # -- lifecycle -------------------------------------------------------- #

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        if request.harness_id != self.descriptor.id:
            raise ValueError(f"PiPy adapter cannot create harness {request.harness_id!r}")
        session_id = request.session_id or f"pipy-{uuid4().hex[:12]}"
        working_directory = request.working_directory.expanduser().resolve()
        coding_session = await self._open(request, working_directory)

        ref = HarnessSessionRef(
            session_id=session_id,
            harness_id=self.descriptor.id,
            external_session_id=(await coding_session.info()).id,
            metadata={
                **dict(request.metadata),
                "provider": request.provider,
                "model": request.model,
                "working_directory": str(working_directory),
                "session_path": str(coding_session.session_path),
                "pure_permissions": True,
            },
        )
        self._sessions[session_id] = coding_session
        self._refs[session_id] = ref
        return ref

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        if session.harness_id != self.descriptor.id:
            raise ValueError(f"PiPy adapter cannot resume harness {session.harness_id!r}")
        if session.session_id in self._sessions:
            return self._refs.get(session.session_id, session)

        metadata = dict(session.metadata)
        working_directory = (
            Path(str(metadata.get("working_directory") or Path.cwd())).expanduser().resolve()
        )
        request = HarnessCreateRequest(
            harness_id=self.descriptor.id,
            provider=str(metadata.get("provider") or ""),
            model=str(metadata.get("model") or ""),
            working_directory=working_directory,
            session_id=session.session_id,
            metadata=metadata,
        )
        existing = str(metadata.get("session_path") or "")
        coding_session = await self._open(request, working_directory, session_path=existing or None)
        ref = HarnessSessionRef(
            session_id=session.session_id,
            harness_id=self.descriptor.id,
            external_session_id=(await coding_session.info()).id,
            metadata={**metadata, "session_path": str(coding_session.session_path)},
        )
        self._sessions[session.session_id] = coding_session
        self._refs[session.session_id] = ref
        return ref

    async def _open(
        self,
        request: HarnessCreateRequest,
        working_directory: Path,
        *,
        session_path: str | None = None,
    ) -> Any:
        if self._session_factory is not None:
            return await self._session_factory(request, working_directory, session_path)

        from superqode.pipy.ai.models import resolve_model
        from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession

        options = CodingSessionOptions(
            cwd=working_directory,
            model=resolve_model(request.model or "", provider=request.provider or ""),
            tool_names=tuple(request.metadata.get("tools") or DEFAULT_TOOLS),
        )
        if session_path and Path(session_path).is_file():
            return await PiPyCodingSession.resume(options, session_path=session_path)
        return await PiPyCodingSession.create(options)

    # -- running ---------------------------------------------------------- #

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        coding_session = await self._require(session)
        model = coding_session.harness.get_model()
        yield HarnessEvent(
            type="model.requested",
            data={"provider": model.provider, "model": model.id, "runtime": "pipy"},
        )
        # The durable ledger records the conversation, not just the deltas, so
        # both sides of the exchange are announced as messages.
        yield HarnessEvent(
            type="message.created",
            data={"role": "user", "content": message.content},
        )

        stream = coding_session.prompt_events(message.content)
        async for event in stream:
            for translated in translate_event(event):
                yield translated

    async def steer(self, session: HarnessSessionRef, message: HarnessMessage) -> None:
        coding_session = await self._require(session)
        await coding_session.steer(message.content)

    async def cancel(self, session: HarnessSessionRef) -> None:
        coding_session = await self._require(session)
        await coding_session.abort()

    async def checkpoint(self, session: HarnessSessionRef) -> HarnessCheckpoint:
        ref = self._refs.get(session.session_id, session)
        coding_session = self._sessions.get(session.session_id)
        leaf = await coding_session.session.get_leaf_id() if coding_session else None
        return HarnessCheckpoint(
            session_id=session.session_id,
            harness_id=self.descriptor.id,
            # PiPy's tree already records every point worth returning to, so a
            # checkpoint is just the leaf it was taken at.
            external_checkpoint_id=leaf,
            state={
                "session_path": str(ref.metadata.get("session_path") or ""),
                "leaf_id": leaf or "",
                "provider": str(ref.metadata.get("provider") or ""),
                "model": str(ref.metadata.get("model") or ""),
            },
        )

    async def _require(self, session: HarnessSessionRef) -> Any:
        active = self._sessions.get(session.session_id)
        if active is not None:
            return active
        await self.resume(session)
        return self._sessions[session.session_id]


# --------------------------------------------------------------------------- #
# Event translation
# --------------------------------------------------------------------------- #


def translate_event(event: Any) -> list[HarnessEvent]:
    """Map one PiPy event onto zero or more protocol events.

    Emitted in SuperQode's runtime vocabulary rather than the canonical one, so
    the existing TUI event handler renders PiPy without a second code path.
    """
    kind = getattr(event, "type", "")

    if kind == "agent_start":
        return [HarnessEvent(type="run_start", data={"runtime": "pipy"})]

    if kind == "message_update":
        delta = _delta_text(event)
        thinking = _delta_thinking(event)
        if thinking:
            return [HarnessEvent(type="thinking", data={"text": thinking})]
        if delta:
            return [HarnessEvent(type="model_delta", data={"text": delta})]
        return []

    if kind == "tool_execution_start":
        return [
            HarnessEvent(
                type="tool_call",
                data={
                    "tool_name": event.tool_name,
                    "tool_call_id": event.tool_call_id,
                    "args": dict(event.args or {}),
                },
            )
        ]

    if kind == "tool_execution_update":
        text = _result_text(event.partial_result)
        return (
            [HarnessEvent(type="tool_delta", data={"tool_name": event.tool_name, "text": text})]
            if text
            else []
        )

    if kind == "tool_execution_end":
        return [
            HarnessEvent(
                type="tool_result",
                data={
                    "tool_name": event.tool_name,
                    "tool_call_id": event.tool_call_id,
                    "success": not event.is_error,
                    "output": _result_text(event.result),
                    "error": _result_text(event.result) if event.is_error else None,
                },
            )
        ]

    if kind == "turn_end":
        message = event.message
        usage = getattr(message, "usage", None)
        events = [
            HarnessEvent(
                type="turn_complete",
                data={
                    "stop_reason": getattr(message, "stop_reason", "stop"),
                    "usage": _usage_dict(usage),
                },
            )
        ]
        text = str(getattr(message, "text", "") or "")
        if text:
            events.insert(
                0,
                HarnessEvent(type="message.created", data={"role": "assistant", "content": text}),
            )
        return events

    if kind == "agent_end":
        return [HarnessEvent(type="run_end", data={"status": "completed"})]

    if kind == "settled":
        return []

    return []


def _delta_text(event: Any) -> str:
    inner = getattr(event, "assistant_message_event", None)
    if inner is not None and getattr(inner, "type", "") == "text_delta":
        return str(getattr(inner, "delta", "") or "")
    return ""


def _delta_thinking(event: Any) -> str:
    inner = getattr(event, "assistant_message_event", None)
    if inner is not None and getattr(inner, "type", "") == "thinking_delta":
        return str(getattr(inner, "delta", "") or "")
    return ""


def _result_text(result: Any) -> str:
    if result is None:
        return ""
    return str(getattr(result, "text", "") or "")


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    return {
        "input_tokens": int(getattr(usage, "input", 0) or 0),
        "output_tokens": int(getattr(usage, "output", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cost_usd": float(getattr(getattr(usage, "cost", None), "total", 0.0) or 0.0),
    }


__all__ = ["DEFAULT_TOOLS", "PiPyHarnessProtocolAdapter", "translate_event"]
