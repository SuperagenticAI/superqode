"""
MCP Search and Execute Tools for SuperQode.

Provides model-accessible tools for:
- mcp_search: Search available MCP tools by relevance (BM25)
- mcp_execute: Execute a specific MCP tool on a specific server

These tools require MCP server configuration in mcp.json.
Enable via SUPERQODE_MCP_SEARCH=1 environment variable.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from ..tools.base import Tool, ToolResult, ToolContext
from ..mcp.search import BM25Search, MCPToolMatch


class MCPSearchTool(Tool):
    """Search available MCP tools by relevance using BM25 ranking."""

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

    def _get_mcp_manager(self):
        """Get MCP client manager if available."""
        if self._mcp_manager_getter:
            try:
                return self._mcp_manager_getter()
            except Exception:
                return None
        return None

    async def _load_tools(self) -> List[MCPToolMatch]:
        """Load and cache MCP tools from all servers."""
        if self._cache_loaded:
            return self._cache

        mcp_manager = self._get_mcp_manager()
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

    def _get_mcp_manager(self):
        """Get MCP client manager if available."""
        if self._mcp_manager_getter:
            try:
                return self._mcp_manager_getter()
            except Exception:
                return None
        return None

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

        mcp_manager = self._get_mcp_manager()
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
    return [MCPSearchTool(mcp_manager_getter), MCPExecuteTool(mcp_manager_getter)]
