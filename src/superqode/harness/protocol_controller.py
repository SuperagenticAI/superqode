"""Durable control plane for Harness Protocol v1 adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .events import HARNESS_PROTOCOL_VERSION, HarnessEvent
from .protocol import (
    TERMINAL_EVENT_TYPES,
    HarnessAdapter,
    HarnessArtifact,
    HarnessCheckpoint,
    HarnessCreateRequest,
    HarnessDescriptor,
    HarnessMessage,
    HarnessNotFoundError,
    HarnessSessionBundle,
    HarnessSessionRef,
    canonical_event_type,
    require_capability,
)
from .spec import HarnessSpec
from .store import FileHarnessStore, MemoryHarnessStore, SQLiteHarnessStore

HarnessProtocolStore = MemoryHarnessStore | FileHarnessStore | SQLiteHarnessStore


class HarnessProtocolController:
    """Run heterogeneous harness adapters through one canonical durable ledger."""

    def __init__(
        self,
        adapters: Iterable[HarnessAdapter] = (),
        *,
        store: HarnessProtocolStore | None = None,
    ) -> None:
        self.store = store or MemoryHarnessStore()
        self._adapters: dict[str, HarnessAdapter] = {}
        self._active_runs: dict[str, str] = {}
        self._cancelled_runs: set[str] = set()
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: HarnessAdapter) -> None:
        """Register or replace one adapter by its stable descriptor id."""
        descriptor = adapter.descriptor
        if descriptor.protocol_version.split(".", maxsplit=1)[0] != "1":
            raise ValueError(
                f"Adapter {descriptor.id!r} targets unsupported Harness Protocol "
                f"{descriptor.protocol_version!r}"
            )
        self._adapters[descriptor.id] = adapter

    def descriptors(self) -> tuple[HarnessDescriptor, ...]:
        """Return registered adapter descriptors in deterministic order."""
        return tuple(self._adapters[key].descriptor for key in sorted(self._adapters))

    def describe(self, harness_id: str) -> HarnessDescriptor:
        return self._adapter(harness_id).descriptor

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        """Create a session and persist its portable routing information."""
        adapter = self._adapter(request.harness_id)
        session = await adapter.create(request)
        if session.harness_id != adapter.descriptor.id:
            raise ValueError(
                f"Adapter {adapter.descriptor.id!r} returned session for {session.harness_id!r}"
            )
        self.store.open_session(
            session.session_id,
            self._spec(adapter.descriptor),
            metadata={
                **dict(request.metadata),
                "protocol": {
                    "version": HARNESS_PROTOCOL_VERSION,
                    "adapter_id": adapter.descriptor.id,
                    "external_session_id": session.external_session_id,
                    "provider": request.provider,
                    "model": request.model,
                    "working_directory": str(request.working_directory),
                    "session_metadata": dict(session.metadata),
                },
            },
        )
        return session

    async def resume(self, session_id: str) -> HarnessSessionRef:
        """Rehydrate an adapter session using only durable ledger metadata."""
        session = self._session_from_store(session_id)
        adapter = self._adapter(session.harness_id)
        require_capability(adapter.descriptor, "resume")
        resumed = await adapter.resume(session)
        self._touch_session(resumed)
        return resumed

    async def send(
        self,
        session: HarnessSessionRef | str,
        message: HarnessMessage | str,
    ) -> AsyncIterator[HarnessEvent]:
        """Send a message and stream canonical, durably recorded events."""
        ref = self._resolve_session(session)
        adapter = self._adapter(ref.harness_id)
        user_message = (
            message if isinstance(message, HarnessMessage) else HarnessMessage("user", message)
        )
        route = self._session_route(ref.session_id)
        run = self.store.start_run(
            session_id=ref.session_id,
            spec=self._spec(adapter.descriptor),
            provider=str(route.get("provider") or ""),
            model=str(route.get("model") or ""),
            runtime=adapter.descriptor.id,
            prompt=user_message.content,
            metadata={
                "protocol_version": HARNESS_PROTOCOL_VERSION,
                "message_id": user_message.message_id,
            },
        )
        self._active_runs[ref.session_id] = run.run_id
        assistant_created = False
        deltas: list[str] = []

        started = self._record(
            run.run_id,
            HarnessEvent(
                type="run.started",
                data={
                    "descriptor": adapter.descriptor.to_dict(),
                    "provider": route.get("provider") or "",
                    "model": route.get("model") or "",
                },
            ),
        )
        yield started
        yield self._record(
            run.run_id,
            HarnessEvent(type="message.created", data=user_message.to_dict()),
        )

        try:
            async for raw_event in adapter.send(ref, user_message):
                if run.run_id in self._cancelled_runs:
                    break
                event = self._canonical_event(raw_event, adapter.descriptor.id, ref, run.run_id)
                if event.type in TERMINAL_EVENT_TYPES:
                    terminal = self._record(run.run_id, event)
                    self.store.end_run(run.run_id, status=_status_for_terminal(event))
                    yield terminal
                    return
                if event.type == "message.delta":
                    deltas.append(str(event.data.get("text") or ""))
                elif event.type == "message.created" and event.data.get("role") == "assistant":
                    assistant_created = True
                yield self._record(run.run_id, event)
        except asyncio.CancelledError:
            await self._mark_cancelled(ref, run.run_id, reason="consumer_cancelled")
            raise
        except Exception as exc:
            failed = self._record(
                run.run_id,
                HarnessEvent(
                    type="run.failed",
                    data={"error": str(exc), "error_type": type(exc).__name__},
                ),
            )
            self.store.end_run(
                run.run_id,
                status="failed",
                metadata={"error": str(exc), "error_type": type(exc).__name__},
            )
            yield failed
            return
        finally:
            self._active_runs.pop(ref.session_id, None)

        if run.run_id in self._cancelled_runs:
            self._cancelled_runs.discard(run.run_id)
            return
        if not assistant_created:
            yield self._record(
                run.run_id,
                HarnessEvent(
                    type="message.created",
                    data=HarnessMessage("assistant", "".join(deltas)).to_dict(),
                ),
            )
        completed = self._record(
            run.run_id,
            HarnessEvent(type="run.completed", data={"status": "succeeded"}),
        )
        self.store.end_run(run.run_id, status="succeeded")
        yield completed

    async def steer(
        self,
        session: HarnessSessionRef | str,
        message: HarnessMessage | str,
    ) -> None:
        ref = self._resolve_session(session)
        adapter = self._adapter(ref.harness_id)
        require_capability(adapter.descriptor, "steer")
        steer_message = (
            message if isinstance(message, HarnessMessage) else HarnessMessage("user", message)
        )
        await adapter.steer(ref, steer_message)

    async def cancel(self, session: HarnessSessionRef | str) -> None:
        ref = self._resolve_session(session)
        adapter = self._adapter(ref.harness_id)
        require_capability(adapter.descriptor, "cancel")
        await adapter.cancel(ref)
        run_id = self._active_runs.get(ref.session_id)
        if run_id:
            await self._mark_cancelled(ref, run_id, reason="requested")

    async def checkpoint(
        self,
        session: HarnessSessionRef | str,
    ) -> HarnessCheckpoint:
        ref = self._resolve_session(session)
        adapter = self._adapter(ref.harness_id)
        require_capability(adapter.descriptor, "checkpoint")
        checkpoint = await adapter.checkpoint(ref)
        record = self.store.get_session(ref.session_id)
        metadata = dict(record.metadata if record else {})
        checkpoints = list(metadata.get("protocol_checkpoints") or [])
        checkpoints.append(checkpoint.to_dict())
        metadata["protocol_checkpoints"] = checkpoints
        self.store.open_session(ref.session_id, self._spec(adapter.descriptor), metadata=metadata)
        route = self._session_route(ref.session_id)
        run = self.store.start_run(
            session_id=ref.session_id,
            spec=self._spec(adapter.descriptor),
            provider=str(route.get("provider") or ""),
            model=str(route.get("model") or ""),
            runtime=adapter.descriptor.id,
            prompt="<checkpoint>",
            metadata={"protocol_operation": "checkpoint"},
        )
        self._record(
            run.run_id,
            HarnessEvent(
                type="run.started",
                data={"operation": "checkpoint"},
                session_id=ref.session_id,
                harness_id=adapter.descriptor.id,
            ),
        )
        self._record(
            run.run_id,
            HarnessEvent(
                type="checkpoint.created",
                data=checkpoint.to_dict(),
                session_id=ref.session_id,
                harness_id=adapter.descriptor.id,
            ),
        )
        self._record(
            run.run_id,
            HarnessEvent(
                type="run.completed",
                data={"status": "succeeded", "operation": "checkpoint"},
                session_id=ref.session_id,
                harness_id=adapter.descriptor.id,
            ),
        )
        self.store.end_run(run.run_id, status="succeeded")
        return checkpoint

    def export(self, session: HarnessSessionRef | str) -> HarnessSessionBundle:
        """Export canonical evidence without requiring a native adapter export."""
        ref = self._resolve_session(session)
        descriptor = self.describe(ref.harness_id)
        session_record = self.store.get_session(ref.session_id)
        runs = sorted(
            self.store.list_runs(session_id=ref.session_id),
            key=lambda item: item.started_at,
        )
        events = tuple(event for run in runs for event in run.events)
        artifacts = tuple(
            _artifact_from_event(event) for event in events if event.type == "artifact.created"
        )
        checkpoint_data = list(
            (session_record.metadata if session_record else {}).get("protocol_checkpoints") or []
        )
        checkpoints = tuple(_checkpoint_from_dict(item) for item in checkpoint_data)
        return HarnessSessionBundle(
            protocol_version=HARNESS_PROTOCOL_VERSION,
            descriptor=descriptor,
            session=ref,
            runs=tuple(run.to_dict() for run in runs),
            events=events,
            artifacts=artifacts,
            checkpoints=checkpoints,
        )

    def _adapter(self, harness_id: str) -> HarnessAdapter:
        try:
            return self._adapters[harness_id]
        except KeyError as exc:
            raise HarnessNotFoundError(f"Unknown harness adapter: {harness_id}") from exc

    def _resolve_session(self, session: HarnessSessionRef | str) -> HarnessSessionRef:
        return (
            session if isinstance(session, HarnessSessionRef) else self._session_from_store(session)
        )

    def _session_from_store(self, session_id: str) -> HarnessSessionRef:
        record = self.store.get_session(session_id)
        if record is None:
            raise HarnessNotFoundError(f"Unknown harness session: {session_id}")
        protocol = dict(record.metadata.get("protocol") or {})
        adapter_id = str(protocol.get("adapter_id") or record.harness)
        session_metadata = dict(protocol.get("session_metadata") or {})
        checkpoints = list(record.metadata.get("protocol_checkpoints") or [])
        if checkpoints:
            session_metadata["checkpoint_state"] = dict(checkpoints[-1].get("state") or {})
        return HarnessSessionRef(
            session_id=record.session_id,
            harness_id=adapter_id,
            external_session_id=protocol.get("external_session_id"),
            metadata=session_metadata,
        )

    def _session_route(self, session_id: str) -> dict[str, Any]:
        record = self.store.get_session(session_id)
        return dict((record.metadata if record else {}).get("protocol") or {})

    def _touch_session(self, session: HarnessSessionRef) -> None:
        adapter = self._adapter(session.harness_id)
        route = self._session_route(session.session_id)
        route.update(
            {
                "external_session_id": session.external_session_id,
                "session_metadata": dict(session.metadata),
            }
        )
        self.store.open_session(
            session.session_id,
            self._spec(adapter.descriptor),
            metadata={"protocol": route},
        )

    def _record(self, run_id: str, event: HarnessEvent) -> HarnessEvent:
        updated = self.store.append_event(run_id, event)
        return updated.events[-1]

    def _canonical_event(
        self,
        event: HarnessEvent,
        harness_id: str,
        session: HarnessSessionRef,
        run_id: str,
    ) -> HarnessEvent:
        event_type = canonical_event_type(event.type, event.data)
        data = dict(event.data)
        if event_type == "artifact.created" and not data.get("artifact_id"):
            artifact = HarnessArtifact(
                kind=str(data.get("kind") or "artifact"),
                uri=str(data.get("uri") or ""),
                name=str(data.get("name") or ""),
                media_type=str(data.get("media_type") or "application/octet-stream"),
                metadata=dict(data.get("metadata") or {}),
            )
            data = artifact.to_dict()
        return replace(
            event,
            type=event_type,
            data=data,
            protocol_version=HARNESS_PROTOCOL_VERSION,
            session_id=session.session_id,
            run_id=run_id,
            harness_id=harness_id,
            sequence=0,
            parent_event_id=None,
        )

    async def _mark_cancelled(
        self,
        session: HarnessSessionRef,
        run_id: str,
        *,
        reason: str,
    ) -> None:
        if run_id in self._cancelled_runs:
            return
        self._cancelled_runs.add(run_id)
        self._record(
            run_id,
            HarnessEvent(
                type="run.cancelled",
                data={"reason": reason},
                session_id=session.session_id,
                harness_id=session.harness_id,
            ),
        )
        self.store.end_run(run_id, status="cancelled", metadata={"reason": reason})

    @staticmethod
    def _spec(descriptor: HarnessDescriptor) -> HarnessSpec:
        return HarnessSpec(name=descriptor.id, description=descriptor.description)


def _status_for_terminal(event: HarnessEvent) -> str:
    default = {
        "run.completed": "succeeded",
        "run.failed": "failed",
        "run.cancelled": "cancelled",
    }[event.type]
    declared = str(event.data.get("status") or "").lower()
    if declared in {"succeeded", "failed", "cancelled", "needs_approval"}:
        return declared
    return default


def _artifact_from_event(event: HarnessEvent) -> HarnessArtifact:
    data = dict(event.data)
    return HarnessArtifact(
        artifact_id=str(data.get("artifact_id") or ""),
        kind=str(data.get("kind") or "artifact"),
        uri=str(data.get("uri") or ""),
        name=str(data.get("name") or ""),
        media_type=str(data.get("media_type") or "application/octet-stream"),
        metadata=dict(data.get("metadata") or {}),
    )


def _checkpoint_from_dict(data: dict[str, Any]) -> HarnessCheckpoint:
    return HarnessCheckpoint(
        checkpoint_id=str(data.get("checkpoint_id") or ""),
        session_id=str(data.get("session_id") or ""),
        harness_id=str(data.get("harness_id") or ""),
        external_checkpoint_id=data.get("external_checkpoint_id"),
        created_at=float(data.get("created_at") or 0),
        state=dict(data.get("state") or {}),
    )
