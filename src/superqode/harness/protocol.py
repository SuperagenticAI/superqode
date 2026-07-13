"""Versioned contracts for running different coding-agent harnesses uniformly."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .events import HARNESS_PROTOCOL_VERSION, HarnessEvent

CANONICAL_EVENT_TYPES = frozenset(
    {
        "run.started",
        "message.created",
        "message.delta",
        "model.requested",
        "model.completed",
        "model.thinking",
        "tool.requested",
        "tool.completed",
        "approval.requested",
        "approval.resolved",
        "artifact.created",
        "checkpoint.created",
        "validation.completed",
        "run.completed",
        "run.failed",
        "run.cancelled",
    }
)

TERMINAL_EVENT_TYPES = frozenset({"run.completed", "run.failed", "run.cancelled"})

_LEGACY_EVENT_TYPES = {
    "run_start": "run.started",
    "model_request": "model.requested",
    "model_result": "model.completed",
    "model_delta": "message.delta",
    "delta": "message.delta",
    "thinking": "model.thinking",
    "tool_call": "tool.requested",
    "tool_result": "tool.completed",
    "approval_required": "approval.requested",
    "approval_decision": "approval.resolved",
    "approval_resumed": "approval.resolved",
    "run_end": "run.completed",
}


class HarnessProtocolError(RuntimeError):
    """Base error raised by the Harness Protocol control plane."""


class HarnessNotFoundError(HarnessProtocolError):
    """Raised when an adapter or durable protocol session does not exist."""


class HarnessCapabilityError(HarnessProtocolError):
    """Raised when an adapter is asked to perform an unsupported operation."""

    def __init__(self, harness_id: str, capability: str) -> None:
        self.harness_id = harness_id
        self.capability = capability
        super().__init__(f"Harness {harness_id!r} does not support {capability!r}")


@dataclass(frozen=True)
class HarnessCapabilities:
    """Operations and evidence an adapter can honestly provide."""

    streaming: bool = True
    resume: bool = False
    steer: bool = False
    cancel: bool = False
    checkpoint: bool = False
    approvals: bool = False
    tools: bool = False
    usage: bool = False
    native_export: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "streaming": self.streaming,
            "resume": self.resume,
            "steer": self.steer,
            "cancel": self.cancel,
            "checkpoint": self.checkpoint,
            "approvals": self.approvals,
            "tools": self.tools,
            "usage": self.usage,
            "native_export": self.native_export,
        }


@dataclass(frozen=True)
class HarnessDescriptor:
    """Stable identity and capability declaration for one adapter."""

    id: str
    name: str
    description: str = ""
    adapter_version: str = "1.0"
    protocol_version: str = HARNESS_PROTOCOL_VERSION
    capabilities: HarnessCapabilities = field(default_factory=HarnessCapabilities)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "adapter_version": self.adapter_version,
            "protocol_version": self.protocol_version,
            "capabilities": self.capabilities.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HarnessCreateRequest:
    """Portable request for creating a harness session."""

    harness_id: str
    provider: str = ""
    model: str = ""
    working_directory: Path = field(default_factory=Path.cwd)
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessSessionRef:
    """Portable reference to a protocol-owned harness session."""

    session_id: str
    harness_id: str
    external_session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "harness_id": self.harness_id,
            "external_session_id": self.external_session_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HarnessMessage:
    """One portable user, assistant, system, or tool message."""

    role: str
    content: str
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex}")
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HarnessArtifact:
    """A file, patch, report, or other output produced by a run."""

    kind: str
    uri: str
    artifact_id: str = field(default_factory=lambda: f"artifact_{uuid.uuid4().hex}")
    name: str = ""
    media_type: str = "application/octet-stream"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "uri": self.uri,
            "name": self.name,
            "media_type": self.media_type,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HarnessCheckpoint:
    """A harness-native state marker that can be recorded in the ledger."""

    session_id: str
    harness_id: str
    checkpoint_id: str = field(default_factory=lambda: f"checkpoint_{uuid.uuid4().hex}")
    external_checkpoint_id: str | None = None
    created_at: float = field(default_factory=time.time)
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "harness_id": self.harness_id,
            "external_checkpoint_id": self.external_checkpoint_id,
            "created_at": self.created_at,
            "state": dict(self.state),
        }


@dataclass(frozen=True)
class HarnessSessionBundle:
    """Portable export of a session and its canonical durable evidence."""

    protocol_version: str
    descriptor: HarnessDescriptor
    session: HarnessSessionRef
    runs: tuple[dict[str, Any], ...]
    events: tuple[HarnessEvent, ...]
    artifacts: tuple[HarnessArtifact, ...] = ()
    checkpoints: tuple[HarnessCheckpoint, ...] = ()
    exported_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "descriptor": self.descriptor.to_dict(),
            "session": self.session.to_dict(),
            "runs": [dict(run) for run in self.runs],
            "events": [event.to_dict() for event in self.events],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "checkpoints": [checkpoint.to_dict() for checkpoint in self.checkpoints],
            "exported_at": self.exported_at,
        }


@runtime_checkable
class HarnessAdapter(Protocol):
    """Structural interface implemented by Core, Python, and ACP adapters."""

    @property
    def descriptor(self) -> HarnessDescriptor: ...

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef: ...

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]: ...

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef: ...

    async def steer(self, session: HarnessSessionRef, message: HarnessMessage) -> None: ...

    async def cancel(self, session: HarnessSessionRef) -> None: ...

    async def checkpoint(self, session: HarnessSessionRef) -> HarnessCheckpoint: ...


def canonical_event_type(event_type: str, data: dict[str, Any] | None = None) -> str:
    """Map legacy kernel names to the v1 canonical event vocabulary."""
    if event_type == "run_end":
        status = str((data or {}).get("status") or "").lower()
        if status in {"failed", "error"}:
            return "run.failed"
        if status in {"cancelled", "canceled"}:
            return "run.cancelled"
    if "." in event_type:
        return event_type
    return _LEGACY_EVENT_TYPES.get(event_type, f"adapter.{event_type.replace('_', '.')}")


def require_capability(descriptor: HarnessDescriptor, capability: str) -> None:
    """Raise a stable protocol error when an optional operation is unavailable."""
    if not bool(getattr(descriptor.capabilities, capability, False)):
        raise HarnessCapabilityError(descriptor.id, capability)
