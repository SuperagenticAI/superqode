"""Harness Protocol adapter for SuperQode's native RLM harness."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from .events import HarnessEvent
from .pipy_adapter import translate_event
from .protocol import (
    HarnessCapabilities,
    HarnessCheckpoint,
    HarnessCreateRequest,
    HarnessDescriptor,
    HarnessMessage,
    HarnessSessionRef,
)

DEFAULT_TOOLS: tuple[str, ...] = ("python",)


class RLMHarnessProtocolAdapter:
    """Run the one-tool RLM coding session behind Harness Protocol v1."""

    def __init__(self, *, session_factory: Any | None = None) -> None:
        self.descriptor = HarnessDescriptor(
            id="rlm",
            name="RLM",
            description="Native recursive coding harness with one persistent Python tool.",
            adapter_version="1.0",
            capabilities=HarnessCapabilities(
                streaming=True,
                resume=True,
                steer=True,
                cancel=True,
                checkpoint=True,
                approvals=False,
                tools=True,
                usage=True,
            ),
            metadata={
                "tools": list(DEFAULT_TOOLS),
                "model_tool_count": 1,
                "persistent_python": True,
                "durable_children": True,
                "pure_permissions": True,
            },
        )
        self._session_factory = session_factory
        self._sessions: dict[str, Any] = {}
        self._refs: dict[str, HarnessSessionRef] = {}

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        if request.harness_id != self.descriptor.id:
            raise ValueError(f"RLM adapter cannot create harness {request.harness_id!r}")
        session_id = request.session_id or f"rlm-{uuid4().hex[:12]}"
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
                "model_tools": list(DEFAULT_TOOLS),
                "persistent_python": True,
                "pure_permissions": True,
            },
        )
        self._sessions[session_id] = coding_session
        self._refs[session_id] = ref
        _record_session_path(session_id, coding_session.session_path)
        return ref

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        if session.harness_id != self.descriptor.id:
            raise ValueError(f"RLM adapter cannot resume harness {session.harness_id!r}")
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
        existing = str(metadata.get("session_path") or "") or _indexed_session_path(
            session.session_id, working_directory
        )
        coding_session = await self._open(
            request,
            working_directory,
            session_path=existing or None,
        )
        ref = HarnessSessionRef(
            session_id=session.session_id,
            harness_id=self.descriptor.id,
            external_session_id=(await coding_session.info()).id,
            metadata={
                **metadata,
                "session_path": str(coding_session.session_path),
                "model_tools": list(DEFAULT_TOOLS),
            },
        )
        self._sessions[session.session_id] = coding_session
        self._refs[session.session_id] = ref
        _record_session_path(session.session_id, coding_session.session_path)
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
        from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
        from superqode.rlm.context import ContextPolicy
        from superqode.rlm.sandbox import RLMSandboxConfig
        from superqode.rlm.subcalls import SubcallPolicy

        limits = dict(request.metadata.get("rlm_config") or {})
        # The backend resolves the profile once, where the HarnessSpec and its
        # execution policy are both in scope. Falling back to the raw runtime
        # config keeps direct adapter use working.
        sandbox = RLMSandboxConfig.from_config(request.metadata.get("rlm_sandbox") or limits)
        options = RLMCodingSessionOptions(
            cwd=working_directory,
            model=resolve_model(request.model or "", provider=request.provider or ""),
            tool_names=DEFAULT_TOOLS,
            max_depth=int(limits.get("max_depth", 3)),
            max_children=int(limits.get("max_children", 8)),
            max_parallel=int(limits.get("max_parallel", 4)),
            goal=str(limits.get("goal") or ""),
            autonomous=bool(limits.get("autonomous", False)),
            gates=tuple(str(item) for item in limits.get("gates") or ()),
            autonomous_max_rounds=int(limits.get("autonomous_max_rounds", 3)),
            gate_timeout=float(limits.get("gate_timeout", 120.0)),
            durable_children=bool(limits.get("durable_children", True)),
            sandbox=sandbox,
            subcall_policy=SubcallPolicy.from_config(limits),
            context_policy=ContextPolicy.from_config(limits),
        )
        if session_path and Path(session_path).is_file():
            return await RLMCodingSession.resume(options, session_path=session_path)
        return await RLMCodingSession.create(options)

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        coding_session = await self._require(session)
        model = coding_session.harness.get_model()
        yield HarnessEvent(
            type="model.requested",
            data={"provider": model.provider, "model": model.id, "runtime": "rlm"},
        )
        yield HarnessEvent(
            type="message.created",
            data={"role": "user", "content": message.content},
        )
        from superqode.rlm.policy import gate_feedback, run_completion_gates

        prompt = message.content
        policy = coding_session.policy
        rounds = policy.max_rounds if policy.autonomous and policy.gates else 1
        for round_number in range(1, rounds + 1):
            stream = coding_session.prompt_events(prompt)
            async for event in stream:
                for translated in translate_event(event, runtime="rlm"):
                    yield translated
            await stream.result()
            policy = coding_session.policy
            if not policy.autonomous or not policy.gates:
                return
            yield HarnessEvent(
                type="autonomous_gates_start",
                data={"round": round_number, "gates": list(policy.gates)},
            )
            results = await run_completion_gates(
                policy.gates,
                cwd=coding_session.cwd,
                timeout=policy.gate_timeout,
                # Under an isolated profile this sends the gate into the same
                # boundary the model's Python runs in.
                runner=getattr(coding_session, "gate_runner", None),
            )
            passed = all(result.ok for result in results)
            yield HarnessEvent(
                type="autonomous_gates_result",
                data={
                    "round": round_number,
                    "passed": passed,
                    "results": [result.to_dict() for result in results],
                },
            )
            if passed:
                return
            if round_number == rounds:
                yield HarnessEvent(
                    type="error",
                    data={
                        "error": f"Autonomous completion gates still fail after {rounds} rounds",
                        "error_type": "RLMCompletionGateError",
                    },
                )
                return
            prompt = gate_feedback(results)

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
            external_checkpoint_id=leaf,
            state={
                "session_path": str(ref.metadata.get("session_path") or ""),
                "leaf_id": leaf or "",
                "provider": str(ref.metadata.get("provider") or ""),
                "model": str(ref.metadata.get("model") or ""),
                "kernel_continuity": "serializable-checkpoint",
            },
        )

    async def _require(self, session: HarnessSessionRef) -> Any:
        active = self._sessions.get(session.session_id)
        if active is not None:
            return active
        await self.resume(session)
        return self._sessions[session.session_id]


def _record_session_path(session_id: str, session_path: Path | str) -> None:
    from superqode.rlm.config import SESSION_INDEX_NAME

    path = Path(session_path)
    index = path.parent / SESSION_INDEX_NAME
    try:
        entries = _read_index(index)
        if entries.get(session_id) == str(path):
            return
        entries[session_id] = str(path)
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def _indexed_session_path(session_id: str, working_directory: Path) -> str:
    from superqode.rlm.config import session_index_for

    try:
        entries = _read_index(session_index_for(working_directory))
    except OSError:
        return ""
    recorded = str(entries.get(session_id) or "")
    return recorded if recorded and Path(recorded).is_file() else ""


def _read_index(index: Path) -> dict[str, str]:
    if not index.is_file():
        return {}
    try:
        loaded = json.loads(index.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return (
        {str(key): str(value) for key, value in loaded.items()} if isinstance(loaded, dict) else {}
    )


__all__ = ["DEFAULT_TOOLS", "RLMHarnessProtocolAdapter"]
