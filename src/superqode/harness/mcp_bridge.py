"""Harness-local MCP server declarations for runtime backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json

from superqode.mcp.client import MCPClientManager
from superqode.mcp.config import MCPServerConfig, _parse_server_config, resolve_mcp_config
from pathlib import Path
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
                error=result.error_message
                or _format_mcp_content(result.content)
                or "MCP tool error",
            )
        return ToolResult(
            success=True,
            output=_format_mcp_content(result.content)
            or (
                json.dumps(result.structured_content)
                if result.structured_content is not None
                else ""
            ),
            metadata={
                "mcp_server": server_id,
                "mcp_tool": tool_name,
                "content": result.content,
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


async def create_harness_mcp_runtime(
    spec: HarnessSpec, *, cwd: Path | None = None
) -> HarnessMCPRuntime:
    """Create connected MCP runtime support from ``spec.runtime.config``."""
    resolution = resolve_mcp_config(spec.runtime.config, cwd=cwd)
    servers = resolution.servers
    if not servers:
        return HarnessMCPRuntime(errors=resolution.errors)

    manager = MCPClientManager()
    runtime = HarnessMCPRuntime(manager=manager, errors=list(resolution.errors))
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


def harness_mcp_server_configs(
    spec: HarnessSpec, *, cwd: Path | None = None
) -> dict[str, MCPServerConfig]:
    """Return shared configuration plus this harness's explicit overrides."""
    return resolve_mcp_config(spec.runtime.config, cwd=cwd).servers


def _server_config_from_dict(server_id: str, data: dict[str, Any]) -> MCPServerConfig:
    return _parse_server_config(server_id, data)


def _format_mcp_content(content: list[Any]) -> str:
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            if "text" in item:
                parts.append(str(item["text"]))
            elif item.get("type") in {"image", "audio"}:
                parts.append(f"[{item['type']}: {item.get('mimeType', 'unknown')}]")
            else:
                parts.append(str(item))
        else:
            parts.append(str(item))
    return "\n".join(parts)
