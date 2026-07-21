"""Harness Protocol v1 adapter for the optional RLM Code backend."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .backends.base import HarnessBackendRequest
from .backends.rlm_code import (
    MINIMUM_RLM_CODE_VERSION,
    RLM_CODE_BACKEND_NAME,
    RLMCodeHarnessBackend,
    RunnerFactory,
    installed_rlm_code_version,
)
from .events import HarnessEvent
from .protocol import (
    HarnessCapabilities,
    HarnessCreateRequest,
    HarnessDescriptor,
    HarnessMessage,
    HarnessSessionRef,
)
from .protocol_adapters import BaseHarnessAdapter
from .spec import AgentSpec, ExecutionPolicySpec, HarnessSpec, ModelPolicySpec, RuntimeSpec


class RLMCodeHarnessProtocolAdapter(BaseHarnessAdapter):
    """Expose RLM Code directly through SuperQode Harness Protocol v1."""

    def __init__(
        self,
        *,
        adapter_id: str = RLM_CODE_BACKEND_NAME,
        config: dict[str, Any] | None = None,
        runner_factory: RunnerFactory | None = None,
    ) -> None:
        self.config = dict(config or {})
        self._backend = RLMCodeHarnessBackend(runner_factory=runner_factory)
        self.descriptor = HarnessDescriptor(
            id=adapter_id,
            name="RLM Code",
            description=(
                "Recursive Language Model harness with repository context profiles, "
                "opaque root observations, trajectory evidence, and length-generalization metrics"
            ),
            capabilities=HarnessCapabilities(
                streaming=False,
                resume=True,
                cancel=True,
                tools=True,
                usage=True,
            ),
            metadata={
                "runtime": "pure_rlm",
                "minimum_rlm_code_version": MINIMUM_RLM_CODE_VERSION,
                "rlm_code_version": installed_rlm_code_version(),
                "profiles": ["reference", "repo_evidence", "lid"],
            },
        )

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        session_id = request.session_id or f"rlm-code-{uuid.uuid4().hex[:12]}"
        metadata = {
            "provider": request.provider,
            "model": request.model,
            "working_directory": str(request.working_directory),
            "rlm_code": {**self.config, **dict(request.metadata.get("rlm_code") or {})},
            **{key: value for key, value in request.metadata.items() if key != "rlm_code"},
        }
        return HarnessSessionRef(
            session_id=session_id,
            harness_id=self.descriptor.id,
            metadata=metadata,
        )

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        return session

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        rlm_config = dict(session.metadata.get("rlm_code") or {})
        spec = HarnessSpec(
            name=self.descriptor.id,
            runtime=RuntimeSpec(
                backend=RLM_CODE_BACKEND_NAME,
                config={"rlm_code": rlm_config},
            ),
            model_policy=ModelPolicySpec(
                primary=str(session.metadata.get("model") or "") or None,
                config={"provider": str(session.metadata.get("provider") or "")},
            ),
            execution_policy=ExecutionPolicySpec(
                sandbox=str(rlm_config.get("sandbox_backend") or "docker"),
                allow_read=True,
                allow_write=False,
                allow_shell=False,
                allow_network=bool(rlm_config.get("network_enabled", False)),
            ),
            agents=(AgentSpec(id="rlm-root", role="recursive repository analysis"),),
        )
        request = HarnessBackendRequest(
            spec=spec,
            prompt=message.content,
            provider=str(session.metadata.get("provider") or ""),
            model=str(session.metadata.get("model") or ""),
            working_directory=Path(str(session.metadata.get("working_directory") or Path.cwd())),
            session_id=session.session_id,
            sandbox_backend=spec.execution_policy.sandbox,
            metadata=dict(message.metadata),
        )
        result = await self._backend.run(request)
        for event in result.metadata.get("events", ()):
            yield event
        yield HarnessEvent(
            type="message.created",
            data=HarnessMessage(
                role="assistant",
                content=result.response.content,
                metadata={
                    "rlm_run_id": result.metadata.get("rlm_run_id"),
                    "rlm_run_path": result.metadata.get("rlm_run_path"),
                },
            ).to_dict(),
        )
        if result.response.stopped_reason == "cancelled":
            yield HarnessEvent(
                type="run.cancelled",
                data={"rlm_run_id": result.metadata.get("rlm_run_id")},
            )
        elif result.response.error:
            yield HarnessEvent(
                type="run.failed",
                data={
                    "error": result.response.error,
                    "rlm_run_id": result.metadata.get("rlm_run_id"),
                },
            )

    async def cancel(self, session: HarnessSessionRef) -> None:
        await self._backend.cancel(session.session_id)


__all__ = ["RLMCodeHarnessProtocolAdapter"]
