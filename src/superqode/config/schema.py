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

    # Expert prompt configuration (for QE roles)
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
    # For QE mode: specify which roles to run in deep analysis
    # If empty, uses all enabled QE roles
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
class OutputConfig:
    """Configuration for QE output."""

    directory: str = ".superqode"
    reports_format: Literal["markdown", "html", "json"] = "markdown"
    keep_history: bool = True


@dataclass
class QEModeConfig:
    """Configuration for a QE execution mode."""

    timeout: int = 60  # Timeout in seconds
    depth: Literal["shallow", "full"] = "shallow"
    generate_tests: bool = False
    destructive: bool = False  # Can run stress/load tests


@dataclass
class ExecutionRoleConfig:
    """Configuration for execution roles (smoke/sanity/regression).

    These are hard-constraint runners - they execute existing tests only.
    No discovery, no inference, no generation.
    """

    test_pattern: str = "**/test_*.py"
    fail_fast: bool = False
    allow_generation: bool = False  # Always False for execution roles
    detect_flakes: bool = False


@dataclass
class TestGenerationConfig:
    """Configuration for test generation."""

    output_dir: str = ".superqode/qe-artifacts/generated-tests"
    frameworks: Dict[str, str] = field(
        default_factory=lambda: {
            "python": "pytest",
            "javascript": "jest",
            "go": "go test",
        }
    )
    coverage_target: int = 80


@dataclass
class HarnessToolConfig:
    """Configuration for a harness validation tool."""

    name: str = ""
    enabled: bool = True
    args: List[str] = field(default_factory=list)
    timeout_seconds: int = 10


@dataclass
class HarnessLanguageConfig:
    """Configuration for a language's harness validators."""

    enabled: bool = True
    tools: List[str] = field(default_factory=list)
    extensions: List[str] = field(default_factory=list)


@dataclass
class HarnessConfig:
    """Configuration for patch harness validation."""

    enabled: bool = True
    timeout_seconds: int = 30
    fail_on_error: bool = False

    # Structural validators (JSON, YAML, TOML)
    structural_formats: List[str] = field(default_factory=lambda: ["json", "yaml", "toml"])

    # Language validators
    python_tools: List[str] = field(default_factory=lambda: ["ruff", "mypy"])
    javascript_tools: List[str] = field(default_factory=lambda: ["eslint"])
    typescript_tools: List[str] = field(default_factory=lambda: ["tsc", "eslint"])
    go_tools: List[str] = field(default_factory=lambda: ["go vet", "golangci-lint"])
    rust_tools: List[str] = field(default_factory=lambda: ["cargo check"])
    shell_tools: List[str] = field(default_factory=lambda: ["shellcheck"])


@dataclass
class GuidanceModeConfig:
    """Configuration for QE guidance mode."""

    timeout_seconds: int = 60
    verification_first: bool = True
    fail_fast: bool = False
    exploration_allowed: bool = False
    destructive_testing: bool = False
    focus_areas: List[str] = field(default_factory=list)
    forbidden_actions: List[str] = field(default_factory=list)


@dataclass
class GuidanceConfig:
    """Configuration for QE guidance prompts."""

    enabled: bool = True
    require_proof: bool = True  # Must verify before claiming success

    # Mode-specific settings
    quick_scan: GuidanceModeConfig = field(
        default_factory=lambda: GuidanceModeConfig(
            timeout_seconds=60,
            verification_first=True,
            fail_fast=True,
            focus_areas=["Run smoke tests", "Validate critical paths"],
        )
    )

    deep_qe: GuidanceModeConfig = field(
        default_factory=lambda: GuidanceModeConfig(
            timeout_seconds=1800,
            verification_first=True,
            exploration_allowed=True,
            destructive_testing=True,
            focus_areas=["Comprehensive coverage", "Edge cases", "Security", "Performance"],
        )
    )

    # Anti-patterns to detect
    anti_patterns: List[str] = field(
        default_factory=lambda: [
            "skip_verification",
            "unconditional_success",
            "weaken_tests",
        ]
    )


@dataclass
class NoiseConfig:
    """Configuration for noise filtering in QE findings."""

    min_confidence: float = 0.7  # Filter findings below this threshold
    deduplicate: bool = True  # Remove similar findings
    min_severity: Literal["low", "medium", "high", "critical"] = "low"
    suppress_known_risks: bool = False  # Suppress acknowledged risks
    max_per_file: int = 10  # Max findings per file
    max_total: int = 100  # Max total findings


@dataclass
class SuggestionConfig:
    """Configuration for the allow_suggestions workflow.

    When enabled, SuperQode will:
    1. Detect bugs during QE analysis
    2. Fix bugs in an isolated workspace (Add-on)
    3. Verify fixes by running tests
    4. Prove improvement with before/after metrics
    5. Report outcomes with evidence
    6. Add findings to QIR with fix verification
    7. REVERT all changes (original code restored)
    8. Preserve patches for user to accept/reject
    """

    enabled: bool = False  # OFF by default - never modify without consent
    verify_fixes: bool = True  # Run tests to verify suggested fixes
    require_proof: bool = True  # Require before/after metrics
    auto_generate_tests: bool = False  # Generate regression tests for fixes
    max_fix_attempts: int = 3  # Max attempts to fix an issue
    revert_on_failure: bool = True  # Revert if fix verification fails


@dataclass
class QEConfig:
    """QE-specific configuration."""

    # Output settings
    output: OutputConfig = field(default_factory=OutputConfig)

    # Suggestion workflow (allow_suggestions mode)
    # When enabled, agents can demonstrate fixes in an isolated workspace, then revert
    allow_suggestions: bool = False  # CRITICAL: OFF by default
    suggestions: SuggestionConfig = field(default_factory=SuggestionConfig)

    # Noise filtering
    noise: NoiseConfig = field(default_factory=NoiseConfig)

    # Execution modes
    modes: Dict[str, QEModeConfig] = field(
        default_factory=lambda: {
            "quick_scan": QEModeConfig(
                timeout=60, depth="shallow", generate_tests=False, destructive=False
            ),
            "deep_qe": QEModeConfig(
                timeout=1800, depth="full", generate_tests=True, destructive=True
            ),
        }
    )

    # Execution roles (hard constraints)
    execution_roles: Dict[str, ExecutionRoleConfig] = field(
        default_factory=lambda: {
            "smoke": ExecutionRoleConfig(test_pattern="**/test_smoke*.py", fail_fast=True),
            "sanity": ExecutionRoleConfig(test_pattern="**/test_sanity*.py", fail_fast=False),
            "regression": ExecutionRoleConfig(test_pattern="**/test_*.py", detect_flakes=True),
        }
    )

    # Test generation settings
    test_generation: TestGenerationConfig = field(default_factory=TestGenerationConfig)

    # Patch Harness - validates patches before including in QIR
    harness: HarnessConfig = field(default_factory=HarnessConfig)

    # QE Guidance - system prompts for time-constrained QE
    guidance: GuidanceConfig = field(default_factory=GuidanceConfig)

    # SuperOpt optimization hook (command-based)
    optimize: "OptimizeConfig" = field(default_factory=lambda: OptimizeConfig())


@dataclass
class OptimizeConfig:
    """Configuration for SuperOpt command-based optimization."""

    enabled: bool = False
    command: str = ""
    timeout_seconds: int = 300


@dataclass
class SuperQodeConfig:
    """Top-level SuperQode configuration."""

    version: str = "1.0"
    team_name: str = "My Development Team"
    description: str = "Multi-agent software development team"

    # Gateway and error handling config
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    cost_tracking: CostTrackingConfig = field(default_factory=CostTrackingConfig)
    errors: ErrorConfig = field(default_factory=ErrorConfig)

    # QE-specific configuration
    qe: QEConfig = field(default_factory=QEConfig)


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
