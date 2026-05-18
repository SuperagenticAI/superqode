"""Base protocol for SuperQode harness backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ...agent.loop import AgentResponse
from ...agent.system_prompts import SystemPromptLevel
from ..spec import HarnessSpec


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

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult: ...
