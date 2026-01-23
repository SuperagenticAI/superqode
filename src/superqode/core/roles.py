"""
Unified Role Definitions for SuperQode.

Provides a single interface for all role types across the platform:
- dev: Development roles (fullstack, frontend, backend, etc.)
- qe: Quality Engineering roles (smoke, regression, security, etc.)
- devops: DevOps roles (deployment, infrastructure, monitoring)

Each role can operate in either BYOK or ACP mode.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Literal, Optional, Any

from ..__init__ import __version__


class RoleCategory(Enum):
    """Role category (top-level grouping)."""

    DEV = "dev"
    QE = "qe"
    DEVOPS = "devops"


class QERoleType(Enum):
    """Type of QE role."""

    EXECUTION = "execution"  # Runs existing tests (smoke, sanity, regression)
    DETECTION = "detection"  # Proactive issue detection (security, api, e2e)


@dataclass
class Role:
    """
    Unified role definition.

    Represents a role in the SuperQode system, whether it's a development,
    QE, or DevOps role. Each role can operate in BYOK or ACP mode.
    """

    category: RoleCategory
    name: str
    description: str
    job_description: str = ""

    # Execution mode
    mode: Literal["byok", "acp"] = "byok"

    # BYOK settings
    provider: Optional[str] = None
    model: Optional[str] = None

    # ACP settings
    agent: Optional[str] = None

    # QE-specific
    qe_type: Optional[QERoleType] = None

    # Common settings
    enabled: bool = True
    mcp_servers: List[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Get display name like 'dev.fullstack'."""
        return f"{self.category.value}.{self.name}"

    @property
    def command(self) -> str:
        """Get TUI command like ':<mode> <role>'."""
        return f":{self.category.value} {self.name}"

    @property
    def is_byok(self) -> bool:
        """Check if role uses BYOK mode."""
        return self.mode == "byok"

    @property
    def is_acp(self) -> bool:
        """Check if role uses ACP mode."""
        return self.mode == "acp"

    @property
    def is_execution_role(self) -> bool:
        """Check if this is an execution QE role."""
        return self.qe_type == QERoleType.EXECUTION

    @property
    def is_detection_role(self) -> bool:
        """Check if this is a detection QE role."""
        return self.qe_type == QERoleType.DETECTION

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "category": self.category.value,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "job_description": self.job_description,
            "mode": self.mode,
            "enabled": self.enabled,
        }

        if self.mode == "byok":
            result["provider"] = self.provider
            result["model"] = self.model
        else:
            result["agent"] = self.agent

        if self.qe_type:
            result["qe_type"] = self.qe_type.value

        if self.mcp_servers:
            result["mcp_servers"] = self.mcp_servers

        return result


# =============================================================================
# Default Role Definitions
# =============================================================================

DEFAULT_DEV_ROLES = {
    "fullstack": Role(
        category=RoleCategory.DEV,
        name="fullstack",
        description="Full-stack development",
        job_description="Implement features, fix bugs, refactor code across the entire stack",
        mode="acp",
        agent="claude-code",
    ),
    "frontend": Role(
        category=RoleCategory.DEV,
        name="frontend",
        description="Frontend/UI specialist",
        job_description="Build and maintain user interfaces, ensure great UX",
        mode="acp",
        agent="claude-code",
    ),
    "backend": Role(
        category=RoleCategory.DEV,
        name="backend",
        description="Backend/API specialist",
        job_description="Design and implement APIs, services, and data layers",
        mode="acp",
        agent="claude-code",
    ),
}

DEFAULT_QE_ROLES = {
    "smoke": Role(
        category=RoleCategory.QE,
        name="smoke",
        description="Fast critical path validation",
        job_description="Run smoke tests to validate critical paths work",
        mode="byok",
        qe_type=QERoleType.EXECUTION,
    ),
    "sanity": Role(
        category=RoleCategory.QE,
        name="sanity",
        description="Core functionality check",
        job_description="Verify core functionality and recent changes",
        mode="byok",
        qe_type=QERoleType.EXECUTION,
    ),
    "regression": Role(
        category=RoleCategory.QE,
        name="regression",
        description="Full test suite execution",
        job_description="Run full regression suite with flake detection",
        mode="byok",
        qe_type=QERoleType.EXECUTION,
    ),
    "security": Role(
        category=RoleCategory.QE,
        name="security",
        description="Security vulnerability scanning",
        job_description="Proactively detect security vulnerabilities and suggest fixes",
        mode="acp",
        agent="claude-code",
        qe_type=QERoleType.DETECTION,
    ),
    "api": Role(
        category=RoleCategory.QE,
        name="api",
        description="API contract and behavior testing",
        job_description="Validate API contracts, test edge cases, check error handling",
        mode="acp",
        agent="claude-code",
        qe_type=QERoleType.DETECTION,
    ),
    "e2e": Role(
        category=RoleCategory.QE,
        name="e2e",
        description="End-to-end workflow validation",
        job_description="Test complete user workflows and integration points",
        mode="acp",
        agent="claude-code",
        qe_type=QERoleType.DETECTION,
    ),
    "performance": Role(
        category=RoleCategory.QE,
        name="performance",
        description="Performance bottleneck detection",
        job_description="Identify performance issues and optimization opportunities",
        mode="acp",
        agent="claude-code",
        qe_type=QERoleType.DETECTION,
    ),
}

DEFAULT_DEVOPS_ROLES = {
    "deployment": Role(
        category=RoleCategory.DEVOPS,
        name="deployment",
        description="Deployment readiness validation",
        job_description="Validate deployment configurations and readiness",
        mode="acp",
        agent="claude-code",
    ),
    "infrastructure": Role(
        category=RoleCategory.DEVOPS,
        name="infrastructure",
        description="Infrastructure and config validation",
        job_description="Review infrastructure code and configurations",
        mode="acp",
        agent="claude-code",
    ),
    "monitoring": Role(
        category=RoleCategory.DEVOPS,
        name="monitoring",
        description="Observability and alerting setup",
        job_description="Set up and validate monitoring, logging, and alerting",
        mode="acp",
        agent="claude-code",
    ),
}


def get_default_roles() -> Dict[str, Dict[str, Role]]:
    """Get all default roles organized by category."""
    return {
        "dev": DEFAULT_DEV_ROLES,
        "qe": DEFAULT_QE_ROLES,
        "devops": DEFAULT_DEVOPS_ROLES,
    }


def get_role(category: str, name: str) -> Optional[Role]:
    """Get a specific role by category and name."""
    defaults = get_default_roles()
    category_roles = defaults.get(category, {})
    return category_roles.get(name)


def list_all_roles() -> List[Role]:
    """List all available roles."""
    roles = []
    for category_roles in get_default_roles().values():
        roles.extend(category_roles.values())
    return roles


def list_roles_by_category(category: str) -> List[Role]:
    """List roles in a specific category."""
    defaults = get_default_roles()
    return list(defaults.get(category, {}).values())


def list_qe_execution_roles() -> List[Role]:
    """List QE roles that run existing tests."""
    return [r for r in DEFAULT_QE_ROLES.values() if r.qe_type == QERoleType.EXECUTION]


def list_qe_detection_roles() -> List[Role]:
    """List QE roles that detect issues proactively."""
    return [r for r in DEFAULT_QE_ROLES.values() if r.qe_type == QERoleType.DETECTION]
