"""Harness-local MCP server declarations for runtime backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from superqode.mcp.client import MCPClientManager
from superqode.mcp.config import MCPHttpConfig, MCPSSEConfig, MCPServerConfig, MCPStdioConfig
from superqode.providers.gateway.base import ToolDefinition
from superqode.tools.base import ToolResult

from .spec import HarnessSpec


@dataclass(slots=True)
class HarnessMCPRuntime:
    """Resolved MCP manager, tool definitions, and execution adapter."""

    manager: MCPClientManager | None = None
    tools: list[ToolDefinition] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.tools)

    async def execute(self, server_id: str, tool_name: str, args: dict[str, Any]) -> ToolResult:
        if self.manager is None:
            return ToolResult(success=False, output="", error="MCP manager is not initialized")
        result = await self.manager.execute_tool(server_id, tool_name, args)
        if result.is_error:
            return ToolResult(
                success=False,
                output="",
                error=result.error_message or _format_mcp_content(result.content) or "MCP tool error",
            )
        return ToolResult(
            success=True,
            output=_format_mcp_content(result.content),
            metadata={
                "mcp_server": server_id,
                "mcp_tool": tool_name,
                **(
                    {"structured_content": result.structured_content}
                    if result.structured_content is not None
                    else {}
                ),
            },
        )

    async def close(self) -> None:
        if self.manager is not None:
            await self.manager.__aexit__(None, None, None)
            self.manager = None


async def create_harness_mcp_runtime(spec: HarnessSpec) -> HarnessMCPRuntime:
    """Create connected MCP runtime support from ``spec.runtime.config``."""
    servers = harness_mcp_server_configs(spec)
    if not servers:
        return HarnessMCPRuntime()

    manager = MCPClientManager()
    runtime = HarnessMCPRuntime(manager=manager)
    try:
        await manager.__aenter__()
        for server in servers.values():
            manager.add_server(server)
        results = await manager.connect_all()
        for server_id, ok in sorted(results.items()):
            if not ok:
                runtime.errors.append(f"MCP server {server_id!r} did not connect")
        runtime.tools = [
            ToolDefinition(
                name=f"mcp_{tool.server_id}_{tool.name}",
                description=f"[MCP:{tool.server_id}] {tool.description}",
                parameters=tool.input_schema or {"type": "object", "properties": {}},
            )
            for tool in manager.list_all_tools()
        ]
        return runtime
    except Exception as exc:
        runtime.errors.append(str(exc))
        await runtime.close()
        return runtime


def harness_mcp_server_configs(spec: HarnessSpec) -> dict[str, MCPServerConfig]:
    """Return inline MCP servers declared on a HarnessSpec."""
    runtime_config = spec.runtime.config
    raw = runtime_config.get("mcp_servers") or runtime_config.get("mcp") or {}
    if not isinstance(raw, dict):
        return {}
    servers: dict[str, MCPServerConfig] = {}
    for server_id, data in raw.items():
        if isinstance(data, dict):
            servers[str(server_id)] = _server_config_from_dict(str(server_id), data)
    return servers


def _server_config_from_dict(server_id: str, data: dict[str, Any]) -> MCPServerConfig:
    transport = str(data.get("transport") or ("http" if data.get("url") else "stdio"))
    if transport == "sse":
        transport_config = MCPSSEConfig(
            url=str(data.get("url") or ""),
            headers=_str_dict(data.get("headers")),
            timeout=float(data.get("timeout", 5.0)),
            sse_read_timeout=float(data.get("sse_read_timeout", 300.0)),
        )
    elif transport == "http":
        transport_config = MCPHttpConfig(
            url=str(data.get("url") or ""),
            headers=_str_dict(data.get("headers")),
            timeout=float(data.get("timeout", 30.0)),
            sse_read_timeout=float(data.get("sse_read_timeout", 300.0)),
        )
    else:
        transport_config = MCPStdioConfig(
            command=str(data.get("command") or ""),
            args=[str(item) for item in data.get("args", [])] if isinstance(data.get("args"), list) else [],
            env=_str_dict(data.get("env")),
            cwd=str(data["cwd"]) if data.get("cwd") else None,
            timeout=float(data.get("timeout", 30.0)),
        )
    return MCPServerConfig(
        id=server_id,
        name=str(data.get("name") or server_id),
        description=str(data.get("description") or ""),
        enabled=bool(data.get("enabled", not data.get("disabled", False))),
        auto_connect=bool(data.get("autoConnect", data.get("auto_connect", True))),
        config=transport_config,
    )


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _format_mcp_content(content: list[Any]) -> str:
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            if "text" in item:
                parts.append(str(item["text"]))
            elif "data" in item:
                parts.append(str(item["data"]))
            else:
                parts.append(str(item))
        else:
            parts.append(str(item))
    return "\n".join(parts)
