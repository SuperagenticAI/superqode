"""Lease a standalone PiPy tool program without replaying a model request."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from superqode.execution_recovery import RecoveryScope, recovery_scope
from superqode.harness.pipy_governance import guard_pipy_tools
from superqode.harness.pipy_mcp import PiPyMCPTools
from superqode.harness.pipy_program import PiPyProgramHost
from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
from superqode.pipy.tools.registry import READ_ONLY_TOOL_NAMES
from superqode.pipy.stream import Model
from superqode.tools.monty_program import cancellable_program
from .models import WorkOrderStatus, WorkTaskRole


async def run_next_program(
    store, *, reference, code, program_id="primary", worker_id="program", lease_seconds=300
):
    """Run one dependency-ready task using PiPy tools, without an LLM turn.

    The same command can reclaim a safe interrupted program. Ordinary coding
    WorkOrders keep their conservative whole-harness recovery envelope.
    """
    from superqode.harness import resolve_harness

    order = store.get(reference)
    root = Path(order.repository).expanduser().resolve()
    spec = resolve_harness(order.harness, root=root).spec
    if spec.runtime.backend != "pipy":
        raise ValueError("Standalone programs require a PiPy WorkOrder harness")
    completed = {task.task_id for task in order.tasks if task.status.value == "succeeded"}
    ready = next(
        (
            task
            for task in order.tasks
            if task.status.value == "pending" and set(task.dependencies).issubset(completed)
        ),
        None,
    )
    if ready is not None and ready.role not in {WorkTaskRole.INVESTIGATOR, WorkTaskRole.CUSTOM}:
        raise ValueError(
            "Standalone read-only programs require an investigator or custom task role"
        )
    claimed = store.claim_next_task(
        worker_id=worker_id, reference=reference, lease_seconds=lease_seconds
    )
    if claimed is None:
        return None
    order, task = claimed
    mcp = None
    execution = None
    stop = asyncio.Event()

    async def heartbeat():
        while not stop.is_set():
            await asyncio.sleep(min(1.0, max(0.1, lease_seconds / 3)))
            store.heartbeat(
                reference,
                task.task_id,
                worker_id=worker_id,
                attempt=task.attempts,
                lease_seconds=lease_seconds,
            )

    pulse = asyncio.create_task(heartbeat())
    try:
        if task.role not in {WorkTaskRole.INVESTIGATOR, WorkTaskRole.CUSTOM}:
            raise ValueError(
                "Standalone read-only programs require an investigator or custom task role"
            )
        spec = resolve_harness(task.harness or order.harness, root=root).spec
        if spec.runtime.backend != "pipy":
            raise ValueError("Standalone programs require a PiPy task harness")
        config = dict(spec.runtime.config)
        host = PiPyProgramHost(root, config)
        mcp = await PiPyMCPTools.create(config, cwd=root)
        session = await PiPyCodingSession.create(
            CodingSessionOptions(
                cwd=root,
                model=Model(id="program-host", provider="local"),
                tool_names=tuple(
                    name
                    for name in READ_ONLY_TOOL_NAMES
                    if any(
                        name in agent.tools or set(agent.tools) & {"full", "read_only"}
                        for agent in spec.agents
                    )
                ),
                extra_tools=mcp.tools,
                tool_transform=guard_pipy_tools,
                session_root=root / ".superqode" / "program-sessions",
            )
        )
        host.harness = session.harness
        host.mcp = mcp
        from superqode.extensions import load_extension_runtime
        from superqode.harness.pipy_extensions import attach_extension_hooks

        attach_extension_hooks(
            session.harness,
            load_extension_runtime(root).build_hooks(),
            session_id=f"{reference}/{task.task_id}",
        )
        from superqode.governance import load_governance, governance_scope
        from .runner import _remaining_time_budget

        governance = load_governance(
            root, harness_spec=spec, work_order=order, secure_defaults=True
        )

        async def bounded_execute():
            async with asyncio.timeout(_remaining_time_budget(order)):
                return await _execute(
                    store, reference, task, worker_id, program_id, code, host, root
                )

        with governance_scope(governance):
            execution = asyncio.create_task(bounded_execute())
        # Stop work immediately if renewal fails; no unfenced result can commit.
        done, _ = await asyncio.wait({execution, pulse}, return_when=asyncio.FIRST_COMPLETED)
        if pulse in done:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            await pulse
        result = await execution
        if store.get(reference).status == WorkOrderStatus.CANCELLED:
            raise ValueError("WorkOrder was cancelled")
        from .usage import WorkOrderUsage
        import time

        _, policy = store.record_usage(
            reference,
            WorkOrderUsage(
                task_id=task.task_id,
                attempt=task.attempts,
                observed_at=time.time(),
                runtime="pipy-monty",
                cost_currency="USD",
                **result["usage"],
            ),
            actor=worker_id,
            invocation_id=f"program/{program_id}",
        )
        if not policy.allowed:
            store.block_task(
                reference,
                task.task_id,
                worker_id=worker_id,
                attempt=task.attempts,
                reason=policy.reason,
            )
            return {**result, "status": "blocked", "error": policy.reason}
        from .programs import ProgramJournal

        ProgramJournal.publish_task_result(
            RecoveryScope(store, reference, task.task_id, worker_id, task.attempts),
            program_id,
            result,
        )
        store.complete_task(
            reference,
            task.task_id,
            worker_id=worker_id,
            attempt=task.attempts,
            metadata={"program_id": program_id},
        )
        return {**result, "status": "succeeded", "task_id": task.task_id}
    except Exception as exc:
        if store.get(reference).status == WorkOrderStatus.CANCELLED:
            return {"status": "cancelled", "error": "WorkOrder was cancelled"}
        try:
            failed = store.fail_task(
                reference,
                task.task_id,
                worker_id=worker_id,
                attempt=task.attempts,
                error=str(exc),
                retry=False,
            )
        except ValueError:
            # Ownership was lost; only the current owner may change the task.
            return {"status": "blocked", "error": str(exc)}
        return {
            "status": "blocked" if failed.status == WorkOrderStatus.BLOCKED else "failed",
            "error": str(exc),
        }
    finally:
        stop.set()
        pulse.cancel()
        if execution is not None and not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        await asyncio.gather(pulse, return_exceptions=True)
        if mcp:
            await mcp.close()


async def _execute(store, reference, task, worker, program_id, code, host, root):
    with recovery_scope(RecoveryScope(store, reference, task.task_id, worker, task.attempts)):
        return await cancellable_program(program_id, code, host, cwd=root)
