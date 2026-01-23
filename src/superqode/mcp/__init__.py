"""MCP (Model Context Protocol) support for SuperQode.

This module provides full MCP client support, allowing SuperQode to connect
to local and remote MCP servers for tool execution, resource access, and
prompt management. Implements the MCP protocol aligned with Zed editor's
implementation.

Features:
- Connect to local MCP servers via stdio (subprocess)
- Connect to remote MCP servers via HTTP or SSE
- Automatic tool/resource/prompt discovery on connection
- Tool execution with result formatting for agents
- Resource reading and subscription support
- Prompt retrieval with argument completion
- Logging level control
- Connection state management with callbacks
- Multi-server support with tool aggregation
"""

from superqode.mcp.config import (
    MCPServerConfig,
    MCPStdioConfig,
    MCPHttpConfig,
    MCPSSEConfig,
    load_mcp_config,
    save_mcp_config,
    create_default_mcp_config,
)
from superqode.mcp.client import (
    MCPClientManager,
    MCPConnection,
    MCPConnectionState,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
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
    MCPRoot,
    ServerCapability,
    LoggingLevel,
    ToolAnnotations,
)

__all__ = [
    # Config
    "MCPServerConfig",
    "MCPStdioConfig",
    "MCPHttpConfig",
    "MCPSSEConfig",
    "load_mcp_config",
    "save_mcp_config",
    "create_default_mcp_config",
    # Client
    "MCPClientManager",
    "MCPConnection",
    "MCPConnectionState",
    "LATEST_PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    # Types
    "MCPTool",
    "MCPResource",
    "MCPResourceTemplate",
    "MCPPrompt",
    "MCPPromptArgument",
    "MCPToolResult",
    "MCPResourceContent",
    "MCPPromptResult",
    "MCPPromptMessage",
    "MCPCompletionResult",
    "MCPServerCapabilities",
    "MCPServerInfo",
    "MCPProgress",
    "MCPRoot",
    "ServerCapability",
    "LoggingLevel",
    "ToolAnnotations",
]
