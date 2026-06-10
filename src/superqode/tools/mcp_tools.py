"""
MCP Search and Execute Tools for SuperQode.

Provides model-accessible tools for:
- mcp_search: Search available MCP tools by relevance (BM25)
- mcp_execute: Execute a specific MCP tool on a specific server
- mcp_list_resources / mcp_read_resource: Discover and read MCP resources
- mcp_list_prompts / mcp_get_prompt: Discover and expand MCP prompt templates

These tools require MCP server configuration in mcp.json.
Enable via SUPERQODE_MCP_SEARCH=1 environment variable.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from typing import Any, Dict, List, Optional

from ..tools.base import Tool, ToolResult, ToolContext
from ..mcp.search import BM25Search, MCPToolMatch


class MCPSearchTool(Tool):
    """Search available MCP tools by relevance using BM25 ranking."""

    read_only = True

    def __init__(self, mcp_manager_getter=None):
        """
        Initialize MCP search tool.

        Args:
            mcp_manager_getter: Optional callable that returns MCPClientManager instance
        """
        self._mcp_manager_getter = mcp_manager_getter
        self._cache: List[MCPToolMatch] = []
        self._cache_loaded = False

    @property
    def name(self) -> str:
        return "mcp_search"

    @property
    def description(self) -> str:
        return """Search for relevant MCP tools by query.

Uses BM25 ranking algorithm to find the most relevant tools across all
connected MCP servers. Returns tool names, descriptions, servers, and schemas.

Use this to discover available MCP tools before executing them with mcp_execute.

Example: Search for "web search" to find EXA or other search tools."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'web search', 'file read', 'database query')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 10,
                },
                "use_bm25": {
                    "type": "boolean",
                    "description": "Use BM25 ranking algorithm (default: true). Set false for simple keyword matching.",
                    "default": True,
                },
                "server": {
                    "type": "string",
                    "description": "Filter tools to a specific server name (optional)",
                },
            },
            "required": ["query"],
        }

    async def _get_mcp_manager(self):
        """Get MCP client manager if available."""
        if self._mcp_manager_getter:
            try:
                manager = self._mcp_manager_getter()
                if inspect.isawaitable(manager):
                    manager = await manager
                return manager
            except Exception:
                return None
        return await _get_default_mcp_manager()

    async def _load_tools(self) -> List[MCPToolMatch]:
        """Load and cache MCP tools from all servers."""
        if self._cache_loaded:
            return self._cache

        mcp_manager = await self._get_mcp_manager()
        if not mcp_manager:
            return []

        try:
            mcp_tools = mcp_manager.list_all_tools()
            self._cache = [
                MCPToolMatch(
                    server=tool.server_id,
                    name=f"mcp_{tool.server_id}_{tool.name}",
                    description=tool.description,
                    input_schema=tool.input_schema,
                    original_name=tool.name,
                )
                for tool in mcp_tools
            ]
        except Exception:
            self._cache = []

        self._cache_loaded = True
        return self._cache

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query", "")
        limit = args.get("limit", 10)
        use_bm25 = args.get("use_bm25", True)
        server_filter = args.get("server")

        if not query:
            return ToolResult(
                success=False,
                output="",
                error="Search query is required",
            )

        tools = await self._load_tools()

        if not tools:
            return ToolResult(
                success=True,
                output="No MCP servers configured. Add MCP servers to mcp.json to enable tool search.",
                metadata={"query": query, "count": 0},
            )

        filtered_tools = tools
        if server_filter:
            filtered_tools = [t for t in tools if t.server == server_filter]

        if use_bm25:
            results = BM25Search.search(filtered_tools, query, limit)
        else:
            from ..mcp.search import keyword_search

            results = keyword_search(filtered_tools, query, limit)

        if not results:
            return ToolResult(
                success=True,
                output=f"No matching MCP tools found for: {query}",
                metadata={"query": query, "count": 0},
            )

        output_lines = [f"MCP Tools matching: {query}\n"]

        for i, tool in enumerate(results, 1):
            output_lines.append(f"{i}. {tool.name}")
            output_lines.append(f"   Server: {tool.server}")
            output_lines.append(f"   Tool: {tool.original_name}")
            output_lines.append(f"   Description: {tool.description[:150]}...")
            output_lines.append(f"   Score: {tool.score:.2f}")
            output_lines.append("")

        output_lines.append("---")
        output_lines.append("To execute a tool, use mcp_execute with server and tool name.")

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            metadata={
                "query": query,
                "count": len(results),
                "tools": [
                    {
                        "server": t.server,
                        "tool": t.original_name,
                        "name": t.name,
                        "score": t.score,
                    }
                    for t in results
                ],
            },
        )


class MCPExecuteTool(Tool):
    """Execute a specific MCP tool on a specific server."""

    def __init__(self, mcp_manager_getter=None):
        """
        Initialize MCP execute tool.

        Args:
            mcp_manager_getter: Optional callable that returns MCPClientManager instance
        """
        self._mcp_manager_getter = mcp_manager_getter

    @property
    def name(self) -> str:
        return "mcp_execute"

    @property
    def description(self) -> str:
        return """Execute a specific MCP tool on a specific MCP server.

Requires server name (from mcp_search results), tool name, and arguments.
Returns the tool's output or error.

Example: Execute web_search on exa server with query argument."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "MCP server name (e.g., 'exa', 'filesystem', 'github')",
                },
                "tool": {
                    "type": "string",
                    "description": "Tool name to execute (e.g., 'web_search', 'read_file')",
                },
                "arguments": {
                    "type": "object",
                    "description": "Tool arguments as key-value pairs",
                },
            },
            "required": ["server", "tool"],
        }

    async def _get_mcp_manager(self):
        """Get MCP client manager if available."""
        if self._mcp_manager_getter:
            try:
                manager = self._mcp_manager_getter()
                if inspect.isawaitable(manager):
                    manager = await manager
                return manager
            except Exception:
                return None
        return await _get_default_mcp_manager()

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        server = args.get("server", "")
        tool = args.get("tool", "")
        arguments = args.get("arguments", {})

        if not server or not tool:
            return ToolResult(
                success=False,
                output="",
                error="Both 'server' and 'tool' are required",
            )

        mcp_manager = await self._get_mcp_manager()
        if not mcp_manager:
            return ToolResult(
                success=False,
                output="",
                error="MCP client not available. Configure MCP servers in mcp.json.",
            )

        try:
            result = await mcp_manager.execute_tool(server, tool, arguments)

            if result.is_error:
                return ToolResult(
                    success=False,
                    output="",
                    error=result.error_message or "MCP tool execution failed",
                )

            output_parts = []
            for item in result.content:
                if isinstance(item, dict):
                    output_parts.append(item.get("text", str(item)))
                else:
                    output_parts.append(str(item))

            return ToolResult(
                success=True,
                output="\n".join(output_parts) if output_parts else "(no output)",
                metadata={"server": server, "tool": tool},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"MCP execution error: {str(e)}",
            )


class MCPListResourcesTool(Tool):
    """List resources exposed by connected MCP servers."""

    read_only = True

    def __init__(self, mcp_manager_getter=None):
        self._mcp_manager_getter = mcp_manager_getter

    @property
    def name(self) -> str:
        return "mcp_list_resources"

    @property
    def description(self) -> str:
        return "List readable resources exposed by connected MCP servers."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Optional MCP server name to filter resources by",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of resources to return (default: 50)",
                    "default": 50,
                },
            },
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = await _resolve_mcp_manager(self._mcp_manager_getter)
        if not manager:
            return ToolResult(success=False, output="", error="MCP client not available")

        server = args.get("server")
        limit = int(args.get("limit", 50) or 50)
        resources = manager.list_all_resources()
        if server:
            resources = [r for r in resources if r.server_id == server]
        resources = resources[: max(0, limit)]

        if not resources:
            return ToolResult(
                success=True,
                output="No MCP resources found.",
                metadata={"count": 0, "server": server},
            )

        lines = ["MCP Resources:"]
        payload = []
        for resource in resources:
            lines.append(f"- {resource.server_id}: {resource.uri}")
            if resource.name:
                lines.append(f"  Name: {resource.name}")
            if resource.description:
                lines.append(f"  Description: {resource.description}")
            if resource.mime_type:
                lines.append(f"  MIME: {resource.mime_type}")
            payload.append(
                {
                    "server": resource.server_id,
                    "uri": resource.uri,
                    "name": resource.name,
                    "description": resource.description,
                    "mime_type": resource.mime_type,
                }
            )

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={"count": len(resources), "resources": payload},
        )


class MCPReadResourceTool(Tool):
    """Read a resource from an MCP server."""

    read_only = True

    def __init__(self, mcp_manager_getter=None):
        self._mcp_manager_getter = mcp_manager_getter

    @property
    def name(self) -> str:
        return "mcp_read_resource"

    @property
    def description(self) -> str:
        return "Read a resource exposed by an MCP server. Use mcp_list_resources first."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "MCP server name"},
                "uri": {"type": "string", "description": "Resource URI to read"},
            },
            "required": ["server", "uri"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        server = args.get("server", "")
        uri = args.get("uri", "")
        if not server or not uri:
            return ToolResult(
                success=False, output="", error="Both 'server' and 'uri' are required"
            )

        manager = await _resolve_mcp_manager(self._mcp_manager_getter)
        if not manager:
            return ToolResult(success=False, output="", error="MCP client not available")

        content = await manager.read_resource(server, uri)
        if content is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Resource not found or unreadable: {server}:{uri}",
            )

        output = content.text if content.text is not None else "[binary resource]"
        return ToolResult(
            success=True,
            output=output,
            metadata={
                "server": server,
                "uri": uri,
                "mime_type": content.mime_type,
                "has_blob": content.blob is not None,
            },
        )


class MCPListPromptsTool(Tool):
    """List prompt templates exposed by connected MCP servers."""

    read_only = True

    def __init__(self, mcp_manager_getter=None):
        self._mcp_manager_getter = mcp_manager_getter

    @property
    def name(self) -> str:
        return "mcp_list_prompts"

    @property
    def description(self) -> str:
        return "List prompt templates exposed by connected MCP servers."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Optional MCP server name to filter prompts by",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of prompts to return (default: 50)",
                    "default": 50,
                },
            },
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = await _resolve_mcp_manager(self._mcp_manager_getter)
        if not manager:
            return ToolResult(success=False, output="", error="MCP client not available")

        server = args.get("server")
        limit = int(args.get("limit", 50) or 50)
        prompts = manager.list_all_prompts()
        if server:
            prompts = [p for p in prompts if p.server_id == server]
        prompts = prompts[: max(0, limit)]

        if not prompts:
            return ToolResult(
                success=True,
                output="No MCP prompts found.",
                metadata={"count": 0, "server": server},
            )

        lines = ["MCP Prompts:"]
        payload = []
        for prompt in prompts:
            arg_names = [arg.name if hasattr(arg, "name") else str(arg) for arg in prompt.arguments]
            lines.append(f"- {prompt.server_id}: {prompt.name}")
            if prompt.description:
                lines.append(f"  Description: {prompt.description}")
            if arg_names:
                lines.append(f"  Arguments: {', '.join(arg_names)}")
            payload.append(
                {
                    "server": prompt.server_id,
                    "name": prompt.name,
                    "description": prompt.description,
                    "arguments": arg_names,
                }
            )

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={"count": len(prompts), "prompts": payload},
        )


class MCPGetPromptTool(Tool):
    """Expand a prompt template from an MCP server."""

    read_only = True

    def __init__(self, mcp_manager_getter=None):
        self._mcp_manager_getter = mcp_manager_getter

    @property
    def name(self) -> str:
        return "mcp_get_prompt"

    @property
    def description(self) -> str:
        return "Get an MCP prompt template result. Use mcp_list_prompts first."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "MCP server name"},
                "prompt": {"type": "string", "description": "Prompt template name"},
                "arguments": {
                    "type": "object",
                    "description": "Prompt arguments as string key-value pairs",
                },
            },
            "required": ["server", "prompt"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        server = args.get("server", "")
        prompt = args.get("prompt", "")
        arguments = args.get("arguments", {}) or {}
        if not server or not prompt:
            return ToolResult(
                success=False,
                output="",
                error="Both 'server' and 'prompt' are required",
            )

        manager = await _resolve_mcp_manager(self._mcp_manager_getter)
        if not manager:
            return ToolResult(success=False, output="", error="MCP client not available")

        result = await manager.get_prompt(
            server, prompt, {str(k): str(v) for k, v in arguments.items()}
        )
        if result is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Prompt not found or failed: {server}:{prompt}",
            )

        lines = []
        if result.description:
            lines.append(f"Description: {result.description}")
        for message in result.messages:
            lines.append(f"{message.role}: {message.content}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={
                "server": server,
                "prompt": prompt,
                "message_count": len(result.messages),
            },
        )


def create_mcp_tools(
    mcp_manager_getter=None,
) -> List[Tool]:
    """
    Create MCP search and execute tools.

    Args:
        mcp_manager_getter: Callable that returns MCPClientManager instance

    Returns:
        List of MCP tools
    """
    return [
        MCPSearchTool(mcp_manager_getter),
        MCPExecuteTool(mcp_manager_getter),
        MCPListResourcesTool(mcp_manager_getter),
        MCPReadResourceTool(mcp_manager_getter),
        MCPListPromptsTool(mcp_manager_getter),
        MCPGetPromptTool(mcp_manager_getter),
    ]


async def _resolve_mcp_manager(mcp_manager_getter=None):
    if mcp_manager_getter:
        try:
            manager = mcp_manager_getter()
            if inspect.isawaitable(manager):
                manager = await manager
            return manager
        except Exception:
            return None
    return await _get_default_mcp_manager()


async def _get_default_mcp_manager():
    """Return the global MCP manager and auto-connect configured servers.

    This makes MCP search/execute usable from BYOK and Local native sessions
    once `SUPERQODE_MCP_SEARCH=1` is enabled, so that configured MCP servers
    are available to the active agent.
    """
    try:
        from superqode.mcp.integration import get_mcp_manager

        manager = await get_mcp_manager()
        status = manager.get_status_summary()
        if status.get("total_servers", 0) and not status.get("connected", 0):
            await manager.connect_all()
        return manager
    except Exception:
        return None


def get_mcp_tools(mcp_manager_getter=None) -> List[Tool]:
    """Backward-compatible alias used by AgentLoop include_mcp wiring."""
    return create_mcp_tools(mcp_manager_getter)
