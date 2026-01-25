"""Configuration loader for SuperQode."""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml

from .schema import (
    Config,
    SuperQodeConfig,
    TeamConfig,
    ModeConfig,
    RoleConfig,
    ProviderConfig,
    ResolvedMode,
    ResolvedRole,
    MCPServerConfigYAML,
    HandoffConfig,
    CrossValidationConfig,
    AgentConfigBlock,
    GatewayConfig,
    CostTrackingConfig,
    ErrorConfig,
)


class ConfigError(Exception):
    """Configuration loading error."""

    pass


def find_config_file() -> Optional[Path]:
    """Find the superqode.yaml configuration file."""
    # Check current directory first
    config_path = Path.cwd() / "superqode.yaml"
    if config_path.exists():
        return config_path

    # Check user home directory
    home_config = Path.home() / ".superqode.yaml"
    if home_config.exists():
        return home_config

    # Check system config directory
    system_config = Path("/etc/superqode/superqode.yaml")
    if system_config.exists():
        return system_config

    return None


def load_config_from_file(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = find_config_file()

    if config_path is None or not config_path.exists():
        # Return default empty config
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        raise ConfigError(f"Failed to load config from {config_path}: {e}")


def parse_provider_config(data: Dict[str, Any]) -> ProviderConfig:
    """Parse provider configuration."""
    return ProviderConfig(
        api_key_env=data.get("api_key_env", data.get("api_key", "")),
        description=data.get("description", ""),
        base_url=data.get("base_url", data.get("endpoint")),
        recommended_models=data.get("recommended_models", data.get("models", [])),
        custom_models_allowed=data.get("custom_models_allowed", True),
    )


def parse_handoff_config(data: Dict[str, Any]) -> HandoffConfig:
    """Parse handoff configuration."""
    return HandoffConfig(
        to=data.get("to", ""),
        when=data.get("when", "task_complete"),
        include=data.get("include", ["summary", "files_modified"]),
    )


def parse_cross_validation_config(data: Dict[str, Any]) -> CrossValidationConfig:
    """Parse cross-validation configuration."""
    return CrossValidationConfig(
        enabled=data.get("enabled", True),
        exclude_same_model=data.get("exclude_same_model", True),
        exclude_same_provider=data.get("exclude_same_provider", False),
    )


def parse_agent_config_block(data: Dict[str, Any]) -> AgentConfigBlock:
    """Parse agent config block for ACP mode."""
    return AgentConfigBlock(
        provider=data.get("provider"),
        model=data.get("model"),
    )


def parse_role_config(data: Dict[str, Any]) -> RoleConfig:
    """Parse role configuration.

    Supports three execution modes:
    - BYOK (mode="byok"): Direct LLM API calls via gateway
    - ACP (mode="acp"): Full coding agent via Agent Client Protocol
    - LOCAL (mode="local"): Local/self-hosted models (no API keys)
    """
    handoff = None
    if "handoff" in data:
        handoff = parse_handoff_config(data["handoff"])

    cross_validation = None
    if "cross_validation" in data:
        cross_validation = parse_cross_validation_config(data["cross_validation"])

    # Parse agent_config if present
    agent_config = None
    if "agent_config" in data:
        agent_config = parse_agent_config_block(data["agent_config"])

    # Determine execution mode
    # Explicit mode takes precedence
    mode = data.get("mode", "").lower()

    # If no explicit mode, infer from config
    if not mode:
        # New explicit 'agent' field = ACP
        if data.get("agent"):
            mode = "acp"
        # Legacy: coding_agent that's a known ACP agent = ACP
        elif data.get("coding_agent") and data.get("coding_agent") not in ("superqode", "byok"):
            # If coding_agent is set to something like "opencode", "claude-code", etc.
            # This is the OLD way of specifying ACP agents
            mode = "acp"
        # Has provider but no coding_agent = BYOK
        elif data.get("provider") and not data.get("coding_agent"):
            mode = "byok"
        # Default to BYOK only if explicitly superqode
        elif data.get("coding_agent") == "superqode":
            mode = "byok"
        else:
            # Default: if coding_agent is set to an agent name, it's ACP
            mode = "acp" if data.get("coding_agent") else "byok"

    # Parse expert prompt configuration
    expert_prompt_enabled = data.get("expert_prompt_enabled", False)  # Default: OSS off
    expert_prompt = data.get("expert_prompt", None)  # Optional override

    # Validate mode - accept "local" as well
    valid_mode = mode if mode in ("byok", "acp", "local") else "byok"

    # If mode is "local", validate provider is local
    if valid_mode == "local":
        from ..providers.registry import PROVIDERS, ProviderCategory

        provider_id = data.get("provider")
        if provider_id:
            provider_def = PROVIDERS.get(provider_id)
            if provider_def and provider_def.category != ProviderCategory.LOCAL:
                # Provider is not local, fall back to byok
                valid_mode = "byok"

    return RoleConfig(
        description=data.get("description", ""),
        mode=valid_mode,
        # BYOK/LOCAL mode settings
        provider=data.get("provider"),
        model=data.get("model"),
        # ACP mode settings
        agent=data.get("agent"),
        agent_config=agent_config,
        # Common settings
        job_description=data.get("job_description", data.get("persona", "")),
        enabled=data.get("enabled", True),
        mcp_servers=data.get("mcp_servers", data.get("mcp", [])),
        handoff=handoff,
        cross_validation=cross_validation,
        # Expert prompt configuration
        expert_prompt_enabled=expert_prompt_enabled,
        expert_prompt=expert_prompt,
        # Legacy field (for backward compatibility) - use 'agent' if 'coding_agent' not set
        coding_agent=data.get("coding_agent") or data.get("agent") or "superqode",
    )


def parse_mode_config(data: Dict[str, Any]) -> ModeConfig:
    """Parse mode configuration."""
    mode = ModeConfig(
        description=data.get("description", ""),
        enabled=data.get("enabled", True),
        mcp_servers=data.get("mcp_servers", []),
    )

    # Handle roles if present
    if "roles" in data:
        for role_name, role_data in data["roles"].items():
            mode.roles[role_name] = parse_role_config(role_data)
    else:
        # Direct mode configuration
        mode.coding_agent = data.get("coding_agent")
        mode.provider = data.get("provider")
        mode.model = data.get("model")
        mode.job_description = data.get("job_description")

    return mode


def parse_mcp_server_config(data: Dict[str, Any]) -> MCPServerConfigYAML:
    """Parse MCP server configuration from YAML."""
    return MCPServerConfigYAML(
        transport=data.get("transport", "stdio"),
        enabled=data.get("enabled", not data.get("disabled", False)),
        auto_connect=data.get("auto_connect", data.get("autoConnect", True)),
        command=data.get("command"),
        args=data.get("args", []),
        env=data.get("env", {}),
        cwd=data.get("cwd"),
        url=data.get("url"),
        headers=data.get("headers", {}),
        timeout=data.get("timeout", 30.0),
    )


def parse_gateway_config(data: Dict[str, Any]) -> GatewayConfig:
    """Parse gateway configuration."""
    return GatewayConfig(
        type=data.get("type", "litellm"),
    )


def parse_cost_tracking_config(data: Dict[str, Any]) -> CostTrackingConfig:
    """Parse cost tracking configuration."""
    return CostTrackingConfig(
        enabled=data.get("enabled", True),
        show_after_task=data.get("show_after_task", True),
    )


def parse_error_config(data: Dict[str, Any]) -> ErrorConfig:
    """Parse error handling configuration."""
    return ErrorConfig(
        surface_rate_limits=data.get("surface_rate_limits", True),
        surface_auth_errors=data.get("surface_auth_errors", True),
    )


def parse_config(data: Dict[str, Any]) -> Config:
    """Parse the complete configuration."""
    config = Config()

    # Parse superqode metadata
    if "superqode" in data:
        sq_data = data["superqode"]
        config.superqode = SuperQodeConfig(
            version=sq_data.get("version", "1.0"),
            team_name=sq_data.get("team_name", sq_data.get("name", "My Development Team")),
            description=sq_data.get("description", "Multi-agent software development team"),
        )

        # Parse gateway config
        if "gateway" in sq_data:
            config.superqode.gateway = parse_gateway_config(sq_data["gateway"])

        # Parse cost tracking config
        if "cost_tracking" in sq_data:
            config.superqode.cost_tracking = parse_cost_tracking_config(sq_data["cost_tracking"])

        # Parse error config
        if "errors" in sq_data:
            config.superqode.errors = parse_error_config(sq_data["errors"])

    # Parse default configuration
    if "default" in data:
        config.default = parse_role_config(data["default"])

    # Parse team configuration
    if "team" in data:
        team_data = data["team"]

        # Handle both flat structure (mode_name: config) and nested structure (modes: {mode_name: config})
        if "modes" in team_data and isinstance(team_data["modes"], dict):
            # Nested structure: team.modes.{mode_name}
            for mode_name, mode_data in team_data["modes"].items():
                config.team.modes[mode_name] = parse_mode_config(mode_data)
        else:
            # Flat structure: team.{mode_name}
            for mode_name, mode_data in team_data.items():
                if mode_name != "modes":  # Skip the nested modes key if it exists
                    config.team.modes[mode_name] = parse_mode_config(mode_data)

    # Parse providers
    if "providers" in data:
        for provider_name, provider_data in data["providers"].items():
            config.providers[provider_name] = parse_provider_config(provider_data)

    # Parse MCP servers
    if "mcp_servers" in data:
        for server_id, server_data in data["mcp_servers"].items():
            config.mcp_servers[server_id] = parse_mcp_server_config(server_data)
    # Also support mcpServers format (for compatibility)
    if "mcpServers" in data:
        for server_id, server_data in data["mcpServers"].items():
            config.mcp_servers[server_id] = parse_mcp_server_config(server_data)

    # Parse other sections
    config.agents = data.get("agents", {})
    config.code_agents = data.get("code_agents", [])
    config.custom_models = data.get("custom_models", {})
    config.model_aliases = data.get("model_aliases", {})
    config.legacy = data.get("legacy", {})

    return config


def resolve_model_spec(model_spec: str, config: Config) -> tuple[str, str]:
    """Resolve a model specification to (provider, model) tuple."""
    # Check aliases first
    if model_spec in config.model_aliases:
        model_spec = config.model_aliases[model_spec]

    # Check custom models
    if model_spec in config.custom_models:
        custom_def = config.custom_models[model_spec]
        return custom_def["provider"], custom_def["model"]

    # Auto-detect provider from model name patterns
    provider_patterns = {
        "claude-": "anthropic",
        "gpt-": "openai",
        "gemini-": "google",
        "glm-": "zhipuai",
        "DeepSeek-": "deepseek",
    }

    for pattern, provider in provider_patterns.items():
        if model_spec.startswith(pattern):
            return provider, model_spec

    # Check for Ollama model patterns (name:tag format)
    if ":" in model_spec and not model_spec.startswith(("http://", "https://")):
        # Common Ollama model patterns
        ollama_indicators = [
            "llama",
            "mistral",
            "codellama",
            "code",
            "qwen",
            "phi",
            "gemma",
            "orca",
            "vicuna",
            "wizard",
            "openchat",
            "zephyr",
            "neural",
            "dolphin",
        ]
        model_base = model_spec.split(":")[0].lower()

        # Check if it matches known Ollama model patterns
        if any(indicator in model_base for indicator in ollama_indicators):
            return "ollama", model_spec

        # If it has the name:tag format and no other provider matches, assume Ollama
        # This covers custom or less common models that follow Ollama naming
        return "ollama", model_spec

    # Default to unknown provider
    return "unknown", model_spec


def resolve_role(
    mode_name: str, role_name: Optional[str], config: Config
) -> Optional[ResolvedRole]:
    """Resolve a mode/role combination to a ResolvedRole."""
    if mode_name not in config.team.modes:
        return None

    mode_config = config.team.modes[mode_name]

    if not mode_config.enabled:
        return None

    if role_name:
        # Hierarchical mode with specific role
        if role_name not in mode_config.roles:
            return None

        role_config = mode_config.roles[role_name]
        if not role_config.enabled:
            return None

        # Resolve provider/model if needed
        provider = role_config.provider
        model = role_config.model

        if role_config.coding_agent == "superqode" and (not provider or not model):
            # Use default if not specified
            if config.default:
                provider = provider or config.default.provider
                model = model or config.default.model

        # Determine agent_type based on execution mode
        execution_mode = role_config.mode
        if execution_mode == "acp":
            agent_type = "acp"
        elif execution_mode == "local":
            # Local mode uses BYOK execution but with local provider identification
            agent_type = "byok"
        elif execution_mode == "byok":
            agent_type = "byok"
        else:
            # Legacy fallback
            agent_type = "acp" if role_config.coding_agent != "superqode" else "superqode"

        # Combine MCP servers from mode and role
        mcp_servers = list(mode_config.mcp_servers) + list(role_config.mcp_servers)

        return ResolvedRole(
            mode=mode_name,
            role=role_name,
            description=role_config.description,
            coding_agent=role_config.coding_agent,
            agent_type=agent_type,
            provider=provider,
            model=model,
            job_description=role_config.job_description,
            enabled=role_config.enabled,
            mcp_servers=mcp_servers,
            # New execution mode fields
            execution_mode=execution_mode if execution_mode in ("byok", "acp", "local") else "byok",
            agent_id=role_config.agent,
            agent_config=role_config.agent_config,
            # Expert prompt configuration
            expert_prompt_enabled=role_config.expert_prompt_enabled,
            expert_prompt=role_config.expert_prompt,
        )
    else:
        # Direct mode
        if not mode_config.coding_agent:
            return None

        provider = mode_config.provider
        model = mode_config.model

        if mode_config.coding_agent == "superqode" and (not provider or not model):
            # Use default if not specified
            if config.default:
                provider = provider or config.default.provider
                model = model or config.default.model

        agent_type = "acp" if mode_config.coding_agent != "superqode" else "superqode"

        return ResolvedRole(
            mode=mode_name,
            role=None,
            description=mode_config.description,
            coding_agent=mode_config.coding_agent,
            agent_type=agent_type,
            provider=provider,
            model=model,
            job_description=mode_config.job_description or "",
            enabled=mode_config.enabled,
            mcp_servers=list(mode_config.mcp_servers),
            # Default to byok for direct modes
            execution_mode="byok",
            # Expert prompts not applicable for direct modes (no role)
            expert_prompt_enabled=False,
            expert_prompt=None,
        )


def load_enabled_modes(config: Optional[Config] = None) -> Dict[str, ResolvedMode]:
    """Load only enabled modes and roles from configuration."""
    if config is None:
        config = load_config()

    enabled_modes = {}

    for mode_name, mode_config in config.team.modes.items():
        if not mode_config.enabled:
            continue

        resolved_mode = ResolvedMode(
            name=mode_name,
            description=mode_config.description,
            enabled=mode_config.enabled,
        )

        if mode_config.roles:
            # Hierarchical mode - load enabled roles
            for role_name, role_config in mode_config.roles.items():
                resolved_role = resolve_role(mode_name, role_name, config)
                if resolved_role:
                    resolved_mode.roles[role_name] = resolved_role
        else:
            # Direct mode
            resolved_role = resolve_role(mode_name, None, config)
            if resolved_role:
                resolved_mode.direct_role = resolved_role

        # Only include modes that have at least one enabled role
        if resolved_mode.roles or resolved_mode.direct_role:
            enabled_modes[mode_name] = resolved_mode

    return enabled_modes


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load and parse the complete SuperQode configuration."""
    try:
        data = load_config_from_file(config_path)
        return parse_config(data)
    except Exception as e:
        raise ConfigError(f"Failed to load configuration: {e}")


def save_config(config: Config, config_path: Optional[Path] = None) -> None:
    """Save configuration to YAML file."""
    if config_path is None:
        config_path = find_config_file() or Path.cwd() / "superqode.yaml"

    # Convert config back to dict for YAML serialization
    config_dict = {
        "superqode": {
            "version": config.superqode.version,
            "team_name": config.superqode.team_name,
            "description": config.superqode.description,
        }
    }

    if config.default:
        config_dict["default"] = {
            "description": config.default.description,
            "coding_agent": config.default.coding_agent,
            "provider": config.default.provider,
            "model": config.default.model,
            "job_description": config.default.job_description,
            "enabled": config.default.enabled,
        }

    if config.team.modes:
        config_dict["team"] = {}
        for mode_name, mode_config in config.team.modes.items():
            mode_dict = {
                "description": mode_config.description,
                "enabled": mode_config.enabled,
            }

            if mode_config.roles:
                mode_dict["roles"] = {}
                for role_name, role_config in mode_config.roles.items():
                    mode_dict["roles"][role_name] = {
                        "description": role_config.description,
                        "mode": role_config.mode,
                        "coding_agent": role_config.coding_agent,
                        "provider": role_config.provider,
                        "model": role_config.model,
                        "job_description": role_config.job_description,
                        "enabled": role_config.enabled,
                    }
            elif mode_config.coding_agent:
                mode_dict["coding_agent"] = mode_config.coding_agent
                mode_dict["provider"] = mode_config.provider
                mode_dict["model"] = mode_config.model
                mode_dict["job_description"] = mode_config.job_description

            config_dict["team"][mode_name] = mode_dict

    if config.providers:
        config_dict["providers"] = {}
        for provider_name, provider_config in config.providers.items():
            config_dict["providers"][provider_name] = {
                "api_key_env": provider_config.api_key_env,
                "description": provider_config.description,
                "base_url": provider_config.base_url,
                "recommended_models": provider_config.recommended_models,
                "custom_models_allowed": provider_config.custom_models_allowed,
            }

    # Add other sections
    if config.agents:
        config_dict["agents"] = config.agents
    if config.code_agents:
        config_dict["code_agents"] = config.code_agents
    if config.custom_models:
        config_dict["custom_models"] = config.custom_models
    if config.model_aliases:
        config_dict["model_aliases"] = config.model_aliases
    if config.legacy:
        config_dict["legacy"] = config.legacy

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_dict, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise ConfigError(f"Failed to save configuration: {e}")


def create_default_config() -> Config:
    """Create a default configuration with simplified ACP-only setup."""
    config = Config()

    # Simplified team configuration - only dev and qe modes
    config.team.modes = {
        "dev": ModeConfig(
            description="Development and coding",
            roles={
                "fullstack": RoleConfig(
                    description="Full-stack development and implementation",
                    coding_agent="claude-code",  # ACP Claude Code agent
                    job_description="""You are a full-stack developer using Claude Code.
Focus on clean, maintainable code across frontend and backend.
Build complete features and hand off to QA for review.""",
                ),
            },
        ),
        "qa": ModeConfig(
            description="Quality assurance and testing",
            roles={
                "api_tester": RoleConfig(
                    description="API testing and validation",
                    coding_agent="gemini-cli",  # ACP Gemini CLI agent
                    job_description="""You are a QA specialist using Gemini CLI.
Focus on testing, validation, and code review.
Critique and improve code quality from development.""",
                ),
            },
        ),
    }

    # Available ACP agents for direct connection (14 Official ACP Agents)
    config.code_agents = [
        "gemini",  # Google's reference ACP implementation
        "claude-code",  # Anthropic's Claude via Zed SDK adapter
        "codex",  # OpenAI's code generation agent
        "junie",  # JetBrains' AI agent for IDE ecosystem
        "goose",  # Square's open-source agent
        "kimi",  # CLI AI agent with ACP support
        "opencode",  # Open-source coding agent
        "stakpak",  # ACP-compatible code assistance
        "vtcode",  # Versatile coding agent
        "auggie",  # Agentic code capabilities
        "code-assistant",  # AI coding assistant in Rust
        "cagent",  # Multi-agent runtime
        "fast-agent",  # Sophisticated agent workflows
        "llmling-agent",  # LLM-powered agent framework
    ]

    # Provider configurations
    config.providers = {
        "anthropic": ProviderConfig(
            api_key_env="ANTHROPIC_API_KEY",
            description="Anthropic Claude models via API",
            recommended_models=["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"],
            custom_models_allowed=True,
        ),
        "openai": ProviderConfig(
            api_key_env="OPENAI_API_KEY",
            description="OpenAI GPT models via API",
            recommended_models=["gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"],
            custom_models_allowed=True,
        ),
        "google": ProviderConfig(
            api_key_env="GOOGLE_API_KEY",
            description="Google Gemini models via Vertex AI",
            recommended_models=["gemini-3-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
            custom_models_allowed=True,
        ),
        "zhipuai": ProviderConfig(
            api_key_env="ZHIPUAI_API_KEY",
            description="ZhipuAI GLM models (智谱AI)",
            recommended_models=["glm-4.7", "glm-4.6", "glm-4.6v", "glm-4.6v-flash"],
            custom_models_allowed=True,
        ),
        "deepseek": ProviderConfig(
            api_key_env="DEEPSEEK_API_KEY",
            description="DeepSeek models",
            recommended_models=["DeepSeek-V3.2-Exp", "DeepSeek-V3.2-Exp-Think"],
            custom_models_allowed=True,
        ),
        "groq": ProviderConfig(
            api_key_env="GROQ_API_KEY",
            description="Groq ultra-fast inference",
            recommended_models=[
                "llama-3.1-70b-versatile",
                "llama-3.1-8b-instant",
                "mixtral-8x7b-32768",
            ],
            custom_models_allowed=True,
        ),
        "ollama": ProviderConfig(
            base_url="http://localhost:11434",
            description="Local Ollama models",
            recommended_models=["llama3.1:70b", "qwen2.5:72b", "codellama:34b", "mistral:7b"],
            custom_models_allowed=True,
        ),
        "openrouter": ProviderConfig(
            api_key_env="OPENROUTER_API_KEY",
            description="OpenRouter - unified API for 100+ models",
            recommended_models=[
                "anthropic/claude-sonnet-4-5",
                "openai/gpt-4o",
                "google/gemini-3-pro-preview",
                "zhipuai/glm-4.7",
            ],
            custom_models_allowed=True,
        ),
    }

    # ACP Agents (14 Official ACP Agents)
    config.agents = {
        "acp": {
            "gemini": {
                "enabled": True,
                "description": "Gemini CLI - Google's reference ACP implementation",
                "install_command": "npm install -g @anthropic-ai/gemini-cli",
                "api_key_env": "GEMINI_API_KEY",
            },
            "claude-code": {
                "enabled": True,
                "description": "Claude Code - Anthropic's Claude via Zed SDK adapter",
                "install_command": "npm install -g @anthropic-ai/claude-code",
                "api_key_env": "ANTHROPIC_API_KEY",
            },
            "codex": {
                "enabled": True,
                "description": "Codex - OpenAI's code generation agent",
                "install_command": "npm install -g @openai/codex",
                "api_key_env": "OPENAI_API_KEY",
            },
            "junie": {
                "enabled": True,
                "description": "JetBrains Junie - AI agent for IDE ecosystem",
                "install_command": "npm install -g @jetbrains/junie",
            },
            "goose": {
                "enabled": True,
                "description": "Goose - Square's open-source agent",
                "install_command": "curl -fsSL https://github.com/block/goose/releases/latest/download/install.sh | bash",
            },
            "kimi": {
                "enabled": True,
                "description": "Kimi CLI - CLI AI agent with ACP support",
                "install_command": "npm install -g @anthropic-ai/kimi-cli",
                "api_key_env": "MOONSHOT_API_KEY",
            },
            "opencode": {
                "enabled": True,
                "description": "OpenCode - Open-source coding agent",
                "install_command": "go install github.com/opencode-ai/opencode@latest",
            },
            "stakpak": {
                "enabled": True,
                "description": "Stakpak - ACP-compatible code assistance",
                "install_command": "npm install -g stakpak",
            },
            "vtcode": {
                "enabled": True,
                "description": "VT Code - Versatile coding agent",
                "install_command": "npm install -g vtcode",
            },
            "auggie": {
                "enabled": True,
                "description": "Augment Code - Agentic code capabilities",
                "install_command": "npm install -g @anthropic-ai/auggie",
                "api_key_env": "AUGMENT_API_KEY",
            },
            "code-assistant": {
                "enabled": True,
                "description": "Code Assistant - AI coding assistant in Rust",
                "install_command": "cargo install code-assistant",
            },
            "cagent": {
                "enabled": True,
                "description": "cagent - Multi-agent runtime orchestration",
                "install_command": "npm install -g cagent",
            },
            "fast-agent": {
                "enabled": True,
                "description": "fast-agent - Sophisticated agent workflows",
                "install_command": "pip install fast-agent",
            },
            "llmling-agent": {
                "enabled": True,
                "description": "LLMling-Agent - LLM-powered agent framework",
                "install_command": "pip install llmling-agent",
            },
        }
    }

    # Model aliases
    config.model_aliases = {
        "latest-sonnet": "claude-sonnet-4-5",
        "latest-gpt": "gpt-4o",
        "latest-gemini": "gemini-3-pro-preview",
        "latest-glm": "glm-4.7",
        "fast": "claude-haiku-4-5",
        "balanced": "claude-sonnet-4-5",
        "powerful": "claude-opus-4-1",
        "thinking": "DeepSeek-V3.2-Exp-Think",
        "vision": "glm-4.6v",
        "coding": "codellama:34b",
    }

    return config
