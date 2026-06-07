"""Configuration schema definitions for SuperQode."""

from typing import Dict, List, Optional, Any, Literal
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProviderConfig:
    """Configuration for an AI provider."""

    api_key_env: str = ""
    description: str = ""
    base_url: Optional[str] = None
    recommended_models: List[str] = field(default_factory=list)
    custom_models_allowed: bool = True
    # New: Provider type for custom providers
    type: Optional[str] = None  # "openai-compatible" for custom endpoints


@dataclass
class HandoffConfig:
    """Configuration for role handoff."""

    to: str  # Target role (e.g., "qa.reviewer")
    when: str = "task_complete"  # Trigger condition
    include: List[str] = field(default_factory=lambda: ["summary", "files_modified"])


@dataclass
class CrossValidationConfig:
    """Configuration for cross-model validation."""

    enabled: bool = True
    exclude_same_model: bool = True
    exclude_same_provider: bool = False


@dataclass
class AgentConfigBlock:
    """Configuration for an ACP agent's internal LLM settings."""

    provider: Optional[str] = None
    model: Optional[str] = None


@dataclass
class RoleConfig:
    """Configuration for a team role.

    Supports three execution modes:
    - BYOK (mode="byok"): Direct LLM API calls via gateway
    - ACP (mode="acp"): Full coding agent via Agent Client Protocol
    - LOCAL (mode="local"): Local/self-hosted models (no API keys)
    """

    description: str

    # Execution mode: "byok", "acp", or "local"
    mode: Literal["byok", "acp", "local"] = "byok"

    # BYOK mode settings
    provider: Optional[str] = None  # LLM provider (e.g., "anthropic")
    model: Optional[str] = None  # Model ID (e.g., "claude-sonnet-4")

    # ACP mode settings
    agent: Optional[str] = None  # Agent ID (e.g., "opencode")
    agent_config: Optional[AgentConfigBlock] = None  # Agent's internal LLM config

    # Common settings
    job_description: str = ""
    enabled: bool = True
    mcp_servers: List[str] = field(default_factory=list)
    handoff: Optional[HandoffConfig] = None
    cross_validation: Optional[CrossValidationConfig] = None

    # Expert prompt configuration (for agent roles)
    expert_prompt_enabled: bool = False  # Default: OSS disables expert prompts
    expert_prompt: Optional[str] = None  # Optional: custom expert prompt override

    # Legacy field (deprecated, use 'agent' instead)
    coding_agent: str = "superqode"


@dataclass
class ModeConfig:
    """Configuration for a team mode (category of roles)."""

    description: str
    enabled: bool = True
    roles: Dict[str, RoleConfig] = field(default_factory=dict)
    # For agent mode: specify which roles to run in deep analysis
    # If empty, uses all enabled agent roles
    deep_analysis_roles: List[str] = field(default_factory=list)
    # For direct modes (no sub-roles)
    coding_agent: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    job_description: Optional[str] = None
    mcp_servers: List[str] = field(default_factory=list)


@dataclass
class TeamConfig:
    """Configuration for the development team."""

    modes: Dict[str, ModeConfig] = field(default_factory=dict)


@dataclass
class MCPServerConfigYAML:
    """MCP server configuration in YAML format."""

    transport: Literal["stdio", "http", "sse"] = "stdio"
    enabled: bool = True
    auto_connect: bool = True
    # Stdio transport
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    # HTTP/SSE transport
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class BYOKConfig:
    """Configuration for BYOK persistent settings."""

    last_provider: str = ""
    last_model: str = ""
    favorites: List[str] = field(default_factory=list)  # "provider/model" format
    history: List[str] = field(default_factory=list)  # Recent connections
    auto_connect: bool = False  # Auto-connect on startup
    show_pricing: bool = True  # Show pricing in model list


@dataclass
class OpenResponsesConfig:
    """Configuration for Open Responses gateway.

    Open Responses provides a unified API for local and custom AI providers
    with support for reasoning/thinking, built-in tools, and streaming.
    """

    # API endpoint
    base_url: str = "http://localhost:11434"
    api_key: Optional[str] = None

    # Reasoning configuration
    reasoning_effort: Literal["low", "medium", "high"] = "medium"

    # Context handling
    truncation: Literal["auto", "disabled"] = "auto"

    # Request settings
    timeout: float = 300.0

    # Built-in tools
    enable_apply_patch: bool = True
    enable_code_interpreter: bool = True
    enable_file_search: bool = False
    enable_web_search: bool = False


@dataclass
class GatewayConfig:
    """Configuration for the LLM gateway (BYOK mode).

    Supports multiple gateway types:
    - litellm: LiteLLM for unified access to 100+ providers (default)
    - openresponses: Open Responses specification for local/custom providers
    """

    type: Literal["litellm", "openresponses"] = "litellm"
    byok: BYOKConfig = field(default_factory=BYOKConfig)
    openresponses: OpenResponsesConfig = field(default_factory=OpenResponsesConfig)


@dataclass
class CostTrackingConfig:
    """Configuration for cost tracking."""

    enabled: bool = True
    show_after_task: bool = True


@dataclass
class ErrorConfig:
    """Configuration for error handling."""

    surface_rate_limits: bool = True
    surface_auth_errors: bool = True


@dataclass
class SuperQodeConfig:
    """Top-level SuperQode configuration."""

    version: str = "1.0"
    team_name: str = "My Development Team"
    description: str = "Multi-agent software development team"

    # Agent runtime backend: "builtin" | "adk" | "openai-agents"
    runtime: Optional[str] = None

    # Gateway and error handling config
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    cost_tracking: CostTrackingConfig = field(default_factory=CostTrackingConfig)
    errors: ErrorConfig = field(default_factory=ErrorConfig)


@dataclass
class Config:
    """Complete SuperQode configuration."""

    superqode: SuperQodeConfig = field(default_factory=SuperQodeConfig)
    default: Optional[RoleConfig] = None
    team: TeamConfig = field(default_factory=TeamConfig)
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    agents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    code_agents: List[str] = field(default_factory=list)
    custom_models: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    model_aliases: Dict[str, str] = field(default_factory=dict)
    mcp_servers: Dict[str, MCPServerConfigYAML] = field(default_factory=dict)
    workflows: Dict[str, Any] = field(default_factory=dict)  # Workflow definitions
    legacy: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedRole:
    """A resolved role with all configuration details."""

    mode: str
    role: Optional[str]
    description: str
    coding_agent: str
    agent_type: Literal["acp", "superqode", "byok"]
    provider: Optional[str] = None
    model: Optional[str] = None
    job_description: str = ""
    enabled: bool = True
    mcp_servers: List[str] = field(default_factory=list)
    handoff: Optional[HandoffConfig] = None
    cross_validation: Optional[CrossValidationConfig] = None

    # New: Execution mode info
    execution_mode: Literal["byok", "acp"] = "byok"
    agent_id: Optional[str] = None  # For ACP mode
    agent_config: Optional[AgentConfigBlock] = None  # For ACP mode

    # Expert prompt configuration
    expert_prompt_enabled: bool = False  # Default: OSS disables expert prompts
    expert_prompt: Optional[str] = None  # Optional: custom expert prompt override


@dataclass
class ResolvedMode:
    """A resolved mode with all its roles."""

    name: str
    description: str
    enabled: bool = True
    roles: Dict[str, ResolvedRole] = field(default_factory=dict)
    # For direct modes
    direct_role: Optional[ResolvedRole] = None
