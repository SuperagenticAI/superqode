"""Workflow execution helpers for HarnessKernel."""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..agent.system_prompts import SystemPromptLevel
from ..workspace.change_summary import capture_workspace_changes, summarize_workspace_changes
from .events import HarnessEvent
from .kernel import HarnessKernel, HarnessRunResult
from .spec import WorkflowMode


@dataclass(frozen=True)
class WorkflowStep:
    """One prompt step in a harness workflow."""

    prompt: str
    id: str | None = None
    result: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowResult:
    """Result for a completed workflow."""

    mode: WorkflowMode
    results: tuple[HarnessRunResult, ...]
    run_id: str = ""
    session_id: str = ""
    failures: tuple[dict[str, Any], ...] = ()

    @property
    def content(self) -> str:
        if self.results:
            return self.results[-1].content
        if self.failures:
            return str(self.failures[-1].get("error", ""))
        return ""

    @property
    def data(self) -> Any | None:
        return self.results[-1].data if self.results else None


@dataclass(frozen=True)
class WorkflowProgress:
    """Progress update emitted while a workflow is running."""

    mode: WorkflowMode
    step_id: str
    status: str
    index: int
    total: int
    detail: str = ""
    result: HarnessRunResult | None = None


WorkflowProgressCallback = Callable[[WorkflowProgress], None]


@dataclass(frozen=True)
class WorkflowFailurePolicy:
    """Failure behavior for a workflow run."""

    continue_on_error: bool = False
    max_retries: int = 0
    fallback_prompt: str = ""
    fallback_step_id: str = "fallback"


class WorkflowStepFailed(RuntimeError):
    """A workflow step failed after retries/fallback."""

    def __init__(self, failure: dict[str, Any]) -> None:
        super().__init__(str(failure.get("error", "workflow step failed")))
        self.failure = failure


def workflow_steps_from_spec(
    spec,
    prompt: str,
) -> list[WorkflowStep]:
    """Build runnable workflow steps from a HarnessSpec and user task.

    This is intentionally deterministic so CLI, TUI, MCP, and Python callers
    turn the same portable spec into the same workflow prompts.
    """
    from .workflow_presets import apply_workflow_preset

    spec = apply_workflow_preset(spec)
    mode = spec.workflow.mode
    task = prompt.strip()
    agents = list(getattr(spec, "agents", ()) or ())

    def agent_step(agent) -> WorkflowStep:
        parts = []
        if getattr(agent, "role", ""):
            parts.append(f"Role: {agent.role}")
        if getattr(agent, "system_prompt", ""):
            parts.append(f"Instructions:\n{agent.system_prompt}")
        parts.append(f"Task:\n{task}")
        return WorkflowStep(
            "\n\n".join(parts),
            id=agent.id,
            metadata={
                "agent_id": agent.id,
                "role": getattr(agent, "role", ""),
                **({"agent_model": agent.model} if agent.model else {}),
                **({"agent_tools": list(agent.tools)} if agent.tools else {}),
                **({"agent_max_iterations": agent.max_iterations} if agent.max_iterations else {}),
                **(
                    {"agent_runtime": agent.config["runtime"]}
                    if agent.config.get("runtime")
                    else {}
                ),
                **(
                    {"agent_provider": agent.config["provider"]}
                    if agent.config.get("provider")
                    else {}
                ),
            },
        )

    if agents:
        steps = [agent_step(agent) for agent in agents]
        if mode == WorkflowMode.ROUTER and not (
            steps and str(steps[0].id or "").lower() == "router"
        ):
            router_prompt = f"Route this request to the best harness agent.\n\nTask:\n{task}"
            steps.insert(0, WorkflowStep(router_prompt, id="router"))
        if mode == WorkflowMode.EVALUATOR_OPTIMIZER:
            defaults = _default_evaluator_optimizer_steps(task)
            steps = (steps + defaults[len(steps) :])[:3]
        return steps

    if mode == WorkflowMode.EVALUATOR_OPTIMIZER:
        return _default_evaluator_optimizer_steps(task)
    if mode == WorkflowMode.ROUTER:
        return [
            WorkflowStep(
                f"Route this request to the best execution path.\n\nTask:\n{task}",
                id="router",
            ),
            WorkflowStep(task, id="default"),
        ]
    return [WorkflowStep(task, id="step-1")]


async def run_workflow(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    *,
    provider: str,
    model: str,
    working_directory: Path | None = None,
    runtime: str | None = None,
    sandbox_backend: str = "local",
    system_level: SystemPromptLevel | None = None,
    session_id: str | None = None,
    progress_callback: WorkflowProgressCallback | None = None,
) -> WorkflowResult:
    """Run steps according to the kernel spec's workflow mode."""
    workflow_session_id = session_id or f"workflow-{uuid.uuid4().hex[:8]}"
    runtime_name = runtime or kernel.spec.runtime.backend
    failure_policy = _failure_policy_from_config(kernel.spec.workflow.config)
    evidence_cwd = working_directory or Path.cwd()
    change_baseline = capture_workspace_changes(evidence_cwd)
    kernel.store.open_session(
        workflow_session_id,
        kernel.spec,
        metadata={"workflow": True, "provider": provider, "model": model},
    )
    workflow_run = kernel.store.start_run(
        session_id=workflow_session_id,
        spec=kernel.spec,
        provider=provider,
        model=model,
        runtime=runtime_name,
        prompt=_workflow_preview(steps),
        metadata={
            "workflow": True,
            "workflow_mode": kernel.spec.workflow.mode.value,
            "step_count": len(steps),
            "failure_policy": _failure_policy_to_dict(failure_policy),
        },
    )
    workflow_run_id = workflow_run.run_id
    _append_workflow_event(
        kernel,
        workflow_run_id,
        workflow_session_id,
        "workflow.run.started",
        {
            "mode": kernel.spec.workflow.mode.value,
            "preset": kernel.spec.workflow.preset,
            "steps": [_step_id(step, index) for index, step in enumerate(steps)],
            "provider": provider,
            "model": model,
            "runtime": runtime_name,
            "failure_policy": _failure_policy_to_dict(failure_policy),
        },
    )

    user_progress_callback = progress_callback

    def persist_progress(progress: WorkflowProgress) -> None:
        event_type = {
            "running": "workflow.step.started",
            "done": "workflow.step.completed",
            "failed": "workflow.step.failed",
        }.get(progress.status, "workflow.step.progress")
        data: dict[str, Any] = {
            "mode": progress.mode.value,
            "step_id": progress.step_id,
            "status": progress.status,
            "index": progress.index,
            "total": progress.total,
            "detail": progress.detail,
        }
        if progress.result is not None:
            data.update(
                {
                    "child_run_id": progress.result.run_id,
                    "child_session_id": progress.result.session_id,
                    "tool_calls_made": progress.result.tool_calls_made,
                    "iterations": progress.result.iterations,
                }
            )
        _append_workflow_event(kernel, workflow_run_id, workflow_session_id, event_type, data)
        if user_progress_callback is not None:
            user_progress_callback(progress)

    workflow_kwargs = {
        "provider": provider,
        "model": model,
        "working_directory": working_directory,
        "runtime": runtime,
        "sandbox_backend": sandbox_backend,
        "system_level": system_level,
        "session_id": workflow_session_id,
        "progress_callback": persist_progress,
        "failure_policy": failure_policy,
    }
    mode = kernel.spec.workflow.mode
    try:
        if mode == WorkflowMode.SINGLE:
            result = await _run_single(kernel, steps, **workflow_kwargs)
        elif mode == WorkflowMode.CHAIN:
            result = await _run_chain(kernel, steps, **workflow_kwargs)
        elif mode == WorkflowMode.PARALLEL:
            result = await _run_parallel(kernel, steps, **workflow_kwargs)
        elif mode == WorkflowMode.ROUTER:
            result = await _run_router(kernel, steps, **workflow_kwargs)
        elif mode == WorkflowMode.ORCHESTRATOR:
            result = await _run_orchestrator(kernel, steps, **workflow_kwargs)
        elif mode == WorkflowMode.EVALUATOR_OPTIMIZER:
            result = await _run_evaluator_optimizer(kernel, steps, **workflow_kwargs)
        else:
            raise NotImplementedError(f"Workflow mode is not implemented yet: {mode.value}")
    except Exception as exc:
        _append_workflow_event(
            kernel,
            workflow_run_id,
            workflow_session_id,
            "workflow.run.failed",
            {"mode": mode.value, "error": str(exc), "error_type": type(exc).__name__},
        )
        kernel.store.end_run(
            workflow_run_id,
            status="failed",
            metadata={"workflow": True, "error": str(exc), "error_type": type(exc).__name__},
        )
        raise

    final = WorkflowResult(
        mode=result.mode,
        results=result.results,
        failures=result.failures,
        run_id=workflow_run_id,
        session_id=workflow_session_id,
    )
    change_summary = summarize_workspace_changes(evidence_cwd, before=change_baseline)
    _append_workflow_event(
        kernel,
        workflow_run_id,
        workflow_session_id,
        "workspace.changes.captured",
        change_summary.to_dict(),
    )
    checks = await _run_checks_steps(
        kernel,
        run_id=workflow_run_id,
        session_id=workflow_session_id,
        cwd=evidence_cwd,
    )
    checks_failed = checks["status"] == "failed"
    workflow_failed = bool(final.failures)
    final_status = (
        "failed"
        if workflow_failed or (checks_failed and kernel.spec.checks.fail_on_error)
        else "succeeded"
    )
    _append_workflow_event(
        kernel,
        workflow_run_id,
        workflow_session_id,
        "workflow.result",
        {
            "status": final_status,
            "result_count": len(final.results),
            "content_preview": _preview_text(final.content),
            "failures": list(final.failures),
            "changed_files": change_summary.to_dict(),
            "checks": checks,
        },
    )
    _append_workflow_event(
        kernel,
        workflow_run_id,
        workflow_session_id,
        "workflow.run.completed",
        {
            "mode": mode.value,
            "status": final_status,
            "result_count": len(final.results),
            "result_run_ids": [item.run_id for item in final.results],
            "failures": list(final.failures),
            "changed_files": change_summary.to_dict(),
            "checks": checks,
        },
    )
    kernel.store.end_run(
        workflow_run_id,
        status=final_status,
        metadata={
            "workflow": True,
            "workflow_mode": mode.value,
            "result_count": len(final.results),
            "result_run_ids": [item.run_id for item in final.results],
            "failures": list(final.failures),
            "changed_files": change_summary.to_dict(),
            "checks": checks,
        },
    )
    return final


async def _run_single(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    if not steps:
        return WorkflowResult(mode=WorkflowMode.SINGLE, results=())
    session = await kernel.session(kwargs.get("session_id"))
    try:
        result = await _prompt_workflow_step(
            session,
            steps[0],
            kwargs,
            mode=WorkflowMode.SINGLE,
            index=0,
            total=1,
            fallback_id="single",
        )
    except WorkflowStepFailed as exc:
        if not _continue_on_error(kwargs):
            raise
        return WorkflowResult(mode=WorkflowMode.SINGLE, results=(), failures=(exc.failure,))
    return WorkflowResult(mode=WorkflowMode.SINGLE, results=(result,))


async def _run_chain(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    session = await kernel.session(kwargs.get("session_id"))
    results: list[HarnessRunResult] = []
    failures: list[dict[str, Any]] = []
    previous = ""
    for index, step in enumerate(steps):
        prompt = step.prompt
        if previous:
            prompt = f"{prompt}\n\nPrevious step result:\n{previous}"
        run_step = WorkflowStep(prompt, id=step.id, result=step.result, metadata=step.metadata)
        try:
            result = await _prompt_workflow_step(
                session,
                run_step,
                kwargs,
                mode=WorkflowMode.CHAIN,
                index=index,
                total=len(steps),
                fallback_id=f"chain-{index + 1}",
            )
        except WorkflowStepFailed as exc:
            failures.append(exc.failure)
            if not _continue_on_error(kwargs):
                raise
            previous = f"Previous step failed: {exc.failure.get('error', '')}"
            continue
        results.append(result)
        previous = result.content
    return WorkflowResult(mode=WorkflowMode.CHAIN, results=tuple(results), failures=tuple(failures))


async def _run_parallel(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    parallelism = max(kernel.spec.workflow.parallelism, 1)
    semaphore = asyncio.Semaphore(parallelism)

    async def run_one(index: int, step: WorkflowStep) -> HarnessRunResult:
        async with semaphore:
            session_suffix = step.id or str(index + 1)
            session = await kernel.session(
                f"{kwargs.get('session_id') or 'workflow'}:{session_suffix}"
            )
            return await _prompt_workflow_step(
                session,
                step,
                kwargs,
                mode=WorkflowMode.PARALLEL,
                index=index,
                total=len(steps),
                fallback_id=f"parallel-{index + 1}",
            )

    raw_results = await asyncio.gather(
        *(run_one(index, step) for index, step in enumerate(steps)),
        return_exceptions=_continue_on_error(kwargs),
    )
    results: list[HarnessRunResult] = []
    failures: list[dict[str, Any]] = []
    for item in raw_results:
        if isinstance(item, WorkflowStepFailed):
            failures.append(item.failure)
        elif isinstance(item, Exception):
            raise item
        else:
            results.append(item)
    return WorkflowResult(
        mode=WorkflowMode.PARALLEL, results=tuple(results), failures=tuple(failures)
    )


async def _run_router(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    if not steps:
        return WorkflowResult(mode=WorkflowMode.ROUTER, results=())
    route_to = kernel.spec.workflow.config.get("route_to")
    if route_to is not None:
        selected = _select_step(steps, str(route_to), default_index=0)
        result = await _run_routed_step(
            kernel,
            selected,
            kwargs,
            route_reason=f"route_to:{route_to}",
            index=0,
            total=1,
        )
        return WorkflowResult(mode=WorkflowMode.ROUTER, results=(result,))
    if len(steps) == 1:
        result = await _run_routed_step(
            kernel,
            steps[0],
            kwargs,
            route_reason="single",
            index=0,
            total=1,
        )
        return WorkflowResult(mode=WorkflowMode.ROUTER, results=(result,))

    router = steps[0]
    candidates = steps[1:]
    session = await kernel.session(kwargs.get("session_id"))
    router_step = WorkflowStep(
        _router_prompt(router.prompt, candidates),
        id=router.id,
        result=router.result,
        metadata=router.metadata,
    )
    router_result = await _prompt_workflow_step(
        session,
        router_step,
        kwargs,
        mode=WorkflowMode.ROUTER,
        index=0,
        total=2,
        fallback_id="router",
    )
    selected = _select_step(candidates, router_result.content, default_index=0)
    routed_result = await _run_routed_step(
        kernel,
        selected,
        kwargs,
        route_reason=f"router_output:{router_result.content}",
        index=1,
        total=2,
    )
    return WorkflowResult(mode=WorkflowMode.ROUTER, results=(router_result, routed_result))


async def _run_orchestrator(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    if not steps:
        return WorkflowResult(mode=WorkflowMode.ORCHESTRATOR, results=())
    parallel = await _run_parallel(kernel, steps, **kwargs)
    if parallel.failures and not parallel.results:
        return WorkflowResult(
            mode=WorkflowMode.ORCHESTRATOR,
            results=(),
            failures=parallel.failures,
        )
    synthesis_prompt = str(
        kernel.spec.workflow.config.get(
            "synthesis_prompt",
            "Synthesize the worker results into one concise final answer.",
        )
    )
    synthesis_input = synthesis_prompt + "\n\nWorker results:\n" + _format_results(parallel.results)
    session = await kernel.session(f"{kwargs.get('session_id') or 'orchestrator'}:synthesis")
    synthesis = await _prompt_workflow_step(
        session,
        WorkflowStep(synthesis_input, id="synthesis"),
        kwargs,
        mode=WorkflowMode.ORCHESTRATOR,
        index=len(steps),
        total=len(steps) + 1,
        fallback_id="synthesis",
    )
    return WorkflowResult(
        mode=WorkflowMode.ORCHESTRATOR,
        results=(*parallel.results, synthesis),
        failures=parallel.failures,
    )


async def _run_evaluator_optimizer(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    if not steps:
        return WorkflowResult(mode=WorkflowMode.EVALUATOR_OPTIMIZER, results=())
    session = await kernel.session(kwargs.get("session_id"))
    candidate_step = steps[0]
    candidate = await _prompt_workflow_step(
        session,
        candidate_step,
        kwargs,
        mode=WorkflowMode.EVALUATOR_OPTIMIZER,
        index=0,
        total=min(max(len(steps), 2), 3),
        fallback_id="candidate",
    )
    evaluator_step = steps[1] if len(steps) > 1 else WorkflowStep("Evaluate the candidate result.")
    evaluator_prompt = (
        f"{evaluator_step.prompt}\n\nCandidate result:\n{candidate.content}\n\n"
        "Respond with PASS if the candidate is acceptable; otherwise explain what to improve."
    )
    evaluation = await _prompt_workflow_step(
        session,
        WorkflowStep(
            evaluator_prompt,
            id=evaluator_step.id,
            result=evaluator_step.result,
            metadata=evaluator_step.metadata,
        ),
        kwargs,
        mode=WorkflowMode.EVALUATOR_OPTIMIZER,
        index=1,
        total=min(max(len(steps), 2), 3),
        fallback_id="evaluator",
    )
    if _evaluation_passed(evaluation.content) or len(steps) < 3:
        return WorkflowResult(
            mode=WorkflowMode.EVALUATOR_OPTIMIZER,
            results=(candidate, evaluation),
        )
    optimizer_step = steps[2]
    optimizer_prompt = (
        f"{optimizer_step.prompt}\n\nCandidate result:\n{candidate.content}\n\n"
        f"Evaluator feedback:\n{evaluation.content}"
    )
    optimized = await _prompt_workflow_step(
        session,
        WorkflowStep(
            optimizer_prompt,
            id=optimizer_step.id,
            result=optimizer_step.result,
            metadata=optimizer_step.metadata,
        ),
        kwargs,
        mode=WorkflowMode.EVALUATOR_OPTIMIZER,
        index=2,
        total=3,
        fallback_id="optimizer",
    )
    return WorkflowResult(
        mode=WorkflowMode.EVALUATOR_OPTIMIZER,
        results=(candidate, evaluation, optimized),
    )


async def _run_routed_step(
    kernel: HarnessKernel,
    step: WorkflowStep,
    kwargs: dict[str, Any],
    *,
    route_reason: str,
    index: int,
    total: int,
) -> HarnessRunResult:
    session = await kernel.session(
        f"{kwargs.get('session_id') or 'router'}:{step.id or 'selected'}"
    )
    return await _prompt_workflow_step(
        session,
        WorkflowStep(
            step.prompt,
            id=step.id,
            result=step.result,
            metadata={"route_reason": route_reason, **step.metadata},
        ),
        kwargs,
        mode=WorkflowMode.ROUTER,
        index=index,
        total=total,
        fallback_id="routed",
    )


async def _prompt_workflow_step(
    session,
    step: WorkflowStep,
    kwargs: dict[str, Any],
    *,
    mode: WorkflowMode,
    index: int,
    total: int,
    fallback_id: str,
) -> HarnessRunResult:
    step_id = step.id or fallback_id
    policy = _failure_policy(kwargs)
    _emit_progress(
        kwargs,
        WorkflowProgress(
            mode=mode,
            step_id=step_id,
            status="running",
            index=index,
            total=total,
        ),
    )
    attempts = policy.max_retries + 1
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await _run_step_prompt(session, step, kwargs, step_id=step_id)
            break
        except Exception as exc:
            last_exc = exc
            if attempt <= policy.max_retries:
                _emit_progress(
                    kwargs,
                    WorkflowProgress(
                        mode=mode,
                        step_id=step_id,
                        status="retrying",
                        index=index,
                        total=total,
                        detail=f"attempt {attempt} failed: {exc}",
                    ),
                )
                continue
    else:
        if policy.fallback_prompt:
            fallback = WorkflowStep(
                _format_fallback_prompt(policy.fallback_prompt, step, last_exc),
                id=policy.fallback_step_id,
                result=step.result,
                metadata={
                    **step.metadata,
                    "fallback_for": step_id,
                    "fallback_error": str(last_exc or ""),
                },
            )
            try:
                result = await _run_step_prompt(
                    session, fallback, kwargs, step_id=fallback.id or "fallback"
                )
                _emit_progress(
                    kwargs,
                    WorkflowProgress(
                        mode=mode,
                        step_id=step_id,
                        status="fallback",
                        index=index,
                        total=total,
                        detail=f"used fallback step {fallback.id}",
                        result=result,
                    ),
                )
            except Exception as fallback_exc:
                failure = _step_failure(step_id, fallback_exc, retries=policy.max_retries)
                _emit_progress(
                    kwargs,
                    WorkflowProgress(
                        mode=mode,
                        step_id=step_id,
                        status="failed",
                        index=index,
                        total=total,
                        detail=str(fallback_exc),
                    ),
                )
                raise WorkflowStepFailed(failure) from fallback_exc
        else:
            failure = _step_failure(step_id, last_exc, retries=policy.max_retries)
            _emit_progress(
                kwargs,
                WorkflowProgress(
                    mode=mode,
                    step_id=step_id,
                    status="failed",
                    index=index,
                    total=total,
                    detail=str(last_exc or "workflow step failed"),
                ),
            )
            raise WorkflowStepFailed(failure) from last_exc
    _emit_progress(
        kwargs,
        WorkflowProgress(
            mode=mode,
            step_id=step_id,
            status="done",
            index=index,
            total=total,
            detail=_result_detail(result),
            result=result,
        ),
    )
    return result


async def _run_step_prompt(session, step: WorkflowStep, kwargs: dict[str, Any], *, step_id: str):
    step_kwargs = _kwargs_for_step(kwargs, step)
    return await session.prompt(
        step.prompt,
        provider=step_kwargs["provider"],
        model=step_kwargs["model"],
        working_directory=kwargs.get("working_directory"),
        runtime=step_kwargs.get("runtime"),
        sandbox_backend=kwargs.get("sandbox_backend", "local"),
        system_level=kwargs.get("system_level"),
        result=step.result,
        metadata={"workflow_step": step_id, **step.metadata},
    )


def _kwargs_for_step(kwargs: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
    """Resolve provider/model/runtime overrides for one workflow step."""
    out = dict(kwargs)
    if step.metadata.get("agent_provider"):
        out["provider"] = step.metadata["agent_provider"]
    if step.metadata.get("agent_model"):
        model_ref = str(step.metadata["agent_model"])
        if "/" in model_ref and not step.metadata.get("agent_provider"):
            provider, model = model_ref.split("/", 1)
            out["provider"] = provider
            out["model"] = model
        else:
            out["model"] = model_ref
    if step.metadata.get("agent_runtime"):
        out["runtime"] = step.metadata["agent_runtime"]
    return out


def _failure_policy(kwargs: dict[str, Any]) -> WorkflowFailurePolicy:
    policy = kwargs.get("failure_policy")
    if isinstance(policy, WorkflowFailurePolicy):
        return policy
    return WorkflowFailurePolicy()


def _continue_on_error(kwargs: dict[str, Any]) -> bool:
    return _failure_policy(kwargs).continue_on_error


def _failure_policy_from_config(config: dict[str, Any]) -> WorkflowFailurePolicy:
    raw = config.get("failure_policy")
    data = raw if isinstance(raw, dict) else config
    return WorkflowFailurePolicy(
        continue_on_error=_as_bool(data.get("continue_on_error", False)),
        max_retries=max(int(data.get("max_retries", data.get("retries", 0)) or 0), 0),
        fallback_prompt=str(data.get("fallback_prompt", "") or ""),
        fallback_step_id=str(data.get("fallback_step_id", "fallback") or "fallback"),
    )


def _failure_policy_to_dict(policy: WorkflowFailurePolicy) -> dict[str, Any]:
    return {
        "continue_on_error": policy.continue_on_error,
        "max_retries": policy.max_retries,
        "fallback_prompt": bool(policy.fallback_prompt),
        "fallback_step_id": policy.fallback_step_id,
    }


def _step_failure(step_id: str, exc: Exception | None, *, retries: int) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "error": str(exc or "workflow step failed"),
        "error_type": type(exc).__name__ if exc is not None else "WorkflowStepFailed",
        "retries": retries,
    }


def _format_fallback_prompt(prompt: str, step: WorkflowStep, exc: Exception | None) -> str:
    return (
        f"{prompt}\n\n"
        f"Failed step: {step.id or 'step'}\n"
        f"Error: {exc}\n\n"
        f"Original prompt:\n{step.prompt}"
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _emit_progress(kwargs: dict[str, Any], progress: WorkflowProgress) -> None:
    callback = kwargs.get("progress_callback")
    if callback is not None:
        callback(progress)


def _append_workflow_event(
    kernel: HarnessKernel,
    run_id: str,
    session_id: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    event = HarnessEvent(type=event_type, data=data, session_id=session_id, run_id=run_id)
    kernel.store.append_event(run_id, event)
    kernel.emit(event)


def _workflow_preview(steps: list[WorkflowStep] | tuple[WorkflowStep, ...]) -> str:
    if not steps:
        return "workflow"
    return "\n".join(f"{_step_id(step, index)}: {step.prompt}" for index, step in enumerate(steps))


def _step_id(step: WorkflowStep, index: int) -> str:
    return step.id or f"step-{index + 1}"


async def _run_checks_steps(
    kernel: HarnessKernel,
    *,
    run_id: str,
    session_id: str,
    cwd: Path,
) -> dict[str, Any]:
    checks = kernel.spec.checks
    if not checks.enabled:
        return {"enabled": False, "status": "skipped", "steps": []}
    steps = [step for step in checks.custom_steps if step.enabled]
    if not steps:
        return {"enabled": True, "status": "skipped", "steps": []}

    results: list[dict[str, Any]] = []
    for step in steps:
        _append_workflow_event(
            kernel,
            run_id,
            session_id,
            "checks.step.started",
            {"name": step.name, "command": step.command, "timeout": step.timeout},
        )
        result = await asyncio.to_thread(_run_checks_command, step.command, cwd, step.timeout)
        step_result = {
            "name": step.name,
            "command": step.command,
            "timeout": step.timeout,
            **result,
        }
        results.append(step_result)
        _append_workflow_event(
            kernel,
            run_id,
            session_id,
            ("checks.step.completed" if result["status"] == "passed" else "checks.step.failed"),
            step_result,
        )
    status = "passed" if all(item["status"] == "passed" for item in results) else "failed"
    return {"enabled": True, "status": status, "steps": results}


def _run_checks_command(command: str, cwd: Path, timeout: int) -> dict[str, Any]:
    try:
        args = shlex.split(command)
        if not args:
            return {"status": "failed", "returncode": None, "stdout": "", "stderr": "empty command"}
        completed = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "returncode": None,
            "stdout": _preview_text(exc.stdout or ""),
            "stderr": f"timed out after {timeout}s",
        }
    except (OSError, ValueError) as exc:
        return {
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": _preview_text(completed.stdout),
        "stderr": _preview_text(completed.stderr),
    }


def _preview_text(value: str, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _result_detail(result: HarnessRunResult) -> str:
    parts = []
    if result.tool_calls_made:
        parts.append(f"{result.tool_calls_made} tool call(s)")
    if result.iterations:
        parts.append(f"{result.iterations} iteration(s)")
    return ", ".join(parts)


def _router_prompt(prompt: str, candidates: list[WorkflowStep] | tuple[WorkflowStep, ...]) -> str:
    options = "\n".join(
        f"- {step.id or index + 1}: {step.prompt}" for index, step in enumerate(candidates)
    )
    return (
        f"{prompt}\n\nChoose exactly one route from these options. "
        "Return only the route id or number.\n"
        f"{options}"
    )


def _select_step(
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    decision: str,
    *,
    default_index: int,
) -> WorkflowStep:
    normalized = decision.strip().lower()
    for index, step in enumerate(steps):
        candidates = {str(index + 1), (step.id or "").strip().lower()}
        candidates.discard("")
        if normalized in candidates:
            return step
        if any(f"route:{candidate}" in normalized for candidate in candidates):
            return step
    for step in steps:
        if step.id and step.id.lower() in normalized:
            return step
    return steps[min(default_index, len(steps) - 1)]


def _format_results(results: tuple[HarnessRunResult, ...]) -> str:
    return "\n\n".join(f"[{index + 1}] {result.content}" for index, result in enumerate(results))


def _evaluation_passed(content: str) -> bool:
    normalized = content.strip().lower()
    return normalized.startswith("pass") or "approved" in normalized or "acceptable" in normalized


def _default_evaluator_optimizer_steps(prompt: str) -> list[WorkflowStep]:
    return [
        WorkflowStep(f"Create a candidate solution.\n\nTask:\n{prompt}", id="candidate"),
        WorkflowStep("Evaluate the candidate for correctness and completeness.", id="evaluator"),
        WorkflowStep("Improve the candidate using the evaluator feedback.", id="optimizer"),
    ]
