"""
SuperQode Core Module - Unified types and interfaces.

This module provides a single import point for core SuperQode types:
- Configuration types (RoleConfig, TeamConfig, etc.)
- Execution modes (BYOK, ACP, Quick Scan, Deep QE)
- Role definitions (dev, qe, devops categories)

Usage:
    from superqode.core import (
        ExecutionMode,
        QEMode,
        RoleConfig,
        TeamConfig,
    )
"""

# Execution modes
from ..execution.modes import (
    ExecutionMode,
    QEMode,
    GatewayType,
    BYOKConfig,
    ACPConfig,
    ExecutionConfig,
    QuickScanConfig,
    DeepQEConfig,
    get_qe_mode_config,
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
    OutputConfig,
    QEModeConfig,
)

# Configuration loader
from ..config.loader import (
    load_config,
    SuperQodeConfig,
)

# Unified roles
from .roles import (
    Role,
    RoleCategory,
    QERoleType,
    get_default_roles,
    get_role,
    list_all_roles,
    list_roles_by_category,
    list_qe_execution_roles,
    list_qe_detection_roles,
    DEFAULT_DEV_ROLES,
    DEFAULT_QE_ROLES,
    DEFAULT_DEVOPS_ROLES,
)

__all__ = [
    # Execution modes
    "ExecutionMode",
    "QEMode",
    "GatewayType",
    "BYOKConfig",
    "ACPConfig",
    "ExecutionConfig",
    "QuickScanConfig",
    "DeepQEConfig",
    "get_qe_mode_config",
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
    "OutputConfig",
    "QEModeConfig",
    # Configuration loader
    "load_config",
    "SuperQodeConfig",
    # Unified roles
    "Role",
    "RoleCategory",
    "QERoleType",
    "get_default_roles",
    "get_role",
    "list_all_roles",
    "list_roles_by_category",
    "list_qe_execution_roles",
    "list_qe_detection_roles",
    "DEFAULT_DEV_ROLES",
    "DEFAULT_QE_ROLES",
    "DEFAULT_DEVOPS_ROLES",
]
