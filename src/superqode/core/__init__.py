"""
SuperQode Core Module - Unified types and interfaces.

This module provides a single import point for core SuperQode types:
- Configuration types (RoleConfig, TeamConfig, etc.)
- Execution modes (BYOK, ACP)

Usage:
    from superqode.core import (
        ExecutionMode,
        RoleConfig,
        TeamConfig,
    )
"""

# Execution modes
from ..execution.modes import (
    ExecutionMode,
    GatewayType,
    BYOKConfig,
    ACPConfig,
    ExecutionConfig,
)

# Configuration schema
from ..config.schema import (
    ProviderConfig,
    HandoffConfig,
    CrossValidationConfig,
    AgentConfigBlock,
    RoleConfig,
    ModeConfig,
    TeamConfig,
    MCPServerConfigYAML,
    GatewayConfig,
    CostTrackingConfig,
    ErrorConfig,
)

# Configuration loader
from ..config.loader import (
    load_config,
    SuperQodeConfig,
)

__all__ = [
    # Execution modes
    "ExecutionMode",
    "GatewayType",
    "BYOKConfig",
    "ACPConfig",
    "ExecutionConfig",
    # Configuration schema
    "ProviderConfig",
    "HandoffConfig",
    "CrossValidationConfig",
    "AgentConfigBlock",
    "RoleConfig",
    "ModeConfig",
    "TeamConfig",
    "MCPServerConfigYAML",
    "GatewayConfig",
    "CostTrackingConfig",
    "ErrorConfig",
    # Configuration loader
    "load_config",
    "SuperQodeConfig",
]
