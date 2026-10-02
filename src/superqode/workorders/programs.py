"""Atomic Monty checkpoint publication in the existing WorkOrder database.

Checkpoint bytes stay in trusted local storage. A revision fences two copies
of a VM even within the same worker attempt; the task lease fences attempts.
"""

from __future__ import annotations

import hashlib
import json
import time

from superqode.execution_recovery import RecoveryScope
from .store import _find_task

MAX_CHECKPOINT_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 64_000


class ProgramJournal:
    def __init__(self, scope: RecoveryScope, program_id: str, fingerprint: str, workspace: str):
        if not program_id or len(program_id) > 512:
            raise ValueError("Program identity must contain 1–512 characters")
        self.scope = scope
        self.store = scope.store
        self.program_id = program_id
        self.fingerprint = fingerprint
        self.workspace = workspace

    def _owner(self, conn):
        s = self.scope
        order = self.store._load_tx(conn, s.work_order_id)
        self.store._assert_running_owner(
            _find_task(order, s.task_id), s.worker_id, attempt=s.attempt
        )
        return order

    def _row(self, conn, order):
        row = conn.execute(
            "select * from work_programs where work_order_id=? and task_id=? and program_id=?",
            (order.work_order_id, self.scope.task_id, self.program_id),
        ).fetchone()
        if row is not None:
            if row["fingerprint"] != self.fingerprint:
                raise ValueError(
                    "Program code, capabilities or runtime changed; reconciliation required"
                )
            if row["workspace"] != self.workspace:
                if (
                    row["state"] == "completed"
                    and self.scope.workspace_root
                    and self.scope.invocation_namespace
                ):
                    # The coding replay driver verified the latest committed
                    # workspace. This is historical data from an earlier model
                    # turn, not permission to rerun reads against a new tree.
                    self.workspace = row["workspace"]
                else:
                    raise ValueError(
                        "Workspace changed since the program checkpoint; reconciliation required"
                    )
            if (
                row["checkpoint"] is not None
                and hashlib.sha256(row["checkpoint"]).hexdigest() != row["checkpoint_sha256"]
            ):
                raise ValueError("Program checkpoint integrity check failed")
        return row

    def load(self):
        # Ownership is checked even when returning an already completed program.
        with self.store._transaction() as conn:
            row = self._row(conn, self._owner(conn))
            if row is None:
                return None
            return {
                **dict(row),
                "metadata": json.loads(row["metadata"]),
                "result": json.loads(row["result"]) if row["result"] else None,
            }

    def stage(self, *, revision, checkpoint, metadata, invocation_id, inputs, replay_safe):
        """Publish the suspended VM and tool intent in one SQLite transaction."""
        if not isinstance(checkpoint, bytes) or len(checkpoint) > MAX_CHECKPOINT_BYTES:
            raise ValueError("Program checkpoint exceeds the 8 MiB limit")
        from superqode.execution_recovery import input_fingerprint

        s = self.scope
        with self.store._transaction() as conn:
            order = self._owner(conn)
            row = self._row(conn, order)
            if (row["revision"] if row else 0) != revision:
                raise ValueError("Stale program revision cannot publish a checkpoint")
            self._budget(conn, order, inputs)
            decision = self.store._begin_invocation_tx(
                conn,
                order,
                s.task_id,
                worker_id=s.worker_id,
                attempt=s.attempt,
                invocation_id=invocation_id,
                operation="pipy.program.host",
                fingerprint=input_fingerprint(inputs),
                replay_safe=replay_safe,
                workspace=self.workspace,
            )
            self._write(conn, order, revision + 1, "pending", checkpoint, metadata, None)
            return decision

    def admit(self, *, invocation_id, inputs, replay_safe):
        """Recover the outstanding call; never automatically drive a snapshot."""
        from superqode.execution_recovery import input_fingerprint

        s = self.scope
        with self.store._transaction() as conn:
            order = self._owner(conn)
            self._row(conn, order)
            row = conn.execute(
                "select status from work_invocations where work_order_id=? and task_id=? and invocation_id=?",
                (order.work_order_id, s.task_id, invocation_id),
            ).fetchone()
            if row is None or row["status"] != "completed":
                self._budget(conn, order, inputs)
            return self.store._begin_invocation_tx(
                conn,
                order,
                s.task_id,
                worker_id=s.worker_id,
                attempt=s.attempt,
                invocation_id=invocation_id,
                operation="pipy.program.host",
                fingerprint=input_fingerprint(inputs),
                replay_safe=replay_safe,
                workspace=self.workspace,
            )

    def _budget(self, conn, order, inputs):
        from .usage import evaluate_work_order_policy

        policy = evaluate_work_order_policy(
            order, phase="completion", task=_find_task(order, self.scope.task_id)
        )
        if not policy.allowed:
            raise ValueError("Program WorkOrder budget denied: " + policy.reason)
        if inputs.get("prepared", {}).get("name") == "mcp_call" and (
            order.budget.max_cost_usd is not None or order.budget.max_tokens is not None
        ):
            raise ValueError(
                "MCP program calls cannot reserve unknown spend against a cost or token budget"
            )
        if order.budget.max_tool_calls is not None:
            calls = conn.execute(
                "select count(*) from work_order_events where work_order_id=? and type='invocation.intent' and (json_extract(data,'$.operation')='pipy.program.host' or json_extract(data,'$.operation') like 'pipy.tool.%')",
                (order.work_order_id,),
            ).fetchone()[0]
            extra = conn.execute(
                "select coalesce(sum(json_extract(data,'$.extra_calls')),0) from work_order_events where work_order_id=? and type='program.parallel_reserved'",
                (order.work_order_id,),
            ).fetchone()[0]
            units = len(inputs.get("prepared", {}).get("calls", [])) or 1
            if calls + extra + units > order.budget.max_tool_calls:
                raise ValueError("Program WorkOrder tool-call budget exhausted")
        units = len(inputs.get("prepared", {}).get("calls", [])) or 1
        if units > 1:
            self.store._append_event_tx(
                conn,
                order.work_order_id,
                "program.parallel_reserved",
                task_id=self.scope.task_id,
                actor=self.scope.worker_id,
                data={"extra_calls": units - 1, "id": inputs["prepared"]["call_id"]},
            )

    def dispatch_count(self, call_ids):
        with self.store._transaction() as conn:
            order = self._owner(conn)
            events = conn.execute(
                "select data from work_order_events where work_order_id=? and task_id=? and type='invocation.intent'",
                (order.work_order_id, self.scope.task_id),
            )
            count = sum(json.loads(event["data"]).get("id") in call_ids for event in events)
            # Each batch is one journaled invocation but reserves every child.
            extra = conn.execute(
                "select data from work_order_events where work_order_id=? and task_id=? and type='program.parallel_reserved'",
                (order.work_order_id, self.scope.task_id),
            )
            count += sum(
                json.loads(event["data"])["extra_calls"]
                for event in extra
                if json.loads(event["data"])["id"] in call_ids
            )
            return count

    def finish_call(self, invocation_id, result):
        s = self.scope
        self.store.finish_invocation(
            s.work_order_id,
            s.task_id,
            worker_id=s.worker_id,
            attempt=s.attempt,
            invocation_id=invocation_id,
            result=result,
            workspace=self.workspace,
        )

    def uncertain(self, invocation_id):
        s = self.scope
        self.store.mark_invocation_uncertain(
            s.work_order_id,
            s.task_id,
            worker_id=s.worker_id,
            attempt=s.attempt,
            invocation_id=invocation_id,
        )

    def complete(self, revision, result, metadata):
        if len(json.dumps(result).encode()) > MAX_RESULT_BYTES:
            raise ValueError("Program result exceeds the 64,000 byte limit")
        with self.store._transaction() as conn:
            order = self._owner(conn)
            row = self._row(conn, order)
            if (row["revision"] if row else 0) != revision:
                raise ValueError("Stale program revision cannot commit completion")
            self._write(conn, order, revision + 1, "completed", None, metadata, result)

    @staticmethod
    def publish_task_result(scope, program_id, result):
        """Publish deduplicated, owner-fenced evidence for standalone tasks."""
        from dataclasses import replace
        from .models import WorkArtifact, generate_artifact_id

        store = scope.store
        with store._transaction() as conn:
            order = store._load_tx(conn, scope.work_order_id)
            store._assert_running_owner(
                _find_task(order, scope.task_id), scope.worker_id, attempt=scope.attempt
            )
            if any(
                a.task_id == scope.task_id
                and a.kind == "agent_result"
                and a.metadata.get("program_id") == program_id
                for a in order.artifacts
            ):
                return
            artifact = WorkArtifact(
                artifact_id=generate_artifact_id(),
                kind="agent_result",
                task_id=scope.task_id,
                created_at=time.time(),
                content=result["output"],
                metadata={
                    "program_id": program_id,
                    "runtime": "pipy-monty",
                    "calls": result["calls"],
                },
            )
            store._save_tx(
                conn, replace(order, artifacts=(*order.artifacts, artifact), updated_at=time.time())
            )
            store._append_event_tx(
                conn,
                order.work_order_id,
                "artifact.created",
                task_id=scope.task_id,
                actor=scope.worker_id,
                data={
                    "artifact_id": artifact.artifact_id,
                    "kind": "agent_result",
                    "program_id": program_id,
                },
            )

    def _write(self, conn, order, revision, state, checkpoint, metadata, result):
        s = self.scope
        conn.execute(
            """insert into work_programs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(work_order_id,task_id,program_id) do update set
            revision=excluded.revision, worker_id=excluded.worker_id,
            attempt=excluded.attempt,state=excluded.state,checkpoint=excluded.checkpoint,
            checkpoint_sha256=excluded.checkpoint_sha256,metadata=excluded.metadata,
            result=excluded.result,updated_at=excluded.updated_at""",
            (
                order.work_order_id,
                s.task_id,
                self.program_id,
                self.fingerprint,
                self.workspace,
                revision,
                s.worker_id,
                s.attempt,
                state,
                checkpoint,
                hashlib.sha256(checkpoint).hexdigest() if checkpoint is not None else "",
                json.dumps(metadata, sort_keys=True),
                json.dumps(result) if result is not None else None,
                time.time(),
            ),
        )
        self.store._append_event_tx(
            conn,
            order.work_order_id,
            "program." + state,
            task_id=s.task_id,
            actor=s.worker_id,
            data={
                "program_id": self.program_id,
                "revision": revision,
                "checkpoint_bytes": len(checkpoint or b""),
                "attempt": s.attempt,
            },
        )


def inspect_programs(store, reference, task_id=""):
    """Content-free inspection: no code, arguments, output, or snapshot bytes."""
    from contextlib import closing

    with closing(store._connect()) as conn:
        order = store._load_tx(conn, reference)
        rows = conn.execute(
            "select task_id,program_id,state,revision,attempt,worker_id,checkpoint_sha256,"
            "length(checkpoint) as checkpoint_bytes,updated_at from work_programs "
            "where work_order_id=? order by updated_at",
            (order.work_order_id,),
        )
        return [dict(row) for row in rows if not task_id or row["task_id"] == task_id]
