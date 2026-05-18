"""Minimal HarnessKernel compatibility layer.

This kernel is intentionally small: it runs HarnessSpec-backed sessions through
today's runtime factory. That gives SuperQode a stable v2-facing API before the
larger session/event/sandbox internals are replaced.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent.loop import AgentResponse
from ..agent.system_prompts import SystemPromptLevel
from .backends.base import HarnessBackendRequest
from .backends.registry import create_harness_backend
from .events import HarnessEvent
from .output import build_typed_output_prompt, parse_typed_output
from .spec import HarnessSpec
from .store import FileHarnessStore


@dataclass(frozen=True)
class HarnessRunRequest:
    """Inputs for one harness prompt call."""

    prompt: str
    provider: str
    model: str
    working_directory: Path = field(default_factory=Path.cwd)
    session_id: str | None = None
    runtime: str | None = None
    sandbox_backend: str = "local"
    system_level: SystemPromptLevel | None = None
    result_schema: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessRunResult:
    """Normalized result returned by a HarnessSession."""

    content: str
    response: AgentResponse
    spec: HarnessSpec
    session_id: str
    run_id: str
    events: tuple[HarnessEvent, ...] = ()
    data: Any | None = None

    @property
    def tool_calls_made(self) -> int:
        return self.response.tool_calls_made

    @property
    def iterations(self) -> int:
        return self.response.iterations


class HarnessKernel:
    """Run HarnessSpec sessions through the current SuperQode runtime stack."""

    def __init__(
        self,
        spec: HarnessSpec,
        *,
        event_callback: Callable[[HarnessEvent], None] | None = None,
        store: FileHarnessStore | None = None,
    ) -> None:
        self.spec = spec
        self.event_callback = event_callback
        self.store = store or FileHarnessStore()

    async def session(self, session_id: str | None = None) -> "HarnessSession":
        """Open a harness session."""
        resolved_session_id = session_id or f"harness-{uuid.uuid4().hex[:8]}"
        self.store.open_session(resolved_session_id, self.spec)
        return HarnessSession(
            kernel=self,
            session_id=resolved_session_id,
        )

    def emit(self, event: HarnessEvent) -> None:
        if self.event_callback is not None:
            self.event_callback(event)


class HarnessSession:
    """A promptable harness session."""

    def __init__(self, *, kernel: HarnessKernel, session_id: str) -> None:
        self.kernel = kernel
        self.session_id = session_id
        self._events: list[HarnessEvent] = []

    async def prompt(
        self,
        prompt: str,
        *,
        provider: str,
        model: str,
        working_directory: Path | None = None,
        runtime: str | None = None,
        sandbox_backend: str = "local",
        system_level: SystemPromptLevel | None = None,
        result: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessRunResult:
        """Run one prompt through this harness session."""
        request = HarnessRunRequest(
            prompt=prompt,
            provider=provider,
            model=model,
            working_directory=working_directory or Path.cwd(),
            session_id=self.session_id,
            runtime=runtime,
            sandbox_backend=sandbox_backend,
            system_level=system_level,
            result_schema=result,
            metadata=dict(metadata or {}),
        )
        return await self.run(request)

    async def run(self, request: HarnessRunRequest) -> HarnessRunResult:
        """Run one fully specified harness request."""
        runtime_name = request.runtime or self.kernel.spec.runtime.backend
        effective_prompt = build_typed_output_prompt(request.prompt, request.result_schema)
        self.kernel.store.open_session(
            request.session_id or self.session_id,
            self.kernel.spec,
            metadata={"provider": request.provider, "model": request.model},
        )
        run_record = self.kernel.store.start_run(
            session_id=request.session_id or self.session_id,
            spec=self.kernel.spec,
            provider=request.provider,
            model=request.model,
            runtime=runtime_name,
            prompt=request.prompt,
            metadata={
                **request.metadata,
                **({"typed_output": True} if request.result_schema is not None else {}),
            },
        )
        run_id = run_record.run_id
        self._emit(
            "run_start",
            run_id,
            {
                "harness": self.kernel.spec.name,
                "flavor": self.kernel.spec.flavor.value,
                "runtime": runtime_name,
                "provider": request.provider,
                "model": request.model,
            },
        )
        backend = create_harness_backend(request.runtime or self.kernel.spec.runtime.backend)
        backend_request = HarnessBackendRequest(
            spec=self.kernel.spec,
            prompt=effective_prompt,
            provider=request.provider,
            model=request.model,
            working_directory=request.working_directory,
            session_id=request.session_id or self.session_id,
            runtime=request.runtime,
            sandbox_backend=request.sandbox_backend,
            system_level=request.system_level,
            metadata=request.metadata,
        )
        try:
            backend_result = await backend.run(backend_request)
        except Exception as exc:
            self._emit(
                "run_end",
                run_id,
                {"status": "failed", "error": str(exc), "error_type": type(exc).__name__},
            )
            self.kernel.store.end_run(
                run_id,
                status="failed",
                metadata={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise
        response = backend_result.response
        try:
            data = parse_typed_output(response.content, request.result_schema)
        except Exception as exc:
            self._emit(
                "run_end",
                run_id,
                {"status": "failed", "error": str(exc), "error_type": type(exc).__name__},
            )
            self.kernel.store.end_run(
                run_id,
                status="failed",
                metadata={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise
        self._emit(
            "run_end",
            run_id,
            {
                "status": "succeeded",
                "backend": backend_result.backend,
                "runtime": backend_result.runtime,
                "tool_calls_made": response.tool_calls_made,
                "iterations": response.iterations,
                "stopped_reason": response.stopped_reason,
                "typed_output": request.result_schema is not None,
            },
        )
        self.kernel.store.end_run(
            run_id,
            status="succeeded",
            metadata={
                "tool_calls_made": response.tool_calls_made,
                "iterations": response.iterations,
                "stopped_reason": response.stopped_reason,
                "typed_output": request.result_schema is not None,
            },
        )
        return HarnessRunResult(
            content=response.content,
            response=response,
            spec=self.kernel.spec,
            session_id=request.session_id or self.session_id,
            run_id=run_id,
            events=tuple(self._events),
            data=data,
        )

    def _emit(self, event_type: str, run_id: str, data: dict[str, Any]) -> None:
        event = HarnessEvent(
            type=event_type,
            data=data,
            session_id=self.session_id,
            run_id=run_id,
        )
        self._events.append(event)
        self.kernel.store.append_event(run_id, event)
        self.kernel.emit(event)


async def init_harness(
    spec: HarnessSpec,
    *,
    event_callback: Callable[[HarnessEvent], None] | None = None,
    store: FileHarnessStore | None = None,
) -> HarnessKernel:
    """Create a HarnessKernel for a spec."""
    return HarnessKernel(spec, event_callback=event_callback, store=store)
