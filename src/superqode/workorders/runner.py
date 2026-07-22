"""Execute leased WorkOrder tasks through existing SuperQode harnesses."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from superqode.providers.model_specs import split_provider_model_ref
from superqode.workspace.change_summary import (
    WorkspaceChangeSnapshot,
    capture_workspace_changes,
    summarize_workspace_changes,
)

from .models import WorkOrder, WorkOrderStatus, WorkOrderTask, WorkTaskRole
from .store import WorkOrderStore
from .usage import usage_from_result


@dataclass(frozen=True)
class WorkTaskExecution:
    """Result of one scheduler claim and harness execution."""

    work_order_id: str
    task_id: str
    status: str
    worker_id: str
    run_id: str = ""
    session_id: str = ""
    content: str = ""
    error: str = ""
    usage: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "task_id": self.task_id,
            "status": self.status,
            "worker_id": self.worker_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "content": self.content,
            "error": self.error,
            "usage": dict(self.usage or {}),
            "policy": dict(self.policy or {}),
        }


@dataclass(frozen=True)
class WorkTaskWorkspace:
    """Repository location allocated to one worker task."""

    path: Path
    isolation: str
    base_commit: str = ""
    baseline_tree: str = ""
    source_tree: str = ""
    workspace_id: str = ""
    scope: str = "task"
    integration_path: Path | None = None


class _WorkOrderCancelled(Exception):
    """Raised after the durable WorkOrder cancellation signal is observed."""


_PATCH_ROLES = frozenset({WorkTaskRole.IMPLEMENTER, WorkTaskRole.SYNTHESIZER, WorkTaskRole.CUSTOM})
_EVIDENCE_ONLY_ROLES = frozenset(
    {WorkTaskRole.INVESTIGATOR, WorkTaskRole.REVIEWER, WorkTaskRole.TESTER}
)


async def run_next_task(
    store: WorkOrderStore,
    *,
    work_order_id: str = "",
    worker_id: str = "",
    lease_seconds: int = 300,
    provider: str = "",
    model: str = "",
    runtime: str = "",
    sandbox: str = "",
    isolation: str = "auto",
    retry: bool = True,
) -> WorkTaskExecution | None:
    """Claim and execute one dependency-ready WorkOrder task."""
    worker = worker_id.strip() or f"local-{os.getpid()}"
    claimed = store.claim_next_task(
        worker_id=worker,
        reference=work_order_id,
        lease_seconds=lease_seconds,
    )
    if claimed is None:
        return None
    order, task = claimed
    return await execute_claimed_task(
        store,
        order=order,
        task=task,
        worker_id=worker,
        lease_seconds=lease_seconds,
        provider=provider,
        model=model,
        runtime=runtime,
        sandbox=sandbox,
        isolation=isolation,
        retry=retry,
    )


async def execute_claimed_task(
    store: WorkOrderStore,
    *,
    order: WorkOrder,
    task: WorkOrderTask,
    worker_id: str,
    lease_seconds: int = 300,
    provider: str = "",
    model: str = "",
    runtime: str = "",
    sandbox: str = "",
    isolation: str = "auto",
    retry: bool = True,
) -> WorkTaskExecution:
    """Run a previously claimed task and close its lease with evidence."""
    stop_heartbeat = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat_loop(
            store,
            order.work_order_id,
            task.task_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            stop=stop_heartbeat,
        )
    )
    workspace: WorkTaskWorkspace | None = None
    baseline = WorkspaceChangeSnapshot()
    usage_payload: dict[str, Any] = {}
    policy_payload: dict[str, Any] = {}
    try:
        workspace = await _prepare_task_workspace(store, order, task, isolation=isolation)
        baseline = await asyncio.to_thread(capture_workspace_changes, workspace.path)
        store.add_artifact(
            order.work_order_id,
            kind="workspace",
            task_id=task.task_id,
            path=str(workspace.path),
            metadata={
                "isolation": workspace.isolation,
                "base_commit": workspace.base_commit,
                "baseline_tree": workspace.baseline_tree,
                "source_tree": workspace.source_tree,
                "workspace_id": workspace.workspace_id,
                "scope": workspace.scope,
                "integration_workspace": str(workspace.integration_path or ""),
            },
            actor=worker_id,
        )
        timeout = _remaining_time_budget(order)
        execution = _execute_harness_task(
            order,
            task,
            provider=provider,
            model=model,
            runtime=runtime,
            sandbox=sandbox,
            working_directory=workspace.path,
        )
        execution_started = time.monotonic()
        result = await _await_harness_or_cancellation(
            store,
            order.work_order_id,
            execution,
            timeout=timeout,
        )
        latency_ms = int((time.monotonic() - execution_started) * 1000)
        status = str(result.get("stopped_reason") or "complete")
        run_id = str(result.get("run_id") or "")
        session_id = str(result.get("session_id") or "")
        content = str(result.get("content") or "")
        usage = usage_from_result(result, task=task, latency_ms=latency_ms)
        usage_payload = usage.to_dict()
        _, policy_decision = store.record_usage(
            order.work_order_id,
            usage,
            actor=worker_id,
        )
        policy_payload = policy_decision.to_dict()
        await _record_workspace_evidence(
            store,
            order,
            task,
            worker_id=worker_id,
            workspace=workspace,
            baseline=baseline,
        )
        if not policy_decision.allowed:
            store.block_task(
                order.work_order_id,
                task.task_id,
                worker_id=worker_id,
                reason=policy_decision.reason,
                run_id=run_id,
                session_id=session_id,
            )
            return WorkTaskExecution(
                work_order_id=order.work_order_id,
                task_id=task.task_id,
                status="blocked",
                worker_id=worker_id,
                run_id=run_id,
                session_id=session_id,
                content=content,
                error=policy_decision.reason,
                usage=usage_payload,
                policy=policy_payload,
            )
        if status == "needs_approval":
            store.add_artifact(
                order.work_order_id,
                kind="agent_result",
                task_id=task.task_id,
                content=content,
                metadata={"run_id": run_id, "session_id": session_id, "status": status},
                actor=worker_id,
            )
            store.block_task(
                order.work_order_id,
                task.task_id,
                worker_id=worker_id,
                reason="Harness run needs approval",
                run_id=run_id,
                session_id=session_id,
            )
            return WorkTaskExecution(
                work_order_id=order.work_order_id,
                task_id=task.task_id,
                status="blocked",
                worker_id=worker_id,
                run_id=run_id,
                session_id=session_id,
                content=content,
                error="Harness run needs approval",
                usage=usage_payload,
                policy=policy_payload,
            )
        if status == "cancelled":
            error = str(result.get("error") or "Harness run was cancelled")
            if store.get(order.work_order_id).status != WorkOrderStatus.CANCELLED:
                store.cancel(order.work_order_id, actor=worker_id, reason=error)
            return WorkTaskExecution(
                work_order_id=order.work_order_id,
                task_id=task.task_id,
                status="cancelled",
                worker_id=worker_id,
                run_id=run_id,
                session_id=session_id,
                content=content,
                error=error,
                usage=usage_payload,
                policy=policy_payload,
            )
        if status in {"error", "failed"}:
            error = str(result.get("error") or f"Harness stopped with {status}")
            store.fail_task(
                order.work_order_id,
                task.task_id,
                worker_id=worker_id,
                error=error,
                retry=retry,
                run_id=run_id,
            )
            return WorkTaskExecution(
                work_order_id=order.work_order_id,
                task_id=task.task_id,
                status="failed",
                worker_id=worker_id,
                run_id=run_id,
                session_id=session_id,
                content=content,
                error=error,
                usage=usage_payload,
                policy=policy_payload,
            )
        store.add_artifact(
            order.work_order_id,
            kind="agent_result",
            task_id=task.task_id,
            content=content,
            metadata={
                "run_id": run_id,
                "session_id": session_id,
                "harness": result.get("harness") or task.harness or order.harness,
                "provider": result.get("provider") or "",
                "model": result.get("model") or "",
                "runtime": result.get("runtime") or "",
                "workspace": str(workspace.path),
                "isolation": workspace.isolation,
                "role": task.role.value,
            },
            actor=worker_id,
        )
        role_error, role_metadata = await _enforce_role_contract(
            store,
            order,
            task,
            workspace=workspace,
            content=content,
            result=result,
            worker_id=worker_id,
        )
        if role_error:
            store.block_task(
                order.work_order_id,
                task.task_id,
                worker_id=worker_id,
                reason=role_error,
                run_id=run_id,
                session_id=session_id,
            )
            return WorkTaskExecution(
                work_order_id=order.work_order_id,
                task_id=task.task_id,
                status="blocked",
                worker_id=worker_id,
                run_id=run_id,
                session_id=session_id,
                content=content,
                error=role_error,
                usage=usage_payload,
                policy=policy_payload,
            )
        integration_metadata: dict[str, Any] = {}
        if (
            task.role in _PATCH_ROLES
            and workspace.isolation == "worktree"
            and workspace.scope == "task"
        ):
            from .integration import integrate_task_workspace

            integration = await asyncio.to_thread(
                integrate_task_workspace,
                store,
                order.work_order_id,
                task_id=task.task_id,
                task_workspace=workspace.path,
                baseline_tree=workspace.baseline_tree,
                actor=worker_id,
            )
            integration_metadata = integration.to_dict()
            if integration.conflicts:
                reason = "Task patch conflicts during integration: " + ", ".join(
                    integration.conflicts
                )
                store.block_task(
                    order.work_order_id,
                    task.task_id,
                    worker_id=worker_id,
                    reason=reason,
                    run_id=run_id,
                    session_id=session_id,
                )
                return WorkTaskExecution(
                    work_order_id=order.work_order_id,
                    task_id=task.task_id,
                    status="blocked",
                    worker_id=worker_id,
                    run_id=run_id,
                    session_id=session_id,
                    content=content,
                    error=reason,
                    usage=usage_payload,
                    policy=policy_payload,
                )
        store.complete_task(
            order.work_order_id,
            task.task_id,
            worker_id=worker_id,
            run_id=run_id,
            session_id=session_id,
            metadata={
                "harness_execution": result,
                "task_integration": integration_metadata,
                "role_result": role_metadata,
            },
        )
        return WorkTaskExecution(
            work_order_id=order.work_order_id,
            task_id=task.task_id,
            status="succeeded",
            worker_id=worker_id,
            run_id=run_id,
            session_id=session_id,
            content=content,
            usage=usage_payload,
            policy=policy_payload,
        )
    except _WorkOrderCancelled:
        await _record_workspace_evidence(
            store,
            order,
            task,
            worker_id=worker_id,
            workspace=workspace,
            baseline=baseline,
        )
        return WorkTaskExecution(
            work_order_id=order.work_order_id,
            task_id=task.task_id,
            status="cancelled",
            worker_id=worker_id,
            error="WorkOrder was cancelled",
            usage=usage_payload,
            policy=policy_payload,
        )
    except asyncio.TimeoutError:
        error = "WorkOrder time budget expired during harness execution"
        await _record_workspace_evidence(
            store,
            order,
            task,
            worker_id=worker_id,
            workspace=workspace,
            baseline=baseline,
        )
        store.fail_task(
            order.work_order_id,
            task.task_id,
            worker_id=worker_id,
            error=error,
            retry=False,
        )
        return WorkTaskExecution(
            work_order_id=order.work_order_id,
            task_id=task.task_id,
            status="failed",
            worker_id=worker_id,
            error=error,
            usage=usage_payload,
            policy=policy_payload,
        )
    except Exception as exc:
        error = str(exc)
        await _record_workspace_evidence(
            store,
            order,
            task,
            worker_id=worker_id,
            workspace=workspace,
            baseline=baseline,
        )
        store.fail_task(
            order.work_order_id,
            task.task_id,
            worker_id=worker_id,
            error=error,
            retry=retry,
        )
        return WorkTaskExecution(
            work_order_id=order.work_order_id,
            task_id=task.task_id,
            status="failed",
            worker_id=worker_id,
            error=error,
            usage=usage_payload,
            policy=policy_payload,
        )
    finally:
        stop_heartbeat.set()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat


async def run_until_idle(
    store: WorkOrderStore,
    *,
    work_order_id: str,
    worker_id: str = "",
    max_tasks: int = 0,
    lease_seconds: int = 300,
    provider: str = "",
    model: str = "",
    runtime: str = "",
    sandbox: str = "",
    isolation: str = "auto",
    retry: bool = True,
) -> list[WorkTaskExecution]:
    """Execute dependency-ready tasks in bounded parallel batches until a gate."""
    results: list[WorkTaskExecution] = []
    while max_tasks <= 0 or len(results) < max_tasks:
        current = store.get(work_order_id)
        if current.status in {
            WorkOrderStatus.REVIEWING,
            WorkOrderStatus.CHECKING,
            WorkOrderStatus.READY_TO_MERGE,
            WorkOrderStatus.MERGING,
            WorkOrderStatus.BLOCKED,
            WorkOrderStatus.ACCEPTED,
            WorkOrderStatus.MERGED,
            WorkOrderStatus.ROLLED_BACK,
            WorkOrderStatus.REJECTED,
            WorkOrderStatus.FAILED,
            WorkOrderStatus.CANCELLED,
        }:
            break
        width = max(1, current.budget.max_workers or 1)
        if max_tasks > 0:
            width = min(width, max_tasks - len(results))
        base_worker = worker_id.strip() or f"local-{os.getpid()}"
        batch = await asyncio.gather(
            *(
                run_next_task(
                    store,
                    work_order_id=work_order_id,
                    worker_id=(base_worker if width == 1 else f"{base_worker}-{slot + 1}"),
                    lease_seconds=lease_seconds,
                    provider=provider,
                    model=model,
                    runtime=runtime,
                    sandbox=sandbox,
                    isolation=isolation,
                    retry=retry,
                )
                for slot in range(width)
            )
        )
        completed = [result for result in batch if result is not None]
        if not completed:
            break
        results.extend(completed)
        if any(result.status == "blocked" for result in completed):
            break
    return results


async def _execute_harness_task(
    order: WorkOrder,
    task: WorkOrderTask,
    *,
    provider: str,
    model: str,
    runtime: str,
    sandbox: str,
    working_directory: Path,
) -> dict[str, Any]:
    from superqode.harness import (
        WorkflowMode,
        create_harness_store,
        init_harness,
        resolve_harness,
        run_workflow,
        workflow_steps_from_spec,
    )

    repository = working_directory.resolve()
    if not repository.is_dir():
        raise ValueError(f"WorkOrder workspace does not exist: {repository}")
    harness_ref = task.harness or order.harness
    entry = resolve_harness(harness_ref, root=repository)
    promotion_selection: dict[str, Any] = {}
    if entry.path is not None:
        from superqode.harness.promotion import select_harness_promotion

        promotion_selection = select_harness_promotion(
            entry.path,
            key=order.work_order_id,
            registry_path=repository / ".superqode" / "harnesses" / "promotions.jsonl",
        )
        selected_spec = str(promotion_selection.get("selected_spec") or "")
        if selected_spec and Path(selected_spec).resolve() != entry.path.resolve():
            entry = resolve_harness(selected_spec, root=repository)
    spec = entry.spec
    from superqode.governance import load_governance

    governance = load_governance(
        repository,
        harness_spec=spec,
        work_order=order,
        secure_defaults=True,
    )
    primary = split_provider_model_ref(spec.model_policy.primary)
    resolved_provider = (
        provider.strip()
        or task.provider
        or primary.provider
        or os.getenv("SUPERQODE_PROVIDER", "")
        or "openai"
    )
    resolved_model = (
        model.strip()
        or task.model
        or primary.model
        or os.getenv("SUPERQODE_MODEL", "")
        or "gpt-4o-mini"
    )
    resolved_runtime = runtime.strip() or task.runtime or spec.runtime.backend
    resolved_sandbox = sandbox.strip() or spec.execution_policy.sandbox or "local"
    session_root = Path(spec.context.session_storage)
    if not session_root.is_absolute():
        session_root = repository / session_root
    store_kind = spec.observability.run_store
    harness_store = create_harness_store(
        store_kind,
        session_root / "store.sqlite3" if store_kind == "sqlite" else session_root,
    )
    kernel = await init_harness(spec, store=harness_store)
    prompt = _task_prompt(order, task)
    if spec.workflow.mode != WorkflowMode.SINGLE:
        workflow_result = await _await_with_governance(
            governance,
            run_workflow(
                kernel,
                workflow_steps_from_spec(spec, prompt),
                provider=resolved_provider,
                model=resolved_model,
                runtime=resolved_runtime,
                working_directory=repository,
                sandbox_backend=resolved_sandbox,
                session_id=f"{order.work_order_id}-{task.task_id}",
            ),
        )
        stopped_reason = "failed" if workflow_result.failures else "complete"
        usage = _aggregate_harness_usage(workflow_result.results)
        return {
            "content": workflow_result.content,
            "session_id": workflow_result.session_id,
            "run_id": workflow_result.run_id,
            "stopped_reason": stopped_reason,
            "error": workflow_result.failures[-1].get("error", "")
            if workflow_result.failures
            else "",
            "harness": spec.name,
            "provider": resolved_provider,
            "model": resolved_model,
            "runtime": resolved_runtime,
            "workflow_mode": workflow_result.mode.value,
            "result_run_ids": [item.run_id for item in workflow_result.results],
            "governance": governance.to_public_dict(),
            "promotion": promotion_selection,
            **usage,
        }
    session = await kernel.session(f"{order.work_order_id}-{task.task_id}")
    result = await _await_with_governance(
        governance,
        session.prompt(
            prompt,
            provider=resolved_provider,
            model=resolved_model,
            runtime=resolved_runtime,
            working_directory=repository,
            sandbox_backend=resolved_sandbox,
        ),
    )
    return {
        "content": result.content,
        "session_id": result.session_id,
        "run_id": result.run_id,
        "stopped_reason": result.response.stopped_reason,
        "harness": result.spec.name,
        "provider": resolved_provider,
        "model": resolved_model,
        "runtime": resolved_runtime,
        "tool_calls_made": result.tool_calls_made,
        "iterations": result.iterations,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "total_tokens": result.total_tokens,
        "cost_usd": result.cost_usd,
        "cost_currency": result.response.cost_currency,
        "governance": governance.to_public_dict(),
        "promotion": promotion_selection,
    }


async def _await_with_governance(bundle: Any, operation: Any) -> Any:
    from superqode.governance import governance_scope

    with governance_scope(bundle):
        return await operation


def _aggregate_harness_usage(results: tuple[Any, ...]) -> dict[str, Any]:
    token_rows = [item for item in results if item.total_tokens is not None]
    cost_rows = [item for item in results if item.cost_usd is not None]
    all_tokens_reported = bool(results) and len(token_rows) == len(results)
    all_costs_reported = bool(results) and len(cost_rows) == len(results)
    currencies = {item.response.cost_currency for item in cost_rows if item.response.cost_currency}
    return {
        "tokens_in": sum(int(item.tokens_in or 0) for item in token_rows)
        if all_tokens_reported
        else None,
        "tokens_out": sum(int(item.tokens_out or 0) for item in token_rows)
        if all_tokens_reported
        else None,
        "total_tokens": sum(int(item.total_tokens or 0) for item in token_rows)
        if all_tokens_reported
        else None,
        "cost_usd": sum(float(item.cost_usd or 0) for item in cost_rows)
        if all_costs_reported
        else None,
        "cost_currency": sorted(currencies)[0] if len(currencies) == 1 else None,
        "tool_calls_made": sum(int(item.tool_calls_made or 0) for item in results),
        "iterations": sum(int(item.iterations or 0) for item in results),
    }


async def _heartbeat_loop(
    store: WorkOrderStore,
    work_order_id: str,
    task_id: str,
    *,
    worker_id: str,
    lease_seconds: int,
    stop: asyncio.Event,
) -> None:
    interval = max(1.0, min(30.0, lease_seconds / 3))
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            await asyncio.to_thread(
                store.heartbeat,
                work_order_id,
                task_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )


async def _await_harness_or_cancellation(
    store: WorkOrderStore,
    work_order_id: str,
    execution: Any,
    *,
    timeout: float | None,
) -> dict[str, Any]:
    """Cancel the live harness coroutine when another CLI cancels its WorkOrder."""
    execution_task = asyncio.create_task(execution)
    cancellation_task = asyncio.create_task(_wait_for_cancellation(store, work_order_id))
    try:
        async with asyncio.timeout(timeout):
            done, _ = await asyncio.wait(
                {execution_task, cancellation_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task in done:
                execution_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await execution_task
                raise _WorkOrderCancelled
            return await execution_task
    finally:
        cancellation_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cancellation_task
        if not execution_task.done():
            execution_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution_task


async def _wait_for_cancellation(store: WorkOrderStore, work_order_id: str) -> None:
    while True:
        order = await asyncio.to_thread(store.get, work_order_id)
        if order.status == WorkOrderStatus.CANCELLED:
            return
        await asyncio.sleep(0.25)


async def _enforce_role_contract(
    store: WorkOrderStore,
    order: WorkOrder,
    task: WorkOrderTask,
    *,
    workspace: WorkTaskWorkspace,
    content: str,
    result: dict[str, Any],
    worker_id: str,
) -> tuple[str, dict[str, Any]]:
    """Turn a role's output into typed evidence and enforce its write/review gate."""
    metadata: dict[str, Any] = {"role": task.role.value}
    if task.role == WorkTaskRole.REVIEWER:
        review = _review_payload(result, content)
        if review is None:
            reason = "Reviewer did not emit the required SUPERQODE_REVIEW JSON verdict"
            store.add_artifact(
                order.work_order_id,
                kind="review",
                task_id=task.task_id,
                content=content,
                metadata={"verdict": "invalid", "error": reason},
                actor=worker_id,
            )
            return reason, {**metadata, "review_verdict": "invalid"}
        verdict = str(review["verdict"])
        metadata.update(
            {
                "review_verdict": verdict,
                "review_summary": str(review.get("summary") or ""),
                "review_issues": list(review.get("issues") or ()),
            }
        )
        store.add_artifact(
            order.work_order_id,
            kind="review",
            task_id=task.task_id,
            content=content,
            metadata=metadata,
            actor=worker_id,
        )

    if (
        task.role in _EVIDENCE_ONLY_ROLES
        and workspace.isolation == "worktree"
        and workspace.scope == "task"
    ):
        from .integration import capture_task_workspace_delta

        delta = await asyncio.to_thread(
            capture_task_workspace_delta,
            workspace.path,
            workspace.baseline_tree,
        )
        metadata["workspace_files"] = list(delta.files)
        if delta.files:
            reason = f"{task.role.value} tasks are evidence-only but changed: " + ", ".join(
                delta.files
            )
            store.add_artifact(
                order.work_order_id,
                kind="workspace_violation",
                task_id=task.task_id,
                path=str(workspace.path),
                content=delta.patch,
                digest=delta.digest,
                metadata={
                    "role": task.role.value,
                    "files": list(delta.files),
                    "baseline_tree": delta.baseline_tree,
                    "candidate_tree": delta.candidate_tree,
                },
                actor=worker_id,
            )
            return reason, metadata

    if task.role == WorkTaskRole.REVIEWER and metadata.get("review_verdict") != "approved":
        issues = metadata.get("review_issues") or ()
        detail = "; ".join(str(item) for item in issues) or str(
            metadata.get("review_summary") or "review requested changes"
        )
        return f"Reviewer requested changes: {detail}", metadata
    return "", metadata


def _review_payload(result: dict[str, Any], content: str) -> dict[str, Any] | None:
    payload = result.get("review")
    if not isinstance(payload, dict):
        match = re.search(r"^SUPERQODE_REVIEW:\s*(\{.*\})\s*$", content, re.MULTILINE)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    verdict = str(payload.get("verdict") or "").strip().lower().replace("-", "_")
    if verdict not in {"approved", "changes_requested"}:
        return None
    issues = payload.get("issues") or []
    if not isinstance(issues, list):
        return None
    return {
        "verdict": verdict,
        "summary": str(payload.get("summary") or ""),
        "issues": [str(item) for item in issues],
    }


async def _prepare_task_workspace(
    store: WorkOrderStore,
    order: WorkOrder,
    task: WorkOrderTask,
    *,
    isolation: str,
) -> WorkTaskWorkspace:
    requested = isolation.strip().lower() or "auto"
    if requested not in {"auto", "worktree", "none"}:
        raise ValueError("WorkOrder isolation must be auto, worktree, or none")
    repository = Path(order.repository).expanduser().resolve()
    if not repository.is_dir():
        raise ValueError(f"WorkOrder repository does not exist: {repository}")
    if requested == "none" and (order.budget.max_workers or 1) > 1:
        raise ValueError("Parallel WorkOrders require Git worktree isolation")

    integration = await _ensure_integration_workspace(store, order, requested=requested)
    if integration.isolation == "none":
        return WorkTaskWorkspace(
            path=repository,
            isolation="none",
            scope="task",
            integration_path=repository,
        )

    from superqode.workspace.worktree import GitWorktreeManager
    from .integration import create_tree_commit, snapshot_worktree_tree

    manager = GitWorktreeManager(repository)
    integration_tree = await asyncio.to_thread(snapshot_worktree_tree, integration.path)
    task_commit = await asyncio.to_thread(
        create_tree_commit,
        integration.path,
        integration_tree,
        parent=integration.base_commit,
        message=f"SuperQode {order.work_order_id} task {task.task_id} baseline",
    )
    workspace_id = _workspace_id(
        order.work_order_id, f"task-{task.task_id}-attempt-{task.attempts}"
    )
    info = await manager.create_qe_worktree(
        session_id=workspace_id,
        base_ref=task_commit,
        copy_uncommitted=False,
        keep_gitignored=True,
    )
    return WorkTaskWorkspace(
        path=info.path,
        isolation="worktree",
        base_commit=task_commit,
        baseline_tree=integration_tree,
        source_tree=integration.source_tree,
        workspace_id=info.session_id,
        scope="task",
        integration_path=integration.path,
    )


async def _ensure_integration_workspace(
    store: WorkOrderStore,
    order: WorkOrder,
    *,
    requested: str,
) -> WorkTaskWorkspace:
    """Create one exact source baseline shared by every isolated task."""
    current = store.get(order.work_order_id)
    existing = _integration_workspace_from_order(current)
    if existing is not None:
        return existing
    return await asyncio.to_thread(
        _create_integration_workspace_sync,
        store,
        current,
        requested,
    )


def _create_integration_workspace_sync(
    store: WorkOrderStore,
    order: WorkOrder,
    requested: str,
) -> WorkTaskWorkspace:
    from superqode.workspace.worktree import GitWorktreeManager
    from .integration import capture_integration_baseline, work_order_integration_lock

    repository = Path(order.repository).expanduser().resolve()
    with work_order_integration_lock(store, order.work_order_id):
        current = store.get(order.work_order_id)
        existing = _integration_workspace_from_order(current)
        if existing is not None:
            return existing

        async def create() -> WorkTaskWorkspace:
            manager = GitWorktreeManager(repository)
            if requested == "none" or not await manager.is_git_repo():
                if requested == "worktree":
                    raise ValueError(f"Worktree isolation requires a Git repository: {repository}")
                workspace = WorkTaskWorkspace(
                    path=repository,
                    isolation="none",
                    scope="work-order",
                    integration_path=repository,
                )
            else:
                info = await manager.create_qe_worktree(
                    session_id=_workspace_id(order.work_order_id, "integration"),
                    base_ref="HEAD",
                    copy_uncommitted=True,
                    keep_gitignored=True,
                )
                baseline = capture_integration_baseline(repository, info.path)
                workspace = WorkTaskWorkspace(
                    path=info.path,
                    isolation="worktree",
                    base_commit=info.base_commit,
                    baseline_tree=baseline["baseline_tree"],
                    source_tree=baseline["source_tree"],
                    workspace_id=info.session_id,
                    scope="work-order",
                    integration_path=info.path,
                )
            store.add_artifact(
                order.work_order_id,
                kind="workspace",
                path=str(workspace.path),
                metadata={
                    "isolation": workspace.isolation,
                    "base_commit": workspace.base_commit,
                    "baseline_tree": workspace.baseline_tree,
                    "source_tree": workspace.source_tree,
                    "workspace_id": workspace.workspace_id,
                    "scope": "work-order",
                },
                actor="scheduler",
            )
            return workspace

        return asyncio.run(create())


def _integration_workspace_from_order(order: WorkOrder) -> WorkTaskWorkspace | None:
    for artifact in reversed(order.artifacts):
        if (
            artifact.kind == "workspace"
            and artifact.metadata.get("scope") == "work-order"
            and Path(artifact.path).is_dir()
        ):
            return WorkTaskWorkspace(
                path=Path(artifact.path),
                isolation=str(artifact.metadata.get("isolation") or "none"),
                base_commit=str(artifact.metadata.get("base_commit") or ""),
                baseline_tree=str(artifact.metadata.get("baseline_tree") or ""),
                source_tree=str(artifact.metadata.get("source_tree") or ""),
                workspace_id=str(artifact.metadata.get("workspace_id") or ""),
                scope="work-order",
                integration_path=Path(artifact.path),
            )
    return None


async def _record_workspace_evidence(
    store: WorkOrderStore,
    order: WorkOrder,
    task: WorkOrderTask,
    *,
    worker_id: str,
    workspace: WorkTaskWorkspace | None,
    baseline: WorkspaceChangeSnapshot,
) -> None:
    if workspace is None:
        return
    try:
        summary = await asyncio.to_thread(
            summarize_workspace_changes,
            workspace.path,
            baseline,
            True,
        )
    except Exception:
        return
    if not summary.files:
        return
    store.add_artifact(
        order.work_order_id,
        kind="patch",
        task_id=task.task_id,
        path=str(workspace.path),
        content=summary.diff,
        metadata={
            **summary.to_dict(),
            "isolation": workspace.isolation,
            "base_commit": workspace.base_commit,
            "baseline_tree": workspace.baseline_tree,
            "scope": workspace.scope,
        },
        actor=worker_id,
    )


def _workspace_id(work_order_id: str, task_id: str) -> str:
    raw = f"{work_order_id}-{task_id}".lower()
    return "".join(
        character if character.isalnum() or character in "-." else "-" for character in raw
    )[:120]


def _remaining_time_budget(order: WorkOrder) -> float | None:
    if order.budget.max_seconds is None:
        return None
    remaining = float(order.budget.max_seconds) - (time.time() - order.created_at)
    if remaining <= 0:
        raise TimeoutError("WorkOrder time budget is already exhausted")
    return remaining


def _task_prompt(order: WorkOrder, task: WorkOrderTask) -> str:
    parts = [
        f"WorkOrder: {order.work_order_id}",
        f"Overall goal:\n{order.goal}",
        f"Assigned role: {task.role.value}",
        f"Assigned task ({task.task_id}):\n{task.goal}",
    ]
    if task.dependencies:
        parts.append(f"Completed dependencies: {', '.join(task.dependencies)}")
        evidence = _dependency_evidence(order, task)
        if evidence:
            parts.append("Dependency evidence:\n" + evidence)
    acceptance = task.acceptance_tests or order.acceptance_tests
    if acceptance:
        parts.append(
            "Acceptance commands run by the WorkOrder controller after execution:\n"
            + "\n".join(f"- {command}" for command in acceptance)
        )
    if task.role == WorkTaskRole.INVESTIGATOR:
        parts.append(
            "Investigate and report repository evidence, relevant files, risks, and a concrete "
            "implementation recommendation. This is an evidence-only role: do not modify files."
        )
    elif task.role == WorkTaskRole.REVIEWER:
        parts.append(
            "Review the integrated repository state and dependency evidence. Do not modify files. "
            'Your final line must be exactly `SUPERQODE_REVIEW: {"verdict":"approved",'
            '"summary":"...","issues":[]}` or use verdict `changes_requested` with '
            "specific issues. Missing or malformed review JSON blocks the WorkOrder."
        )
    elif task.role == WorkTaskRole.TESTER:
        parts.append(
            "Run or inspect the requested verification and report commands, outcomes, and failure "
            "evidence. This is an evidence-only role: do not modify tracked repository files."
        )
    elif task.role == WorkTaskRole.SYNTHESIZER:
        parts.append(
            "Reconcile the integrated outputs and dependency evidence into one coherent final "
            "implementation. Preserve correct predecessor work and resolve inconsistencies."
        )
    else:
        parts.append("Implement the assigned change in the isolated task workspace.")
    parts.append(
        "Report concrete evidence. Do not claim final WorkOrder acceptance; the controller owns "
        "review, deterministic checks, approval, and merge."
    )
    return "\n\n".join(parts)


def _dependency_evidence(order: WorkOrder, task: WorkOrderTask) -> str:
    chunks: list[str] = []
    remaining = 12000
    for dependency in task.dependencies:
        artifacts = [
            artifact
            for artifact in order.artifacts
            if artifact.task_id == dependency
            and artifact.kind in {"agent_result", "review"}
            and artifact.content.strip()
        ]
        if not artifacts or remaining <= 0:
            continue
        artifact = artifacts[-1]
        content = artifact.content.strip()
        excerpt = content[: min(4000, remaining)]
        chunks.append(f"[{dependency} / {artifact.kind}]\n{excerpt}")
        remaining -= len(excerpt)
    return "\n\n".join(chunks)
