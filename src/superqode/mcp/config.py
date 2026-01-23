"""MCP server configuration for SuperQode.

This module handles loading, saving, and managing MCP server configurations.
Supports stdio (local process), HTTP, and SSE transport types.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
import json
import logging
import os

logger = logging.getLogger(__name__)

# Default MCP config file locations
MCP_CONFIG_FILENAME = "mcp.json"
MCP_CONFIG_DIRS = [
    Path.cwd() / ".superqode",
    Path.home() / ".superqode",
    Path.home() / ".config" / "superqode",
]


@dataclass
class MCPStdioConfig:
    """Configuration for stdio-based MCP server (local process).

    Attributes:
        command: The executable command to run
        args: Command line arguments
        env: Environment variables to set
        cwd: Working directory for the process
        timeout: Connection timeout in seconds
    """

    transport: Literal["stdio"] = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout: float = 30.0


@dataclass
class MCPHttpConfig:
    """Configuration for HTTP-based MCP server (streamable HTTP).

    Attributes:
        url: The HTTP endpoint URL
        headers: HTTP headers to include in requests
        timeout: Request timeout in seconds
        sse_read_timeout: SSE read timeout in seconds
    """

    transport: Literal["http"] = "http"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    sse_read_timeout: float = 300.0


@dataclass
class MCPSSEConfig:
    """Configuration for SSE-based MCP server.

    Attributes:
        url: The SSE endpoint URL
        headers: HTTP headers to include in requests
        timeout: Request timeout in seconds
        sse_read_timeout: SSE read timeout in seconds
    """

    transport: Literal["sse"] = "sse"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 5.0
    sse_read_timeout: float = 300.0


@dataclass
class MCPServerConfig:
    """Complete configuration for an MCP server.

    Attributes:
        id: Unique identifier for this server
        name: Human-readable name
        description: Optional description
        enabled: Whether the server is enabled
        auto_connect: Whether to connect automatically on startup
        config: Transport-specific configuration
    """

    id: str
    name: str
    description: str = ""
    enabled: bool = True
    auto_connect: bool = True
    config: MCPStdioConfig | MCPHttpConfig | MCPSSEConfig = field(default_factory=MCPStdioConfig)


def find_mcp_config_file() -> Path | None:
    """Find the MCP configuration file.

    Searches in order:
    1. .superqode/mcp.json in current directory
    2. ~/.superqode/mcp.json
    3. ~/.config/superqode/mcp.json

    Returns:
        Path to config file if found, None otherwise
    """
    for config_dir in MCP_CONFIG_DIRS:
        config_path = config_dir / MCP_CONFIG_FILENAME
        if config_path.exists():
            return config_path
    return None


def load_mcp_config(config_path: Path | None = None) -> dict[str, MCPServerConfig]:
    """Load MCP server configurations from file.

    Args:
        config_path: Optional explicit path to config file

    Returns:
        Dictionary mapping server IDs to their configurations
    """
    if config_path is None:
        config_path = find_mcp_config_file()

    if config_path is None or not config_path.exists():
        return {}

    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load MCP config from {config_path}: {e}")
        return {}

    servers: dict[str, MCPServerConfig] = {}

    # Handle both formats: {"mcpServers": {...}} and {"servers": {...}}
    servers_data = data.get("mcpServers", data.get("servers", {}))

    for server_id, server_data in servers_data.items():
        try:
            server_config = _parse_server_config(server_id, server_data)
            servers[server_id] = server_config
        except Exception as e:
            logger.warning(f"Failed to parse MCP server config '{server_id}': {e}")

    return servers


def _parse_server_config(server_id: str, data: dict[str, Any]) -> MCPServerConfig:
    """Parse a single server configuration from JSON data."""
    # Determine transport type
    transport = data.get("transport", "stdio")

    # Handle legacy format (command at top level = stdio)
    if "command" in data and "transport" not in data:
        transport = "stdio"
    elif "url" in data and "transport" not in data:
        # Determine if HTTP or SSE based on URL or other hints
        transport = data.get("transport", "http")

    # Parse transport-specific config
    if transport == "stdio":
        config = MCPStdioConfig(
            command=data.get("command", ""),
            args=data.get("args", []),
            env=_resolve_env_vars(data.get("env", {})),
            cwd=data.get("cwd"),
            timeout=data.get("timeout", 30.0),
        )
    elif transport == "sse":
        config = MCPSSEConfig(
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            timeout=data.get("timeout", 5.0),
            sse_read_timeout=data.get("sse_read_timeout", 300.0),
        )
    else:  # http (streamable)
        config = MCPHttpConfig(
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            timeout=data.get("timeout", 30.0),
            sse_read_timeout=data.get("sse_read_timeout", 300.0),
        )

    return MCPServerConfig(
        id=server_id,
        name=data.get("name", server_id),
        description=data.get("description", ""),
        enabled=data.get("enabled", not data.get("disabled", False)),
        auto_connect=data.get("autoConnect", data.get("auto_connect", True)),
        config=config,
    )


def _resolve_env_vars(env: dict[str, str]) -> dict[str, str]:
    """Resolve environment variable references in env dict.

    Supports ${VAR} syntax for referencing environment variables.
    """
    resolved = {}
    for key, value in env.items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            var_name = value[2:-1]
            resolved[key] = os.environ.get(var_name, "")
        else:
            resolved[key] = value
    return resolved


def save_mcp_config(
    servers: dict[str, MCPServerConfig],
    config_path: Path | None = None,
) -> None:
    """Save MCP server configurations to file.

    Args:
        servers: Dictionary mapping server IDs to configurations
        config_path: Optional explicit path to config file
    """
    if config_path is None:
        # Default to .superqode/mcp.json in current directory
        config_path = MCP_CONFIG_DIRS[0] / MCP_CONFIG_FILENAME

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to JSON-serializable format
    data = {"mcpServers": {}}

    for server_id, server_config in servers.items():
        server_data: dict[str, Any] = {
            "name": server_config.name,
            "enabled": server_config.enabled,
            "autoConnect": server_config.auto_connect,
        }

        if server_config.description:
            server_data["description"] = server_config.description

        config = server_config.config
        if isinstance(config, MCPStdioConfig):
            server_data["transport"] = "stdio"
            server_data["command"] = config.command
            if config.args:
                server_data["args"] = config.args
            if config.env:
                server_data["env"] = config.env
            if config.cwd:
                server_data["cwd"] = config.cwd
            if config.timeout != 30.0:
                server_data["timeout"] = config.timeout
        elif isinstance(config, MCPSSEConfig):
            server_data["transport"] = "sse"
            server_data["url"] = config.url
            if config.headers:
                server_data["headers"] = config.headers
            if config.timeout != 5.0:
                server_data["timeout"] = config.timeout
            if config.sse_read_timeout != 300.0:
                server_data["sse_read_timeout"] = config.sse_read_timeout
        else:  # MCPHttpConfig
            server_data["transport"] = "http"
            server_data["url"] = config.url
            if config.headers:
                server_data["headers"] = config.headers
            if config.timeout != 30.0:
                server_data["timeout"] = config.timeout
            if config.sse_read_timeout != 300.0:
                server_data["sse_read_timeout"] = config.sse_read_timeout

        data["mcpServers"][server_id] = server_data

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved MCP config to {config_path}")
    except OSError as e:
        logger.error(f"Failed to save MCP config to {config_path}: {e}")
        raise


def create_default_mcp_config() -> dict[str, MCPServerConfig]:
    """Create a default MCP configuration with example servers.

    Returns:
        Dictionary with example MCP server configurations
    """
    return {
        "filesystem": MCPServerConfig(
            id="filesystem",
            name="Filesystem",
            description="Access to local filesystem",
            enabled=False,  # Disabled by default for security
            auto_connect=False,
            config=MCPStdioConfig(
                command="uvx",
                args=["mcp-server-filesystem", "--root", "."],
            ),
        ),
        "fetch": MCPServerConfig(
            id="fetch",
            name="Fetch",
            description="HTTP fetch capabilities",
            enabled=False,
            auto_connect=False,
            config=MCPStdioConfig(
                command="uvx",
                args=["mcp-server-fetch"],
            ),
        ),
    }
