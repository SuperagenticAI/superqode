"""SuperQode configuration system."""

from .loader import (
    load_config,
    save_config,
    create_default_config,
    find_config_file,
    ConfigError,
    load_enabled_modes,
    resolve_role,
    resolve_model_spec,
)
from .schema import (
    Config,
    SuperQodeConfig,
    TeamConfig,
    ModeConfig,
    RoleConfig,
    ProviderConfig,
    ResolvedRole,
    ResolvedMode,
    AgentConfigBlock,
    GatewayConfig,
    CostTrackingConfig,
    ErrorConfig,
)

__all__ = [
    # Loader functions
    "load_config",
    "save_config",
    "create_default_config",
    "find_config_file",
    "load_enabled_modes",
    "resolve_role",
    "resolve_model_spec",
    "ConfigError",
    # Schema classes
    "Config",
    "SuperQodeConfig",
    "TeamConfig",
    "ModeConfig",
    "RoleConfig",
    "ProviderConfig",
    "ResolvedRole",
    "ResolvedMode",
    "AgentConfigBlock",
    "GatewayConfig",
    "CostTrackingConfig",
    "ErrorConfig",
]
