"""Bounded host bridge for the existing Monty interpreter.

All execution goes back through AgentLoop's dispatcher. No tool instance is
executed directly here. Receipts contain identities and hashes, never raw
arguments or output. Selected output is retained in bounded, expiring local
evidence files; availability and omissions are explicit in each receipt.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import threading
import time
from typing import Any
from uuid import uuid4

from .base import ToolContext
from .composition_evidence import CompositionEvidence


class ToolComposition:
    MAX_CALLS = 32
    MAX_CONCURRENCY = 8
    MAX_RESULT_BYTES = 64_000
    BLOCKED = frozenset(
        {
            "python_repl",
            "batch",
            "dynamic_workflow",
            "dynamic_workflow_script",
            "spawn_agent",
            "sub_agent",
            "delegate",
            "task",
            "agent",
            "coordinate",
            "send_input",
            "close_agent",
            "agent_session",
        }
    )

    def __init__(self, ctx: ToolContext, *, deadline_seconds: float = 30) -> None:
        self.ctx = ctx
        self.loop = asyncio.get_running_loop()
        self.deadline = time.monotonic() + deadline_seconds
        self.parent = ctx.invocation_id or f"composition-{uuid4().hex}"
        self._pending: set[concurrent.futures.Future] = set()
        self._lock = threading.Lock()
        self._calls = 0
        self._closed = False
        self._trace: list[dict[str, Any]] = []
        self._tasks: set[asyncio.Task] = set()
        self._evidence = CompositionEvidence(
            ctx.working_directory.resolve() / ".superqode" / "composition-evidence"
        )

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self._submit(self._search(query, limit))

    async def _search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self.ctx.tool_registry is None:
            return []
        limit = max(1, min(int(limit), 20))
        tools = [tool for tool in self.ctx.tool_registry.list() if tool.name not in self.BLOCKED]
        from .discovery import DiscoverySettings, ToolDescriptor, retrieve

        catalogue = [
            ToolDescriptor(
                id=t.name,
                exposed_name=t.name,
                original_name=t.name,
                source="native",
                description=t.description,
                input_schema=t.parameters,
                read_only=t.read_only,
            )
            for t in tools
        ]
        selected, _ = await retrieve(
            query, catalogue, DiscoverySettings(search_limit=limit, candidate_limit=limit)
        )
        return [
            {
                "name": c.descriptor.exposed_name,
                "description": c.descriptor.description,
                "parameters": dict(c.descriptor.input_schema),
            }
            for c in selected
        ]

    def _submit(self, coro):
        with self._lock:
            remaining = self.deadline - time.monotonic()
            if self._closed or remaining <= 0:
                coro.close()
                raise TimeoutError("Tool composition deadline exceeded")
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            self._pending.add(future)
        try:
            return future.result(timeout=remaining)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError("Tool composition deadline exceeded") from None
        finally:
            with self._lock:
                self._pending.discard(future)

    async def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._closed or time.monotonic() >= self.deadline:
            raise TimeoutError("Tool composition deadline exceeded")
        if not isinstance(arguments, dict) or not isinstance(name, str):
            raise ValueError("tool_call requires a name and argument object")
        if self._calls >= self.MAX_CALLS:
            raise ValueError("Tool composition call budget exceeded")
        self._calls += 1
        task = asyncio.current_task()
        self._tasks.add(task)
        call_id = f"{self.parent}/call-{self._calls}"
        trace = {
            "id": call_id,
            "parent_id": self.parent,
            "tool": name,
            "arguments_sha256": hashlib.sha256(
                json.dumps(arguments, sort_keys=True).encode()
            ).hexdigest(),
            "started_at": time.time(),
            "status": "running",
            "usage": None,
        }
        self._trace.append(trace)
        try:
            if self.ctx.execute_tool is None:
                trace["status"] = "blocked"
                raise RuntimeError("This execution context has no governed tool dispatcher")
            if name in self.BLOCKED:
                trace["status"] = "blocked"
                raise ValueError(
                    f"Nested orchestration is unavailable through tool composition: {name}"
                )
            self._record(trace)
            result = await self.ctx.execute_tool(name, arguments, call_id)
            output = str(result.output or "")
            encoded = output.encode()
            truncated = len(encoded) > self.MAX_RESULT_BYTES
            output = encoded[: self.MAX_RESULT_BYTES].decode(errors="ignore")
            trace.update(
                status="succeeded" if result.success else "failed",
                output_sha256=hashlib.sha256(encoded).hexdigest(),
                output_bytes=len(encoded),
                retained_bytes=len(output.encode()),
                truncated=truncated,
                effective_arguments_sha256=result.metadata.get("effective_arguments_sha256"),
                permission=str(result.metadata.get("permission", "allowed"))[:80],
                usage={
                    key: value
                    for key, value in (
                        result.metadata.get("usage")
                        if isinstance(result.metadata.get("usage"), dict)
                        else {}
                    ).items()
                    if key in {"tokens_in", "tokens_out", "total_tokens", "cost_usd"}
                    and isinstance(value, (int, float))
                }
                or None,
            )
            if not result.success and "denied" in trace["permission"]:
                trace["status"] = "blocked"
            try:
                trace.update(
                    self._evidence.retain(
                        call_id,
                        str(result.output or ""),
                        sensitive=bool(result.metadata.get("sensitive")),
                    )
                )
            except OSError:
                trace.update(
                    evidence_available=False, evidence_reason="evidence storage unavailable"
                )
            structured = result.metadata.get("structured_content")
            structured_truncated = (
                structured is not None
                and len(json.dumps(structured, default=str).encode()) > self.MAX_RESULT_BYTES
            )
            trace["structured_truncated"] = structured_truncated
            return {
                "success": result.success,
                "output": output,
                "error": result.error,
                "invocation_id": call_id,
                "truncated": truncated,
                **(
                    {
                        "structured_content": None if structured_truncated else structured,
                        "structured_truncated": structured_truncated,
                    }
                    if structured is not None
                    else {}
                ),
            }
        except asyncio.CancelledError:
            trace["status"] = "cancelled"
            raise
        except Exception:
            if trace["status"] != "blocked":
                trace["status"] = "failed"
            raise
        finally:
            trace["ended_at"] = time.time()
            self._tasks.discard(task)
            self._record(trace)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._submit(self._call(name, arguments))

    async def _parallel(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(calls, list) or not 1 <= len(calls) <= self.MAX_CONCURRENCY:
            raise ValueError("tool_parallel requires 1–8 calls")
        for call in calls:
            tool = self.ctx.tool_registry.get(call["name"]) if self.ctx.tool_registry else None
            # Remote annotations are advisory: only native declarations qualify.
            if tool is None or not tool.read_only or call["name"].startswith("mcp_"):
                raise ValueError("Parallel composition requires trusted read-only native tools")
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(self._call(c["name"], c.get("arguments", {}))) for c in calls
            ]
        return [task.result() for task in tasks]

    def parallel(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._submit(self._parallel(calls))

    def externals(self) -> dict[str, Any]:
        return {
            "tool_search": self.search,
            "tool_call": self.call,
            "tool_parallel": self.parallel,
            "tool_evidence": self._evidence.read,
        }

    def receipt(self) -> dict[str, Any]:
        return {
            "parent_id": self.parent,
            "calls": list(self._trace),
            "evidence_retention_seconds": self._evidence.RETENTION_SECONDS,
            "usage_complete": False,
        }

    def _record(self, trace: dict[str, Any]) -> None:
        if self.ctx.harness_store is not None and self.ctx.harness_run_id:
            from superqode.harness.events import HarnessEvent

            self.ctx.harness_store.append_event(
                self.ctx.harness_run_id,
                HarnessEvent(
                    type="tool.composition",
                    data=dict(trace),
                    session_id=self.ctx.session_id,
                    run_id=self.ctx.harness_run_id,
                ),
            )

    async def close(self) -> None:
        with self._lock:
            self._closed = True
            pending = list(self._pending)
        for future in pending:
            future.cancel()
        if pending:
            await asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True)
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
