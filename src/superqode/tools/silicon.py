"""Small model-facing tools for Silicon."""

import json

from .base import Tool, ToolResult
from .permissions import Permission
from .search_tools import GrepTool


def preview(value: str, limit: int = 1800) -> str:
    data = value.encode("utf-8")
    if len(data) <= limit:
        return value
    return data[:limit].decode("utf-8", errors="ignore") + "\n[output shortened]"


class SiliconSearch(Tool):
    read_only = True
    name = "search"
    description = "Find matching lines in the repository."

    def __init__(self, mcp=None):
        self.mcp = mcp
        self.grep = GrepTool()
        self.grep.MAX_RESULTS = 20

    @property
    def parameters(self):
        properties = {"query": {"type": "string"}, "path": {"type": "string"}}
        if self.mcp is not None:
            properties["scope"] = {"type": "string", "enum": ["repo", "mcp"]}
        return {"type": "object", "properties": properties, "required": ["query"]}

    async def execute(self, args, ctx):
        query = args["query"]
        if args.get("scope") == "mcp":
            if self.mcp is None:
                return ToolResult(False, "", "MCP is disabled for this harness")
            terms = query.casefold().split()
            matches = [
                tool
                for tool in self.mcp.silicon_tools()
                if all(
                    term in f"{tool.server_id}/{tool.name} {tool.description}".casefold()
                    for term in terms
                )
            ]
            return ToolResult(
                True,
                preview(
                    "\n".join(
                        f"{tool.server_id}/{tool.name}: {tool.description[:110]}\n"
                        f"{json.dumps(tool.input_schema, ensure_ascii=False, separators=(',', ':'))}"
                        for tool in matches[:3]
                    )
                )
                or "No matching MCP capabilities.",
            )
        result = await self.grep.execute({"pattern": query, "path": args.get("path", ".")}, ctx)
        result.output = preview(result.output)
        return result


class SiliconExecute(Tool):
    name = "execute"
    description = "Call one discovered MCP capability with JSON arguments."
    parameters = {
        "type": "object",
        "properties": {
            "capability": {"type": "string", "description": "Exact server/tool from search"},
            "arguments_json": {"type": "string", "description": "JSON object with arguments"},
        },
        "required": ["capability", "arguments_json"],
    }

    def __init__(self, mcp=None):
        self.mcp = mcp

    async def execute(self, args, ctx):
        if self.mcp is None:
            return ToolResult(False, "", "MCP is disabled for this harness")
        server, _, name = args["capability"].partition("/")
        tool = next(
            (t for t in self.mcp.silicon_tools() if (t.server_id, t.name) == (server, name)), None
        )
        if tool is None:
            return ToolResult(False, "", "Use a capability from MCP search")
        try:
            arguments = json.loads(args["arguments_json"])
        except ValueError:
            return ToolResult(False, "", "MCP arguments must be a JSON object")
        if not isinstance(arguments, dict):
            return ToolResult(False, "", "MCP arguments must be a JSON object")
        if (
            ctx.permission_manager is None
            or ctx.permission_manager.check_permission(f"mcp_{server}_{name}", arguments)
            is not Permission.ALLOW
        ):
            return ToolResult(False, "", "This MCP capability requires an explicit tool permission")
        result = await self.mcp.execute(server, name, arguments, timeout=25)
        return ToolResult(
            result.success, preview(result.output), preview(result.error or "") or None
        )


class SiliconCodeExecute(SiliconExecute):
    """Experimental single-call composition, sharing the typed call's policy."""

    description = "Run Python in Monty. Use tool_call('server/tool', arguments) once."
    parameters = {
        "type": "object",
        "properties": {"code": {"type": "string", "maxLength": 3000}},
        "required": ["code"],
    }

    async def execute(self, args, ctx):
        import asyncio
        from dataclasses import replace

        from .composition import ToolComposition
        from .monty_tool import _load_monty, run_monty_snippet

        module = _load_monty()
        if module is None:
            return ToolResult(
                False, "", "Install the optional SuperQode Monty runtime for Code Mode"
            )

        async def invoke(capability, arguments, _call_id):
            result = await super(SiliconCodeExecute, self).execute(
                {"capability": capability, "arguments_json": json.dumps(arguments)}, ctx
            )
            result.metadata["sensitive"] = True
            return result

        composition = ToolComposition(replace(ctx, execute_tool=invoke), deadline_seconds=10)
        composition.MAX_CALLS = 1
        try:
            result = await asyncio.to_thread(
                run_monty_snippet,
                module,
                args["code"],
                external_lookup={"tool_call": composition.call},
            )
        except Exception as exc:
            return ToolResult(False, "", preview(str(exc), 500))
        finally:
            await composition.close()
        return ToolResult(True, preview(result))
