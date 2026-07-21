"""RLM Code integration for HarnessSpec and Harness Protocol v1.

RLM Code owns the recursive execution semantics.  This module keeps the
SuperQode boundary deliberately small: translate HarnessSpec policy into an
``RLMRunner`` request, then normalize the persisted RLM trajectory into the
same event and evidence model used by every other SuperQode backend.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...agent.loop import AgentResponse
from ...providers.env_introspect import install_command
from ..events import HarnessEvent
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult

MINIMUM_RLM_CODE_VERSION = "0.1.11"
RLM_CODE_BACKEND_NAME = "rlm-code"

RunnerFactory = Callable[[HarnessBackendRequest, "RLMCodeSettings"], Any]


@dataclass(frozen=True)
class RLMCodeSettings:
    """Resolved RLM Code options for one HarnessSpec run."""

    profile: str = "lid"
    context_profile: str = "evidence"
    context: Any | None = None
    context_description: str | None = None
    context_paths: tuple[str, ...] = ()
    context_include: tuple[str, ...] = ()
    context_exclude: tuple[str, ...] = ()
    root_observation_mode: str | None = None
    history_policy: str | None = None
    decomposition_hint: bool | None = None
    max_root_history_chars: int = 40_000
    history_preserve_last: int = 2
    max_iteration_output_chars: int = 12_000
    output_mode: str = "summarize"
    max_steps: int | None = None
    exec_timeout: int = 60
    branch_width: int = 1
    max_depth: int = 0
    max_children_per_step: int = 4
    parallelism: int = 2
    time_budget_seconds: int | None = None
    sub_provider: str | None = None
    sub_model: str | None = None
    sandbox_backend: str = "docker"
    allow_unsafe_exec: bool = False
    network_enabled: bool = False
    base_url: str | None = None
    run_dir: Path | None = None

    @classmethod
    def from_request(cls, request: HarnessBackendRequest) -> "RLMCodeSettings":
        raw_runtime = request.spec.runtime.config
        nested = raw_runtime.get("rlm_code")
        config = dict(nested) if isinstance(nested, dict) else dict(raw_runtime)

        profile = _choice(config.get("profile", "lid"), {"reference", "repo_evidence", "lid"})
        context_profile = _choice(
            config.get("context_profile", "evidence"),
            {"auto", "mini", "evidence", "full", "explicit"},
        )
        observation = _optional_choice(
            config.get("root_observation_mode"),
            {"configured", "raw", "metadata", "opaque"},
        )
        history = _optional_choice(
            config.get("history_policy"),
            {"full", "structural", "offload"},
        )

        model_iterations = request.spec.model_policy.config.get("max_iterations")
        agent_iterations = next(
            (agent.max_iterations for agent in request.spec.agents if agent.max_iterations),
            None,
        )
        max_steps = _optional_int(config.get("max_steps", model_iterations or agent_iterations))
        policy_sandbox = str(request.spec.execution_policy.sandbox or "local").strip().lower()
        sandbox = str(config.get("sandbox_backend") or request.sandbox_backend or policy_sandbox)
        if sandbox == "local":
            sandbox = "docker"
        sandbox = _choice(sandbox, {"docker", "monty", "exec"})
        if policy_sandbox in {"docker", "monty"} and sandbox != policy_sandbox:
            raise ValueError(
                "runtime.config.rlm_code.sandbox_backend cannot weaken or replace "
                f"execution_policy.sandbox={policy_sandbox!r}"
            )

        sub_provider = _optional_text(config.get("sub_provider"))
        sub_model = _optional_text(config.get("sub_model") or request.spec.recursion.child_model)
        if sub_model:
            sub_provider, sub_model = _split_model(sub_provider or "", sub_model)

        configured_run_dir = _optional_text(config.get("run_dir"))
        run_dir = (
            _resolve_path(request.working_directory, configured_run_dir)
            if configured_run_dir
            else request.working_directory / ".superqode" / "rlm-code" / "runs"
        )
        return cls(
            profile=profile,
            context_profile=context_profile,
            context=config.get("context", request.metadata.get("rlm_context")),
            context_description=_optional_text(config.get("context_description")),
            context_paths=_string_tuple(config.get("context_paths")),
            context_include=_string_tuple(config.get("context_include")),
            context_exclude=_string_tuple(config.get("context_exclude")),
            root_observation_mode=observation,
            history_policy=history,
            decomposition_hint=_optional_bool(config.get("decomposition_hint")),
            max_root_history_chars=max(
                1_000,
                _int(config.get("max_root_history_chars"), 40_000),
            ),
            history_preserve_last=max(1, _int(config.get("history_preserve_last"), 2)),
            max_iteration_output_chars=max(
                2_000,
                _int(config.get("max_iteration_output_chars"), 12_000),
            ),
            output_mode=_choice(
                config.get("output_mode", "summarize"),
                {"truncate", "summarize", "metadata"},
            ),
            max_steps=max_steps,
            exec_timeout=max(1, _int(config.get("exec_timeout"), 60)),
            branch_width=max(1, _int(config.get("branch_width"), 1)),
            max_depth=max(0, _int(config.get("max_depth"), 0)),
            max_children_per_step=max(1, _int(config.get("max_children_per_step"), 4)),
            parallelism=max(1, _int(config.get("parallelism"), request.spec.workflow.parallelism)),
            time_budget_seconds=_optional_int(
                config.get("time_budget_seconds", request.spec.recursion.max_wall_seconds)
            ),
            sub_provider=sub_provider,
            sub_model=sub_model,
            sandbox_backend=sandbox,
            allow_unsafe_exec=bool(config.get("allow_unsafe_exec", False)),
            network_enabled=bool(
                request.spec.execution_policy.allow_network
                and config.get("network_enabled", request.spec.execution_policy.allow_network)
            ),
            base_url=_optional_text(
                config.get("base_url") or request.spec.model_policy.config.get("base_url")
            ),
            run_dir=run_dir,
        )


class RLMCodeHarnessBackend:
    """Run an RLM Code v0.1.11+ harness behind a SuperQode HarnessSpec."""

    name = RLM_CODE_BACKEND_NAME
    capabilities = HarnessBackendCapabilities(
        backend=RLM_CODE_BACKEND_NAME,
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=False,
        supports_approvals=False,
        supports_sandbox=True,
        supports_shell=False,
        supports_mcp=False,
        supports_typed_output=False,
        supports_workflow_children=True,
        event_detail="rich",
        notes=(
            "RLM Code owns recursive REPL execution and trajectory persistence.",
            "SuperQode normalizes RLM steps, usage, harness metrics, and artifacts.",
        ),
    )

    def __init__(self, *, runner_factory: RunnerFactory | None = None) -> None:
        self._runner_factory = runner_factory or _default_runner_factory
        self._active_runners: dict[str, Any] = {}

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        settings = RLMCodeSettings.from_request(request)
        runner = self._runner_factory(request, settings)
        session_key = request.session_id or "default"
        self._active_runners[session_key] = runner
        try:
            result = await _run_task(runner, request, settings)
        finally:
            self._active_runners.pop(session_key, None)

        raw_events = _load_run_events(runner, result)
        final_event = next(
            (event for event in reversed(raw_events) if event.get("type") == "final"),
            {},
        )
        usage = dict(getattr(result, "usage_summary", None) or final_event.get("usage") or {})
        harness_metrics = dict(final_event.get("harness") or {})
        context_event = next(
            (event for event in raw_events if event.get("type") == "context"),
            {},
        )
        cancelled = bool(final_event.get("cancelled"))
        completed = bool(getattr(result, "completed", False))
        stopped_reason = "cancelled" if cancelled else ("complete" if completed else "error")
        normalized_usage = _normalized_usage(usage)
        trajectory_path = Path(str(getattr(result, "run_path", ""))).resolve()
        events = _normalize_rlm_events(
            raw_events,
            request=request,
            result=result,
            settings=settings,
            usage=usage,
            harness_metrics=harness_metrics,
            context_event=context_event,
            trajectory_path=trajectory_path,
        )
        response = AgentResponse(
            content=str(getattr(result, "final_response", "") or ""),
            messages=[],
            tool_calls_made=_subcall_count(usage, raw_events),
            iterations=int(getattr(result, "steps", 0) or 0),
            stopped_reason=stopped_reason,
            error=(
                None
                if stopped_reason == "complete"
                else str(final_event.get("error") or "RLM Code did not reach FINAL")
            ),
            input_tokens=normalized_usage["input_tokens"],
            output_tokens=normalized_usage["output_tokens"],
            total_tokens=normalized_usage["total_tokens"],
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime="pure_rlm",
            metadata={
                "events": events,
                "rlm_run_id": str(getattr(result, "run_id", "")),
                "rlm_run_path": str(trajectory_path),
                "rlm_usage": usage,
                "rlm_harness_metrics": harness_metrics,
                "rlm_context": context_event,
                "rlm_code_version": installed_rlm_code_version(),
            },
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        """Expose a completed RLM run as ordered events; RLMRunner is not token-streaming."""
        result = await self.run(request)
        for event in result.metadata.get("events", ()):
            yield event
        if result.response.content:
            yield HarnessEvent(type="delta", data={"text": result.response.content})
        yield HarnessEvent(
            type="end",
            data={
                "backend": self.name,
                "runtime": result.runtime,
                "rlm_run_id": result.metadata.get("rlm_run_id"),
            },
        )

    async def cancel(self, session_id: str) -> None:
        """Request cooperative cancellation of the active RLM run for a session."""
        runner = self._active_runners.get(session_id)
        if runner is None:
            return
        cancel = getattr(runner, "request_cancel", None)
        if callable(cancel):
            cancel()


def rlm_code_installation_status() -> tuple[bool, str]:
    """Return whether a compatible RLM Code package is importable and why not."""
    if importlib.util.find_spec("rlm_code") is None:
        return False, f"RLM Code is not installed; run {install_command('rlm-code')}"
    version = installed_rlm_code_version()
    if version and _version_tuple(version) < _version_tuple(MINIMUM_RLM_CODE_VERSION):
        return (
            False,
            f"RLM Code {version} is too old; version {MINIMUM_RLM_CODE_VERSION}+ is required",
        )
    return True, ""


def installed_rlm_code_version() -> str:
    try:
        return importlib.metadata.version("rlm-code")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _default_runner_factory(
    request: HarnessBackendRequest,
    settings: RLMCodeSettings,
) -> Any:
    available, issue = rlm_code_installation_status()
    if not available:
        raise RuntimeError(issue)

    from rlm_code.core.config import ConfigManager
    from rlm_code.execution import ExecutionEngine
    from rlm_code.models.llm_connector import LLMConnector
    from rlm_code.rlm import RLMRunner

    manager = ConfigManager(project_root=request.working_directory)
    config = manager.config
    config.sandbox.pure_rlm_backend = settings.sandbox_backend
    config.sandbox.pure_rlm_allow_unsafe_exec = settings.allow_unsafe_exec
    config.sandbox.pure_rlm_profile = settings.profile
    config.sandbox.pure_rlm_root_observation_mode = settings.root_observation_mode or "configured"
    config.sandbox.pure_rlm_history_policy = settings.history_policy or "profile"
    config.sandbox.pure_rlm_decomposition_hint = bool(settings.decomposition_hint)
    config.sandbox.pure_rlm_max_root_history_chars = settings.max_root_history_chars
    config.sandbox.pure_rlm_history_preserve_last = settings.history_preserve_last
    config.sandbox.pure_rlm_max_iteration_output_chars = settings.max_iteration_output_chars
    config.sandbox.pure_rlm_output_mode = settings.output_mode
    config.sandbox.default_timeout_seconds = settings.exec_timeout
    config.sandbox.docker.network_enabled = settings.network_enabled

    provider, model = _split_model(request.provider, request.model)
    if not model:
        raise ValueError("The rlm-code backend requires a model")
    connector = LLMConnector(manager)
    connector.connect_to_model(
        model,
        model_type=provider or None,
        base_url=settings.base_url,
    )
    engine = ExecutionEngine(manager)
    return RLMRunner(
        llm_connector=connector,
        execution_engine=engine,
        run_dir=settings.run_dir,
        workdir=request.working_directory,
        max_parallelism=settings.parallelism,
    )


async def _run_task(
    runner: Any,
    request: HarnessBackendRequest,
    settings: RLMCodeSettings,
) -> Any:
    kwargs = {
        "max_steps": settings.max_steps,
        "exec_timeout": settings.exec_timeout,
        "environment": "pure_rlm",
        "sub_model": settings.sub_model,
        "sub_provider": settings.sub_provider,
        "branch_width": settings.branch_width,
        "max_depth": settings.max_depth,
        "max_children_per_step": settings.max_children_per_step,
        "parallelism": settings.parallelism,
        "time_budget_seconds": settings.time_budget_seconds,
        "context": settings.context,
        "context_description": settings.context_description,
        "context_profile": settings.context_profile,
        "context_paths": list(settings.context_paths) or None,
        "pure_rlm_profile": settings.profile,
        "root_observation_mode": settings.root_observation_mode,
        "history_policy": settings.history_policy,
        "decomposition_hint": settings.decomposition_hint,
    }
    async_runner = getattr(runner, "arun_task", None)
    if callable(async_runner) and not settings.context_include and not settings.context_exclude:
        return await async_runner(request.prompt, **kwargs)
    return await asyncio.to_thread(
        runner.run_task,
        request.prompt,
        **kwargs,
        context_include=list(settings.context_include) or None,
        context_exclude=list(settings.context_exclude) or None,
    )


def _load_run_events(runner: Any, result: Any) -> list[dict[str, Any]]:
    loader = getattr(runner, "load_run_events", None)
    if callable(loader):
        loaded = loader(str(getattr(result, "run_id", "")))
        if isinstance(loaded, list):
            return [dict(item) for item in loaded if isinstance(item, dict)]
    path = Path(str(getattr(result, "run_path", "")))
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _normalize_rlm_events(
    raw_events: list[dict[str, Any]],
    *,
    request: HarnessBackendRequest,
    result: Any,
    settings: RLMCodeSettings,
    usage: dict[str, Any],
    harness_metrics: dict[str, Any],
    context_event: dict[str, Any],
    trajectory_path: Path,
) -> list[HarnessEvent]:
    events = [
        HarnessEvent(
            type="model_request",
            data={
                "provider": request.provider,
                "model": request.model,
                "runtime": "pure_rlm",
                "profile": settings.profile,
                "context_profile": context_event.get("context_profile", settings.context_profile),
                "sub_provider": settings.sub_provider,
                "sub_model": settings.sub_model,
            },
        )
    ]
    for item in raw_events:
        if item.get("type") != "step":
            continue
        shared = {
            "rlm_run_id": item.get("run_id"),
            "step": item.get("step"),
            "depth": item.get("depth"),
            "root_prompt_chars": item.get("root_prompt_chars"),
            "root_prompt_sha256": item.get("root_prompt_sha256"),
            "role_usage": item.get("role_usage") or {},
        }
        action = dict(item.get("action") or {})
        events.append(
            HarnessEvent(
                type="tool_call",
                data={**shared, "tool_name": "rlm_repl", "action": action},
            )
        )
        events.append(
            HarnessEvent(
                type="tool_result",
                data={
                    **shared,
                    "tool_name": "rlm_repl",
                    "success": _observation_success(item.get("observation")),
                    "observation": item.get("observation"),
                    "reward": item.get("reward"),
                    "usage": item.get("usage") or {},
                },
            )
        )
    events.extend(
        [
            HarnessEvent(
                type="validation.completed",
                data={
                    "validator": "rlm-code-harness",
                    "completed": bool(getattr(result, "completed", False)),
                    "steps": int(getattr(result, "steps", 0) or 0),
                    "total_reward": float(getattr(result, "total_reward", 0.0) or 0.0),
                    "context": {
                        "profile": context_event.get("context_profile"),
                        "source": context_event.get("context_source"),
                        "files": context_event.get("context_files") or [],
                        "chars": context_event.get("context_chars"),
                    },
                    "harness": harness_metrics,
                },
            ),
            HarnessEvent(
                type="artifact.created",
                data={
                    "artifact_id": f"artifact_rlm_{getattr(result, 'run_id', '')}",
                    "kind": "rlm-trajectory",
                    "uri": trajectory_path.as_uri(),
                    "name": trajectory_path.name,
                    "media_type": "application/x-ndjson",
                    "metadata": {
                        "rlm_run_id": str(getattr(result, "run_id", "")),
                        "profile": settings.profile,
                        "context_profile": context_event.get("context_profile"),
                    },
                },
            ),
            HarnessEvent(
                type="model_result",
                data={
                    "provider": request.provider,
                    "model": request.model,
                    "runtime": "pure_rlm",
                    "rlm_run_id": str(getattr(result, "run_id", "")),
                    "iterations": int(getattr(result, "steps", 0) or 0),
                    "tool_calls_made": _subcall_count(usage, raw_events),
                    "usage": {
                        **_normalized_usage(usage),
                        "roles": usage.get("roles") or {},
                    },
                    "harness": harness_metrics,
                },
            ),
        ]
    )
    return events


def _normalized_usage(usage: dict[str, Any]) -> dict[str, int | None]:
    input_tokens = _optional_int(usage.get("prompt_tokens"))
    output_tokens = _optional_int(usage.get("completion_tokens"))
    total_tokens = None
    if input_tokens is not None or output_tokens is not None:
        total_tokens = int(input_tokens or 0) + int(output_tokens or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _subcall_count(usage: dict[str, Any], events: list[dict[str, Any]]) -> int:
    roles = usage.get("roles")
    if isinstance(roles, dict) and isinstance(roles.get("sub"), dict):
        return max(0, _int(roles["sub"].get("total_calls"), 0))
    return sum(
        _int(dict(item.get("role_usage") or {}).get("sub", {}).get("total_calls"), 0)
        for item in events
        if item.get("type") == "step"
    )


def _observation_success(value: Any) -> bool:
    if isinstance(value, dict) and "success" in value:
        return bool(value["success"])
    return True


def _split_model(provider: str, model: str) -> tuple[str, str]:
    normalized_provider = str(provider or "").strip()
    normalized_model = str(model or "").strip()
    for separator in (":", "/"):
        if separator not in normalized_model:
            continue
        prefix, remainder = normalized_model.split(separator, 1)
        if prefix and remainder and (not normalized_provider or prefix == normalized_provider):
            return normalized_provider or prefix, remainder
    return normalized_provider, normalized_model


def _choice(value: Any, supported: set[str]) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized not in supported:
        raise ValueError(f"Unsupported RLM Code option {value!r}; choose from {sorted(supported)}")
    return normalized


def _optional_choice(value: Any, supported: set[str]) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return _choice(value, supported)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError("RLM Code path/include/exclude settings must be strings or lists")


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _int(value: Any, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    return int(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    return int(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"Expected a boolean RLM Code option, got {value!r}")


def _resolve_path(workdir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else workdir / path


def _version_tuple(version: str) -> tuple[int, ...]:
    numeric = version.split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for value in numeric.split("."):
        digits = "".join(character for character in value if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


__all__ = [
    "MINIMUM_RLM_CODE_VERSION",
    "RLM_CODE_BACKEND_NAME",
    "RLMCodeHarnessBackend",
    "RLMCodeSettings",
    "installed_rlm_code_version",
    "rlm_code_installation_status",
]
