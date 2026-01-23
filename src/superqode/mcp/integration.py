"""MCP integration utilities for SuperQode.

This module provides high-level integration functions for using MCP
within SuperQode' agent system.
"""

import asyncio
import logging
from typing import Any

from superqode.mcp.client import MCPClientManager, MCPConnectionState
from superqode.mcp.config import (
    MCPServerConfig,
    MCPStdioConfig,
    MCPHttpConfig,
    MCPSSEConfig,
    load_mcp_config,
    save_mcp_config,
    create_default_mcp_config,
)
from superqode.mcp.types import (
    MCPTool,
    MCPToolResult,
    MCPResource,
    MCPPrompt,
    ServerCapability,
    LoggingLevel,
)

logger = logging.getLogger(__name__)

# Global MCP client manager instance
_mcp_manager: MCPClientManager | None = None


async def get_mcp_manager() -> MCPClientManager:
    """Get or create the global MCP client manager."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPClientManager()
        await _mcp_manager.__aenter__()
        _mcp_manager.load_config()
    return _mcp_manager


async def shutdown_mcp_manager() -> None:
    """Shutdown the global MCP client manager."""
    global _mcp_manager
    if _mcp_manager is not None:
        await _mcp_manager.__aexit__(None, None, None)
        _mcp_manager = None


async def initialize_mcp(auto_connect: bool = True) -> dict[str, bool]:
    """Initialize MCP support and optionally connect to servers."""
    manager = await get_mcp_manager()
    if auto_connect:
        return await manager.connect_all()
    return {}


def get_mcp_tools_for_agent() -> list[dict[str, Any]]:
    """Get MCP tools formatted for agent tool use.

    Returns tools in a format suitable for LLM function calling.
    """
    if _mcp_manager is None:
        return []

    tools = _mcp_manager.list_all_tools()
    return [
        {
            "type": "function",
            "function": {
                "name": f"mcp_{tool.server_id}_{tool.name}",
                "description": f"[MCP:{tool.server_id}] {tool.description}",
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


async def execute_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> MCPToolResult:
    """Execute an MCP tool by name.

    Handles the mcp_{server_id}_{tool_name} format used by agents.
    """
    if _mcp_manager is None:
        return MCPToolResult(
            content=[],
            is_error=True,
            error_message="MCP not initialized",
        )

    # Parse tool name: mcp_{server_id}_{tool_name}
    if tool_name.startswith("mcp_"):
        parts = tool_name[4:].split("_", 1)
        if len(parts) == 2:
            server_id, actual_tool_name = parts
            return await _mcp_manager.call_tool(server_id, actual_tool_name, arguments)

    # Try to find tool across all servers
    result = _mcp_manager.find_tool(tool_name)
    if result:
        server_id, tool = result
        return await _mcp_manager.call_tool(server_id, tool.name, arguments)

    return MCPToolResult(
        content=[],
        is_error=True,
        error_message=f"Tool not found: {tool_name}",
    )


def format_tool_result_for_agent(result: MCPToolResult) -> str:
    """Format an MCP tool result for agent consumption."""
    if result.is_error:
        return f"Error: {result.error_message}"

    output_parts = []
    for item in result.content:
        if item.get("type") == "text":
            output_parts.append(item.get("text", ""))
        elif item.get("type") == "image":
            output_parts.append(f"[Image: {item.get('mimeType', 'image')}]")
        elif item.get("type") == "audio":
            output_parts.append(f"[Audio: {item.get('mimeType', 'audio')}]")
        elif item.get("type") == "resource":
            output_parts.append(f"[Resource: {item.get('uri', 'unknown')}]")
        else:
            output_parts.append(str(item))

    return "\n".join(output_parts)


class MCPToolHandler:
    """Handler for MCP tools within SuperQode' agent system."""

    def __init__(self, manager: MCPClientManager | None = None):
        self._manager = manager

    @property
    def manager(self) -> MCPClientManager | None:
        return self._manager or _mcp_manager

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name refers to an MCP tool."""
        if tool_name.startswith("mcp_"):
            return True
        if self.manager:
            return self.manager.find_tool(tool_name) is not None
        return False

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an MCP tool."""
        result = await execute_mcp_tool(tool_name, arguments)
        return {
            "success": not result.is_error,
            "content": result.content,
            "error": result.error_message,
            "formatted": format_tool_result_for_agent(result),
        }

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions for agent use."""
        return get_mcp_tools_for_agent()


# Convenience functions for common operations


async def add_mcp_server(
    server_id: str,
    name: str,
    command: str | None = None,
    args: list[str] | None = None,
    url: str | None = None,
    transport: str = "stdio",
    enabled: bool = True,
    auto_connect: bool = True,
    **kwargs: Any,
) -> MCPServerConfig:
    """Add a new MCP server configuration."""
    if transport == "stdio":
        config = MCPStdioConfig(
            command=command or "",
            args=args or [],
            env=kwargs.get("env", {}),
            cwd=kwargs.get("cwd"),
            timeout=kwargs.get("timeout", 30.0),
        )
    elif transport == "sse":
        config = MCPSSEConfig(
            url=url or "",
            headers=kwargs.get("headers", {}),
            timeout=kwargs.get("timeout", 5.0),
            sse_read_timeout=kwargs.get("sse_read_timeout", 300.0),
        )
    else:  # http
        config = MCPHttpConfig(
            url=url or "",
            headers=kwargs.get("headers", {}),
            timeout=kwargs.get("timeout", 30.0),
            sse_read_timeout=kwargs.get("sse_read_timeout", 300.0),
        )

    server_config = MCPServerConfig(
        id=server_id,
        name=name,
        description=kwargs.get("description", ""),
        enabled=enabled,
        auto_connect=auto_connect,
        config=config,
    )

    manager = await get_mcp_manager()
    manager.add_server(server_config)

    return server_config


async def connect_mcp_server(server_id: str) -> bool:
    """Connect to a specific MCP server."""
    manager = await get_mcp_manager()
    return await manager.connect(server_id)


async def disconnect_mcp_server(server_id: str) -> None:
    """Disconnect from a specific MCP server."""
    manager = await get_mcp_manager()
    await manager.disconnect(server_id)


async def restart_mcp_server(server_id: str) -> bool:
    """Restart a specific MCP server."""
    manager = await get_mcp_manager()
    return await manager.restart_server(server_id)


def get_mcp_status() -> dict[str, Any]:
    """Get current MCP status summary."""
    if _mcp_manager is None:
        return {
            "initialized": False,
            "total_servers": 0,
            "connected": 0,
            "total_tools": 0,
        }

    return {
        "initialized": True,
        **_mcp_manager.get_status_summary(),
    }


def has_mcp_capability(server_id: str, capability: ServerCapability) -> bool:
    """Check if a server has a specific capability."""
    if _mcp_manager is None:
        return False
    return _mcp_manager.has_capability(server_id, capability)


async def set_mcp_logging_level(server_id: str, level: LoggingLevel) -> bool:
    """Set logging level for an MCP server."""
    if _mcp_manager is None:
        return False
    return await _mcp_manager.set_logging_level(server_id, level)


async def read_mcp_resource(server_id: str, uri: str) -> dict[str, Any] | None:
    """Read a resource from an MCP server."""
    if _mcp_manager is None:
        return None

    content = await _mcp_manager.read_resource(server_id, uri)
    if content is None:
        return None

    return {
        "uri": content.uri,
        "mime_type": content.mime_type,
        "text": content.text,
        "blob": content.blob,
    }


async def get_mcp_prompt(
    server_id: str,
    prompt_name: str,
    arguments: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Get a prompt from an MCP server."""
    if _mcp_manager is None:
        return None

    result = await _mcp_manager.get_prompt(server_id, prompt_name, arguments)
    if result is None:
        return None

    return {
        "description": result.description,
        "messages": [{"role": msg.role, "content": msg.content} for msg in result.messages],
    }


def list_mcp_servers() -> list[dict[str, Any]]:
    """List all configured MCP servers with their status."""
    if _mcp_manager is None:
        return []

    servers = []
    for server_id, config in _mcp_manager.get_server_configs().items():
        conn = _mcp_manager.get_connection(server_id)
        servers.append(
            {
                "id": server_id,
                "name": config.name,
                "description": config.description,
                "enabled": config.enabled,
                "auto_connect": config.auto_connect,
                "transport": type(config.config)
                .__name__.replace("MCP", "")
                .replace("Config", "")
                .lower(),
                "state": conn.state.value if conn else "disconnected",
                "error": conn.error_message if conn else None,
            }
        )
    return servers
