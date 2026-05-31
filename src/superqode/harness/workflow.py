"""Workflow execution helpers for HarnessKernel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..agent.system_prompts import SystemPromptLevel
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

    @property
    def content(self) -> str:
        return self.results[-1].content if self.results else ""

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
    mode = kernel.spec.workflow.mode
    if mode == WorkflowMode.SINGLE:
        return await _run_single(
            kernel,
            steps,
            provider=provider,
            model=model,
            working_directory=working_directory,
            runtime=runtime,
            sandbox_backend=sandbox_backend,
            system_level=system_level,
            session_id=session_id,
            progress_callback=progress_callback,
        )
    if mode == WorkflowMode.CHAIN:
        return await _run_chain(
            kernel,
            steps,
            provider=provider,
            model=model,
            working_directory=working_directory,
            runtime=runtime,
            sandbox_backend=sandbox_backend,
            system_level=system_level,
            session_id=session_id,
            progress_callback=progress_callback,
        )
    if mode == WorkflowMode.PARALLEL:
        return await _run_parallel(
            kernel,
            steps,
            provider=provider,
            model=model,
            working_directory=working_directory,
            runtime=runtime,
            sandbox_backend=sandbox_backend,
            system_level=system_level,
            session_id=session_id,
            progress_callback=progress_callback,
        )
    if mode == WorkflowMode.ROUTER:
        return await _run_router(
            kernel,
            steps,
            provider=provider,
            model=model,
            working_directory=working_directory,
            runtime=runtime,
            sandbox_backend=sandbox_backend,
            system_level=system_level,
            session_id=session_id,
            progress_callback=progress_callback,
        )
    if mode == WorkflowMode.ORCHESTRATOR:
        return await _run_orchestrator(
            kernel,
            steps,
            provider=provider,
            model=model,
            working_directory=working_directory,
            runtime=runtime,
            sandbox_backend=sandbox_backend,
            system_level=system_level,
            session_id=session_id,
            progress_callback=progress_callback,
        )
    if mode == WorkflowMode.EVALUATOR_OPTIMIZER:
        return await _run_evaluator_optimizer(
            kernel,
            steps,
            provider=provider,
            model=model,
            working_directory=working_directory,
            runtime=runtime,
            sandbox_backend=sandbox_backend,
            system_level=system_level,
            session_id=session_id,
            progress_callback=progress_callback,
        )
    raise NotImplementedError(f"Workflow mode is not implemented yet: {mode.value}")


async def _run_single(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    if not steps:
        return WorkflowResult(mode=WorkflowMode.SINGLE, results=())
    session = await kernel.session(kwargs.get("session_id"))
    result = await _prompt_workflow_step(
        session,
        steps[0],
        kwargs,
        mode=WorkflowMode.SINGLE,
        index=0,
        total=1,
        fallback_id="single",
    )
    return WorkflowResult(mode=WorkflowMode.SINGLE, results=(result,))


async def _run_chain(
    kernel: HarnessKernel,
    steps: list[WorkflowStep] | tuple[WorkflowStep, ...],
    **kwargs: Any,
) -> WorkflowResult:
    session = await kernel.session(kwargs.get("session_id"))
    results: list[HarnessRunResult] = []
    previous = ""
    for index, step in enumerate(steps):
        prompt = step.prompt
        if previous:
            prompt = f"{prompt}\n\nPrevious step result:\n{previous}"
        run_step = WorkflowStep(prompt, id=step.id, result=step.result, metadata=step.metadata)
        result = await _prompt_workflow_step(
            session,
            run_step,
            kwargs,
            mode=WorkflowMode.CHAIN,
            index=index,
            total=len(steps),
            fallback_id=f"chain-{index + 1}",
        )
        results.append(result)
        previous = result.content
    return WorkflowResult(mode=WorkflowMode.CHAIN, results=tuple(results))


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

    results = await asyncio.gather(*(run_one(index, step) for index, step in enumerate(steps)))
    return WorkflowResult(mode=WorkflowMode.PARALLEL, results=tuple(results))


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
    return WorkflowResult(mode=WorkflowMode.ORCHESTRATOR, results=(*parallel.results, synthesis))


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
    try:
        result = await session.prompt(
            step.prompt,
            provider=kwargs["provider"],
            model=kwargs["model"],
            working_directory=kwargs.get("working_directory"),
            runtime=kwargs.get("runtime"),
            sandbox_backend=kwargs.get("sandbox_backend", "local"),
            system_level=kwargs.get("system_level"),
            result=step.result,
            metadata={"workflow_step": step_id, **step.metadata},
        )
    except Exception as exc:
        _emit_progress(
            kwargs,
            WorkflowProgress(
                mode=mode,
                step_id=step_id,
                status="failed",
                index=index,
                total=total,
                detail=str(exc),
            ),
        )
        raise
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


def _emit_progress(kwargs: dict[str, Any], progress: WorkflowProgress) -> None:
    callback = kwargs.get("progress_callback")
    if callback is not None:
        callback(progress)


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
