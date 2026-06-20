"""Bounded model-authored dynamic workflow tools."""

from __future__ import annotations

import ast
from typing import Any

from .base import Tool, ToolContext, ToolResult
from .spawn_harness import SpawnHarnessTool


MAX_DYNAMIC_STEPS = 12
WORKFLOW_KEYS = {"objective", "max_steps", "max_depth", "max_children", "max_wall_seconds", "stop_on_error"}
STEP_KEYS = {
    "id",
    "task",
    "context_handle",
    "mode",
    "steering",
    "fanout",
    "chunk_chars",
    "max_chunks",
    "max_parallel",
    "model",
    "sandbox",
}


class DynamicWorkflowTool(Tool):
    """Execute a bounded child-harness orchestration plan."""

    @property
    def name(self) -> str:
        return "dynamic_workflow"

    @property
    def description(self) -> str:
        return (
            "Run a bounded dynamic workflow plan. Provide an objective and a list "
            "of child steps; each step delegates through spawn_harness and may use "
            "context_handle fanout. Use this when the task needs runtime-decided "
            "multi-child orchestration over logs, diffs, traces, or repo slices."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "Overall workflow objective to include in the report.",
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered child harness steps to execute.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Stable step id."},
                            "task": {
                                "type": "string",
                                "description": "Self-contained child task.",
                            },
                            "context_handle": {
                                "type": "string",
                                "description": "Optional file:/repo:/diff:/run: handle.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["read-only", "write"],
                                "description": "Child access mode.",
                            },
                            "steering": {
                                "type": "string",
                                "description": "Task-specific guidance for the child.",
                            },
                            "fanout": {
                                "type": "boolean",
                                "description": "Chunk context_handle and run one child per chunk.",
                            },
                            "chunk_chars": {
                                "type": "integer",
                                "description": "Approximate chars per chunk for fanout.",
                            },
                            "max_chunks": {
                                "type": "integer",
                                "description": "Maximum chunks for fanout.",
                            },
                            "max_parallel": {
                                "type": "integer",
                                "description": "Maximum parallel children for fanout.",
                            },
                            "model": {
                                "type": "string",
                                "description": "Optional child model override label.",
                            },
                            "sandbox": {
                                "type": "string",
                                "description": "Optional child sandbox override label.",
                            },
                        },
                        "required": ["task"],
                    },
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum workflow steps allowed for this call.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursive child depth passed to spawn_harness.",
                },
                "max_children": {
                    "type": "integer",
                    "description": "Maximum child runs across this workflow session.",
                },
                "max_wall_seconds": {
                    "type": "integer",
                    "description": "Maximum wall-clock budget for child spawning.",
                },
                "stop_on_error": {
                    "type": "boolean",
                    "description": "Stop executing remaining steps after the first failure.",
                },
            },
            "required": ["objective", "steps"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        objective = str(args.get("objective") or "").strip()
        if not objective:
            return ToolResult(success=False, output="", error="objective is required")
        raw_steps = args.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return ToolResult(success=False, output="", error="steps must be a non-empty list")

        max_steps = min(max(1, int(args.get("max_steps", MAX_DYNAMIC_STEPS) or 1)), MAX_DYNAMIC_STEPS)
        steps = raw_steps[:max_steps]
        truncated = len(raw_steps) > len(steps)
        stop_on_error = bool(args.get("stop_on_error", True))
        spawn = SpawnHarnessTool()
        results: list[dict[str, Any]] = []

        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                item = {
                    "index": index,
                    "id": f"step-{index}",
                    "success": False,
                    "error": "step must be an object",
                }
                results.append(item)
                if stop_on_error:
                    break
                continue
            step_id = str(raw_step.get("id") or f"step-{index}").strip()
            task = str(raw_step.get("task") or "").strip()
            if not task:
                item = {
                    "index": index,
                    "id": step_id,
                    "success": False,
                    "error": "step task is required",
                }
                results.append(item)
                if stop_on_error:
                    break
                continue
            step_args = {
                "task": task,
                "context_handle": str(raw_step.get("context_handle") or ""),
                "mode": str(raw_step.get("mode") or "read-only"),
                "steering": _step_steering(objective, step_id, raw_step),
                "fanout": bool(raw_step.get("fanout", False)),
                "model": str(raw_step.get("model") or ""),
                "sandbox": str(raw_step.get("sandbox") or ""),
                "max_depth": int(args.get("max_depth", 1) or 1),
                "max_children": int(args.get("max_children", 6) or 6),
                "max_wall_seconds": int(args.get("max_wall_seconds", 600) or 600),
            }
            for key in ("chunk_chars", "max_chunks", "max_parallel"):
                if raw_step.get(key) is not None:
                    step_args[key] = int(raw_step[key])
            result = await spawn.execute(step_args, ctx)
            item = {
                "index": index,
                "id": step_id,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "metadata": dict(result.metadata),
            }
            results.append(item)
            if not result.success and stop_on_error:
                break

        failures = [item for item in results if not item.get("success")]
        output = _render_dynamic_workflow(objective, results, truncated=truncated)
        return ToolResult(
            success=not failures,
            output=output,
            error=f"{len(failures)} dynamic workflow step(s) failed" if failures else None,
            metadata={
                "objective": objective,
                "steps": len(results),
                "failed": len(failures),
                "truncated": truncated,
                "child_run_ids": [
                    run_id
                    for item in results
                    for run_id in _child_run_ids(item.get("metadata") or {})
                ],
                "results": [
                    {
                        "id": item.get("id"),
                        "success": item.get("success"),
                        "error": item.get("error"),
                        "metadata": item.get("metadata") or {},
                    }
                    for item in results
                ],
            },
        )


class DynamicWorkflowScriptTool(Tool):
    """Compile a restricted Python-like orchestration script into a workflow plan."""

    @property
    def name(self) -> str:
        return "dynamic_workflow_script"

    @property
    def description(self) -> str:
        return (
            "Compile and run a restricted Python-like dynamic workflow script. "
            "Allowed calls are workflow(...) and step(...), with literal keyword "
            "arguments only. The compiled plan executes through dynamic_workflow."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": (
                        "Restricted script. Example: workflow('Audit auth', max_children=8); "
                        "step('routes', task='Scan route chunk', context_handle='repo:src/routes/**/*.py', fanout=True)"
                    ),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Only compile and return the normalized plan without executing children.",
                },
            },
            "required": ["script"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        script = str(args.get("script") or "")
        if not script.strip():
            return ToolResult(success=False, output="", error="script is required")
        try:
            plan = compile_dynamic_workflow_script(script)
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"script_compiled": False, "exception": type(exc).__name__},
            )
        if bool(args.get("dry_run")):
            return ToolResult(
                success=True,
                output=_render_compiled_plan(plan),
                metadata={"script_compiled": True, "dry_run": True, "plan": plan},
            )
        result = await DynamicWorkflowTool().execute(plan, ctx)
        metadata = dict(result.metadata)
        metadata.update({"script_compiled": True, "plan": plan})
        return ToolResult(
            success=result.success,
            output=result.output,
            error=result.error,
            metadata=metadata,
        )


def compile_dynamic_workflow_script(script: str) -> dict[str, Any]:
    """Compile a literal-only orchestration script into dynamic_workflow args."""
    module = ast.parse(script, mode="exec")
    objective = ""
    workflow_kwargs: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    for statement in module.body:
        call = _statement_call(statement)
        if call is None:
            raise ValueError(
                "dynamic workflow scripts may only contain workflow(...) and step(...) calls"
            )
        if not isinstance(call.func, ast.Name):
            raise ValueError("only direct workflow(...) and step(...) calls are allowed")
        name = call.func.id
        if name == "workflow":
            if objective:
                raise ValueError("workflow(...) may only be declared once")
            parsed = _parse_call_args(call, allowed=WORKFLOW_KEYS)
            if call.args:
                if len(call.args) > 1:
                    raise ValueError("workflow(...) accepts at most one positional objective")
                parsed["objective"] = _literal(call.args[0])
            objective = str(parsed.pop("objective", "")).strip()
            workflow_kwargs.update(parsed)
            continue
        if name == "step":
            parsed = _parse_call_args(call, allowed=STEP_KEYS)
            if call.args:
                if len(call.args) > 1:
                    raise ValueError("step(...) accepts at most one positional id")
                parsed["id"] = _literal(call.args[0])
            if not str(parsed.get("task") or "").strip():
                raise ValueError("step(...) requires task=")
            steps.append(parsed)
            continue
        raise ValueError(f"unsupported call: {name}(...)")
    if not objective:
        raise ValueError("script requires workflow(objective=...) or workflow('objective')")
    if not steps:
        raise ValueError("script requires at least one step(...)")
    return {"objective": objective, "steps": steps, **workflow_kwargs}


def _statement_call(statement: ast.stmt) -> ast.Call | None:
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        return statement.value
    return None


def _parse_call_args(call: ast.Call, *, allowed: set[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            raise ValueError("**kwargs are not allowed in dynamic workflow scripts")
        if keyword.arg not in allowed:
            raise ValueError(f"unsupported argument: {keyword.arg}")
        parsed[keyword.arg] = _literal(keyword.value)
    return parsed


def _literal(node: ast.AST) -> Any:
    try:
        value = ast.literal_eval(node)
    except Exception as exc:
        raise ValueError("only literal strings, numbers, booleans, and nulls are allowed") from exc
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("only scalar literal values are allowed")


def _render_compiled_plan(plan: dict[str, Any]) -> str:
    lines = [f"Compiled dynamic workflow: {plan['objective']}"]
    lines.append(f"Steps: {len(plan['steps'])}")
    for step in plan["steps"]:
        lines.append(f"- {step.get('id') or '(unnamed)'}: {step.get('task')}")
    return "\n".join(lines)


def _step_steering(objective: str, step_id: str, step: dict[str, Any]) -> str:
    steering = str(step.get("steering") or "").strip()
    parts = [f"Dynamic workflow objective: {objective}", f"Step id: {step_id}"]
    if steering:
        parts.append(steering)
    return "\n".join(parts)


def _child_run_ids(metadata: dict[str, Any]) -> list[str]:
    if metadata.get("child_run_id"):
        return [str(metadata["child_run_id"])]
    ids = metadata.get("child_run_ids")
    if isinstance(ids, list):
        return [str(item) for item in ids if item]
    return []


def _render_dynamic_workflow(
    objective: str, results: list[dict[str, Any]], *, truncated: bool
) -> str:
    lines = [f"Dynamic workflow objective: {objective}", f"Steps executed: {len(results)}"]
    if truncated:
        lines.append("Plan was truncated to the configured max_steps.")
    for item in results:
        status = "ok" if item.get("success") else "failed"
        lines.append("")
        lines.append(f"[{item.get('id')}] {status}")
        metadata = item.get("metadata") or {}
        child_ids = _child_run_ids(metadata)
        if child_ids:
            lines.append(f"child_runs: {', '.join(child_ids)}")
        if item.get("error"):
            lines.append(f"error: {item['error']}")
        output = str(item.get("output") or "").strip()
        if output:
            lines.append(output[:4000])
    return "\n".join(lines)


__all__ = ["DynamicWorkflowScriptTool", "DynamicWorkflowTool", "compile_dynamic_workflow_script"]
