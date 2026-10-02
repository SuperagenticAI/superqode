"""Lightweight invocation contract; no scheduler imports on ordinary tool calls."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass
class RecoveryScope:
    store: Any
    work_order_id: str
    task_id: str
    worker_id: str
    attempt: int
    workspace_root: str | None = None
    invocation_namespace: str = ""


async def check_recovery_workspace(scope):
    """Verify the last committed PiPy boundary before resumed execution."""
    if scope.workspace_root is None:
        return ""
    import asyncio
    from pathlib import Path
    from superqode.workorders.recovery import workspace_fingerprint

    current = await asyncio.to_thread(
        workspace_fingerprint, Path(scope.workspace_root), exclude_paths=(scope.store.path,)
    )
    rows = [
        row
        for row in scope.store.invocations(scope.work_order_id, scope.task_id)
        if row["operation"].startswith("pipy.")
        and row["status"] == "completed"
        and row["workspace"]
    ]
    if rows and current != rows[-1]["workspace"]:
        raise ValueError("Workspace changed since the last PiPy boundary; reconciliation required")
    return current


_active_recovery: ContextVar[RecoveryScope | None] = ContextVar("workorder_recovery", default=None)


def active_recovery() -> RecoveryScope | None:
    """Return the host-owned recovery scope, never supplied by generated code."""
    return _active_recovery.get()


@contextmanager
def recovery_scope(scope: RecoveryScope | None):
    token = _active_recovery.set(scope)
    try:
        yield
    finally:
        _active_recovery.reset(token)


async def recoverable_call(
    *,
    identity: str,
    operation: str,
    inputs: Any,
    execute,
    encode,
    decode,
    replay_safe: bool = False,
):
    scope = _active_recovery.get()
    if scope is None:
        return await execute()
    identity = identity or f"unidentified-{uuid4().hex}"
    identity = f"{operation}/{identity}"
    if scope.invocation_namespace:
        identity = f"{scope.invocation_namespace}/{identity}"
    await check_recovery_workspace(scope)
    existing = (
        next(
            (
                row
                for row in scope.store.invocations(scope.work_order_id, scope.task_id)
                if row["invocation_id"] == identity
            ),
            None,
        )
        if scope.workspace_root
        else None
    )
    decision = scope.store.begin_invocation(
        scope.work_order_id,
        scope.task_id,
        worker_id=scope.worker_id,
        attempt=scope.attempt,
        invocation_id=identity,
        operation=operation,
        fingerprint=input_fingerprint(inputs),
        replay_safe=replay_safe,
        workspace=existing["workspace"] if existing and existing["status"] == "completed" else "",
    )
    if decision["action"] == "reuse":
        return decode(decision["result"])
    try:
        value = await execute()
    except BaseException:
        with suppress(Exception):
            scope.store.mark_invocation_uncertain(
                scope.work_order_id,
                scope.task_id,
                worker_id=scope.worker_id,
                attempt=scope.attempt,
                invocation_id=identity,
            )
        raise
    # Normalize extension metadata before entering SQLite; arbitrary Python
    # objects cannot turn a completed call into an unrecordable outcome.
    result = json.loads(json.dumps(encode(value), default=str))
    workspace = ""
    if scope.workspace_root:
        import asyncio
        from pathlib import Path
        from superqode.workorders.recovery import workspace_fingerprint

        workspace = await asyncio.to_thread(
            workspace_fingerprint, Path(scope.workspace_root), exclude_paths=(scope.store.path,)
        )
    scope.store.finish_invocation(
        scope.work_order_id,
        scope.task_id,
        worker_id=scope.worker_id,
        attempt=scope.attempt,
        invocation_id=identity,
        result=result,
        workspace=workspace,
    )
    return value


def input_fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
