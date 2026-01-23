"""
Batch Tool - Execute multiple tools in parallel.
Enables parallel execution of up to 10 tools. Recursive batch calls are blocked.
"""

import asyncio
from typing import Any, Dict, List

from .base import Tool, ToolResult, ToolContext

MAX_CONCURRENT = 10
BATCH_TOOL_NAME = "batch"


class BatchTool(Tool):
    """Execute multiple tool calls in parallel."""

    @property
    def name(self) -> str:
        return BATCH_TOOL_NAME

    @property
    def description(self) -> str:
        return (
            "Execute multiple tool calls in parallel (up to 10). "
            "Provide a list of {tool, parameters} objects. "
            "Useful for parallel reads, searches, or independent operations. "
            "Cannot include batch itself. Results are returned together."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tool_calls": {
                    "type": "array",
                    "description": "Array of tool calls to execute in parallel",
                    "minItems": 1,
                    "maxItems": MAX_CONCURRENT,
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "description": "Name of the tool to execute",
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Parameters for the tool",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["tool", "parameters"],
                    },
                }
            },
            "required": ["tool_calls"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        tool_calls = args.get("tool_calls", [])
        if not tool_calls:
            return ToolResult(success=False, output="", error="At least one tool call is required")

        if len(tool_calls) > MAX_CONCURRENT:
            return ToolResult(
                success=False,
                output="",
                error=f"At most {MAX_CONCURRENT} tool calls allowed, got {len(tool_calls)}",
            )

        # Block recursive batch
        names = [t.get("tool") or t.get("tool_name") for t in tool_calls]
        if BATCH_TOOL_NAME in names:
            return ToolResult(
                success=False,
                output="",
                error="Recursive batch calls are not allowed",
            )

        registry = getattr(ctx, "tool_registry", None)
        if not registry:
            return ToolResult(
                success=False,
                output="",
                error="Batch tool requires a tool registry in context",
            )

        async def run_one(tc: Dict[str, Any]) -> ToolResult:
            name = tc.get("tool") or tc.get("tool_name", "")
            params = tc.get("parameters") or tc.get("params") or {}
            tool = registry.get(name)
            if not tool:
                return ToolResult(success=False, output="", error=f"Unknown tool: {name}")
            try:
                return await tool.execute(params, ctx)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Tool error: {str(e)}")

        tasks = [run_one(t) for t in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to ToolResult
        out_results: List[ToolResult] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                name = tool_calls[i].get("tool", "?")
                out_results.append(ToolResult(success=False, output="", error=f"{name}: {str(r)}"))
            else:
                out_results.append(r)

        # Format output
        lines = []
        for i, (tc, res) in enumerate(zip(tool_calls, out_results)):
            name = tc.get("tool", "?")
            status = "OK" if res.success else "FAILED"
            lines.append(f"[{i + 1}] {name}: {status}")
            lines.append(res.output if res.success else (res.error or ""))
            lines.append("")
        output = "\n".join(lines).strip()

        return ToolResult(
            success=all(r.success for r in out_results),
            output=output,
            error=None if all(r.success for r in out_results) else "One or more tools failed",
            metadata={
                "results": [
                    {"success": r.success, "output": r.output, "error": r.error}
                    for r in out_results
                ]
            },
        )
