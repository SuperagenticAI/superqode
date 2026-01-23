"""MCP type definitions for SuperQode.

This module defines the data types used for MCP tool, resource, and prompt
representations within SuperQode. Aligned with MCP protocol version 2025-03-26.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class ServerCapability(Enum):
    """Server capabilities that can be checked."""

    EXPERIMENTAL = "experimental"
    LOGGING = "logging"
    PROMPTS = "prompts"
    RESOURCES = "resources"
    TOOLS = "tools"
    COMPLETIONS = "completions"


class LoggingLevel(Enum):
    """MCP logging levels."""

    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    ALERT = "alert"
    EMERGENCY = "emergency"


@dataclass
class ToolAnnotations:
    """Annotations providing hints about tool behavior.

    Attributes:
        title: Human-readable title for the tool
        read_only_hint: If true, the tool does not modify its environment
        destructive_hint: If true, the tool may perform destructive updates
        idempotent_hint: If true, calling repeatedly has no additional effect
        open_world_hint: If true, tool may interact with external entities
    """

    title: str | None = None
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None


@dataclass
class MCPTool:
    """Represents an MCP tool available from a server.

    Attributes:
        name: The tool's unique name
        description: Human-readable description of what the tool does
        input_schema: JSON Schema defining the tool's input parameters
        output_schema: Optional JSON Schema for tool output
        server_id: ID of the server providing this tool
        annotations: Optional hints about tool behavior
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    server_id: str
    output_schema: dict[str, Any] | None = None
    annotations: ToolAnnotations | None = None


@dataclass
class MCPResource:
    """Represents an MCP resource available from a server.

    Attributes:
        uri: The resource's unique URI
        name: Human-readable name for the resource
        description: Optional description of the resource
        mime_type: Optional MIME type of the resource content
        server_id: ID of the server providing this resource
    """

    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = None
    server_id: str = ""


@dataclass
class MCPResourceTemplate:
    """Represents an MCP resource template for dynamic resources.

    Attributes:
        uri_template: URI template with placeholders
        name: Human-readable name for the template
        description: Optional description
        mime_type: Optional MIME type of generated resources
        server_id: ID of the server providing this template
    """

    uri_template: str
    name: str
    description: str | None = None
    mime_type: str | None = None
    server_id: str = ""


@dataclass
class MCPPromptArgument:
    """Argument definition for an MCP prompt.

    Attributes:
        name: Argument name
        description: Optional description
        required: Whether the argument is required
    """

    name: str
    description: str | None = None
    required: bool = False


@dataclass
class MCPPrompt:
    """Represents an MCP prompt template from a server.

    Attributes:
        name: The prompt's unique name
        description: Human-readable description of the prompt
        arguments: List of argument definitions for the prompt
        server_id: ID of the server providing this prompt
    """

    name: str
    description: str | None = None
    arguments: list[MCPPromptArgument] = field(default_factory=list)
    server_id: str = ""


@dataclass
class MCPToolResult:
    """Result from executing an MCP tool.

    Attributes:
        content: The tool's output content (text, images, etc.)
        is_error: Whether the tool execution resulted in an error
        error_message: Error message if is_error is True
        structured_content: Optional structured output data
    """

    content: list[dict[str, Any]]
    is_error: bool = False
    error_message: str | None = None
    structured_content: dict[str, Any] | None = None


@dataclass
class MCPResourceContent:
    """Content retrieved from an MCP resource.

    Attributes:
        uri: The resource URI
        mime_type: MIME type of the content
        text: Text content (if text-based)
        blob: Binary content as base64 (if binary)
    """

    uri: str
    mime_type: str | None = None
    text: str | None = None
    blob: str | None = None


@dataclass
class MCPPromptMessage:
    """A message from an MCP prompt.

    Attributes:
        role: The message role (user, assistant)
        content: The message content
    """

    role: Literal["user", "assistant"]
    content: str | dict[str, Any]


@dataclass
class MCPPromptResult:
    """Result from getting an MCP prompt.

    Attributes:
        description: Optional description of the prompt
        messages: List of messages in the prompt
    """

    description: str | None = None
    messages: list[MCPPromptMessage] = field(default_factory=list)


@dataclass
class MCPCompletionResult:
    """Result from a completion request.

    Attributes:
        values: List of completion values
        total: Total number of completions (if known)
        has_more: Whether more completions are available
    """

    values: list[str]
    total: int | None = None
    has_more: bool | None = None


@dataclass
class MCPRoot:
    """Represents a root directory for the MCP client.

    Attributes:
        uri: The root URI
        name: Optional human-readable name
    """

    uri: str
    name: str | None = None


@dataclass
class MCPServerCapabilities:
    """Server capabilities reported during initialization.

    Attributes:
        experimental: Experimental capabilities
        logging: Logging capability
        prompts: Prompts capability with list_changed support
        resources: Resources capability with subscribe and list_changed
        tools: Tools capability with list_changed support
        completions: Completions capability
    """

    experimental: dict[str, Any] | None = None
    logging: bool = False
    prompts: bool = False
    prompts_list_changed: bool = False
    resources: bool = False
    resources_subscribe: bool = False
    resources_list_changed: bool = False
    tools: bool = False
    tools_list_changed: bool = False
    completions: bool = False


@dataclass
class MCPServerInfo:
    """Information about an MCP server.

    Attributes:
        name: Server name
        version: Server version
        capabilities: Server capabilities
        protocol_version: MCP protocol version
    """

    name: str
    version: str
    capabilities: MCPServerCapabilities
    protocol_version: str = ""


@dataclass
class MCPProgress:
    """Progress notification data.

    Attributes:
        progress_token: Token identifying the operation
        progress: Current progress value (0.0 to 1.0 or absolute)
        total: Optional total value for absolute progress
        message: Optional progress message
    """

    progress_token: str | int
    progress: float
    total: float | None = None
    message: str | None = None
