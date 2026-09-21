"""MCP interface for the reusable Jev Tool Routing decision service."""

from __future__ import annotations

from typing import Any


def build_jev_mcp_server(coordinator=None):
    """Build a FastMCP server with one closed-set routing tool."""
    from fastmcp import FastMCP

    if coordinator is None:
        from superqode.jev_tools.service import RoutingCoordinator

        coordinator = RoutingCoordinator()

    server = FastMCP("superqode-jev-tool-routing")

    @server.tool()
    async def route_tools(
        request: str,
        tools: list[dict[str, Any]],
        turn_id: str = "",
        mode: str = "enforce",
        threshold: float = 0.30,
    ) -> dict[str, Any]:
        """Select tools needed to finish a request; failures retain all tools.

        Pass the same non-empty turn_id for every model step in one user turn.
        The returned tools preserve the caller's original schema objects.
        """
        result = await coordinator.route(
            request,
            tools,
            turn_id=turn_id,
            mode=mode,
            threshold=threshold,
        )
        return result.as_dict()

    return server


def run_jev_mcp_server() -> None:
    """Run the local stdio transport for desktop and CLI harnesses."""
    build_jev_mcp_server().run(transport="stdio")


__all__ = ["build_jev_mcp_server", "run_jev_mcp_server"]
