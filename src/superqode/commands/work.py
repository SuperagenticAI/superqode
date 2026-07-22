"""Terminal-first WorkOrder lifecycle commands."""

from __future__ import annotations

import json
import shlex
import signal
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import click

from superqode.workorders import (
    RISK_LEVELS,
    WorkOrder,
    WorkOrderBudget,
    WorkOrderStatus,
    WorkOrderStore,
    WorkOrderTask,
    WorkTaskRole,
    build_cockpit_snapshot,
    evaluate_work_order_policy,
    generate_work_order_id,
    list_worker_snapshots,
    project_usage,
    render_cockpit,
)

DEFAULT_WORK_STORE = Path(".superqode/workorders/store.sqlite3")


@click.group()
@click.option(
    "--store",
    "store_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=DEFAULT_WORK_STORE,
    show_default=True,
    help="WorkOrder SQLite store",
)
@click.pass_context
def work(ctx: click.Context, store_path: Path) -> None:
    """Create, schedule, inspect, and decide durable WorkOrders."""
    ctx.ensure_object(dict)
    ctx.obj["work_store_path"] = store_path


@work.command("create")
@click.argument("goal")
@click.option(
    "--repo",
    "repository",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
)
@click.option("--acceptance-test", multiple=True, help="Required acceptance command")
@click.option("--harness", default="coding", show_default=True)
@click.option("--harness-version", default="")
@click.option("--provider", default="")
@click.option("--model", default="")
@click.option("--runtime", default="")
@click.option("--task-id", default="primary", show_default=True)
@click.option("--task-title", default="Implementation", show_default=True)
@click.option(
    "--role",
    type=click.Choice([item.value for item in WorkTaskRole], case_sensitive=False),
    default=WorkTaskRole.IMPLEMENTER.value,
    show_default=True,
)
@click.option(
    "--risk",
    type=click.Choice(["auto", *RISK_LEVELS], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Task risk; auto derives it from the worker role",
)
@click.option("--max-attempts", default=2, show_default=True, type=click.IntRange(min=1))
@click.option("--max-cost", type=click.FloatRange(min=0), default=None)
@click.option("--max-tokens", type=click.IntRange(min=1), default=None)
@click.option("--max-seconds", type=click.IntRange(min=1), default=None)
@click.option("--max-workers", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--max-tool-calls", type=click.IntRange(min=1), default=None)
@click.option(
    "--max-risk",
    type=click.Choice(list(RISK_LEVELS), case_sensitive=False),
    default=None,
    help="Highest task risk the WorkOrder may admit",
)
@click.option("--queue/--draft", default=False, help="Queue immediately instead of leaving a draft")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_create(
    ctx: click.Context,
    goal: str,
    repository: Path,
    acceptance_test: tuple[str, ...],
    harness: str,
    harness_version: str,
    provider: str,
    model: str,
    runtime: str,
    task_id: str,
    task_title: str,
    role: str,
    risk: str,
    max_attempts: int,
    max_cost: float | None,
    max_tokens: int | None,
    max_seconds: int | None,
    max_workers: int | None,
    max_tool_calls: int | None,
    max_risk: str | None,
    queue: bool,
    json_output: bool,
) -> None:
    """Create a WorkOrder with one primary implementation task."""
    now_id = generate_work_order_id()
    task = WorkOrderTask(
        task_id=_safe_task_id(task_id),
        title=task_title.strip() or "Implementation",
        goal=goal.strip(),
        role=WorkTaskRole(role),
        risk="" if risk == "auto" else risk,
        harness=harness.strip(),
        provider=provider.strip(),
        model=model.strip(),
        runtime=runtime.strip(),
        acceptance_tests=tuple(acceptance_test),
        max_attempts=max_attempts,
    )
    order = WorkOrder(
        work_order_id=now_id,
        goal=goal.strip(),
        repository=str(repository.resolve()),
        acceptance_tests=tuple(acceptance_test),
        harness=harness.strip() or "coding",
        harness_version=harness_version.strip(),
        budget=WorkOrderBudget(
            max_cost_usd=max_cost,
            max_tokens=max_tokens,
            max_seconds=max_seconds,
            max_workers=max_workers,
            max_tool_calls=max_tool_calls,
            max_risk=(max_risk or "").strip(),
        ),
        tasks=(task,),
    )
    try:
        store = _store(ctx)
        created = store.create(order)
        if queue:
            created = store.queue(created.work_order_id, actor="cli")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(created, json_output=json_output)


@work.command("add-task")
@click.argument("work_order_id")
@click.argument("goal")
@click.option("--task-id", required=True)
@click.option("--title", default="")
@click.option(
    "--role",
    type=click.Choice([item.value for item in WorkTaskRole], case_sensitive=False),
    default=WorkTaskRole.IMPLEMENTER.value,
    show_default=True,
)
@click.option(
    "--risk",
    type=click.Choice(["auto", *RISK_LEVELS], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Task risk; auto derives it from the worker role",
)
@click.option("--depends-on", multiple=True)
@click.option("--harness", default="")
@click.option("--provider", default="")
@click.option("--model", default="")
@click.option("--runtime", default="")
@click.option("--acceptance-test", multiple=True)
@click.option("--max-attempts", default=2, show_default=True, type=click.IntRange(min=1))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_add_task(
    ctx: click.Context,
    work_order_id: str,
    goal: str,
    task_id: str,
    title: str,
    role: str,
    risk: str,
    depends_on: tuple[str, ...],
    harness: str,
    provider: str,
    model: str,
    runtime: str,
    acceptance_test: tuple[str, ...],
    max_attempts: int,
    json_output: bool,
) -> None:
    """Add a dependency-aware task to a draft WorkOrder."""
    normalized = _safe_task_id(task_id)
    task = WorkOrderTask(
        task_id=normalized,
        title=title.strip() or normalized,
        goal=goal.strip(),
        role=WorkTaskRole(role),
        risk="" if risk == "auto" else risk,
        dependencies=tuple(_safe_task_id(item) for item in depends_on),
        harness=harness.strip(),
        provider=provider.strip(),
        model=model.strip(),
        runtime=runtime.strip(),
        acceptance_tests=tuple(acceptance_test),
        max_attempts=max_attempts,
    )
    try:
        order = _store(ctx).add_task(work_order_id, task, actor="cli")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("list")
@click.option(
    "--status",
    type=click.Choice([item.value for item in WorkOrderStatus], case_sensitive=False),
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_list(ctx: click.Context, status: str | None, json_output: bool) -> None:
    """List local WorkOrders."""
    orders = _store(ctx).list(status=status)
    if json_output:
        click.echo(json.dumps([order.to_dict() for order in orders], indent=2))
        return
    if not orders:
        click.echo("No WorkOrders.")
        return
    click.echo(f"{'ID':<31} {'STATUS':<15} {'TASKS':<9} GOAL")
    for order in orders:
        done = sum(task.status.value == "succeeded" for task in order.tasks)
        click.echo(
            f"{order.work_order_id:<31} {order.status.value:<15} "
            f"{done}/{len(order.tasks):<7} {_preview(order.goal, 60)}"
        )


@work.command("status")
@click.argument("work_order_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_status(ctx: click.Context, work_order_id: str, json_output: bool) -> None:
    """Show one WorkOrder, its tasks, budgets, and decision."""
    try:
        order = _store(ctx).get(work_order_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("usage")
@click.argument("work_order_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_usage(ctx: click.Context, work_order_id: str, json_output: bool) -> None:
    """Show normalized cost, token, tool, and latency accounting."""
    try:
        summary = _store(ctx).usage_summary(work_order_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = summary.to_dict()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"runs: {payload['run_count']}")
    click.echo(
        f"tokens: {payload['total_tokens']} "
        f"(in={payload['tokens_in']}, out={payload['tokens_out']}, "
        f"unreported={payload['unknown_token_runs']})"
    )
    click.echo(
        f"cost: ${payload['cost_usd']:.6f} "
        f"(unreported={payload['unknown_cost_runs']})"
    )
    click.echo(
        f"tool calls: {payload['tool_calls']} "
        f"(unreported={payload['unknown_tool_call_runs']})"
    )
    click.echo(
        f"iterations: {payload['iterations']}  latency: {payload['latency_ms']}ms"
    )


@work.command("policy")
@click.argument("work_order_id")
@click.option(
    "--phase",
    type=click.Choice(["admission", "completion"]),
    default="admission",
    show_default=True,
)
@click.option("--task", "task_id", default="", help="Evaluate a specific task")
@click.option(
    "--risk",
    type=click.Choice(list(RISK_LEVELS), case_sensitive=False),
    default=None,
    help="Simulate a task risk without changing the WorkOrder",
)
@click.option("--add-cost", type=click.FloatRange(min=0), default=0.0, show_default=True)
@click.option("--add-tokens", type=click.IntRange(min=0), default=0, show_default=True)
@click.option(
    "--add-tool-calls", type=click.IntRange(min=0), default=0, show_default=True
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_policy(
    ctx: click.Context,
    work_order_id: str,
    phase: str,
    task_id: str,
    risk: str | None,
    add_cost: float,
    add_tokens: int,
    add_tool_calls: int,
    json_output: bool,
) -> None:
    """Explain or simulate WorkOrder budget and risk gates without mutation."""
    try:
        store = _store(ctx)
        order = store.get(work_order_id)
        task = next((item for item in order.tasks if item.task_id == task_id), None)
        if task_id and task is None:
            raise ValueError(f"Unknown WorkOrder task: {task_id}")
        if risk and task is None:
            raise ValueError("--risk requires --task")
        if risk and task is not None:
            task = replace(task, risk=risk)
        current = store.usage_summary(work_order_id)
        projected = project_usage(
            current,
            add_cost_usd=add_cost,
            add_tokens=add_tokens,
            add_tool_calls=add_tool_calls,
        )
        decision = evaluate_work_order_policy(
            order,
            phase=phase,
            task=task,
            usage=projected,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "work_order_id": order.work_order_id,
        "task_id": task.task_id if task else "",
        "budget": order.budget.to_dict(),
        "current_usage": current.to_dict(),
        "projected_usage": projected.to_dict(),
        "simulation": {
            "add_cost_usd": add_cost,
            "add_tokens": add_tokens,
            "add_tool_calls": add_tool_calls,
            "risk": risk or "",
        },
        "decision": decision.to_dict(),
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    outcome = "ALLOW" if decision.allowed else "DENY"
    click.echo(f"{outcome}  phase={phase} task={payload['task_id'] or '-'}")
    click.echo(
        f"projected cost=${projected.cost_usd:.6f} "
        f"tokens={projected.total_tokens} tool_calls={projected.tool_calls}"
    )
    for violation in decision.violations:
        click.echo(f"- {violation.code}: {violation.message}")


@work.command("tree")
@click.argument("work_order_id")
@click.pass_context
def work_tree(ctx: click.Context, work_order_id: str) -> None:
    """Render task dependencies and worker state."""
    try:
        order = _store(ctx).get(work_order_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{order.work_order_id}  {order.status.value.upper()}  {order.goal}")
    for index, task in enumerate(order.tasks):
        branch = "└──" if index == len(order.tasks) - 1 else "├──"
        worker = f" worker={task.worker_id}" if task.worker_id else ""
        dependencies = f" after={','.join(task.dependencies)}" if task.dependencies else ""
        click.echo(
            f"{branch} {task.task_id:<18} {task.role.value:<12} {task.status.value:<10} "
            f"attempt={task.attempts}/{task.max_attempts}{worker}{dependencies}"
        )


@work.command("queue")
@click.argument("work_order_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_queue(ctx: click.Context, work_order_id: str, json_output: bool) -> None:
    """Validate and queue a draft or blocked WorkOrder."""
    try:
        order = _store(ctx).queue(work_order_id, actor="cli")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("claim")
@click.argument("work_order_id", required=False)
@click.option("--worker", "worker_id", required=True)
@click.option(
    "--lease", "lease_seconds", default=300, show_default=True, type=click.IntRange(min=1)
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_claim(
    ctx: click.Context,
    work_order_id: str | None,
    worker_id: str,
    lease_seconds: int,
    json_output: bool,
) -> None:
    """Atomically claim the next dependency-ready task."""
    try:
        claimed = _store(ctx).claim_next_task(
            worker_id=worker_id,
            reference=work_order_id or "",
            lease_seconds=lease_seconds,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if claimed is None:
        if json_output:
            click.echo("null")
        else:
            click.echo("No claimable WorkOrder task.")
        return
    order, task = claimed
    payload = {"work_order_id": order.work_order_id, "task": task.to_dict()}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(f"Claimed {order.work_order_id}/{task.task_id} for {worker_id}")
        click.echo(task.goal)


@work.command("heartbeat")
@click.argument("work_order_id")
@click.argument("task_id")
@click.option("--worker", "worker_id", required=True)
@click.option(
    "--lease", "lease_seconds", default=300, show_default=True, type=click.IntRange(min=1)
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_heartbeat(
    ctx: click.Context,
    work_order_id: str,
    task_id: str,
    worker_id: str,
    lease_seconds: int,
    json_output: bool,
) -> None:
    """Renew a running task lease."""
    try:
        task = _store(ctx).heartbeat(
            work_order_id,
            task_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(task.to_dict(), indent=2))
    else:
        click.echo(f"Renewed {task_id} until {task.lease_expires_at:.3f}")


@work.command("complete")
@click.argument("work_order_id")
@click.argument("task_id")
@click.option("--worker", "worker_id", required=True)
@click.option("--run-id", default="")
@click.option("--session-id", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_complete(
    ctx: click.Context,
    work_order_id: str,
    task_id: str,
    worker_id: str,
    run_id: str,
    session_id: str,
    json_output: bool,
) -> None:
    """Complete a leased task and persist its run lineage."""
    try:
        order = _store(ctx).complete_task(
            work_order_id,
            task_id,
            worker_id=worker_id,
            run_id=run_id,
            session_id=session_id,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("fail")
@click.argument("work_order_id")
@click.argument("task_id")
@click.option("--worker", "worker_id", required=True)
@click.option("--error", required=True)
@click.option("--run-id", default="")
@click.option("--retry/--no-retry", default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_fail(
    ctx: click.Context,
    work_order_id: str,
    task_id: str,
    worker_id: str,
    error: str,
    run_id: str,
    retry: bool,
    json_output: bool,
) -> None:
    """Fail a leased task, optionally scheduling another attempt."""
    try:
        order = _store(ctx).fail_task(
            work_order_id,
            task_id,
            worker_id=worker_id,
            error=error,
            retry=retry,
            run_id=run_id,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("recover")
@click.argument("work_order_id", required=False)
@click.option("--stale-after", default=300, show_default=True, type=click.IntRange(min=0))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_recover(
    ctx: click.Context,
    work_order_id: str | None,
    stale_after: int,
    json_output: bool,
) -> None:
    """Recover tasks whose worker heartbeat or lease expired."""
    try:
        orders = _store(ctx).recover_stale(
            work_order_id or "", stale_after_seconds=stale_after, actor="cli"
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps([order.to_dict() for order in orders], indent=2))
    else:
        click.echo(f"Recovered {len(orders)} WorkOrder(s).")


@work.command("run")
@click.argument("work_order_id")
@click.option("--worker", "worker_id", default="")
@click.option("--max-tasks", default=0, show_default=True, type=click.IntRange(min=0))
@click.option(
    "--lease", "lease_seconds", default=300, show_default=True, type=click.IntRange(min=1)
)
@click.option("--provider", default="", help="Override task and harness provider")
@click.option("--model", default="", help="Override task and harness model")
@click.option("--runtime", default="", help="Override task and harness runtime")
@click.option("--sandbox", default="", help="Override the harness sandbox")
@click.option(
    "--isolation",
    type=click.Choice(["auto", "worktree", "none"]),
    default="auto",
    show_default=True,
    help="Allocate a Git worktree automatically when possible",
)
@click.option("--retry/--no-retry", default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_run(
    ctx: click.Context,
    work_order_id: str,
    worker_id: str,
    max_tasks: int,
    lease_seconds: int,
    provider: str,
    model: str,
    runtime: str,
    sandbox: str,
    isolation: str,
    retry: bool,
    json_output: bool,
) -> None:
    """Run dependency-ready tasks through their assigned HarnessSpecs."""
    import asyncio

    from superqode.workorders import run_until_idle

    store = _store(ctx)
    try:
        results = asyncio.run(
            run_until_idle(
                store,
                work_order_id=work_order_id,
                worker_id=worker_id,
                max_tasks=max_tasks,
                lease_seconds=lease_seconds,
                provider=provider,
                model=model,
                runtime=runtime,
                sandbox=sandbox,
                isolation=isolation,
                retry=retry,
            )
        )
        order = store.get(work_order_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "work_order": order.to_dict(),
        "executions": [result.to_dict() for result in results],
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not results:
        click.echo("No dependency-ready WorkOrder tasks.")
    for result in results:
        click.echo(
            f"{result.status.upper():<9} {result.task_id} "
            f"run={result.run_id or '-'} session={result.session_id or '-'}"
        )
        if result.error:
            click.echo(f"  {result.error}")
    click.echo(f"WorkOrder status: {order.status.value}")


@work.command("worker")
@click.argument("work_order_id", required=False)
@click.option("--id", "worker_id", default="", help="Stable worker service identity")
@click.option("--concurrency", default=1, show_default=True, type=click.IntRange(min=1, max=64))
@click.option("--poll", default=1.0, show_default=True, type=click.FloatRange(min=0.05))
@click.option(
    "--lease", "lease_seconds", default=300, show_default=True, type=click.IntRange(min=1)
)
@click.option("--stale-after", default=300, show_default=True, type=click.IntRange(min=0))
@click.option("--provider", default="", help="Override task and harness provider")
@click.option("--model", default="", help="Override task and harness model")
@click.option("--runtime", default="", help="Override task and harness runtime")
@click.option("--sandbox", default="", help="Override the harness sandbox")
@click.option(
    "--isolation",
    type=click.Choice(["auto", "worktree", "none"]),
    default="auto",
    show_default=True,
)
@click.option("--retry/--no-retry", default=True)
@click.option("--once", is_flag=True, help="Drain claimable work, then exit")
@click.option("--max-tasks", default=0, show_default=True, type=click.IntRange(min=0))
@click.option("--json", "json_output", is_flag=True, help="Emit final worker stats as JSON")
@click.pass_context
def work_worker(
    ctx: click.Context,
    work_order_id: str | None,
    worker_id: str,
    concurrency: int,
    poll: float,
    lease_seconds: int,
    stale_after: int,
    provider: str,
    model: str,
    runtime: str,
    sandbox: str,
    isolation: str,
    retry: bool,
    once: bool,
    max_tasks: int,
    json_output: bool,
) -> None:
    """Run a persistent headless worker for one WorkOrder or the global queue."""
    import asyncio

    from superqode.workorders import WorkOrderWorker, WorkOrderWorkerConfig

    service = WorkOrderWorker(
        _store(ctx),
        WorkOrderWorkerConfig(
            worker_id=worker_id,
            reference=work_order_id or "",
            concurrency=concurrency,
            poll_interval=poll,
            lease_seconds=lease_seconds,
            stale_after_seconds=stale_after,
            provider=provider,
            model=model,
            runtime=runtime,
            sandbox=sandbox,
            isolation=isolation,
            retry=retry,
            once=once,
            max_tasks=max_tasks,
        ),
    )
    if not json_output:
        scope = service.config.reference or "all queued WorkOrders"
        click.echo(
            f"Worker {service.config.worker_id} watching {scope} "
            f"(concurrency={service.config.concurrency})"
        )
        click.echo("Press Ctrl+C to stop claiming and drain active tasks.")
    try:
        stats = asyncio.run(_run_worker_service(service))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(
            json.dumps({"worker_id": service.config.worker_id, "stats": stats.to_dict()}, indent=2)
        )
    else:
        click.echo(
            f"Worker stopped: claimed={stats.claimed} succeeded={stats.succeeded} "
            f"blocked={stats.blocked} failed={stats.failed}"
        )


@work.command("workers")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_workers(ctx: click.Context, json_output: bool) -> None:
    """Inspect durable worker heartbeats for this WorkOrder store."""
    snapshots = list_worker_snapshots(_store(ctx))
    if json_output:
        click.echo(json.dumps([snapshot.to_dict() for snapshot in snapshots], indent=2))
        return
    if not snapshots:
        click.echo("No WorkOrder workers recorded.")
        return
    now = time.time()
    click.echo(f"{'WORKER':<30} {'STATE':<10} {'PID':<8} {'ACTIVE':<8} UPDATED")
    for snapshot in snapshots:
        poll = float(snapshot.config.get("poll_interval") or 1.0)
        responsive = snapshot.status == "running" and now - snapshot.updated_at <= max(
            10.0, poll * 4
        )
        state = (
            "live" if responsive else "stale" if snapshot.status == "running" else snapshot.status
        )
        click.echo(
            f"{snapshot.worker_id:<30} {state:<10} {snapshot.pid:<8} "
            f"{len(snapshot.active):<8} {_human_duration(now - snapshot.updated_at)} ago"
        )


@work.command("watch")
@click.argument("work_order_id")
@click.option("--interval", default=1.0, show_default=True, type=click.FloatRange(min=0.1))
@click.option("--events", "event_limit", default=8, show_default=True, type=click.IntRange(min=1))
@click.option("--follow/--once", default=True, help="Refresh until the WorkOrder is terminal")
@click.option("--clear/--no-clear", default=True, help="Clear the terminal between refreshes")
@click.option("--json", "json_output", is_flag=True, help="Emit one JSON snapshot")
@click.pass_context
def work_watch(
    ctx: click.Context,
    work_order_id: str,
    interval: float,
    event_limit: int,
    follow: bool,
    clear: bool,
    json_output: bool,
) -> None:
    """Watch tasks, leases, gates, evidence, and worker health live."""
    from superqode.workorders import TERMINAL_WORK_ORDER_STATUSES

    store = _store(ctx)
    while True:
        try:
            snapshot = build_cockpit_snapshot(store, work_order_id, event_limit=event_limit)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        if json_output:
            click.echo(json.dumps(snapshot, indent=2))
            return
        if follow and clear and click.get_text_stream("stdout").isatty():
            click.echo("\033[2J\033[H", nl=False)
        click.echo(render_cockpit(snapshot))
        terminal = snapshot["status"] in {status.value for status in TERMINAL_WORK_ORDER_STATUSES}
        if not follow or terminal:
            return
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return


@work.command("resume")
@click.argument("work_order_id")
@click.option("--task", "task_id", default="")
@click.option("--actor", default="human", show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_resume(
    ctx: click.Context,
    work_order_id: str,
    task_id: str,
    actor: str,
    json_output: bool,
) -> None:
    """Return blocked work to the dependency queue."""
    try:
        order = _store(ctx).resume(work_order_id, task_id=task_id, actor=actor)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("check")
@click.argument("work_order_id")
@click.option("--timeout", default=300, show_default=True, type=click.IntRange(min=1))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_check(
    ctx: click.Context,
    work_order_id: str,
    timeout: int,
    json_output: bool,
) -> None:
    """Run deterministic WorkOrder acceptance commands."""
    store = _store(ctx)
    try:
        order = store.get(work_order_id)
        if not order.acceptance_tests:
            raise ValueError("WorkOrder has no acceptance tests")
        check_directory = _acceptance_directory(order)
        results = [
            _run_acceptance_command(command, cwd=check_directory, timeout=timeout)
            for command in order.acceptance_tests
        ]
        updated = store.record_checks(order.work_order_id, results, actor="cli")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps({"work_order": updated.to_dict(), "results": results}, indent=2))
    else:
        for result in results:
            click.echo(
                f"{result['status'].upper():<6} {result['command']} "
                f"(exit {result.get('returncode')})"
            )
        click.echo(f"WorkOrder status: {updated.status.value}")
    if any(result["status"] != "passed" for result in results):
        raise click.exceptions.Exit(2)


@work.command("artifact-add")
@click.argument("work_order_id")
@click.option("--kind", required=True)
@click.option("--task", "task_id", default="")
@click.option("--path", "artifact_path", default="")
@click.option("--content", default="")
@click.option("--digest", default="")
@click.option("--actor", default="human", show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_artifact_add(
    ctx: click.Context,
    work_order_id: str,
    kind: str,
    task_id: str,
    artifact_path: str,
    content: str,
    digest: str,
    actor: str,
    json_output: bool,
) -> None:
    """Attach a typed plan, patch, review, check, cost, or log artifact."""
    try:
        artifact = _store(ctx).add_artifact(
            work_order_id,
            kind=kind,
            task_id=task_id,
            path=artifact_path,
            content=content,
            digest=digest,
            actor=actor,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(artifact.to_dict(), indent=2))
    else:
        click.echo(f"Artifact {artifact.artifact_id}: {artifact.kind}")


@work.command("artifacts")
@click.argument("work_order_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_artifacts(ctx: click.Context, work_order_id: str, json_output: bool) -> None:
    """List typed artifacts attached to a WorkOrder."""
    try:
        artifacts = _store(ctx).get(work_order_id).artifacts
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps([item.to_dict() for item in artifacts], indent=2))
        return
    if not artifacts:
        click.echo("No WorkOrder artifacts.")
        return
    for artifact in artifacts:
        target = artifact.path or _preview(artifact.content, 60)
        click.echo(f"{artifact.artifact_id}  {artifact.kind:<14} {target}")


@work.command("events")
@click.argument("work_order_id")
@click.option("--limit", type=click.IntRange(min=1), default=None)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_events(
    ctx: click.Context,
    work_order_id: str,
    limit: int | None,
    json_output: bool,
) -> None:
    """Show the append-only WorkOrder decision timeline."""
    try:
        events = _store(ctx).events(work_order_id, limit=limit)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps([event.to_dict() for event in events], indent=2))
        return
    for event in events:
        task = f" [{event.task_id}]" if event.task_id else ""
        actor = f" @{event.actor}" if event.actor else ""
        click.echo(f"{event.created_at:.3f}  {event.type}{task}{actor}")


@work.command("prepare")
@click.argument("work_order_id")
@click.option("--actor", default="integration", show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_prepare(
    ctx: click.Context,
    work_order_id: str,
    actor: str,
    json_output: bool,
) -> None:
    """Build a content-addressed candidate and check target conflicts."""
    from superqode.workorders import prepare_integration

    store = _store(ctx)
    try:
        candidate = prepare_integration(store, work_order_id, actor=actor)
        order = store.get(work_order_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"work_order": order.to_dict(), "candidate": candidate.to_dict()}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(f"Candidate: {candidate.artifact_id}")
        click.echo(f"Digest: {candidate.digest}")
        click.echo(f"Files: {len(candidate.files)}")
        for path in candidate.files:
            marker = "CONFLICT" if path in candidate.conflicts else "ready"
            click.echo(f"  {marker:<8} {path}")
        click.echo(f"WorkOrder status: {order.status.value}")
    if candidate.conflicts or not candidate.expected_tree:
        raise click.exceptions.Exit(2)


@work.command("diff")
@click.argument("work_order_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_diff(ctx: click.Context, work_order_id: str, json_output: bool) -> None:
    """Print the exact integration candidate awaiting approval."""
    try:
        order = _store(ctx).get(work_order_id)
        candidate = next(
            item for item in reversed(order.artifacts) if item.kind == "integration_candidate"
        )
    except StopIteration as exc:
        raise click.ClickException("WorkOrder has no prepared integration candidate") from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(candidate.to_dict(), indent=2))
    else:
        click.echo(candidate.content, nl=not candidate.content.endswith("\n"))


@work.command("approve")
@click.argument("work_order_id")
@click.option("--actor", default="human", show_default=True)
@click.option("--reason", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_approve(
    ctx: click.Context,
    work_order_id: str,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Approve completed work or the exact prepared merge candidate."""
    try:
        order = _store(ctx).accept(work_order_id, actor=actor, reason=reason)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("merge")
@click.argument("work_order_id")
@click.option("--actor", default="human", show_default=True)
@click.option("--cleanup", is_flag=True, help="Remove the managed worktree after merge")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_merge(
    ctx: click.Context,
    work_order_id: str,
    actor: str,
    cleanup: bool,
    json_output: bool,
) -> None:
    """Apply the approved candidate without staging or committing user files."""
    import asyncio

    from superqode.workorders import cleanup_integration_workspace, merge_integration

    store = _store(ctx)
    try:
        order = merge_integration(store, work_order_id, actor=actor)
        if cleanup:
            order = asyncio.run(cleanup_integration_workspace(store, work_order_id, actor=actor))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("rollback")
@click.argument("work_order_id")
@click.option("--actor", default="human", show_default=True)
@click.option("--reason", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_rollback(
    ctx: click.Context,
    work_order_id: str,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Reverse a merge only if no later target changes would be overwritten."""
    from superqode.workorders import rollback_integration

    try:
        order = rollback_integration(_store(ctx), work_order_id, actor=actor, reason=reason)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("cleanup")
@click.argument("work_order_id")
@click.option("--actor", default="human", show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_cleanup(
    ctx: click.Context,
    work_order_id: str,
    actor: str,
    json_output: bool,
) -> None:
    """Remove a terminal WorkOrder's managed integration worktree."""
    import asyncio

    from superqode.workorders import cleanup_integration_workspace

    try:
        order = asyncio.run(cleanup_integration_workspace(_store(ctx), work_order_id, actor=actor))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("reject")
@click.argument("work_order_id")
@click.option("--actor", default="human", show_default=True)
@click.option("--reason", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_reject(
    ctx: click.Context,
    work_order_id: str,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Reject a WorkOrder while preserving all evidence."""
    try:
        order = _store(ctx).reject(work_order_id, actor=actor, reason=reason)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


@work.command("cancel")
@click.argument("work_order_id")
@click.option("--actor", default="human", show_default=True)
@click.option("--reason", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.pass_context
def work_cancel(
    ctx: click.Context,
    work_order_id: str,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Cancel unfinished work and release every task lease."""
    try:
        order = _store(ctx).cancel(work_order_id, actor=actor, reason=reason)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_order(order, json_output=json_output)


async def _run_worker_service(service: Any) -> Any:
    import asyncio

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
            installed.append(signum)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        return await service.run(stop=stop)
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


def _store(ctx: click.Context) -> WorkOrderStore:
    return WorkOrderStore(ctx.obj["work_store_path"])


def _emit_order(order: WorkOrder, *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(order.to_dict(), indent=2))
        return
    click.echo(f"WorkOrder: {order.work_order_id}")
    click.echo(f"Status: {order.status.value}")
    click.echo(f"Goal: {order.goal}")
    click.echo(f"Repository: {order.repository}")
    click.echo(
        f"Harness: {order.harness}{'@' + order.harness_version if order.harness_version else ''}"
    )
    limits = {
        key: value
        for key, value in order.budget.to_dict().items()
        if value is not None and value != ""
    }
    click.echo(f"Budget: {json.dumps(limits, sort_keys=True) if limits else '-'}")
    click.echo(f"Tasks: {len(order.tasks)}")
    for task in order.tasks:
        worker = f" ({task.worker_id})" if task.worker_id else ""
        click.echo(
            f"  {task.task_id}: {task.role.value}/{task.status.value}{worker} — {task.title}"
        )
    if order.decision:
        click.echo(f"Decision: {order.decision.verdict} by {order.decision.actor or '-'}")


def _run_acceptance_command(command: str, *, cwd: Path, timeout: int) -> dict[str, Any]:
    args = shlex.split(command)
    if not args:
        return {
            "command": command,
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": "empty command",
        }
    try:
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
            "command": command,
            "status": "failed",
            "returncode": None,
            "stdout": _preview(exc.stdout or "", 2000),
            "stderr": f"timed out after {timeout}s",
        }
    except (OSError, ValueError) as exc:
        return {
            "command": command,
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "command": command,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": _preview(completed.stdout, 2000),
        "stderr": _preview(completed.stderr, 2000),
    }


def _acceptance_directory(order: WorkOrder) -> Path:
    for artifact in reversed(order.artifacts):
        if artifact.kind == "workspace" and artifact.metadata.get("scope") == "work-order":
            candidate = Path(artifact.path)
            if candidate.is_dir():
                return candidate
    return Path(order.repository)


def _safe_task_id(value: str) -> str:
    normalized = "-".join(value.strip().lower().replace("_", "-").split())
    if not normalized or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in normalized
    ):
        raise click.BadParameter("task ids may contain lowercase letters, numbers, dash, and dot")
    return normalized


def _preview(value: Any, limit: int) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _human_duration(value: float) -> str:
    seconds = max(0, int(value))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"
