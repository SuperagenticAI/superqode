"""Base protocol for SuperQode harness backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from ...agent.loop import AgentResponse
from ...agent.system_prompts import SystemPromptLevel
from ..events import HarnessEvent
from ..spec import HarnessSpec


@dataclass(frozen=True)
class HarnessBackendCapabilities:
    """Feature surface advertised by a harness backend."""

    backend: str
    supports_coding: bool = True
    supports_no_tool: bool = True
    supports_streaming: bool = True
    supports_approvals: bool = False
    supports_sandbox: bool = False
    supports_shell: bool = False
    supports_mcp: bool = False
    supports_typed_output: bool = True
    supports_workflow_children: bool = True
    event_detail: str = "coarse"
    availability: str = "unknown"
    install_hint: str | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "supports_coding": self.supports_coding,
            "supports_no_tool": self.supports_no_tool,
            "supports_streaming": self.supports_streaming,
            "supports_approvals": self.supports_approvals,
            "supports_sandbox": self.supports_sandbox,
            "supports_shell": self.supports_shell,
            "supports_mcp": self.supports_mcp,
            "supports_typed_output": self.supports_typed_output,
            "supports_workflow_children": self.supports_workflow_children,
            "event_detail": self.event_detail,
            "availability": self.availability,
            "install_hint": self.install_hint,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class HarnessBackendIssue:
    """Compatibility issue found while inspecting a HarnessSpec."""

    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class HarnessBackendInspection:
    """Resolved backend capability and compatibility report."""

    backend: str
    capabilities: HarnessBackendCapabilities
    issues: tuple[HarnessBackendIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "ok": self.ok,
            "capabilities": self.capabilities.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class HarnessBackendRequest:
    """Backend-ready request produced by the HarnessKernel."""

    spec: HarnessSpec
    prompt: str
    provider: str
    model: str
    working_directory: Path = field(default_factory=Path.cwd)
    session_id: str | None = None
    runtime: str | None = None
    sandbox_backend: str = "local"
    system_level: SystemPromptLevel | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessBackendResult:
    """Backend result before kernel-level normalization."""

    response: AgentResponse
    backend: str
    runtime: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class HarnessBackend(Protocol):
    """Executable backend behind a HarnessSpec."""

    name: str
    capabilities: HarnessBackendCapabilities

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult: ...

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]: ...
