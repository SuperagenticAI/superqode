"""Tests for MCP (Model Context Protocol) support in SuperQode."""

import pytest
from pathlib import Path
import json
import tempfile

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
    MCPResource,
    MCPPrompt,
    MCPToolResult,
)
from superqode.mcp.client import (
    MCPClientManager,
    MCPConnection,
    MCPConnectionState,
)


class TestMCPConfig:
    """Tests for MCP configuration loading and saving."""

    def test_load_empty_config(self):
        """Test loading from non-existent file returns empty dict."""
        config = load_mcp_config(Path("/nonexistent/path/mcp.json"))
        assert config == {}

    def test_load_config_from_file(self, tmp_path: Path):
        """Test loading MCP config from JSON file."""
        config_data = {
            "mcpServers": {
                "test-server": {
                    "name": "Test Server",
                    "transport": "stdio",
                    "command": "test-command",
                    "args": ["--arg1", "value1"],
                    "enabled": True,
                    "autoConnect": False,
                }
            }
        }

        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config_data))

        config = load_mcp_config(config_file)

        assert "test-server" in config
        server = config["test-server"]
        assert server.name == "Test Server"
        assert server.enabled is True
        assert server.auto_connect is False
        assert isinstance(server.config, MCPStdioConfig)
        assert server.config.command == "test-command"
        assert server.config.args == ["--arg1", "value1"]

    def test_load_http_config(self, tmp_path: Path):
        """Test loading HTTP transport config."""
        config_data = {
            "mcpServers": {
                "http-server": {
                    "name": "HTTP Server",
                    "transport": "http",
                    "url": "http://localhost:8080/mcp",
                    "headers": {"Authorization": "Bearer token"},
                    "timeout": 60.0,
                }
            }
        }

        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config_data))

        config = load_mcp_config(config_file)

        server = config["http-server"]
        assert isinstance(server.config, MCPHttpConfig)
        assert server.config.url == "http://localhost:8080/mcp"
        assert server.config.headers == {"Authorization": "Bearer token"}
        assert server.config.timeout == 60.0

    def test_load_sse_config(self, tmp_path: Path):
        """Test loading SSE transport config."""
        config_data = {
            "mcpServers": {
                "sse-server": {
                    "name": "SSE Server",
                    "transport": "sse",
                    "url": "http://localhost:8080/sse",
                    "sse_read_timeout": 600.0,
                }
            }
        }

        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config_data))

        config = load_mcp_config(config_file)

        server = config["sse-server"]
        assert isinstance(server.config, MCPSSEConfig)
        assert server.config.url == "http://localhost:8080/sse"
        assert server.config.sse_read_timeout == 600.0

    def test_save_config(self, tmp_path: Path):
        """Test saving MCP config to file."""
        servers = {
            "test-server": MCPServerConfig(
                id="test-server",
                name="Test Server",
                description="A test server",
                enabled=True,
                auto_connect=True,
                config=MCPStdioConfig(
                    command="test-cmd",
                    args=["--test"],
                ),
            )
        }

        config_file = tmp_path / "mcp.json"
        save_mcp_config(servers, config_file)

        # Reload and verify
        loaded = load_mcp_config(config_file)
        assert "test-server" in loaded
        assert loaded["test-server"].name == "Test Server"
        assert loaded["test-server"].description == "A test server"

    def test_create_default_config(self):
        """Test creating default MCP configuration."""
        config = create_default_mcp_config()

        assert "filesystem" in config
        assert "fetch" in config

        # Default servers should be disabled
        assert config["filesystem"].enabled is False
        assert config["fetch"].enabled is False


class TestMCPTypes:
    """Tests for MCP type definitions."""

    def test_mcp_tool(self):
        """Test MCPTool dataclass."""
        tool = MCPTool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
            server_id="test-server",
        )

        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.server_id == "test-server"

    def test_mcp_resource(self):
        """Test MCPResource dataclass."""
        resource = MCPResource(
            uri="file:///test.txt",
            name="Test File",
            description="A test file",
            mime_type="text/plain",
            server_id="test-server",
        )

        assert resource.uri == "file:///test.txt"
        assert resource.name == "Test File"
        assert resource.mime_type == "text/plain"

    def test_mcp_prompt(self):
        """Test MCPPrompt dataclass."""
        prompt = MCPPrompt(
            name="test_prompt",
            description="A test prompt",
            arguments=[{"name": "arg1", "required": True}],
            server_id="test-server",
        )

        assert prompt.name == "test_prompt"
        assert len(prompt.arguments) == 1

    def test_mcp_tool_result_success(self):
        """Test MCPToolResult for successful execution."""
        result = MCPToolResult(
            content=[{"type": "text", "text": "Success!"}],
            is_error=False,
        )

        assert not result.is_error
        assert len(result.content) == 1
        assert result.content[0]["text"] == "Success!"

    def test_mcp_tool_result_error(self):
        """Test MCPToolResult for error case."""
        result = MCPToolResult(
            content=[],
            is_error=True,
            error_message="Something went wrong",
        )

        assert result.is_error
        assert result.error_message == "Something went wrong"


class TestMCPClientManager:
    """Tests for MCP client manager."""

    def test_manager_initialization(self):
        """Test MCPClientManager initialization."""
        manager = MCPClientManager()

        assert manager._connections == {}
        assert manager._server_configs == {}

    def test_add_server(self):
        """Test adding server configuration."""
        manager = MCPClientManager()

        config = MCPServerConfig(
            id="test-server",
            name="Test Server",
            config=MCPStdioConfig(command="test"),
        )

        manager.add_server(config)

        assert "test-server" in manager.get_server_configs()

    def test_remove_server(self):
        """Test removing server configuration."""
        manager = MCPClientManager()

        config = MCPServerConfig(
            id="test-server",
            name="Test Server",
            config=MCPStdioConfig(command="test"),
        )

        manager.add_server(config)
        manager.remove_server("test-server")

        assert "test-server" not in manager.get_server_configs()

    def test_connection_state_disconnected(self):
        """Test connection state for unknown server."""
        manager = MCPClientManager()

        state = manager.get_connection_state("unknown-server")
        assert state == MCPConnectionState.DISCONNECTED

    def test_list_all_tools_empty(self):
        """Test listing tools when no servers connected."""
        manager = MCPClientManager()

        tools = manager.list_all_tools()
        assert tools == []

    def test_list_all_resources_empty(self):
        """Test listing resources when no servers connected."""
        manager = MCPClientManager()

        resources = manager.list_all_resources()
        assert resources == []

    def test_list_all_prompts_empty(self):
        """Test listing prompts when no servers connected."""
        manager = MCPClientManager()

        prompts = manager.list_all_prompts()
        assert prompts == []

    def test_get_status_summary_empty(self):
        """Test status summary with no servers."""
        manager = MCPClientManager()

        status = manager.get_status_summary()

        assert status["total_servers"] == 0
        assert status["connected"] == 0
        assert status["total_tools"] == 0

    def test_state_change_callback(self):
        """Test state change callback registration."""
        manager = MCPClientManager()

        states_received = []

        def callback(server_id: str, state: MCPConnectionState):
            states_received.append((server_id, state))

        manager.on_state_change(callback)

        # Manually trigger notification
        manager._notify_state_change("test", MCPConnectionState.CONNECTING)

        assert len(states_received) == 1
        assert states_received[0] == ("test", MCPConnectionState.CONNECTING)


class TestMCPConnection:
    """Tests for MCP connection dataclass."""

    def test_connection_defaults(self):
        """Test MCPConnection default values."""
        config = MCPServerConfig(
            id="test",
            name="Test",
            config=MCPStdioConfig(command="test"),
        )

        conn = MCPConnection(server_config=config)

        assert conn.state == MCPConnectionState.DISCONNECTED
        assert conn.session is None
        assert conn.tools == []
        assert conn.resources == []
        assert conn.prompts == []
        assert conn.error_message is None
