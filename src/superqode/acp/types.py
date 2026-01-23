"""
ACP Protocol Types for SuperQode.

Based on https://agentclientprotocol.com/protocol/schema
"""

from typing import TypedDict, Literal, Any, List, Dict, Optional, Union

try:
    from typing import Required
except ImportError:
    # Python < 3.12 compatibility
    from typing_extensions import Required


# Client Capabilities
class FileSystemCapability(TypedDict, total=False):
    readTextFile: bool
    writeTextFile: bool


class ClientCapabilities(TypedDict, total=False):
    fs: FileSystemCapability
    terminal: bool


class Implementation(TypedDict, total=False):
    name: str
    title: Optional[str]
    version: str


# Agent Capabilities
class PromptCapabilities(TypedDict, total=False):
    audio: bool
    embeddedContent: bool
    image: bool


class AgentCapabilities(TypedDict, total=False):
    loadSession: bool
    promptCapabilities: PromptCapabilities


# Content Types
class TextContent(TypedDict, total=False):
    type: str
    text: str


class ImageContent(TypedDict, total=False):
    type: str
    data: str
    mimeType: str


ContentBlock = Union[TextContent, ImageContent, Dict[str, Any]]


# Tool Call Types
ToolKind = Literal[
    "read", "edit", "delete", "move", "search", "execute", "think", "fetch", "switch_mode", "other"
]

ToolCallStatus = Literal["pending", "in_progress", "completed", "failed"]


class ToolCallLocation(TypedDict, total=False):
    line: Optional[int]
    path: str


class ToolCallContentDiff(TypedDict, total=False):
    newText: str
    oldText: Optional[str]
    path: str
    type: str


class ToolCallContentTerminal(TypedDict, total=False):
    terminalId: str
    type: str


ToolCallContent = Union[ToolCallContentDiff, ToolCallContentTerminal, Dict[str, Any]]


class ToolCall(TypedDict, total=False):
    _meta: dict
    content: List[ToolCallContent]
    kind: str
    locations: List[ToolCallLocation]
    rawInput: dict
    rawOutput: dict
    sessionUpdate: str
    status: str
    title: str
    toolCallId: str


class ToolCallUpdate(TypedDict, total=False):
    _meta: dict
    content: Optional[List[ToolCallContent]]
    kind: Optional[str]
    locations: Optional[list]
    rawInput: dict
    rawOutput: dict
    sessionUpdate: str
    status: Optional[str]
    title: Optional[str]
    toolCallId: str


# Permission Types
PermissionOptionKind = Literal["allow_once", "allow_always", "reject_once", "reject_always"]


class PermissionOption(TypedDict, total=False):
    _meta: dict
    kind: str
    name: str
    optionId: str


class PermissionRequest(TypedDict, total=False):
    sessionId: str
    options: List[PermissionOption]
    toolCall: ToolCall


# Session Updates
class AgentMessageChunk(TypedDict, total=False):
    content: ContentBlock
    sessionUpdate: str


class AgentThoughtChunk(TypedDict, total=False):
    content: ContentBlock
    sessionUpdate: str


class PlanEntry(TypedDict, total=False):
    content: str
    priority: str
    status: str


class Plan(TypedDict, total=False):
    entries: List[PlanEntry]
    sessionUpdate: str


SessionUpdate = Union[
    AgentMessageChunk, AgentThoughtChunk, ToolCall, ToolCallUpdate, Plan, Dict[str, Any]
]


# Response Types
class InitializeResponse(TypedDict, total=False):
    agentCapabilities: AgentCapabilities
    protocolVersion: int


class SessionMode(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]


class SessionModeState(TypedDict, total=False):
    availableModes: List[SessionMode]
    currentModeId: str


class NewSessionResponse(TypedDict, total=False):
    sessionId: str
    modes: Optional[SessionModeState]


class SessionPromptResponse(TypedDict, total=False):
    stopReason: str


class RequestPermissionResponse(TypedDict, total=False):
    outcome: Dict[str, Any]


# Terminal Types
class EnvVariable(TypedDict, total=False):
    name: str
    value: str


class CreateTerminalResponse(TypedDict, total=False):
    terminalId: str


class TerminalOutputResponse(TypedDict, total=False):
    output: str
    truncated: bool
    exitStatus: Optional[dict]


class WaitForTerminalExitResponse(TypedDict, total=False):
    exitCode: Optional[int]
    signal: Optional[str]


# ============================================================================
# Authentication Types (ACP Protocol Completeness)
# ============================================================================


class AuthMethod(TypedDict, total=False):
    """Authentication method supported by the agent."""

    type: str  # "api_key", "oauth2", "bearer", etc.
    name: str
    description: Optional[str]
    required: bool
    config: Optional[Dict[str, Any]]


class AuthMethodsResponse(TypedDict, total=False):
    """Response containing available authentication methods."""

    authMethods: List[AuthMethod]


class AuthConfig(TypedDict, total=False):
    """Authentication configuration."""

    type: str
    credentials: Dict[str, Any]


# ============================================================================
# Mode and Model Types (ACP Protocol Completeness)
# ============================================================================


class AvailableMode(TypedDict, total=False):
    """An available mode that the agent can operate in."""

    slug: str
    name: str
    description: Optional[str]
    icon: Optional[str]


class AvailableModel(TypedDict, total=False):
    """An available model that the agent can use."""

    id: str
    name: str
    provider: Optional[str]
    description: Optional[str]
    capabilities: Optional[List[str]]
    context_window: Optional[int]
    max_output_tokens: Optional[int]


class ModesResponse(TypedDict, total=False):
    """Response containing available modes."""

    modes: List[AvailableMode]
    currentMode: Optional[str]


class ModelsResponse(TypedDict, total=False):
    """Response containing available models."""

    models: List[AvailableModel]
    currentModel: Optional[str]


class SetModeRequest(TypedDict, total=False):
    """Request to set the current mode."""

    sessionId: str
    modeSlug: str


class SetModelRequest(TypedDict, total=False):
    """Request to set the current model."""

    sessionId: str
    modelId: str


# ============================================================================
# Slash Command Types (ACP Protocol Completeness)
# ============================================================================


class CommandArg(TypedDict, total=False):
    """Argument for a slash command."""

    name: str
    description: Optional[str]
    required: bool
    type: str  # "string", "number", "boolean", "file", etc.
    default: Optional[Any]
    choices: Optional[List[str]]


class SlashCommand(TypedDict, total=False):
    """A slash command available in the agent."""

    name: str
    description: str
    args: Optional[List[CommandArg]]
    category: Optional[str]
    aliases: Optional[List[str]]


class AvailableCommandsUpdate(TypedDict, total=False):
    """Update containing available commands."""

    commands: List[SlashCommand]
    sessionUpdate: str  # "available_commands"


class AvailableCommandsResponse(TypedDict, total=False):
    """Response containing available commands."""

    commands: List[SlashCommand]


# ============================================================================
# Batch Request Types (ACP Protocol Completeness)
# ============================================================================


class BatchRequestItem(TypedDict, total=False):
    """A single request in a batch."""

    id: str
    method: str
    params: Dict[str, Any]


class BatchRequest(TypedDict, total=False):
    """A batch of requests to execute."""

    requests: List[BatchRequestItem]


class BatchResponseItem(TypedDict, total=False):
    """A single response in a batch."""

    id: str
    result: Optional[Dict[str, Any]]
    error: Optional[Dict[str, Any]]


class BatchResponse(TypedDict, total=False):
    """Response containing batch results."""

    responses: List[BatchResponseItem]


# ============================================================================
# Extended Session Types (ACP Protocol Completeness)
# ============================================================================


class SessionConfig(TypedDict, total=False):
    """Configuration for a session."""

    cwd: str
    env: Optional[Dict[str, str]]
    mcpServers: Optional[List[Dict[str, Any]]]
    mode: Optional[str]
    model: Optional[str]
    systemPrompt: Optional[str]
    maxTurns: Optional[int]
    autoApprove: Optional[List[str]]


class LoadSessionRequest(TypedDict, total=False):
    """Request to load an existing session."""

    sessionId: str
    sessionPath: Optional[str]


class LoadSessionResponse(TypedDict, total=False):
    """Response from loading a session."""

    sessionId: str
    history: List[Dict[str, Any]]
    modes: Optional[SessionModeState]


class SessionInfo(TypedDict, total=False):
    """Information about a session."""

    sessionId: str
    created: str
    lastActive: str
    cwd: str
    mode: Optional[str]
    model: Optional[str]
    messageCount: int


class ListSessionsResponse(TypedDict, total=False):
    """Response containing list of sessions."""

    sessions: List[SessionInfo]


# ============================================================================
# Context Types (ACP Protocol Completeness)
# ============================================================================


class FileContext(TypedDict, total=False):
    """File context to include in a prompt."""

    path: str
    content: Optional[str]
    startLine: Optional[int]
    endLine: Optional[int]


class URLContext(TypedDict, total=False):
    """URL context to include in a prompt."""

    url: str
    content: Optional[str]
    fetchedAt: Optional[str]


class ContextItem(TypedDict, total=False):
    """A context item for the prompt."""

    type: str  # "file", "url", "text", "image"
    file: Optional[FileContext]
    url: Optional[URLContext]
    text: Optional[str]
    image: Optional[ImageContent]


class PromptWithContext(TypedDict, total=False):
    """A prompt with additional context."""

    prompt: List[ContentBlock]
    context: Optional[List[ContextItem]]
    sessionId: str


# ============================================================================
# Capability Extensions (ACP Protocol Completeness)
# ============================================================================


class ExtendedAgentCapabilities(TypedDict, total=False):
    """Extended agent capabilities."""

    loadSession: bool
    promptCapabilities: PromptCapabilities
    modes: bool
    models: bool
    commands: bool
    batch: bool
    streaming: bool
    cancellation: bool


class ExtendedClientCapabilities(TypedDict, total=False):
    """Extended client capabilities."""

    fs: FileSystemCapability
    terminal: bool
    browser: bool  # Can open URLs in browser
    notifications: bool  # Can show notifications
    clipboard: bool  # Can access clipboard
    ui: bool  # Has UI for interactive prompts
