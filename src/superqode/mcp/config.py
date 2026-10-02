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
import re

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


def mcp_config_paths(cwd: Path | str | None = None) -> list[Path]:
    """Configuration layers, from lowest to highest precedence, resolved now."""
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    return list(
        dict.fromkeys(
            [
                Path.home() / ".config" / "superqode" / MCP_CONFIG_FILENAME,
                Path.home() / ".superqode" / MCP_CONFIG_FILENAME,
                root / ".superqode" / MCP_CONFIG_FILENAME,
            ]
        )
    )


@dataclass
class MCPConfigResolution:
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def resolve_mcp_config(
    runtime_config: dict[str, Any] | None = None, *, cwd: Path | str | None = None
) -> MCPConfigResolution:
    """Resolve the shared files and host overrides without starting any server.

    ``mcp_config: false`` selects inline-only configuration; a path selects one
    explicit file. Project entries and then inline entries replace whole server
    declarations. An invalid higher-priority entry masks an earlier declaration
    rather than silently launching the earlier server.
    """
    runtime = runtime_config or {}
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    choice = runtime.get("mcp_config")
    paths = mcp_config_paths(root)
    if choice is False:
        paths = []
    elif isinstance(choice, (str, Path)):
        path = Path(choice).expanduser()
        paths = [path if path.is_absolute() else root / path]
    elif choice not in (None, True):
        raise ValueError("mcp_config requires a path or boolean")
    resolved = MCPConfigResolution()

    def merge(data, source, base):
        if not isinstance(data, dict):
            resolved.errors.append(f"{source}: MCP servers must be an object")
            return
        for sid, declaration in data.items():
            resolved.servers.pop(sid, None)
            resolved.sources[sid] = source
            try:
                if not isinstance(declaration, dict):
                    raise ValueError("server declaration must be an object")
                server = _parse_server_config(sid, declaration)
                if isinstance(server.config, MCPStdioConfig):
                    path = Path(server.config.cwd).expanduser() if server.config.cwd else root
                    server.config.cwd = str(path if path.is_absolute() else base / path)
                resolved.servers[sid] = server
            except (TypeError, ValueError):
                resolved.errors.append(f"{source}: invalid MCP server {sid!r}")

    for path in paths:
        if not path.exists():
            if isinstance(choice, (str, Path)):
                resolved.errors.append(f"MCP configuration file not found: {path}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            merge(data.get("mcpServers", data.get("servers", {})), str(path), root)
        except (OSError, ValueError, AttributeError):
            resolved.errors.append(f"Invalid MCP configuration file: {path}")
    if "mcp_servers" in runtime or "mcp" in runtime:
        merge(runtime.get("mcp_servers", runtime.get("mcp")), "runtime.config", root)
    return resolved


def find_mcp_config_file() -> Path | None:
    """Find the MCP configuration file.

    Searches in order:
    1. .superqode/mcp.json in current directory
    2. ~/.superqode/mcp.json
    3. ~/.config/superqode/mcp.json

    Returns:
        Path to config file if found, None otherwise
    """
    for config_path in reversed(mcp_config_paths()):
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
        return resolve_mcp_config().servers

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
    if not isinstance(data, dict):
        logger.error("MCP configuration must be an object")
        return {}
    servers_data = data.get("mcpServers", data.get("servers", {}))
    if not isinstance(servers_data, dict):
        logger.error("MCP servers must be an object")
        return {}

    for server_id, server_data in servers_data.items():
        try:
            server_config = _parse_server_config(server_id, server_data)
            servers[server_id] = server_config
        except Exception as e:
            logger.warning(f"Failed to parse MCP server config '{server_id}': {e}")

    return servers


def get_acp_mcp_servers(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Return enabled MCP servers in the list format expected by ACP sessions."""
    servers = load_mcp_config(config_path)
    acp_servers: list[dict[str, Any]] = []

    for server_id, server in servers.items():
        if not server.enabled:
            continue

        config = server.config
        server_data: dict[str, Any] = {
            "name": server_id,
            "transport": config.transport,
        }

        if server.description:
            server_data["description"] = server.description

        if isinstance(config, MCPStdioConfig):
            server_data["command"] = config.command
            if config.args:
                server_data["args"] = config.args
            if config.env:
                server_data["env"] = config.env
            if config.cwd:
                server_data["cwd"] = config.cwd
        elif isinstance(config, MCPSSEConfig):
            server_data["url"] = config.url
            if config.headers:
                server_data["headers"] = config.headers
        else:
            server_data["url"] = config.url
            if config.headers:
                server_data["headers"] = config.headers

        acp_servers.append(server_data)

    return acp_servers


def _parse_server_config(server_id: str, data: dict[str, Any]) -> MCPServerConfig:
    """Parse a single server configuration from JSON data."""
    if not isinstance(data, dict) or not isinstance(server_id, str) or not server_id:
        raise ValueError("Invalid server declaration")
    # Determine transport type
    transport = data.get("transport", data.get("type", "http" if "url" in data else "stdio"))
    if transport == "streamable-http":
        transport = "http"
    if transport not in {"stdio", "http", "sse"}:
        raise ValueError("Unknown MCP transport")
    endpoint = data.get("command" if transport == "stdio" else "url", "")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("MCP server requires command or URL")
    for key in ("enabled", "disabled", "autoConnect", "auto_connect"):
        if key in data and not isinstance(data[key], bool):
            raise ValueError(f"{key} must be a boolean")
    if not isinstance(data.get("args", []), list) or any(
        not isinstance(arg, str) for arg in data.get("args", [])
    ):
        raise ValueError("args must be a list of strings")
    for key in ("timeout", "sse_read_timeout"):
        if key in data and (not isinstance(data[key], (int, float)) or data[key] <= 0):
            raise ValueError(f"{key} must be positive")

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
            headers=_resolve_env_vars(data.get("headers", {})),
            timeout=data.get("timeout", 5.0),
            sse_read_timeout=data.get("sse_read_timeout", 300.0),
        )
    else:  # http (streamable)
        config = MCPHttpConfig(
            url=data.get("url", ""),
            headers=_resolve_env_vars(data.get("headers", {})),
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
    if not isinstance(env, dict):
        raise ValueError("Environment and headers require an object")
    resolved = {}
    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Environment and header values must be strings")
        resolved[key] = re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda match: os.environ.get(match[1], ""), value
        )
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
        config_path = mcp_config_paths()[-1]

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
