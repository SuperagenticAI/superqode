"""MCP client manager for SuperQode.

This module provides the MCPClientManager class that handles connections
to multiple MCP servers, tool discovery, and tool execution.
Implements full MCP protocol support aligned with Zed editor's implementation.
"""

import asyncio
import contextlib
import logging
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from superqode.mcp.config import (
    MCPServerConfig,
    MCPStdioConfig,
    MCPHttpConfig,
    MCPSSEConfig,
    load_mcp_config,
)
from superqode.mcp.types import (
    MCPTool,
    MCPResource,
    MCPResourceTemplate,
    MCPPrompt,
    MCPPromptArgument,
    MCPToolResult,
    MCPResourceContent,
    MCPPromptResult,
    MCPPromptMessage,
    MCPCompletionResult,
    MCPServerCapabilities,
    MCPServerInfo,
    MCPProgress,
    ServerCapability,
    LoggingLevel,
    ToolAnnotations,
)

logger = logging.getLogger(__name__)

# MCP Protocol version
LATEST_PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_PROTOCOL_VERSIONS = [LATEST_PROTOCOL_VERSION, "2024-11-05"]


class MCPConnectionState(Enum):
    """Connection state for an MCP server."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    NEEDS_AUTH = "needs_auth"  # Waiting for OAuth authentication


@dataclass
class MCPConnection:
    """Represents a connection to an MCP server.

    Attributes:
        server_config: The server configuration
        state: Current connection state
        session: The MCP client session (when connected)
        server_info: Server information from initialization
        capabilities: Server capabilities
        tools: Available tools from this server
        resources: Available resources from this server
        resource_templates: Available resource templates
        prompts: Available prompts from this server
        subscribed_resources: Set of subscribed resource URIs
        error_message: Error message if state is ERROR
    """

    server_config: MCPServerConfig
    state: MCPConnectionState = MCPConnectionState.DISCONNECTED
    session: Any = None  # mcp.ClientSession
    server_info: MCPServerInfo | None = None
    capabilities: MCPServerCapabilities = field(default_factory=MCPServerCapabilities)
    tools: list[MCPTool] = field(default_factory=list)
    resources: list[MCPResource] = field(default_factory=list)
    resource_templates: list[MCPResourceTemplate] = field(default_factory=list)
    prompts: list[MCPPrompt] = field(default_factory=list)
    subscribed_resources: set[str] = field(default_factory=set)
    error_message: str | None = None
    _exit_stack: Any = None  # contextlib.AsyncExitStack


# Type aliases for callbacks
StateChangeCallback = Callable[[str, MCPConnectionState], None]
ToolsChangedCallback = Callable[[str], None]
ResourcesChangedCallback = Callable[[str], None]
PromptsChangedCallback = Callable[[str], None]
ResourceUpdatedCallback = Callable[[str, str], None]  # server_id, uri
ProgressCallback = Callable[[str, MCPProgress], None]
LogCallback = Callable[[str, LoggingLevel, str, Any], None]  # server_id, level, logger, data


class MCPClientManager:
    """Manages connections to multiple MCP servers.

    This class provides a unified interface for:
    - Connecting to and disconnecting from MCP servers
    - Discovering tools, resources, and prompts
    - Executing tools and reading resources
    - Managing server lifecycle
    - Handling notifications (list changes, resource updates, progress)
    - Resource subscriptions
    - Logging level control
    - Completion requests

    Example:
        async with MCPClientManager() as manager:
            await manager.load_config()
            await manager.connect_all()

            tools = manager.list_all_tools()
            result = await manager.call_tool("server_id", "tool_name", {"arg": "value"})
    """

    def __init__(self) -> None:
        """Initialize the MCP client manager."""
        self._connections: dict[str, MCPConnection] = {}
        self._server_configs: dict[str, MCPServerConfig] = {}
        self._exit_stack: contextlib.AsyncExitStack | None = None

        # Callbacks
        self._state_callbacks: list[StateChangeCallback] = []
        self._tools_changed_callbacks: list[ToolsChangedCallback] = []
        self._resources_changed_callbacks: list[ResourcesChangedCallback] = []
        self._prompts_changed_callbacks: list[PromptsChangedCallback] = []
        self._resource_updated_callbacks: list[ResourceUpdatedCallback] = []
        self._progress_callbacks: list[ProgressCallback] = []
        self._log_callbacks: list[LogCallback] = []

        self._initialized = False

    async def __aenter__(self) -> "MCPClientManager":
        """Enter async context."""
        self._exit_stack = contextlib.AsyncExitStack()
        await self._exit_stack.__aenter__()
        self._initialized = True
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context and cleanup all connections."""
        await self.disconnect_all()
        if self._exit_stack:
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
        self._initialized = False

    def load_config(self, config_path: Any = None) -> None:
        """Load MCP server configurations from file."""
        self._server_configs = load_mcp_config(config_path)
        logger.info(f"Loaded {len(self._server_configs)} MCP server configurations")

    def add_server(self, config: MCPServerConfig) -> None:
        """Add a server configuration."""
        self._server_configs[config.id] = config
        logger.debug(f"Added MCP server config: {config.id}")

    def remove_server(self, server_id: str) -> None:
        """Remove a server configuration."""
        if server_id in self._server_configs:
            del self._server_configs[server_id]
        if server_id in self._connections:
            del self._connections[server_id]
        logger.debug(f"Removed MCP server config: {server_id}")

    def get_server_configs(self) -> dict[str, MCPServerConfig]:
        """Get all server configurations."""
        return self._server_configs.copy()

    def get_connection(self, server_id: str) -> MCPConnection | None:
        """Get connection for a server."""
        return self._connections.get(server_id)

    def get_connection_state(self, server_id: str) -> MCPConnectionState:
        """Get connection state for a server."""
        conn = self._connections.get(server_id)
        return conn.state if conn else MCPConnectionState.DISCONNECTED

    # Callback registration methods
    def on_state_change(self, callback: StateChangeCallback) -> None:
        """Register callback for connection state changes."""
        self._state_callbacks.append(callback)

    def on_tools_changed(self, callback: ToolsChangedCallback) -> None:
        """Register callback for tools list changes."""
        self._tools_changed_callbacks.append(callback)

    def on_resources_changed(self, callback: ResourcesChangedCallback) -> None:
        """Register callback for resources list changes."""
        self._resources_changed_callbacks.append(callback)

    def on_prompts_changed(self, callback: PromptsChangedCallback) -> None:
        """Register callback for prompts list changes."""
        self._prompts_changed_callbacks.append(callback)

    def on_resource_updated(self, callback: ResourceUpdatedCallback) -> None:
        """Register callback for resource content updates."""
        self._resource_updated_callbacks.append(callback)

    def on_progress(self, callback: ProgressCallback) -> None:
        """Register callback for progress notifications."""
        self._progress_callbacks.append(callback)

    def on_log(self, callback: LogCallback) -> None:
        """Register callback for log messages from servers."""
        self._log_callbacks.append(callback)

    def _notify_state_change(self, server_id: str, state: MCPConnectionState) -> None:
        """Notify callbacks of state change."""
        for callback in self._state_callbacks:
            try:
                callback(server_id, state)
            except Exception as e:
                logger.warning(f"State change callback error: {e}")

    def _notify_tools_changed(self, server_id: str) -> None:
        """Notify callbacks of tools list change."""
        for callback in self._tools_changed_callbacks:
            try:
                callback(server_id)
            except Exception as e:
                logger.warning(f"Tools changed callback error: {e}")

    def _notify_resources_changed(self, server_id: str) -> None:
        """Notify callbacks of resources list change."""
        for callback in self._resources_changed_callbacks:
            try:
                callback(server_id)
            except Exception as e:
                logger.warning(f"Resources changed callback error: {e}")

    def _notify_prompts_changed(self, server_id: str) -> None:
        """Notify callbacks of prompts list change."""
        for callback in self._prompts_changed_callbacks:
            try:
                callback(server_id)
            except Exception as e:
                logger.warning(f"Prompts changed callback error: {e}")

    def _notify_resource_updated(self, server_id: str, uri: str) -> None:
        """Notify callbacks of resource content update."""
        for callback in self._resource_updated_callbacks:
            try:
                callback(server_id, uri)
            except Exception as e:
                logger.warning(f"Resource updated callback error: {e}")

    def _notify_progress(self, server_id: str, progress: MCPProgress) -> None:
        """Notify callbacks of progress update."""
        for callback in self._progress_callbacks:
            try:
                callback(server_id, progress)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    def _notify_log(self, server_id: str, level: LoggingLevel, logger_name: str, data: Any) -> None:
        """Notify callbacks of log message."""
        for callback in self._log_callbacks:
            try:
                callback(server_id, level, logger_name, data)
            except Exception as e:
                logger.warning(f"Log callback error: {e}")

    # Server capability checking
    def has_capability(self, server_id: str, capability: ServerCapability) -> bool:
        """Check if a server has a specific capability."""
        conn = self._connections.get(server_id)
        if not conn or conn.state != MCPConnectionState.CONNECTED:
            return False

        caps = conn.capabilities
        match capability:
            case ServerCapability.EXPERIMENTAL:
                return caps.experimental is not None
            case ServerCapability.LOGGING:
                return caps.logging
            case ServerCapability.PROMPTS:
                return caps.prompts
            case ServerCapability.RESOURCES:
                return caps.resources
            case ServerCapability.TOOLS:
                return caps.tools
            case ServerCapability.COMPLETIONS:
                return caps.completions
        return False

    async def connect(self, server_id: str) -> bool:
        """Connect to an MCP server."""
        if server_id not in self._server_configs:
            logger.error(f"Unknown MCP server: {server_id}")
            return False

        config = self._server_configs[server_id]

        if not config.enabled:
            logger.info(f"MCP server {server_id} is disabled")
            return False

        # Check if already connected
        existing = self._connections.get(server_id)
        if existing and existing.state == MCPConnectionState.CONNECTED:
            logger.debug(f"Already connected to {server_id}")
            return True

        # Create connection object
        connection = MCPConnection(server_config=config)
        connection.state = MCPConnectionState.CONNECTING
        self._connections[server_id] = connection
        self._notify_state_change(server_id, MCPConnectionState.CONNECTING)

        try:
            await self._establish_connection(connection)
            connection.state = MCPConnectionState.CONNECTED
            self._notify_state_change(server_id, MCPConnectionState.CONNECTED)
            logger.info(f"Connected to MCP server: {server_id}")
            return True
        except Exception as e:
            connection.state = MCPConnectionState.ERROR
            connection.error_message = str(e)
            self._notify_state_change(server_id, MCPConnectionState.ERROR)
            logger.error(f"Failed to connect to MCP server {server_id}: {e}")
            return False

    async def _establish_connection(self, connection: MCPConnection) -> None:
        """Establish connection to an MCP server."""
        try:
            import mcp
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp.client.sse import sse_client
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as e:
            raise RuntimeError(
                f"MCP package import error: {e}. Install with: pip install mcp>=1.25.0"
            ) from e

        config = connection.server_config.config
        server_id = connection.server_config.id
        connection._exit_stack = contextlib.AsyncExitStack()

        try:
            # Create transport based on config type
            if isinstance(config, MCPStdioConfig):
                server_params = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=config.env if config.env else None,
                    cwd=config.cwd,
                )
                transport = stdio_client(server_params)
                read_stream, write_stream = await connection._exit_stack.enter_async_context(
                    transport
                )
            elif isinstance(config, MCPSSEConfig):
                transport = sse_client(
                    url=config.url,
                    headers=config.headers if config.headers else None,
                    timeout=config.timeout,
                    sse_read_timeout=config.sse_read_timeout,
                )
                read_stream, write_stream = await connection._exit_stack.enter_async_context(
                    transport
                )
            else:  # MCPHttpConfig
                import httpx
                from mcp.shared._httpx_utils import create_mcp_http_client

                http_client = create_mcp_http_client(
                    headers=config.headers if config.headers else None,
                    timeout=httpx.Timeout(config.timeout, read=config.sse_read_timeout),
                )
                await connection._exit_stack.enter_async_context(http_client)

                transport = streamablehttp_client(
                    url=config.url,
                    http_client=http_client,
                )
                read_stream, write_stream, _ = await connection._exit_stack.enter_async_context(
                    transport
                )

            # Create and initialize session
            session = await connection._exit_stack.enter_async_context(
                mcp.ClientSession(
                    read_stream,
                    write_stream,
                    client_info=mcp.Implementation(
                        name="SuperQode",
                        version="0.1.0",
                    ),
                )
            )

            # Initialize the connection
            result = await session.initialize()
            connection.session = session

            # Parse server capabilities
            connection.capabilities = self._parse_capabilities(result.capabilities)
            connection.server_info = MCPServerInfo(
                name=result.serverInfo.name,
                version=result.serverInfo.version,
                capabilities=connection.capabilities,
                protocol_version=str(result.protocolVersion)
                if hasattr(result, "protocolVersion")
                else "",
            )

            # Discover tools, resources, and prompts
            await self._discover_capabilities(connection)

            # Set up notification handlers
            self._setup_notification_handlers(connection, server_id)

        except Exception:
            if connection._exit_stack:
                await connection._exit_stack.aclose()
                connection._exit_stack = None
            raise

    def _parse_capabilities(self, caps: Any) -> MCPServerCapabilities:
        """Parse server capabilities from initialization response."""
        if caps is None:
            return MCPServerCapabilities()

        result = MCPServerCapabilities()

        if hasattr(caps, "experimental") and caps.experimental:
            result.experimental = dict(caps.experimental)

        if hasattr(caps, "logging") and caps.logging:
            result.logging = True

        if hasattr(caps, "prompts") and caps.prompts:
            result.prompts = True
            if hasattr(caps.prompts, "listChanged"):
                result.prompts_list_changed = bool(caps.prompts.listChanged)

        if hasattr(caps, "resources") and caps.resources:
            result.resources = True
            if hasattr(caps.resources, "subscribe"):
                result.resources_subscribe = bool(caps.resources.subscribe)
            if hasattr(caps.resources, "listChanged"):
                result.resources_list_changed = bool(caps.resources.listChanged)

        if hasattr(caps, "tools") and caps.tools:
            result.tools = True
            if hasattr(caps.tools, "listChanged"):
                result.tools_list_changed = bool(caps.tools.listChanged)

        if hasattr(caps, "completions") and caps.completions:
            result.completions = True

        return result

    def _setup_notification_handlers(self, connection: MCPConnection, server_id: str) -> None:
        """Set up handlers for server notifications."""
        # Note: The MCP Python SDK handles notifications through callbacks
        # This is a placeholder for when we need to handle specific notifications
        pass

    async def _discover_capabilities(self, connection: MCPConnection) -> None:
        """Discover tools, resources, and prompts from a connected server."""
        session = connection.session
        server_id = connection.server_config.id

        # Discover tools
        if connection.capabilities.tools:
            try:
                tools_result = await session.list_tools()
                connection.tools = [
                    self._parse_tool(tool, server_id) for tool in tools_result.tools
                ]
                logger.debug(f"Discovered {len(connection.tools)} tools from {server_id}")
            except Exception as e:
                logger.warning(f"Failed to list tools from {server_id}: {e}")
                connection.tools = []

        # Discover resources
        if connection.capabilities.resources:
            try:
                resources_result = await session.list_resources()
                connection.resources = [
                    MCPResource(
                        uri=str(resource.uri),
                        name=resource.name,
                        description=resource.description,
                        mime_type=getattr(resource, "mimeType", None),
                        server_id=server_id,
                    )
                    for resource in resources_result.resources
                ]
                logger.debug(f"Discovered {len(connection.resources)} resources from {server_id}")
            except Exception as e:
                logger.warning(f"Failed to list resources from {server_id}: {e}")
                connection.resources = []

            # Discover resource templates
            try:
                templates_result = await session.list_resource_templates()
                connection.resource_templates = [
                    MCPResourceTemplate(
                        uri_template=template.uriTemplate,
                        name=template.name,
                        description=template.description,
                        mime_type=getattr(template, "mimeType", None),
                        server_id=server_id,
                    )
                    for template in templates_result.resourceTemplates
                ]
                logger.debug(
                    f"Discovered {len(connection.resource_templates)} resource templates from {server_id}"
                )
            except Exception as e:
                logger.debug(f"No resource templates from {server_id}: {e}")
                connection.resource_templates = []

        # Discover prompts
        if connection.capabilities.prompts:
            try:
                prompts_result = await session.list_prompts()
                connection.prompts = [
                    MCPPrompt(
                        name=prompt.name,
                        description=prompt.description,
                        arguments=[
                            MCPPromptArgument(
                                name=arg.name,
                                description=arg.description,
                                required=getattr(arg, "required", False),
                            )
                            for arg in (prompt.arguments or [])
                        ],
                        server_id=server_id,
                    )
                    for prompt in prompts_result.prompts
                ]
                logger.debug(f"Discovered {len(connection.prompts)} prompts from {server_id}")
            except Exception as e:
                logger.warning(f"Failed to list prompts from {server_id}: {e}")
                connection.prompts = []

    def _parse_tool(self, tool: Any, server_id: str) -> MCPTool:
        """Parse a tool from the MCP response."""
        annotations = None
        if hasattr(tool, "annotations") and tool.annotations:
            annotations = ToolAnnotations(
                title=getattr(tool.annotations, "title", None),
                read_only_hint=getattr(tool.annotations, "readOnlyHint", None),
                destructive_hint=getattr(tool.annotations, "destructiveHint", None),
                idempotent_hint=getattr(tool.annotations, "idempotentHint", None),
                open_world_hint=getattr(tool.annotations, "openWorldHint", None),
            )

        return MCPTool(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
            output_schema=getattr(tool, "outputSchema", None),
            server_id=server_id,
            annotations=annotations,
        )

    async def disconnect(self, server_id: str) -> None:
        """Disconnect from an MCP server."""
        connection = self._connections.get(server_id)
        if not connection:
            return

        # Mark as disconnected first to prevent race conditions
        old_state = connection.state
        connection.state = MCPConnectionState.DISCONNECTED
        connection.session = None

        if connection._exit_stack:
            try:
                # Give the exit stack a chance to clean up with a timeout
                import asyncio

                await asyncio.wait_for(connection._exit_stack.aclose(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout closing connection to {server_id}")
            except asyncio.CancelledError:
                logger.debug(f"Disconnect cancelled for {server_id}")
            except RuntimeError as e:
                # Handle anyio cancel scope issues gracefully
                if "cancel scope" in str(e).lower():
                    logger.debug(f"Cancel scope issue during disconnect from {server_id}: {e}")
                else:
                    logger.warning(f"Runtime error closing connection to {server_id}: {e}")
            except Exception as e:
                logger.warning(f"Error closing connection to {server_id}: {e}")
            finally:
                connection._exit_stack = None

        connection.tools = []
        connection.resources = []
        connection.resource_templates = []
        connection.prompts = []
        connection.subscribed_resources.clear()

        if old_state != MCPConnectionState.DISCONNECTED:
            self._notify_state_change(server_id, MCPConnectionState.DISCONNECTED)
        logger.info(f"Disconnected from MCP server: {server_id}")

    async def connect_all(self) -> dict[str, bool]:
        """Connect to all enabled servers with auto_connect=True."""
        results = {}
        for server_id, config in self._server_configs.items():
            if config.enabled and config.auto_connect:
                results[server_id] = await self.connect(server_id)
        return results

    async def disconnect_all(self) -> None:
        """Disconnect from all connected servers."""
        # Must disconnect sequentially - anyio cancel scopes must be exited
        # in the same task they were entered
        for server_id in list(self._connections.keys()):
            try:
                await self.disconnect(server_id)
            except Exception as e:
                logger.warning(f"Error disconnecting from {server_id}: {e}")

    async def reconnect(self, server_id: str) -> bool:
        """Reconnect to an MCP server."""
        await self.disconnect(server_id)
        return await self.connect(server_id)

    async def restart_server(self, server_id: str) -> bool:
        """Restart an MCP server (stop and start)."""
        return await self.reconnect(server_id)

    # Tool operations

    def list_all_tools(self) -> list[MCPTool]:
        """List all available tools from all connected servers."""
        tools = []
        for connection in self._connections.values():
            if connection.state == MCPConnectionState.CONNECTED:
                tools.extend(connection.tools)
        return tools

    def get_tool(self, server_id: str, tool_name: str) -> MCPTool | None:
        """Get a specific tool by server ID and name."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return None

        for tool in connection.tools:
            if tool.name == tool_name:
                return tool
        return None

    def find_tool(self, tool_name: str) -> tuple[str, MCPTool] | None:
        """Find a tool by name across all servers."""
        for server_id, connection in self._connections.items():
            if connection.state != MCPConnectionState.CONNECTED:
                continue
            for tool in connection.tools:
                if tool.name == tool_name:
                    return (server_id, tool)
        return None

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> MCPToolResult:
        """Execute a tool on an MCP server."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return MCPToolResult(
                content=[],
                is_error=True,
                error_message=f"Not connected to server: {server_id}",
            )

        try:
            result = await connection.session.call_tool(tool_name, arguments)

            # Convert content to dict format
            content = []
            for item in result.content:
                if hasattr(item, "text"):
                    content.append({"type": "text", "text": item.text})
                elif hasattr(item, "data") and hasattr(item, "mimeType"):
                    if "image" in getattr(item, "mimeType", ""):
                        content.append(
                            {
                                "type": "image",
                                "data": item.data,
                                "mimeType": item.mimeType,
                            }
                        )
                    elif "audio" in getattr(item, "mimeType", ""):
                        content.append(
                            {
                                "type": "audio",
                                "data": item.data,
                                "mimeType": item.mimeType,
                            }
                        )
                elif hasattr(item, "resource"):
                    content.append(
                        {
                            "type": "resource",
                            "uri": str(item.resource.uri),
                            "mimeType": getattr(item.resource, "mimeType", None),
                        }
                    )
                else:
                    content.append({"type": "unknown", "data": str(item)})

            return MCPToolResult(
                content=content,
                is_error=getattr(result, "isError", False),
                structured_content=getattr(result, "structuredContent", None),
            )
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return MCPToolResult(
                content=[],
                is_error=True,
                error_message=str(e),
            )

    # Resource operations

    def list_all_resources(self) -> list[MCPResource]:
        """List all available resources from all connected servers."""
        resources = []
        for connection in self._connections.values():
            if connection.state == MCPConnectionState.CONNECTED:
                resources.extend(connection.resources)
        return resources

    def list_all_resource_templates(self) -> list[MCPResourceTemplate]:
        """List all available resource templates from all connected servers."""
        templates = []
        for connection in self._connections.values():
            if connection.state == MCPConnectionState.CONNECTED:
                templates.extend(connection.resource_templates)
        return templates

    async def read_resource(self, server_id: str, uri: str) -> MCPResourceContent | None:
        """Read a resource from an MCP server."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return None

        try:
            result = await connection.session.read_resource(uri)

            if result.contents:
                content = result.contents[0]
                return MCPResourceContent(
                    uri=uri,
                    mime_type=getattr(content, "mimeType", None),
                    text=getattr(content, "text", None),
                    blob=getattr(content, "blob", None),
                )
            return None
        except Exception as e:
            logger.error(f"Failed to read resource {uri}: {e}")
            return None

    async def subscribe_resource(self, server_id: str, uri: str) -> bool:
        """Subscribe to resource updates."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return False

        if not connection.capabilities.resources_subscribe:
            logger.warning(f"Server {server_id} does not support resource subscriptions")
            return False

        try:
            await connection.session.subscribe_resource(uri)
            connection.subscribed_resources.add(uri)
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to resource {uri}: {e}")
            return False

    async def unsubscribe_resource(self, server_id: str, uri: str) -> bool:
        """Unsubscribe from resource updates."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return False

        try:
            await connection.session.unsubscribe_resource(uri)
            connection.subscribed_resources.discard(uri)
            return True
        except Exception as e:
            logger.error(f"Failed to unsubscribe from resource {uri}: {e}")
            return False

    # Prompt operations

    def list_all_prompts(self) -> list[MCPPrompt]:
        """List all available prompts from all connected servers."""
        prompts = []
        for connection in self._connections.values():
            if connection.state == MCPConnectionState.CONNECTED:
                prompts.extend(connection.prompts)
        return prompts

    async def get_prompt(
        self,
        server_id: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> MCPPromptResult | None:
        """Get a prompt from an MCP server."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return None

        try:
            result = await connection.session.get_prompt(prompt_name, arguments or {})

            messages = []
            for msg in result.messages:
                role = msg.role
                if hasattr(msg.content, "text"):
                    content = msg.content.text
                else:
                    content = str(msg.content)
                messages.append(MCPPromptMessage(role=role, content=content))

            return MCPPromptResult(
                description=result.description,
                messages=messages,
            )
        except Exception as e:
            logger.error(f"Failed to get prompt {prompt_name}: {e}")
            return None

    # Completion operations

    async def complete_prompt_argument(
        self,
        server_id: str,
        prompt_name: str,
        argument_name: str,
        argument_value: str,
    ) -> MCPCompletionResult | None:
        """Get completions for a prompt argument."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return None

        if not connection.capabilities.completions:
            return None

        try:
            result = await connection.session.complete(
                ref={"type": "ref/prompt", "name": prompt_name},
                argument={"name": argument_name, "value": argument_value},
            )

            return MCPCompletionResult(
                values=result.completion.values,
                total=getattr(result.completion, "total", None),
                has_more=getattr(result.completion, "hasMore", None),
            )
        except Exception as e:
            logger.error(f"Failed to get completions: {e}")
            return None

    async def complete_resource_argument(
        self,
        server_id: str,
        uri: str,
        argument_name: str,
        argument_value: str,
    ) -> MCPCompletionResult | None:
        """Get completions for a resource argument."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return None

        if not connection.capabilities.completions:
            return None

        try:
            result = await connection.session.complete(
                ref={"type": "ref/resource", "uri": uri},
                argument={"name": argument_name, "value": argument_value},
            )

            return MCPCompletionResult(
                values=result.completion.values,
                total=getattr(result.completion, "total", None),
                has_more=getattr(result.completion, "hasMore", None),
            )
        except Exception as e:
            logger.error(f"Failed to get completions: {e}")
            return None

    # Logging operations

    async def set_logging_level(self, server_id: str, level: LoggingLevel) -> bool:
        """Set the logging level for a server."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return False

        if not connection.capabilities.logging:
            logger.warning(f"Server {server_id} does not support logging")
            return False

        try:
            await connection.session.set_logging_level(level.value)
            return True
        except Exception as e:
            logger.error(f"Failed to set logging level: {e}")
            return False

    # Refresh operations (for list_changed notifications)

    async def refresh_tools(self, server_id: str) -> None:
        """Refresh the tools list for a server."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return

        if not connection.capabilities.tools:
            return

        try:
            tools_result = await connection.session.list_tools()
            connection.tools = [self._parse_tool(tool, server_id) for tool in tools_result.tools]
            self._notify_tools_changed(server_id)
        except Exception as e:
            logger.error(f"Failed to refresh tools: {e}")

    async def refresh_resources(self, server_id: str) -> None:
        """Refresh the resources list for a server."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return

        if not connection.capabilities.resources:
            return

        try:
            resources_result = await connection.session.list_resources()
            connection.resources = [
                MCPResource(
                    uri=str(resource.uri),
                    name=resource.name,
                    description=resource.description,
                    mime_type=getattr(resource, "mimeType", None),
                    server_id=server_id,
                )
                for resource in resources_result.resources
            ]
            self._notify_resources_changed(server_id)
        except Exception as e:
            logger.error(f"Failed to refresh resources: {e}")

    async def refresh_prompts(self, server_id: str) -> None:
        """Refresh the prompts list for a server."""
        connection = self._connections.get(server_id)
        if not connection or connection.state != MCPConnectionState.CONNECTED:
            return

        if not connection.capabilities.prompts:
            return

        try:
            prompts_result = await connection.session.list_prompts()
            connection.prompts = [
                MCPPrompt(
                    name=prompt.name,
                    description=prompt.description,
                    arguments=[
                        MCPPromptArgument(
                            name=arg.name,
                            description=arg.description,
                            required=getattr(arg, "required", False),
                        )
                        for arg in (prompt.arguments or [])
                    ],
                    server_id=server_id,
                )
                for prompt in prompts_result.prompts
            ]
            self._notify_prompts_changed(server_id)
        except Exception as e:
            logger.error(f"Failed to refresh prompts: {e}")

    # Utility methods

    def get_status_summary(self) -> dict[str, Any]:
        """Get a summary of all server connection statuses."""
        return {
            "total_servers": len(self._server_configs),
            "connected": sum(
                1 for c in self._connections.values() if c.state == MCPConnectionState.CONNECTED
            ),
            "total_tools": len(self.list_all_tools()),
            "total_resources": len(self.list_all_resources()),
            "total_resource_templates": len(self.list_all_resource_templates()),
            "total_prompts": len(self.list_all_prompts()),
            "servers": {
                server_id: {
                    "state": conn.state.value,
                    "server_name": conn.server_info.name if conn.server_info else None,
                    "server_version": conn.server_info.version if conn.server_info else None,
                    "tools": len(conn.tools),
                    "resources": len(conn.resources),
                    "resource_templates": len(conn.resource_templates),
                    "prompts": len(conn.prompts),
                    "subscribed_resources": len(conn.subscribed_resources),
                    "capabilities": {
                        "logging": conn.capabilities.logging,
                        "prompts": conn.capabilities.prompts,
                        "resources": conn.capabilities.resources,
                        "tools": conn.capabilities.tools,
                        "completions": conn.capabilities.completions,
                    },
                    "error": conn.error_message,
                }
                for server_id, conn in self._connections.items()
            },
        }

    def get_server_info(self, server_id: str) -> MCPServerInfo | None:
        """Get server information for a connected server."""
        connection = self._connections.get(server_id)
        if connection and connection.state == MCPConnectionState.CONNECTED:
            return connection.server_info
        return None

    def configured_server_ids(self) -> list[str]:
        """Get list of configured server IDs (enabled only)."""
        return [server_id for server_id, config in self._server_configs.items() if config.enabled]

    def running_server_ids(self) -> list[str]:
        """Get list of currently running server IDs."""
        return [
            server_id
            for server_id, conn in self._connections.items()
            if conn.state == MCPConnectionState.CONNECTED
        ]

    # ========================================================================
    # OAuth Support Methods
    # ========================================================================

    async def authenticate_server(self, server_id: str) -> bool:
        """
        Perform OAuth authentication for a server.

        Opens browser for user authentication and waits for callback.
        Returns True if authentication succeeds.
        """
        config = self._server_configs.get(server_id)
        if not config:
            logger.error(f"Unknown server: {server_id}")
            return False

        # Only HTTP/SSE configs might need OAuth
        if isinstance(config.config, MCPStdioConfig):
            logger.debug(f"Server {server_id} uses stdio, OAuth not applicable")
            return True

        try:
            from superqode.mcp.oauth import MCPOAuthProvider, OAuthConfig
            from superqode.mcp.oauth_callback import get_callback_server
            from superqode.mcp.auth_storage import get_auth_storage

            # Get server URL
            if isinstance(config.config, (MCPHttpConfig, MCPSSEConfig)):
                server_url = config.config.url
            else:
                return True  # Non-HTTP doesn't need OAuth

            # Check for existing valid tokens
            storage = get_auth_storage()
            existing_tokens = storage.load_tokens(server_url)
            if existing_tokens and not existing_tokens.is_expired():
                logger.debug(f"Using existing tokens for {server_id}")
                return True

            # Try to refresh if we have a refresh token
            if existing_tokens and existing_tokens.refresh_token:
                try:
                    provider = MCPOAuthProvider()
                    new_tokens = await provider.refresh_tokens(
                        existing_tokens.refresh_token,
                        server_url,
                    )
                    storage.save_tokens(server_url, new_tokens)
                    logger.info(f"Refreshed tokens for {server_id}")
                    return True
                except Exception as e:
                    logger.debug(f"Token refresh failed: {e}")

            # Start OAuth flow
            callback_server = await get_callback_server()
            oauth_config = OAuthConfig(
                redirect_uri=callback_server.get_redirect_uri(),
            )
            provider = MCPOAuthProvider(oauth_config)

            # Get authorization URL
            auth_url = await provider.start_auth_flow(server_url)

            # Update connection state
            connection = self._connections.get(server_id)
            if connection:
                connection.state = MCPConnectionState.NEEDS_AUTH
                self._notify_state_change(server_id, MCPConnectionState.NEEDS_AUTH)

            # Open browser for authentication
            logger.info(f"Opening browser for {server_id} authentication")
            webbrowser.open(auth_url)

            # Wait for callback
            # Extract state from URL
            import urllib.parse

            parsed = urllib.parse.urlparse(auth_url)
            params = urllib.parse.parse_qs(parsed.query)
            state = params.get("state", [None])[0]

            if not state:
                logger.error("Failed to extract state from auth URL")
                return False

            result = await callback_server.wait_for_callback(state, timeout=300)

            if result.error:
                logger.error(f"OAuth error: {result.error} - {result.error_description}")
                return False

            if not result.code:
                logger.error("No authorization code received")
                return False

            # Exchange code for tokens
            tokens = await provider.handle_callback(result.code, result.state)

            # Store tokens
            storage.save_tokens(server_url, tokens)
            logger.info(f"OAuth authentication successful for {server_id}")

            return True

        except ImportError as e:
            logger.warning(f"OAuth dependencies not available: {e}")
            return True  # Continue without OAuth
        except Exception as e:
            logger.error(f"OAuth authentication failed for {server_id}: {e}")
            return False

    async def get_auth_headers(self, server_id: str) -> dict[str, str]:
        """
        Get authentication headers for a server.

        Returns headers dict with Authorization if tokens are available.
        """
        config = self._server_configs.get(server_id)
        if not config:
            return {}

        if isinstance(config.config, MCPStdioConfig):
            return {}

        try:
            from superqode.mcp.auth_storage import get_auth_storage

            # Get server URL
            if isinstance(config.config, (MCPHttpConfig, MCPSSEConfig)):
                server_url = config.config.url
            else:
                return {}

            storage = get_auth_storage()

            # Try OAuth tokens first
            tokens = storage.load_tokens(server_url)
            if tokens and not tokens.is_expired():
                return {"Authorization": f"{tokens.token_type} {tokens.access_token}"}

            # Try bearer token
            bearer = storage.load_bearer_token(server_url)
            if bearer:
                return {"Authorization": f"Bearer {bearer}"}

            # Try API key
            api_key = storage.load_api_key(server_url)
            if api_key:
                return {"X-API-Key": api_key}

            return {}

        except ImportError:
            return {}
        except Exception as e:
            logger.debug(f"Error getting auth headers: {e}")
            return {}

    def needs_authentication(self, server_id: str) -> bool:
        """Check if a server is waiting for authentication."""
        connection = self._connections.get(server_id)
        return connection is not None and connection.state == MCPConnectionState.NEEDS_AUTH

    async def clear_server_credentials(self, server_id: str) -> None:
        """Clear stored credentials for a server."""
        config = self._server_configs.get(server_id)
        if not config:
            return

        try:
            from superqode.mcp.auth_storage import get_auth_storage

            if isinstance(config.config, (MCPHttpConfig, MCPSSEConfig)):
                storage = get_auth_storage()
                storage.clear_tokens(config.config.url)
                logger.info(f"Cleared credentials for {server_id}")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Error clearing credentials: {e}")
