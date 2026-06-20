"""Bounded recursive harness delegation tool.

This is the local-first bridge between ordinary sub-agent delegation and the
recursive harness design. The first implementation runs through AgentLoop's
existing child-runner so it inherits the parent model gateway, approvals, and
tool policy while adding explicit recursion budget checks.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from ..harness.context_handles import ContextChunk, chunk_context_handle
from .base import Tool, ToolContext, ToolResult


READ_ONLY_TOOLS = [
    "read_file",
    "list_directory",
    "grep",
    "glob",
    "local_code_search",
    "repo_search",
    "code_search",
    "semantic_search",
    "context_handle",
    "diagnostics",
    "get_context_remaining",
]


class SpawnHarnessTool(Tool):
    """Spawn a bounded child harness task using the current local agent runtime."""

    _session_children: dict[str, int] = {}
    _session_started_at: dict[str, float] = {}
    _session_budget_spent: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "spawn_harness"

    @property
    def description(self) -> str:
        return (
            "Delegate a bounded recursive child harness task. Use for long, dense "
            "repo/log/trace searches where a child should inspect one fragment and "
            "return a compact finding. The child inherits current runtime policy."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Self-contained task for the child harness.",
                },
                "context_handle": {
                    "type": "string",
                    "description": "Optional handle or path/glob describing the fragment to inspect.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["read-only", "write"],
                    "description": "Child access mode. read-only restricts tools to inspection tools.",
                },
                "sandbox": {
                    "type": "string",
                    "description": "Requested child sandbox label for audit metadata.",
                },
                "model": {
                    "type": "string",
                    "description": "Requested child model label for audit metadata.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursive depth allowed for this delegation.",
                },
                "max_children": {
                    "type": "integer",
                    "description": "Maximum children allowed for the parent session.",
                },
                "max_wall_seconds": {
                    "type": "integer",
                    "description": "Maximum wall-clock budget for child spawning in this session.",
                },
                "max_budget": {
                    "type": "number",
                    "description": "Maximum child spawn-unit budget for this session. One child costs 1.0.",
                },
                "steering": {
                    "type": "string",
                    "description": "Task-specific guidance to improve child quality.",
                },
                "fanout": {
                    "type": "boolean",
                    "description": "When true, chunk context_handle and spawn one child per chunk.",
                },
                "chunk_chars": {
                    "type": "integer",
                    "description": "Approximate characters per context chunk for fanout.",
                },
                "max_chunks": {
                    "type": "integer",
                    "description": "Maximum context chunks to fan out.",
                },
                "max_parallel": {
                    "type": "integer",
                    "description": "Maximum child tasks to run concurrently for fanout.",
                },
            },
            "required": ["task"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        task = str(args.get("task") or "").strip()
        if not task:
            return ToolResult(success=False, output="", error="task is required")
        has_harness_context = (
            ctx.harness_store is not None and ctx.harness_spec is not None and ctx.harness_run_id
        )
        if ctx.sub_agent_runner is None and not has_harness_context:
            return ToolResult(
                success=False,
                output="",
                error="spawn_harness requires HarnessKernel context or the builtin child runner",
            )
        recursion = getattr(ctx.harness_spec, "recursion", None) if has_harness_context else None
        if recursion is not None and not bool(getattr(recursion, "enabled", False)):
            return ToolResult(
                success=False,
                output="",
                error="Recursive harnessing is disabled by recursion.enabled=false",
                metadata={"recursion_enabled": False},
            )

        max_depth = _policy_int(args, "max_depth", recursion, default=1, minimum=0)
        child_depth = int(getattr(ctx, "delegation_depth", 0)) + 1
        if child_depth > max_depth:
            return ToolResult(
                success=False,
                output="",
                error=f"Recursive harness depth {child_depth} exceeds max_depth {max_depth}",
                metadata={"delegation_depth": child_depth, "max_depth": max_depth},
            )

        session_key = str(ctx.session_id or "default")
        max_children = _policy_int(args, "max_children", recursion, default=6, minimum=0)
        count = self._session_children.get(session_key, 0)
        if count >= max_children:
            return ToolResult(
                success=False,
                output="",
                error=f"Recursive harness child limit reached ({count}/{max_children})",
                metadata={"child_count": count, "max_children": max_children},
            )

        max_wall_seconds = _policy_int(args, "max_wall_seconds", recursion, default=600, minimum=0)
        started = self._session_started_at.setdefault(session_key, time.monotonic())
        if max_wall_seconds and time.monotonic() - started > max_wall_seconds:
            return ToolResult(
                success=False,
                output="",
                error=f"Recursive harness wall-clock budget exceeded ({max_wall_seconds}s)",
                metadata={"max_wall_seconds": max_wall_seconds},
            )

        mode = str(args.get("mode") or "read-only").strip().lower()
        write_policy = str(getattr(recursion, "write_policy", "approval") or "approval").lower()
        approval = await _check_write_policy(ctx, args, mode=mode, write_policy=write_policy)
        if approval is not None:
            return approval
        allowed_tools = READ_ONLY_TOOLS if mode != "write" else None
        context_handle = str(args.get("context_handle") or "").strip()
        steering = str(args.get("steering") or "").strip()
        budget_limit = _policy_budget(args, recursion)
        requested_model = _policy_label(
            args,
            "model",
            recursion,
            spec_attr="child_model",
            fallback="",
        )
        requested_sandbox = _policy_label(
            args,
            "sandbox",
            recursion,
            spec_attr="child_sandbox",
            fallback="",
        )
        if bool(args.get("fanout")):
            return await self._run_fanout(
                ctx,
                task=task,
                context_handle=context_handle,
                steering=steering,
                mode=mode,
                allowed_tools=allowed_tools,
                child_depth=child_depth,
                requested_model=requested_model,
                requested_sandbox=requested_sandbox,
                max_children=max_children,
                current_children=count,
                chunk_chars=int(args.get("chunk_chars", 12000) or 12000),
                max_chunks=int(args.get("max_chunks", max_children) or max_children),
                max_parallel=_policy_int(args, "max_parallel", recursion, default=2, minimum=1),
                has_harness_context=bool(has_harness_context),
                budget_limit=budget_limit,
                session_key=session_key,
            )
        child_task = _compose_child_task(task, context_handle=context_handle, steering=steering)
        child_id = f"child-{uuid.uuid4().hex[:8]}"

        budget_error = self._reserve_budget(session_key, budget_limit=budget_limit, units=1.0)
        if budget_error:
            return budget_error
        self._session_children[session_key] = count + 1
        if has_harness_context:
            return await self._run_kernel_child(
                ctx,
                child_task=child_task,
                child_id=child_id,
                child_depth=child_depth,
                mode=mode,
                context_handle=context_handle,
                allowed_tools=allowed_tools,
                requested_model=requested_model,
                requested_sandbox=requested_sandbox,
            )

        try:
            return await self._run_agent_loop_child(
                ctx,
                child_task=child_task,
                child_id=child_id,
                child_depth=child_depth,
                mode=mode,
                context_handle=context_handle,
                allowed_tools=allowed_tools,
                requested_model=requested_model,
                requested_sandbox=requested_sandbox,
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={
                    "child_id": child_id,
                    "delegation_depth": child_depth,
                    "context_handle": context_handle,
                },
            )

    async def _run_fanout(
        self,
        ctx: ToolContext,
        *,
        task: str,
        context_handle: str,
        steering: str,
        mode: str,
        allowed_tools: list[str] | None,
        child_depth: int,
        requested_model: str,
        requested_sandbox: str,
        max_children: int,
        current_children: int,
        chunk_chars: int,
        max_chunks: int,
        max_parallel: int,
        has_harness_context: bool,
        budget_limit: float | None,
        session_key: str,
    ) -> ToolResult:
        if not context_handle:
            return ToolResult(
                success=False,
                output="",
                error="fanout requires context_handle",
            )
        available = max(0, max_children - current_children)
        if available <= 0:
            return ToolResult(
                success=False,
                output="",
                error=f"Recursive harness child limit reached ({current_children}/{max_children})",
                metadata={"child_count": current_children, "max_children": max_children},
            )
        chunks = chunk_context_handle(
            context_handle,
            ctx.working_directory,
            chunk_chars=chunk_chars,
            max_chunks=min(max(1, max_chunks), available),
        )
        if not chunks:
            return ToolResult(success=False, output="", error="context_handle produced no chunks")

        budget_error = self._reserve_budget(
            session_key,
            budget_limit=budget_limit,
            units=float(len(chunks)),
        )
        if budget_error:
            return budget_error
        self._session_children[session_key] = current_children + len(chunks)
        semaphore = asyncio.Semaphore(max(1, min(max_parallel, len(chunks))))

        async def run_one(chunk: ContextChunk) -> ToolResult:
            async with semaphore:
                chunk_child_id = f"child-{uuid.uuid4().hex[:8]}"
                chunk_task = _compose_child_task(
                    task,
                    context_handle=context_handle,
                    steering=steering,
                    chunk_id=chunk.chunk_id,
                    chunk_text=chunk.text,
                )
                if has_harness_context:
                    return await self._run_kernel_child(
                        ctx,
                        child_task=chunk_task,
                        child_id=chunk_child_id,
                        child_depth=child_depth,
                        mode=mode,
                        context_handle=f"{context_handle}#{chunk.chunk_id}",
                        allowed_tools=allowed_tools,
                        requested_model=requested_model,
                        requested_sandbox=requested_sandbox,
                    )
                return await self._run_agent_loop_child(
                    ctx,
                    child_task=chunk_task,
                    child_id=chunk_child_id,
                    child_depth=child_depth,
                    mode=mode,
                    context_handle=f"{context_handle}#{chunk.chunk_id}",
                    allowed_tools=allowed_tools,
                    requested_model=requested_model,
                    requested_sandbox=requested_sandbox,
                )

        results = await asyncio.gather(*(run_one(chunk) for chunk in chunks))
        failures = [item for item in results if not item.success]
        output_parts = [
            (
                f"{item.metadata.get('child_id', 'child')} "
                f"run={item.metadata.get('child_run_id', '(ephemeral)')}\n"
                f"{item.output or item.error or ''}"
            )
            for item in results
        ]
        return ToolResult(
            success=not failures,
            output="\n\n---\n\n".join(output_parts),
            error=f"{len(failures)} child chunks failed" if failures else None,
            metadata={
                "fanout": True,
                "context_handle": context_handle,
                "chunks": len(chunks),
                "failed": len(failures),
                "child_ids": [item.metadata.get("child_id") for item in results],
                "child_run_ids": [
                    item.metadata.get("child_run_id")
                    for item in results
                    if item.metadata.get("child_run_id")
                ],
                "truncated_to_available_children": available < max_chunks,
            },
        )

    def _reserve_budget(
        self,
        session_key: str,
        *,
        budget_limit: float | None,
        units: float,
    ) -> ToolResult | None:
        if budget_limit is None:
            return None
        spent = self._session_budget_spent.get(session_key, 0.0)
        if spent + units > budget_limit:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Recursive harness budget exceeded "
                    f"({spent + units:.2f}/{budget_limit:.2f} spawn units)"
                ),
                metadata={
                    "budget_spent": spent,
                    "budget_requested": units,
                    "max_budget": budget_limit,
                },
            )
        self._session_budget_spent[session_key] = spent + units
        return None

    async def _run_agent_loop_child(
        self,
        ctx: ToolContext,
        *,
        child_task: str,
        child_id: str,
        child_depth: int,
        mode: str,
        context_handle: str,
        allowed_tools: list[str] | None,
        requested_model: str,
        requested_sandbox: str,
    ) -> ToolResult:
        if ctx.sub_agent_runner is None:
            return ToolResult(
                success=False,
                output="",
                error="spawn_harness requires the builtin AgentLoop child runner",
            )
        result = await ctx.sub_agent_runner(
            child_task,
            {
                "delegation_depth": child_depth,
                "allowed_tools": allowed_tools,
                "context_handle": context_handle,
                "requested_model": requested_model,
                "requested_sandbox": requested_sandbox,
                "recursive_child_id": child_id,
            },
        )
        output = (
            f"Child harness {child_id} completed.\n"
            f"Mode: {mode}\n"
            f"Context: {context_handle or '(none)'}\n\n"
            f"{result}"
        )
        return ToolResult(
            success=True,
            output=output,
            metadata={
                "child_id": child_id,
                "delegation_depth": child_depth,
                "context_handle": context_handle,
                "mode": mode,
                "requested_model": requested_model,
                "requested_sandbox": requested_sandbox,
            },
        )

    async def _run_kernel_child(
        self,
        ctx: ToolContext,
        *,
        child_task: str,
        child_id: str,
        child_depth: int,
        mode: str,
        context_handle: str,
        allowed_tools: list[str] | None,
        requested_model: str,
        requested_sandbox: str,
    ) -> ToolResult:
        store = ctx.harness_store
        spec = ctx.harness_spec
        parent_run_id = ctx.harness_run_id
        root_run_id = ctx.harness_root_run_id or parent_run_id
        child_model = requested_model or ctx.harness_model
        child_sandbox = requested_sandbox or ctx.harness_sandbox_backend
        child_session_id = f"{ctx.session_id}:child:{child_id}"
        store.append_event(
            parent_run_id,
            _event(
                "recursive.child.started",
                {
                    "child_id": child_id,
                    "context_handle": context_handle,
                    "mode": mode,
                    "sandbox": child_sandbox,
                    "model": child_model,
                },
                session_id=ctx.session_id,
                run_id=parent_run_id,
            ),
        )
        started = time.monotonic()
        try:
            from ..harness.kernel import HarnessKernel

            child_kernel = HarnessKernel(spec, store=store)
            child_session = await child_kernel.session(child_session_id)
            child_result = await child_session.prompt(
                child_task,
                provider=ctx.harness_provider,
                model=child_model,
                working_directory=ctx.working_directory,
                runtime=ctx.harness_runtime or None,
                sandbox_backend=child_sandbox,
                metadata={
                    "parent_run_id": parent_run_id,
                    "root_run_id": root_run_id,
                    "recursive_child_id": child_id,
                    "context_handle": context_handle,
                    "mode": mode,
                    "delegation_depth": child_depth,
                    "agent_tools": allowed_tools,
                    "requested_model": child_model,
                    "requested_sandbox": child_sandbox,
                },
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            store.append_event(
                parent_run_id,
                _event(
                    "recursive.child.failed",
                    {"child_id": child_id, "error": str(exc), "latency_ms": latency_ms},
                    session_id=ctx.session_id,
                    run_id=parent_run_id,
                ),
            )
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"child_id": child_id},
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        result = child_result.content
        store.append_event(
            parent_run_id,
            _event(
                "recursive.child.completed",
                {
                    "child_run_id": child_result.run_id,
                    "child_id": child_id,
                    "latency_ms": latency_ms,
                    "content_preview": result[:500],
                },
                session_id=ctx.session_id,
                run_id=parent_run_id,
            ),
        )
        output = (
            f"Child harness {child_id} completed.\n"
            f"Run: {child_result.run_id}\n"
            f"Mode: {mode}\n"
            f"Context: {context_handle or '(none)'}\n\n"
            f"{result}"
        )
        return ToolResult(
            success=True,
            output=output,
            metadata={
                "child_id": child_id,
                "child_run_id": child_result.run_id,
                "delegation_depth": child_depth,
                "context_handle": context_handle,
                "mode": mode,
                "requested_model": child_model,
                "requested_sandbox": child_sandbox,
            },
        )


def _policy_int(
    args: dict[str, Any],
    key: str,
    recursion: Any,
    *,
    default: int,
    minimum: int,
) -> int:
    spec_value = getattr(recursion, key, None) if recursion is not None else None
    limit = default if spec_value is None else int(spec_value)
    if key in args and args.get(key) is not None:
        requested = int(args.get(key) or 0)
        limit = min(limit, requested) if recursion is not None else requested
    return max(minimum, limit)


def _policy_budget(args: dict[str, Any], recursion: Any) -> float | None:
    spec_value = getattr(recursion, "max_budget", None) if recursion is not None else None
    requested = args.get("max_budget")
    values = [
        float(value)
        for value in (spec_value, requested)
        if value is not None and float(value) >= 0
    ]
    if not values:
        return None
    return min(values)


def _policy_label(
    args: dict[str, Any],
    key: str,
    recursion: Any,
    *,
    spec_attr: str,
    fallback: str,
) -> str:
    spec_value = getattr(recursion, spec_attr, None) if recursion is not None else None
    if spec_value:
        return str(spec_value)
    return str(args.get(key) or fallback)


async def _check_write_policy(
    ctx: ToolContext,
    args: dict[str, Any],
    *,
    mode: str,
    write_policy: str,
) -> ToolResult | None:
    if mode != "write":
        return None
    if write_policy == "deny":
        return ToolResult(
            success=False,
            output="",
            error="Recursive write-mode child runs are denied by recursion.write_policy=deny",
            metadata={"write_policy": write_policy},
        )
    if write_policy == "allow":
        return None
    manager = getattr(ctx, "permission_manager", None)
    if manager is None:
        return ToolResult(
            success=False,
            output="",
            error="Recursive write-mode child runs require approval, but no permission manager is available",
            metadata={"write_policy": write_policy},
        )
    approved = await manager.request_permission(
        "spawn_harness",
        {
            "mode": "write",
            "task": str(args.get("task") or "")[:500],
            "context_handle": str(args.get("context_handle") or ""),
        },
        description="Approve write-capable recursive child harness run",
    )
    if approved:
        return None
    return ToolResult(
        success=False,
        output="",
        error="Recursive write-mode child run was not approved",
        metadata={"write_policy": write_policy},
    )


def _compose_child_task(
    task: str,
    *,
    context_handle: str,
    steering: str,
    chunk_id: str = "",
    chunk_text: str = "",
) -> str:
    parts = [
        "You are a bounded child harness. Work narrowly and return compact findings.",
        "Do not make broad edits unless the task explicitly requires write mode.",
    ]
    if context_handle:
        parts.append(f"Context handle or fragment: {context_handle}")
    if chunk_id:
        parts.append(f"Chunk: {chunk_id}")
    if chunk_text:
        parts.append(f"Chunk text:\n{chunk_text}")
    if steering:
        parts.append(f"Steering guidance: {steering}")
    parts.append(f"Task: {task}")
    parts.append("Return: findings, evidence paths/lines if available, and confidence.")
    return "\n\n".join(parts)


def _event(event_type: str, data: dict[str, Any], *, session_id: str, run_id: str):
    from ..harness.events import HarnessEvent

    return HarnessEvent(type=event_type, data=data, session_id=session_id, run_id=run_id)


__all__ = ["SpawnHarnessTool"]
