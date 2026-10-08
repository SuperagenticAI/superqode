"""SuperQode-owned tools exposed to Codex through its dynamic-tool protocol."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from superqode.tools.base import Tool, ToolRegistry, ToolResult


class MemorySearch(Tool):
    name = "memory_search"
    description = "Search SuperQode's local project memory."
    read_only = True
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    async def execute(self, args, ctx):
        from superqode.memory import create_memory_provider

        def read():
            provider = create_memory_provider(project_root=ctx.working_directory)
            return [
                item.to_dict()
                for item in provider.search(args["query"], limit=args.get("limit", 8))
            ]

        return ToolResult(success=True, output=json.dumps(await asyncio.to_thread(read)))


class MemoryRemember(Tool):
    name = "memory_remember"
    description = "Save a note in SuperQode's local project memory. Requires host permission."
    parameters = {
        "type": "object",
        "properties": {"content": {"type": "string", "minLength": 1}},
        "required": ["content"],
        "additionalProperties": False,
    }

    async def execute(self, args, ctx):
        from superqode.memory import create_memory_provider

        record = await asyncio.to_thread(
            lambda: create_memory_provider(project_root=ctx.working_directory).remember(
                args["content"]
            )
        )
        return ToolResult(success=True, output=json.dumps(record.to_dict()))


class WorkOrdersRead(Tool):
    name = "workorders_read"
    description = "List SuperQode WorkOrders or inspect one by reference. Delivery and Git operations stay with SuperQode."
    read_only = True
    parameters = {
        "type": "object",
        "properties": {
            "reference": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "additionalProperties": False,
    }

    async def execute(self, args, ctx):
        from superqode.workorders.store import WorkOrderStore
        from superqode.systemone.state import redact_evidence

        def read():
            path = ctx.working_directory / ".superqode/workorders/store.sqlite3"
            if not path.is_file():
                return []
            store = WorkOrderStore.read_only(path)
            if args.get("reference"):
                return store.get(args["reference"]).to_dict()
            return [order.to_dict() for order in store.list(limit=args.get("limit", 20))]

        return ToolResult(
            success=True,
            output=json.dumps(redact_evidence(await asyncio.to_thread(read)), default=str),
        )


def host_tool_registry(tools=None):
    """Only host capabilities; never duplicate Codex's exec/file/git tools."""
    registry = ToolRegistry()
    for tool in (MemorySearch(), MemoryRemember(), WorkOrdersRead()):
        registry.register(tool)
    from superqode.tools.mcp_tools import get_mcp_tools

    for tool in get_mcp_tools():
        registry.register(tool)
    for tool in tools.list() if tools is not None else ():
        if tool.name.startswith(("memory_", "workorder", "mcp_")):
            registry.register(tool)
    return registry


class CodexHostTools:
    def _init_host_tools(self, tools, gateway=None, hooks=None, on_systemone=None):
        self._host_tools = host_tool_registry(tools)
        self._host_gateway = gateway
        self._host_hooks = hooks
        self._host_on_systemone = on_systemone
        self._host_loop = None
        self._host_tool_lock = asyncio.Lock()

    def _dynamic_tool_specs(self):
        return [
            {
                "type": "function",
                "name": "superqode_" + tool.name,
                "description": tool.description,
                "inputSchema": tool.parameters,
                "deferLoading": False,
            }
            for tool in self._host_tools.active_tools()
        ]

    async def _dynamic_tool_call(self, params):
        from superqode.agent.loop import AgentLoop, ToolApprovalRequired
        from superqode.tools.approval_receipts import issue_receipt

        def response(result):
            return {
                "success": result.success,
                "contentItems": [{"type": "inputText", "text": result.to_message()}],
            }

        name = str(params.get("tool") or "")
        if params.get("namespace") or not name.startswith("superqode_"):
            return response(ToolResult(False, "", "Unknown SuperQode dynamic tool"))
        name = name.removeprefix("superqode_")
        if self._host_tools.get(name) is None or not self.config.tools_enabled:
            return response(ToolResult(False, "", "SuperQode tool is unavailable"))
        args = params.get("arguments")
        if not isinstance(args, dict):
            return response(ToolResult(False, "", "Tool arguments must be an object"))
        call_id = str(params.get("callId") or "")
        if not call_id:
            return response(ToolResult(False, "", "Missing dynamic tool call id"))
        async with self._host_tool_lock:
            if self._host_loop is None:
                self._host_loop = AgentLoop(
                    gateway=self._host_gateway,
                    tools=self._host_tools,
                    config=replace(self.config, enable_session_storage=False),
                    permission_manager=self._permission_manager,
                    hooks=self._host_hooks,
                    on_systemone=self._host_on_systemone,
                    allow_peer_agents=False,
                )
                self._host_loop.pause_on_approval = True
            loop = self._host_loop
            loop.session_id = self.session_id
            loop.config.plan_mode = self._collaboration_mode == "plan" or self._turn_read_only
            if name == "mcp_execute":
                # Check the discovery wrapper, then execute under the real MCP
                # capability identity so tool-specific policy and audit apply.
                from superqode.tools.permissions import Permission
                from superqode.tools.mcp_tools import MCPProxyTool

                permission = self._permission_manager.check_permission(name, args)
                choice = await self._approval_choice(name, args, permission)
                if choice == "cancel":
                    self.cancel()
                if choice != "accept":
                    return response(ToolResult(False, "", "MCP execution declined"))
                manager = await self._host_tools.get(name)._get_mcp_manager()
                server, tool_name = args.get("server"), args.get("tool")
                tool = (
                    manager.get_tool(server, tool_name)
                    if manager and server and tool_name
                    else None
                )
                if tool is None:
                    return response(
                        ToolResult(
                            False,
                            "",
                            "Unknown MCP capability; discover it with superqode_mcp_search first",
                        )
                    )
                name = f"mcp_{server}_{tool_name}"
                self._host_tools.register(
                    MCPProxyTool(
                        exposed_name=name,
                        server=server,
                        original_name=tool_name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                        read_only=False,
                        mcp_manager_getter=lambda: manager,
                    )
                )
                args = args.get("arguments") or {}
                if not isinstance(args, dict):
                    return response(ToolResult(False, "", "MCP arguments must be an object"))
            try:
                result = await loop._execute_tool(name, args, call_id)
            except ToolApprovalRequired:
                pending = loop._pending_approval
                try:
                    from superqode.tools.permissions import Permission

                    permission = self._permission_manager.check_permission(name, args)
                    choice = await self._approval_choice(
                        name,
                        {"toolArguments": args, "_codex_call_id": call_id},
                        Permission.DENY if permission == Permission.DENY else Permission.ASK,
                    )
                    if choice != "accept":
                        if choice == "cancel":
                            self.cancel()
                        return response(ToolResult(False, "", "SuperQode tool permission declined"))
                    issue_receipt(loop, pending)
                    result = await loop._execute_tool(name, args, call_id)
                finally:
                    loop._pending_approval = None
                    loop._approval_receipts.pop(call_id, None)
            return response(result)
