"""Live integration tests for MCP features with real MCP servers.

These tests verify the full MCP implementation works with actual MCP servers.
Uses mcp-server-fetch which is available via uvx.
"""

import asyncio
import os
from pathlib import Path

import pytest

from superqode.mcp import (
    MCPClientManager,
    MCPConnectionState,
    MCPServerConfig,
    MCPStdioConfig,
    ServerCapability,
    LATEST_PROTOCOL_VERSION,
)
from superqode.mcp.integration import format_tool_result_for_agent

if not os.environ.get("SUPERQODE_MCP_LIVE"):
    pytest.skip("Set SUPERQODE_MCP_LIVE=1 to run live MCP tests", allow_module_level=True)


@pytest.mark.asyncio
class TestMCPLiveServerConnection:
    """Test actual MCP server connections using mcp-server-fetch."""

    async def test_connect_to_fetch_server(self):
        """Test connecting to the fetch MCP server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="fetch",
                    name="Fetch Server",
                    enabled=True,
                    auto_connect=False,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            # Connect
            success = await manager.connect("fetch")
            assert success, "Failed to connect to fetch server"

            # Verify connection state
            assert manager.get_connection_state("fetch") == MCPConnectionState.CONNECTED

            # Get server info
            info = manager.get_server_info("fetch")
            assert info is not None
            print(f"Server name: {info.name}")
            print(f"Server version: {info.version}")
            print(f"Protocol version: {info.protocol_version}")

            # Check capabilities
            conn = manager.get_connection("fetch")
            assert conn is not None
            print(
                f"Capabilities: tools={conn.capabilities.tools}, resources={conn.capabilities.resources}, prompts={conn.capabilities.prompts}"
            )

            # Verify has tools capability
            assert manager.has_capability("fetch", ServerCapability.TOOLS)

            # Disconnect
            await manager.disconnect("fetch")
            assert manager.get_connection_state("fetch") == MCPConnectionState.DISCONNECTED

    async def test_list_tools_from_fetch_server(self):
        """Test listing tools from the fetch server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="fetch",
                    name="Fetch Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            success = await manager.connect("fetch")
            assert success

            # List tools
            tools = manager.list_all_tools()
            assert len(tools) > 0, "Fetch server should have at least one tool"

            print(f"\nFetch server tools ({len(tools)}):")
            for tool in tools:
                print(f"  - {tool.name}: {tool.description[:50]}...")
                print(
                    f"    Input schema keys: {list(tool.input_schema.get('properties', {}).keys())}"
                )
                if tool.annotations:
                    print(f"    Annotations: read_only={tool.annotations.read_only_hint}")

            # Verify tool structure
            tool = tools[0]
            assert tool.name is not None
            assert tool.server_id == "fetch"
            assert tool.input_schema is not None

            await manager.disconnect("fetch")

    async def test_execute_fetch_tool(self):
        """Test executing the fetch tool."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="fetch",
                    name="Fetch Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            success = await manager.connect("fetch")
            assert success

            # Find the fetch tool
            tools = manager.list_all_tools()
            fetch_tool = next((t for t in tools if "fetch" in t.name.lower()), None)

            if fetch_tool:
                print(f"\nExecuting tool: {fetch_tool.name}")
                print(f"Input schema: {fetch_tool.input_schema}")

                # Execute fetch on a simple URL
                result = await manager.call_tool(
                    "fetch",
                    fetch_tool.name,
                    {"url": "https://httpbin.org/get"},
                )

                print(f"Result: is_error={result.is_error}")
                if result.is_error:
                    print(f"Error: {result.error_message}")
                else:
                    print(f"Content items: {len(result.content)}")
                    for item in result.content[:2]:  # Show first 2 items
                        print(f"  Type: {item.get('type')}")
                        if item.get("type") == "text":
                            text = item.get("text", "")[:200]
                            print(f"  Text preview: {text}...")

                # Format for agent
                formatted = format_tool_result_for_agent(result)
                assert isinstance(formatted, str)
                print(f"\nFormatted result preview: {formatted[:200]}...")

            await manager.disconnect("fetch")

    async def test_find_tool_across_servers(self):
        """Test finding a tool by name."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="fetch",
                    name="Fetch Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            success = await manager.connect("fetch")
            assert success

            # Get tool names
            tools = manager.list_all_tools()
            if tools:
                tool_name = tools[0].name

                # Find by name
                result = manager.find_tool(tool_name)
                assert result is not None
                server_id, found_tool = result
                assert server_id == "fetch"
                assert found_tool.name == tool_name

                # Get specific tool
                specific = manager.get_tool("fetch", tool_name)
                assert specific is not None
                assert specific.name == tool_name

            await manager.disconnect("fetch")

    async def test_status_summary_with_connection(self):
        """Test status summary with connected server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="fetch",
                    name="Fetch Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            # Status before connection
            status = manager.get_status_summary()
            assert status["total_servers"] == 1
            assert status["connected"] == 0

            success = await manager.connect("fetch")
            assert success

            # Status after connection
            status = manager.get_status_summary()
            print(f"\nStatus summary:")
            print(f"  Total servers: {status['total_servers']}")
            print(f"  Connected: {status['connected']}")
            print(f"  Total tools: {status['total_tools']}")
            print(f"  Total resources: {status['total_resources']}")
            print(f"  Total prompts: {status['total_prompts']}")

            assert status["connected"] == 1
            assert status["total_tools"] > 0
            assert "fetch" in status["servers"]
            assert status["servers"]["fetch"]["state"] == "connected"

            await manager.disconnect("fetch")

    async def test_reconnect_server(self):
        """Test reconnecting to a server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="fetch",
                    name="Fetch Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            # Initial connect
            success = await manager.connect("fetch")
            assert success

            initial_tools = len(manager.list_all_tools())

            # Reconnect
            success = await manager.reconnect("fetch")
            assert success
            assert manager.get_connection_state("fetch") == MCPConnectionState.CONNECTED

            # Should have same tools after reconnect
            assert len(manager.list_all_tools()) == initial_tools

            await manager.disconnect("fetch")

    async def test_multiple_server_connections(self):
        """Test connecting to multiple instances of the same server."""
        async with MCPClientManager() as manager:
            # Add two fetch server instances
            manager.add_server(
                MCPServerConfig(
                    id="fetch1",
                    name="Fetch Server 1",
                    enabled=True,
                    auto_connect=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )
            manager.add_server(
                MCPServerConfig(
                    id="fetch2",
                    name="Fetch Server 2",
                    enabled=True,
                    auto_connect=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            # Connect all
            results = await manager.connect_all()
            print(f"\nConnection results: {results}")

            connected = sum(1 for v in results.values() if v)
            assert connected == 2, f"Expected 2 connections, got {connected}"

            # Tools should be aggregated from both
            all_tools = manager.list_all_tools()
            print(f"Total tools from both servers: {len(all_tools)}")

            # Each tool should have correct server_id
            server_ids = set(t.server_id for t in all_tools)
            assert "fetch1" in server_ids
            assert "fetch2" in server_ids

            # Running servers
            running = manager.running_server_ids()
            assert len(running) == 2

            # Disconnect all
            await manager.disconnect_all()
            assert len(manager.running_server_ids()) == 0


@pytest.mark.asyncio
class TestMCPCallbacksLive:
    """Test MCP callbacks with live server."""

    async def test_state_change_callbacks(self):
        """Test state change callbacks during connection lifecycle."""
        state_changes = []

        async with MCPClientManager() as manager:
            manager.on_state_change(lambda sid, state: state_changes.append((sid, state)))

            manager.add_server(
                MCPServerConfig(
                    id="fetch",
                    name="Fetch Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-fetch"],
                    ),
                )
            )

            await manager.connect("fetch")
            await manager.disconnect("fetch")

        print(f"\nState changes: {state_changes}")

        # Should have connecting -> connected -> disconnected
        states = [s[1] for s in state_changes if s[0] == "fetch"]
        assert MCPConnectionState.CONNECTING in states
        assert MCPConnectionState.CONNECTED in states
        assert MCPConnectionState.DISCONNECTED in states


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
