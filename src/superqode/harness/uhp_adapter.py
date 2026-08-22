"""Unified Harness Protocol adapter for Harness Protocol v1.

UHP threads a conversation with ``previous_response_id`` rather than a
long-lived connection, so the ids learned during a turn are handed back to the
controller through :meth:`session_state` and survive a restart.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from .events import HarnessEvent
from .protocol import (
    HarnessCapabilities,
    HarnessCapabilityError,
    HarnessCreateRequest,
    HarnessDescriptor,
    HarnessMessage,
    HarnessSessionRef,
)
from .protocol_adapters import BaseHarnessAdapter
from .uhp_client import (
    UHP_PROTOCOL_VERSION,
    UHPClient,
    UHPError,
    UHPResponse,
    UHPStreamEvent,
)

#: Session metadata keys the controller persists between turns.
PREVIOUS_RESPONSE_KEY = "uhp_previous_response_id"
SESSION_KEY = "uhp_session_id"


class UHPHarnessProtocolAdapter(BaseHarnessAdapter):
    """Run any Unified Harness Protocol server through Harness Protocol v1.

    Args:
        base_url: Root URL of the UHP server.
        harness_id: Server-side harness to run.  Falls back to the first
            harness the server advertises when omitted.
        api_key: Bearer credential for the server.
        adapter_id: Identity this adapter reports to the controller.
        name: Human-readable adapter name.
        client: An existing :class:`UHPClient` to use instead of building one.
    """

    def __init__(
        self,
        base_url: str,
        *,
        harness_id: str | None = None,
        api_key: str | None = None,
        adapter_id: str = "uhp",
        name: str = "UHP harness",
        max_output_tokens: int | None = None,
        client: UHPClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.harness_id = harness_id
        self.max_output_tokens = max_output_tokens
        self._client = client or UHPClient(base_url, api_key=api_key)
        self.descriptor = HarnessDescriptor(
            id=adapter_id,
            name=name,
            description="Unified Harness Protocol remote harness adapter",
            adapter_version="0.1",
            capabilities=HarnessCapabilities(
                streaming=True,
                resume=True,
                cancel=True,
                tools=True,
                usage=True,
            ),
            metadata={
                "transport": "uhp",
                "base_url": self._client.base_url,
                "uhp_version": UHP_PROTOCOL_VERSION,
                "harness_id": harness_id or "",
                # Tools, sandbox, and approvals belong to the server, so a
                # local HarnessSpec does not govern this route.
                "policy_owner": "server",
            },
        )
        self._previous_response: dict[str, str] = {}
        self._uhp_session: dict[str, str] = {}
        self._active_response: dict[str, str] = {}

    @property
    def client(self) -> UHPClient:
        """The underlying protocol client."""
        return self._client

    def session_state(self, session: HarnessSessionRef) -> dict[str, Any]:
        """Return the ids the controller should persist for this session."""
        state: dict[str, Any] = {}
        previous = self._previous_response.get(session.session_id)
        if previous:
            state[PREVIOUS_RESPONSE_KEY] = previous
        remote = self._uhp_session.get(session.session_id) or session.external_session_id
        if remote:
            state[SESSION_KEY] = remote
        return state

    def _adopt(self, session: HarnessSessionRef) -> None:
        """Seed in-memory ids from persisted session metadata."""
        previous = session.metadata.get(PREVIOUS_RESPONSE_KEY)
        if previous and session.session_id not in self._previous_response:
            self._previous_response[session.session_id] = str(previous)
        remote = session.metadata.get(SESSION_KEY) or session.external_session_id
        if remote and session.session_id not in self._uhp_session:
            self._uhp_session[session.session_id] = str(remote)

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        session_id = request.session_id or f"uhp-{uuid.uuid4().hex[:12]}"
        harness_id = str(request.metadata.get("harness_id") or self.harness_id or "")
        if not harness_id:
            harnesses = await self._client.list_harnesses()
            if not harnesses:
                raise RuntimeError(f"UHP server advertises no harnesses: {self.base_url}")
            harness_id = harnesses[0].id
        external = request.metadata.get("external_session_id") or request.metadata.get(SESSION_KEY)
        ref = HarnessSessionRef(
            session_id=session_id,
            harness_id=self.descriptor.id,
            external_session_id=str(external) if external else None,
            metadata={
                "base_url": self._client.base_url,
                "uhp_harness_id": harness_id,
                "provider": request.provider,
                "model": request.model,
                "working_directory": str(request.working_directory),
                "policy_owner": "server",
                **dict(request.metadata),
            },
        )
        self._adopt(ref)
        return ref

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        self._adopt(session)
        if session.session_id in self._previous_response:
            return session
        remote = self._uhp_session.get(session.session_id)
        if not remote:
            raise HarnessCapabilityError(self.descriptor.id, "resume without a UHP session")
        response_id = await self._client.latest_response_id(remote)
        if not response_id:
            raise HarnessCapabilityError(self.descriptor.id, "resume for this UHP session")
        self._previous_response[session.session_id] = response_id
        return session

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        self._adopt(session)
        harness_id = str(session.metadata.get("uhp_harness_id") or self.harness_id or "")
        # The server's harness already has a model. Sending one anyway is only
        # correct when the caller asked for it; a local default would override
        # a remote choice the caller never saw.
        model = str(session.metadata.get("model") or "")
        override = model if session.metadata.get("model_explicit") else ""
        previous_response_id = self._previous_response.get(session.session_id)

        yield HarnessEvent(
            type="model.requested",
            data={
                "provider": session.metadata.get("provider") or "",
                "model": override or "(server default)",
                "transport": "uhp",
                "harness_id": harness_id,
            },
        )

        final: UHPResponse | None = None
        text_parts: list[str] = []
        open_calls: dict[str, str] = {}

        stream = self._client.stream_response(
            message.content,
            harness_id=harness_id or None,
            model=override or None,
            previous_response_id=previous_response_id,
            max_output_tokens=self.max_output_tokens,
        )
        try:
            async for event in stream:
                if event.type == "response.created":
                    created = event.response
                    if created is not None and created.id:
                        self._active_response[session.session_id] = created.id
                for harness_event in _translate(event, text_parts, open_calls):
                    yield harness_event
                if event.is_terminal:
                    final = event.response
        finally:
            await stream.aclose()
            pending = self._active_response.pop(session.session_id, None)
            if final is None and pending:
                # A dropped stream does not stop the task, so re-read it and
                # cancel whatever is still running before giving up.
                with suppress(Exception):
                    final = await self._recover(pending)

        if final is None:
            raise RuntimeError("UHP stream ended without a terminal response event")
        final.raise_for_error()

        if final.id:
            self._previous_response[session.session_id] = final.id
        if final.session_id:
            self._uhp_session[session.session_id] = final.session_id

        for citation in final.file_citations:
            yield HarnessEvent(
                type="artifact.created",
                data={
                    "kind": "file",
                    "uri": citation.download_url
                    or f"uhp://{citation.container_id}/{citation.file_id}",
                    "name": citation.filename,
                    "container_id": citation.container_id,
                    "file_id": citation.file_id,
                },
            )

        completed: dict[str, Any] = {
            "stopped_reason": final.status,
            "tool_calls_made": len(final.function_calls),
            "response_id": final.id,
            "session_id": final.session_id,
            "model": final.model or override,
        }
        if final.usage is not None:
            completed["usage"] = final.usage.to_dict()
        yield HarnessEvent(type="model.completed", data=completed)
        yield HarnessEvent(
            type="message.created",
            data=HarnessMessage("assistant", final.output_text or "".join(text_parts)).to_dict(),
        )

    async def _recover(self, response_id: str) -> UHPResponse | None:
        """Re-read a task whose stream ended early, cancelling it if it runs on."""
        try:
            response = await self._client.get_response(response_id)
        except UHPError:
            return None
        if response.is_terminal:
            return response
        with suppress(UHPError):
            await self._client.cancel_response(response_id)
        return None

    async def cancel(self, session: HarnessSessionRef) -> None:
        response_id = self._active_response.get(session.session_id)
        if response_id:
            await self._client.cancel_response(response_id)
            return
        remote = self._uhp_session.get(session.session_id) or session.external_session_id
        if remote:
            await self._client.cancel_session(remote)
            return
        raise HarnessCapabilityError(self.descriptor.id, "cancel without an active response")

    async def close(self, session: HarnessSessionRef) -> None:
        """Forget per-session state.  The shared client stays open."""
        self._previous_response.pop(session.session_id, None)
        self._uhp_session.pop(session.session_id, None)
        self._active_response.pop(session.session_id, None)

    async def aclose(self) -> None:
        """Close the underlying protocol client."""
        await self._client.aclose()


def _translate(
    event: UHPStreamEvent,
    text_parts: list[str],
    open_calls: dict[str, str],
) -> list[HarnessEvent]:
    """Map one UHP stream event onto canonical harness events."""
    if event.type == "response.output_text.delta":
        delta = str(event.data.get("delta") or "")
        if not delta:
            return []
        text_parts.append(delta)
        return [HarnessEvent(type="message.delta", data={"text": delta})]

    if event.type == "response.reasoning_summary_text.delta":
        delta = str(event.data.get("delta") or "")
        if not delta:
            return []
        return [HarnessEvent(type="model.thinking", data={"text": delta})]

    if event.is_error:
        # The task continues after an error event, so this is recorded rather
        # than treated as the end of the run.
        error = event.error
        return [
            HarnessEvent(
                type="validation.completed",
                data={
                    "status": "error",
                    "code": error.code if error else "",
                    "message": error.message if error else "",
                },
            )
        ]

    if event.type == "response.output_item.added":
        item = event.data.get("item")
        if isinstance(item, dict) and item.get("type") == "function_call":
            call_id = str(item.get("call_id") or item.get("id") or "")
            name = str(item.get("name") or "")
            open_calls[call_id] = name
            return [
                HarnessEvent(
                    type="tool.requested",
                    data={"tool_name": name, "call_id": call_id},
                )
            ]
        return []

    if event.type == "response.function_call_arguments.done":
        call_id = str(event.data.get("call_id") or "")
        return [
            HarnessEvent(
                type="tool.requested",
                data={
                    "tool_name": open_calls.get(call_id, ""),
                    "call_id": call_id,
                    "arguments": str(event.data.get("arguments") or ""),
                },
            )
        ]

    if event.type == "response.output_item.done":
        item = event.data.get("item")
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            call_id = str(item.get("call_id") or "")
            return [
                HarnessEvent(
                    type="tool.completed",
                    data={
                        "tool_name": open_calls.get(call_id, ""),
                        "call_id": call_id,
                        "output": str(item.get("output") or ""),
                        "success": str(item.get("status") or "completed") != "failed",
                    },
                )
            ]
        return []

    return []
