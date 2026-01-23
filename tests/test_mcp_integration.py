"""Integration tests for MCP features with real MCP servers.

These tests verify the full MCP implementation works with actual MCP servers.
Requires uvx to be installed for running MCP servers.
"""

import asyncio
import pytest
import tempfile
import os
from pathlib import Path

from superqode.mcp import (
    MCPClientManager,
    MCPConnectionState,
    MCPServerConfig,
    MCPStdioConfig,
    MCPHttpConfig,
    MCPSSEConfig,
    ServerCapability,
    LoggingLevel,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from superqode.mcp.integration import (
    get_mcp_status,
    format_tool_result_for_agent,
)


class TestMCPProtocolVersion:
    """Test MCP protocol version support."""

    def test_latest_protocol_version(self):
        """Verify latest protocol version is set."""
        assert LATEST_PROTOCOL_VERSION == "2025-03-26"

    def test_supported_versions(self):
        """Verify supported protocol versions."""
        assert "2025-03-26" in SUPPORTED_PROTOCOL_VERSIONS
        assert "2024-11-05" in SUPPORTED_PROTOCOL_VERSIONS


class TestMCPClientManagerFeatures:
    """Test MCPClientManager features without real server connection."""

    def test_capability_checking_disconnected(self):
        """Test capability checking when not connected."""
        manager = MCPClientManager()
        assert not manager.has_capability("unknown", ServerCapability.TOOLS)
        assert not manager.has_capability("unknown", ServerCapability.RESOURCES)
        assert not manager.has_capability("unknown", ServerCapability.PROMPTS)

    def test_callback_registration(self):
        """Test all callback registration methods."""
        manager = MCPClientManager()

        # State change callback
        state_changes = []
        manager.on_state_change(lambda sid, state: state_changes.append((sid, state)))

        # Tools changed callback
        tools_changes = []
        manager.on_tools_changed(lambda sid: tools_changes.append(sid))

        # Resources changed callback
        resources_changes = []
        manager.on_resources_changed(lambda sid: resources_changes.append(sid))

        # Prompts changed callback
        prompts_changes = []
        manager.on_prompts_changed(lambda sid: prompts_changes.append(sid))

        # Resource updated callback
        resource_updates = []
        manager.on_resource_updated(lambda sid, uri: resource_updates.append((sid, uri)))

        # Progress callback
        progress_updates = []
        manager.on_progress(lambda sid, prog: progress_updates.append((sid, prog)))

        # Log callback
        log_messages = []
        manager.on_log(lambda sid, lvl, lgr, data: log_messages.append((sid, lvl)))

        # Trigger notifications
        manager._notify_state_change("test", MCPConnectionState.CONNECTING)
        manager._notify_tools_changed("test")
        manager._notify_resources_changed("test")
        manager._notify_prompts_changed("test")
        manager._notify_resource_updated("test", "file:///test.txt")

        assert len(state_changes) == 1
        assert state_changes[0] == ("test", MCPConnectionState.CONNECTING)
        assert "test" in tools_changes
        assert "test" in resources_changes
        assert "test" in prompts_changes
        assert ("test", "file:///test.txt") in resource_updates

    def test_server_id_methods(self):
        """Test configured and running server ID methods."""
        manager = MCPClientManager()

        # Add some configs
        manager.add_server(
            MCPServerConfig(
                id="server1",
                name="Server 1",
                enabled=True,
                config=MCPStdioConfig(command="test"),
            )
        )
        manager.add_server(
            MCPServerConfig(
                id="server2",
                name="Server 2",
                enabled=False,
                config=MCPStdioConfig(command="test"),
            )
        )

        # Check configured (enabled only)
        configured = manager.configured_server_ids()
        assert "server1" in configured
        assert "server2" not in configured

        # Check running (none connected)
        running = manager.running_server_ids()
        assert len(running) == 0

    def test_find_tool_not_found(self):
        """Test finding a tool that doesn't exist."""
        manager = MCPClientManager()
        result = manager.find_tool("nonexistent_tool")
        assert result is None

    def test_get_server_info_not_connected(self):
        """Test getting server info when not connected."""
        manager = MCPClientManager()
        info = manager.get_server_info("unknown")
        assert info is None


@pytest.mark.asyncio
class TestMCPServerConnection:
    """Test actual MCP server connections using mcp-server-memory."""

    async def test_connect_to_memory_server(self):
        """Test connecting to the memory MCP server."""
        async with MCPClientManager() as manager:
            # Add memory server config
            manager.add_server(
                MCPServerConfig(
                    id="memory",
                    name="Memory Server",
                    enabled=True,
                    auto_connect=False,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-memory"],
                    ),
                )
            )

            # Connect
            success = await manager.connect("memory")

            if success:
                # Verify connection state
                assert manager.get_connection_state("memory") == MCPConnectionState.CONNECTED

                # Get server info
                info = manager.get_server_info("memory")
                assert info is not None
                assert info.name is not None

                # Check capabilities
                conn = manager.get_connection("memory")
                assert conn is not None
                assert conn.capabilities is not None

                # List tools
                tools = manager.list_all_tools()
                print(f"Memory server tools: {[t.name for t in tools]}")

                # Disconnect
                await manager.disconnect("memory")
                assert manager.get_connection_state("memory") == MCPConnectionState.DISCONNECTED
            else:
                pytest.skip("Could not connect to memory server (uvx may not have it cached)")

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

            success = await manager.connect("fetch")

            if success:
                assert manager.get_connection_state("fetch") == MCPConnectionState.CONNECTED

                # Check for fetch tool
                tools = manager.list_all_tools()
                tool_names = [t.name for t in tools]
                print(f"Fetch server tools: {tool_names}")

                # Verify tool has proper schema
                if tools:
                    tool = tools[0]
                    assert tool.name is not None
                    assert tool.input_schema is not None

                await manager.disconnect("fetch")
            else:
                pytest.skip("Could not connect to fetch server")

    async def test_tool_execution(self):
        """Test executing a tool on an MCP server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="memory",
                    name="Memory Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-memory"],
                    ),
                )
            )

            success = await manager.connect("memory")

            if success:
                tools = manager.list_all_tools()

                # Find a tool to test (memory server has store/retrieve)
                store_tool = None
                for tool in tools:
                    if "store" in tool.name.lower() or "write" in tool.name.lower():
                        store_tool = tool
                        break

                if store_tool:
                    print(f"Testing tool: {store_tool.name}")
                    print(f"Input schema: {store_tool.input_schema}")

                    # Try to execute (may fail depending on required args)
                    # This tests the execution path even if it returns an error
                    result = await manager.call_tool(
                        "memory",
                        store_tool.name,
                        {"key": "test_key", "value": "test_value"},
                    )

                    print(f"Tool result: is_error={result.is_error}, content={result.content}")

                    # Format for agent
                    formatted = format_tool_result_for_agent(result)
                    assert isinstance(formatted, str)

                await manager.disconnect("memory")
            else:
                pytest.skip("Could not connect to memory server")

    async def test_status_summary(self):
        """Test getting status summary with connected server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="memory",
                    name="Memory Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-memory"],
                    ),
                )
            )

            # Status before connection
            status = manager.get_status_summary()
            assert status["total_servers"] == 1
            assert status["connected"] == 0

            success = await manager.connect("memory")

            if success:
                # Status after connection
                status = manager.get_status_summary()
                assert status["connected"] == 1
                assert "memory" in status["servers"]
                assert status["servers"]["memory"]["state"] == "connected"

                await manager.disconnect("memory")
            else:
                pytest.skip("Could not connect to memory server")


@pytest.mark.asyncio
class TestMCPResourceOperations:
    """Test MCP resource operations."""

    async def test_list_resources(self):
        """Test listing resources from a server."""
        async with MCPClientManager() as manager:
            # Use filesystem server which has resources
            manager.add_server(
                MCPServerConfig(
                    id="filesystem",
                    name="Filesystem Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-filesystem", str(Path.cwd())],
                    ),
                )
            )

            success = await manager.connect("filesystem")

            if success:
                resources = manager.list_all_resources()
                print(f"Filesystem resources: {len(resources)}")

                templates = manager.list_all_resource_templates()
                print(f"Resource templates: {len(templates)}")

                await manager.disconnect("filesystem")
            else:
                pytest.skip("Could not connect to filesystem server")


@pytest.mark.asyncio
class TestMCPPromptOperations:
    """Test MCP prompt operations."""

    async def test_list_prompts(self):
        """Test listing prompts from a server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="memory",
                    name="Memory Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-memory"],
                    ),
                )
            )

            success = await manager.connect("memory")

            if success:
                prompts = manager.list_all_prompts()
                print(f"Memory server prompts: {len(prompts)}")

                for prompt in prompts:
                    print(f"  - {prompt.name}: {prompt.description}")
                    print(f"    Arguments: {[a.name for a in prompt.arguments]}")

                await manager.disconnect("memory")
            else:
                pytest.skip("Could not connect to memory server")


@pytest.mark.asyncio
class TestMCPMultipleServers:
    """Test managing multiple MCP servers."""

    async def test_connect_multiple_servers(self):
        """Test connecting to multiple servers simultaneously."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="memory1",
                    name="Memory Server 1",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-memory"],
                    ),
                )
            )
            manager.add_server(
                MCPServerConfig(
                    id="memory2",
                    name="Memory Server 2",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-memory"],
                    ),
                )
            )

            # Connect to both
            results = await manager.connect_all()

            connected_count = sum(1 for v in results.values() if v)
            print(f"Connected to {connected_count} servers")

            if connected_count > 0:
                # All tools should be aggregated
                all_tools = manager.list_all_tools()
                print(f"Total tools from all servers: {len(all_tools)}")

                # Each tool should have server_id
                for tool in all_tools:
                    assert tool.server_id in ["memory1", "memory2"]

                # Disconnect all
                await manager.disconnect_all()

                assert manager.get_connection_state("memory1") == MCPConnectionState.DISCONNECTED
                assert manager.get_connection_state("memory2") == MCPConnectionState.DISCONNECTED
            else:
                pytest.skip("Could not connect to any servers")

    async def test_reconnect_server(self):
        """Test reconnecting to a server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="memory",
                    name="Memory Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="uvx",
                        args=["mcp-server-memory"],
                    ),
                )
            )

            success = await manager.connect("memory")

            if success:
                # Reconnect
                success = await manager.reconnect("memory")
                assert success
                assert manager.get_connection_state("memory") == MCPConnectionState.CONNECTED

                await manager.disconnect("memory")
            else:
                pytest.skip("Could not connect to memory server")


@pytest.mark.asyncio
class TestMCPErrorHandling:
    """Test MCP error handling."""

    async def test_connect_invalid_command(self):
        """Test connecting with invalid command."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="invalid",
                    name="Invalid Server",
                    enabled=True,
                    config=MCPStdioConfig(
                        command="nonexistent-mcp-server-xyz",
                        args=[],
                    ),
                )
            )

            success = await manager.connect("invalid")
            assert not success
            assert manager.get_connection_state("invalid") == MCPConnectionState.ERROR

            conn = manager.get_connection("invalid")
            assert conn is not None
            assert conn.error_message is not None

    async def test_call_tool_not_connected(self):
        """Test calling tool when not connected."""
        async with MCPClientManager() as manager:
            result = await manager.call_tool("unknown", "some_tool", {})
            assert result.is_error
            assert "Not connected" in result.error_message

    async def test_connect_disabled_server(self):
        """Test connecting to disabled server."""
        async with MCPClientManager() as manager:
            manager.add_server(
                MCPServerConfig(
                    id="disabled",
                    name="Disabled Server",
                    enabled=False,
                    config=MCPStdioConfig(command="uvx", args=["mcp-server-memory"]),
                )
            )

            success = await manager.connect("disabled")
            assert not success


class TestMCPConfigFormats:
    """Test different MCP configuration formats."""

    def test_stdio_config(self):
        """Test stdio configuration."""
        config = MCPStdioConfig(
            command="uvx",
            args=["mcp-server-memory"],
            env={"DEBUG": "true"},
            cwd="/tmp",
            timeout=60.0,
        )
        assert config.transport == "stdio"
        assert config.command == "uvx"
        assert config.args == ["mcp-server-memory"]
        assert config.env == {"DEBUG": "true"}
        assert config.cwd == "/tmp"
        assert config.timeout == 60.0

    def test_http_config(self):
        """Test HTTP configuration."""
        config = MCPHttpConfig(
            url="http://localhost:8080/mcp",
            headers={"Authorization": "Bearer token"},
            timeout=30.0,
            sse_read_timeout=300.0,
        )
        assert config.transport == "http"
        assert config.url == "http://localhost:8080/mcp"
        assert config.headers == {"Authorization": "Bearer token"}

    def test_sse_config(self):
        """Test SSE configuration."""
        config = MCPSSEConfig(
            url="http://localhost:8080/sse",
            headers={},
            timeout=5.0,
            sse_read_timeout=600.0,
        )
        assert config.transport == "sse"
        assert config.url == "http://localhost:8080/sse"
        assert config.sse_read_timeout == 600.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
