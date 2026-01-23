"""
MCP Tool Adapter for Open Responses.

Adapts MCP (Model Context Protocol) tools for use with Open Responses.
Provides bidirectional conversion between MCP and Open Responses tool formats.

Features:
- MCP tool discovery
- Tool execution wrapping
- Result format conversion
- Server management

Usage:
    adapter = MCPToolAdapter()
    adapter.register_mcp_server("filesystem", server)
    tools = adapter.get_openresponses_tools()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable


@dataclass
class MCPTool:
    """An MCP tool definition."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str = ""


@dataclass
class MCPServer:
    """An MCP server reference."""

    name: str
    tools: List[MCPTool] = field(default_factory=list)
    execute_fn: Optional[Callable[[str, Dict[str, Any]], Awaitable[Any]]] = None


class MCPToolAdapter:
    """
    Adapter for MCP tools in Open Responses.

    Bridges MCP tool servers with Open Responses tool format,
    enabling seamless integration of MCP capabilities.

    Usage:
        adapter = MCPToolAdapter()

        # Register an MCP server
        adapter.register_server("filesystem", filesystem_server)

        # Get tools in Open Responses format
        tools = adapter.get_openresponses_tools()

        # Execute a tool call
        result = await adapter.execute_tool("filesystem__read_file", {"path": "test.py"})
    """

    def __init__(self):
        self._servers: Dict[str, MCPServer] = {}
        self._tool_map: Dict[str, MCPTool] = {}

    def register_server(
        self,
        name: str,
        tools: List[Dict[str, Any]],
        execute_fn: Optional[Callable[[str, Dict[str, Any]], Awaitable[Any]]] = None,
    ) -> None:
        """
        Register an MCP server.

        Args:
            name: Server name
            tools: List of tool definitions from MCP server
            execute_fn: Function to execute tools on this server
        """
        mcp_tools = []
        for tool_def in tools:
            tool = MCPTool(
                name=tool_def.get("name", ""),
                description=tool_def.get("description", ""),
                input_schema=tool_def.get("inputSchema", {}),
                server_name=name,
            )
            mcp_tools.append(tool)

            # Register in tool map with namespaced name
            namespaced_name = f"{name}__{tool.name}"
            self._tool_map[namespaced_name] = tool

        self._servers[name] = MCPServer(
            name=name,
            tools=mcp_tools,
            execute_fn=execute_fn,
        )

    def unregister_server(self, name: str) -> None:
        """Unregister an MCP server."""
        if name in self._servers:
            server = self._servers[name]
            for tool in server.tools:
                namespaced_name = f"{name}__{tool.name}"
                if namespaced_name in self._tool_map:
                    del self._tool_map[namespaced_name]
            del self._servers[name]

    def get_openresponses_tools(self) -> List[Dict[str, Any]]:
        """
        Get all registered MCP tools in Open Responses format.

        Returns:
            List of Open Responses tool definitions
        """
        tools = []
        for namespaced_name, tool in self._tool_map.items():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": namespaced_name,
                        "description": f"[{tool.server_name}] {tool.description}",
                        "parameters": tool.input_schema,
                    },
                }
            )
        return tools

    def get_mcp_tools(self, server_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get tools in MCP format.

        Args:
            server_name: Optional filter by server

        Returns:
            List of MCP tool definitions
        """
        tools = []
        for tool in self._tool_map.values():
            if server_name and tool.server_name != server_name:
                continue
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
            )
        return tools

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a tool call.

        Args:
            tool_name: Namespaced tool name (server__tool)
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        if tool_name not in self._tool_map:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
            }

        tool = self._tool_map[tool_name]
        server = self._servers.get(tool.server_name)

        if not server or not server.execute_fn:
            return {
                "success": False,
                "error": f"Server not available: {tool.server_name}",
            }

        try:
            result = await server.execute_fn(tool.name, arguments)
            return {
                "success": True,
                "result": result,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def parse_tool_call(
        self,
        tool_name: str,
    ) -> Optional[tuple[str, str]]:
        """
        Parse a namespaced tool name into server and tool names.

        Args:
            tool_name: Namespaced tool name

        Returns:
            Tuple of (server_name, tool_name) or None
        """
        if "__" in tool_name:
            parts = tool_name.split("__", 1)
            return (parts[0], parts[1])
        return None

    def get_server_names(self) -> List[str]:
        """Get all registered server names."""
        return list(self._servers.keys())

    def get_server_tools(self, server_name: str) -> List[MCPTool]:
        """Get tools for a specific server."""
        server = self._servers.get(server_name)
        return server.tools if server else []


def create_mcp_tool_filter(
    allowed_servers: Optional[List[str]] = None,
    allowed_tools: Optional[List[str]] = None,
    blocked_tools: Optional[List[str]] = None,
) -> Callable[[MCPTool], bool]:
    """
    Create a filter function for MCP tools.

    Args:
        allowed_servers: Only include tools from these servers
        allowed_tools: Only include these specific tools
        blocked_tools: Exclude these specific tools

    Returns:
        Filter function
    """

    def filter_fn(tool: MCPTool) -> bool:
        if allowed_servers and tool.server_name not in allowed_servers:
            return False
        if blocked_tools and tool.name in blocked_tools:
            return False
        if allowed_tools and tool.name not in allowed_tools:
            return False
        return True

    return filter_fn
