"""
QE Roles - Agentic detection roles for quality engineering.

Implements the PRD role model:

Execution-only roles (deterministic, run existing tests):
- smoke_tester: Fast critical path validation
- sanity_tester: Quick functionality check
- regression_tester: Full test suite execution

Agentic detection roles (AI-powered, discover issues):
- api_tester: API contract and security testing
- unit_tester: Function/class unit testing
- e2e_tester: End-to-end workflow testing
- security_tester: Security vulnerability detection
- performance_tester: Performance bottleneck detection

Heuristic role:
- fullstack: Senior QE/Tech Lead comprehensive review
 - lint_tester: Run linters across the codebase
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import logging
import asyncio

logger = logging.getLogger(__name__)


class RoleType(Enum):
    """Type of QE role."""

    EXECUTION = "execution"  # Run existing tests only
    DETECTION = "detection"  # AI-driven issue detection
    HEURISTIC = "heuristic"  # Senior QE review


@dataclass
class RoleConfig:
    """Configuration for a QE role."""

    name: str
    role_type: RoleType
    description: str

    # Execution role settings
    test_pattern: str = ""
    fail_fast: bool = False
    detect_flakes: bool = False

    # Detection role settings
    focus_areas: List[str] = field(default_factory=list)
    max_findings: int = 50
    min_confidence: float = 0.7

    # Agent settings (for detection roles)
    provider: Optional[str] = None
    model: Optional[str] = None
    timeout_seconds: int = 300

    # System prompt components
    job_description: str = ""
    forbidden_actions: List[str] = field(default_factory=list)


@dataclass
class RoleResult:
    """Result from a QE role execution."""

    role_name: str
    role_type: RoleType
    success: bool

    # Test results (for execution roles)
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0

    # Findings (for detection roles)
    findings: List[Dict[str, Any]] = field(default_factory=list)

    # Artifacts generated
    patches_generated: int = 0
    tests_generated: int = 0

    # Timing
    duration_seconds: float = 0.0

    # Errors
    errors: List[str] = field(default_factory=list)


class QERole(ABC):
    """Base class for QE roles."""

    def __init__(
        self,
        config: RoleConfig,
        project_root: Path,
        allow_suggestions: bool = False,
    ):
        self.config = config
        self.project_root = project_root
        self.allow_suggestions = allow_suggestions

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def role_type(self) -> RoleType:
        return self.config.role_type

    @abstractmethod
    async def run(self) -> RoleResult:
        """Execute the role and return results."""
        pass

    def get_system_prompt(self) -> str:
        """Get the system prompt for this role (detection roles only)."""
        return self.config.job_description


# =============================================================================
# Execution Roles (Deterministic, run existing tests)
# =============================================================================


class SmokeTestRole(QERole):
    """
    Smoke Test Role - Fast critical path validation.

    Runs existing smoke tests to verify critical functionality.
    Fail-fast behavior: stops on first failure.
    """

    async def run(self) -> RoleResult:
        from superqode.execution.runner import SmokeRunner

        runner = SmokeRunner(
            self.project_root,
            test_pattern=self.config.test_pattern or "**/test_smoke*.py",
            timeout_seconds=min(60, self.config.timeout_seconds),
        )

        suite_result = await runner.run()

        return RoleResult(
            role_name=self.name,
            role_type=self.role_type,
            success=suite_result.success,
            tests_run=suite_result.total_tests,
            tests_passed=suite_result.passed,
            tests_failed=suite_result.failed,
            tests_skipped=suite_result.skipped,
            duration_seconds=suite_result.duration_seconds,
            errors=suite_result.errors if hasattr(suite_result, "errors") else [],
        )


class SanityTestRole(QERole):
    """
    Sanity Test Role - Quick functionality verification.

    Runs sanity tests for basic functionality checks.
    """

    async def run(self) -> RoleResult:
        from superqode.execution.runner import SanityRunner

        runner = SanityRunner(
            self.project_root,
            test_pattern=self.config.test_pattern or "**/test_sanity*.py",
            timeout_seconds=min(120, self.config.timeout_seconds),
        )

        suite_result = await runner.run()

        return RoleResult(
            role_name=self.name,
            role_type=self.role_type,
            success=suite_result.success,
            tests_run=suite_result.total_tests,
            tests_passed=suite_result.passed,
            tests_failed=suite_result.failed,
            tests_skipped=suite_result.skipped,
            duration_seconds=suite_result.duration_seconds,
            errors=suite_result.errors if hasattr(suite_result, "errors") else [],
        )


class RegressionTestRole(QERole):
    """
    Regression Test Role - Full test suite execution.

    Runs all tests including flake detection.
    """

    async def run(self) -> RoleResult:
        from superqode.execution.runner import RegressionRunner

        runner = RegressionRunner(
            self.project_root,
            test_pattern=self.config.test_pattern or "**/test_*.py",
            timeout_seconds=self.config.timeout_seconds,
            detect_flakes=self.config.detect_flakes,
        )

        suite_result = await runner.run()

        return RoleResult(
            role_name=self.name,
            role_type=self.role_type,
            success=suite_result.success,
            tests_run=suite_result.total_tests,
            tests_passed=suite_result.passed,
            tests_failed=suite_result.failed,
            tests_skipped=suite_result.skipped,
            duration_seconds=suite_result.duration_seconds,
            errors=suite_result.errors if hasattr(suite_result, "errors") else [],
        )


class LintTestRole(QERole):
    """
    Lint Test Role - Run fast linters for detected languages.

    Executes local linters (ruff, eslint/biome, golangci-lint, clippy, etc.)
    and reports findings without failing the QE session.
    """

    async def run(self) -> RoleResult:
        from superqode.execution.linter import LinterRunner

        runner = LinterRunner(self.project_root, timeout_seconds=self.config.timeout_seconds)
        lint_result = await runner.run()

        return RoleResult(
            role_name=self.name,
            role_type=self.role_type,
            success=True,
            findings=lint_result.findings,
            duration_seconds=0.0,
            errors=lint_result.errors,
        )


# =============================================================================
# Detection Roles (AI-powered, discover issues)
# =============================================================================


async def _run_acp_role(
    role: QERole,
    role_name: str,
    allow_suggestions: bool = False,
) -> RoleResult:
    """
    Helper function to run a QE role using ACP agent.

    This is shared by all detection roles to reduce code duplication.

    Args:
        role: The QE role to run
        role_name: Name of the role for prompt selection
        allow_suggestions: If True, ask agent to generate and verify fixes
    """
    from .acp_runner import ACPQERunner, ACPRunnerConfig, get_qe_prompt

    logger.info(f"Running {role_name} role with ACP agent (suggestions={allow_suggestions})")

    # Create ACP runner with suggestion mode settings
    runner_config = ACPRunnerConfig(
        timeout_seconds=role.config.timeout_seconds,
        verbose=False,
        allow_suggestions=allow_suggestions,
    )
    runner = ACPQERunner(role.project_root, runner_config)

    # Get the QE prompt for this role (enhanced if suggestions enabled)
    prompt = get_qe_prompt(role_name, allow_suggestions=allow_suggestions)

    # Run the analysis
    result = await runner.run(prompt, role_name)

    # Check if the runner encountered errors (common in OSS when agents aren't installed)
    if result.errors and any("Failed to start ACP agent" in error for error in result.errors):
        logger.warning(f"ACP agent not available for {role_name}, providing graceful degradation")
        # Create a graceful finding instead of failing
        from .acp_runner import ACPFinding

        graceful_finding = ACPFinding(
            id=f"{role_name}-oss-info",
            severity="info",
            title=f"{role_name.replace('_', ' ').title()} - Agent Not Available",
            description=f"This QE role requires ACP-compatible coding agents (OpenCode, Claude Code, etc.). Install coding agents to enable full analysis capabilities.",
            file_path=None,
            line_number=None,
            evidence="ACP agent connection failed - this is normal in OSS environments without coding agents installed",
            suggested_fix="Install OpenCode (npm i -g opencode-ai) or other ACP-compatible coding agents",
            confidence=0.0,
            category="infrastructure",
        )
        result.findings = [graceful_finding]
        result.errors = []  # Clear the errors since we're handling them gracefully

    # Convert findings to dict format
    findings = []
    for f in result.findings:
        finding_dict = {
            "id": f.id,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "file_path": f.file_path,
            "line_number": f.line_number,
            "evidence": f.evidence,
            "suggested_fix": f.suggested_fix,
            "confidence": f.confidence,
            "category": f.category,
        }

        # Include fix verification data if available
        if f.fix_verification:
            finding_dict["fix_verification"] = {
                "fix_applied": f.fix_verification.fix_applied,
                "tests_passed": f.fix_verification.tests_passed,
                "tests_total": f.fix_verification.tests_total,
                "fix_verified": f.fix_verification.fix_verified,
                "is_improvement": f.fix_verification.is_improvement,
                "outcome": f.fix_verification.outcome,
            }

        findings.append(finding_dict)

    critical_count = len([f for f in findings if f.get("severity") == "critical"])

    return RoleResult(
        role_name=role.name,
        role_type=role.role_type,
        success=result.success and critical_count == 0,
        findings=findings,
        duration_seconds=result.duration_seconds,
        errors=result.errors,
    )


class APITestRole(QERole):
    """
    API Test Role - API contract and security testing.

    Uses ACP agent (OpenCode) to:
    - Discover API endpoints
    - Test API contracts
    - Find security vulnerabilities in APIs
    - Generate API test cases
    """

    DEFAULT_JOB_DESCRIPTION = ""

    async def run(self) -> RoleResult:
        return await _run_acp_role(self, "api_tester", self.allow_suggestions)

    def get_system_prompt(self) -> str:
        return self.config.job_description


class UnitTestRole(QERole):
    """
    Unit Test Role - Function/class unit testing.

    Uses ACP agent (OpenCode) to:
    - Identify functions lacking tests
    - Generate unit tests for uncovered code
    - Find edge cases and error conditions
    """

    DEFAULT_JOB_DESCRIPTION = ""

    async def run(self) -> RoleResult:
        return await _run_acp_role(self, "unit_tester", self.allow_suggestions)

    def get_system_prompt(self) -> str:
        return self.config.job_description


class E2ETestRole(QERole):
    """
    E2E Test Role - End-to-end workflow testing.

    Uses ACP agent (OpenCode) to:
    - Map user workflows
    - Generate E2E test scenarios
    - Test complete user journeys
    - Verify integration points
    """

    DEFAULT_JOB_DESCRIPTION = ""

    async def run(self) -> RoleResult:
        return await _run_acp_role(self, "e2e_tester", self.allow_suggestions)

    def get_system_prompt(self) -> str:
        return self.config.job_description


class SecurityTestRole(QERole):
    """
    Security Test Role - Security vulnerability detection.

    Uses ACP agent (OpenCode) to:
    - Find common vulnerabilities (OWASP Top 10)
    - Analyze authentication/authorization
    - Check for injection vulnerabilities
    - Review secrets/credentials handling
    """

    DEFAULT_JOB_DESCRIPTION = ""

    async def run(self) -> RoleResult:
        return await _run_acp_role(self, "security_tester", self.allow_suggestions)

    def get_system_prompt(self) -> str:
        return self.config.job_description


class PerformanceTestRole(QERole):
    """
    Performance Test Role - Performance bottleneck detection.

    Uses ACP agent (OpenCode) to:
    - Identify performance bottlenecks
    - Find N+1 queries
    - Detect memory leaks
    - Analyze algorithm complexity
    """

    DEFAULT_JOB_DESCRIPTION = ""

    async def run(self) -> RoleResult:
        return await _run_acp_role(self, "performance_tester", self.allow_suggestions)

    def get_system_prompt(self) -> str:
        return self.config.job_description


# =============================================================================
# Heuristic Role (Senior QE Review)
# =============================================================================


class FullstackQERole(QERole):
    """
    Fullstack QE Role - Senior QE/Tech Lead comprehensive review.

    The heuristic role that combines all detection capabilities using ACP:
    - Reviews code like a senior QE engineer
    - Prioritizes findings by business impact
    - Makes judgment calls on edge cases
    - Provides actionable recommendations
    """

    DEFAULT_JOB_DESCRIPTION = ""

    async def run(self) -> RoleResult:
        return await _run_acp_role(self, "fullstack", self.allow_suggestions)

    def get_system_prompt(self) -> str:
        return self.config.job_description


# =============================================================================
# Role Registry and Factory
# =============================================================================

# Registry of all available roles
ROLE_REGISTRY: Dict[str, type] = {
    "smoke_tester": SmokeTestRole,
    "sanity_tester": SanityTestRole,
    "regression_tester": RegressionTestRole,
    "lint_tester": LintTestRole,
    "api_tester": APITestRole,
    "unit_tester": UnitTestRole,
    "e2e_tester": E2ETestRole,
    "security_tester": SecurityTestRole,
    "performance_tester": PerformanceTestRole,
    "fullstack": FullstackQERole,
}


def _load_yaml_data(project_root: Path) -> Dict[str, Any]:
    """Load raw YAML config for the current project."""
    from superqode.config.loader import find_config_file, load_config_from_file

    config_path = find_config_file()
    if config_path is None:
        candidate = project_root / "superqode.yaml"
        if not candidate.exists():
            # Fall back to packaged template
            template_path = Path(__file__).parent.parent / "data" / "superqode-template.yaml"
            if template_path.exists():
                return load_config_from_file(template_path)
            return {}
        config_path = candidate

    return load_config_from_file(config_path)


def _get_qe_role_map(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return QE role definitions from the raw YAML structure."""
    team = data.get("team", {})
    if "modes" in team:
        qe_mode = team.get("modes", {}).get("qe", {})
    else:
        qe_mode = team.get("qe", {})
    roles = qe_mode.get("roles", {})
    return roles if isinstance(roles, dict) else {}


def load_role_config_from_yaml(role_name: str, project_root: Path) -> Optional[Dict[str, Any]]:
    """Load role configuration from superqode.yaml."""
    data = _load_yaml_data(project_root)
    role_data = _get_qe_role_map(data).get(role_name)
    return role_data if isinstance(role_data, dict) else None


def _build_role_config(role_name: str, data: Dict[str, Any]) -> RoleConfig:
    """Build a RoleConfig from YAML data."""
    role_type_raw = data.get("role_type")
    if not role_type_raw:
        raise ValueError(f"Role '{role_name}' missing role_type in superqode.yaml")

    try:
        role_type = RoleType(role_type_raw)
    except ValueError as exc:
        raise ValueError(f"Invalid role_type '{role_type_raw}' for role '{role_name}'") from exc

    return RoleConfig(
        name=role_name,
        role_type=role_type,
        description=data.get("description", ""),
        test_pattern=data.get("test_pattern", ""),
        fail_fast=data.get("fail_fast", False),
        detect_flakes=data.get("detect_flakes", False),
        focus_areas=data.get("focus_areas", []) or [],
        max_findings=int(data.get("max_findings", 50)),
        min_confidence=float(data.get("min_confidence", 0.7)),
        provider=data.get("provider"),
        model=data.get("model"),
        timeout_seconds=int(data.get("timeout_seconds", 300)),
        job_description=data.get("job_description", ""),
        forbidden_actions=data.get("forbidden_actions", []) or [],
    )


def get_role(
    role_name: str,
    project_root: Path,
    allow_suggestions: bool = False,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> QERole:
    """Get a QE role instance from YAML configuration."""
    if role_name not in ROLE_REGISTRY:
        raise ValueError(f"Unknown role: {role_name}. Available: {list(ROLE_REGISTRY.keys())}")

    yaml_config_data = load_role_config_from_yaml(role_name, project_root)
    if not yaml_config_data:
        raise ValueError(
            f"Role '{role_name}' is not configured in superqode.yaml. "
            "Define it under team.qe.roles."
        )

    config = _build_role_config(role_name, yaml_config_data)

    if config_overrides:
        for key, value in config_overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)

    role_class = ROLE_REGISTRY[role_name]
    return role_class(config, project_root, allow_suggestions=allow_suggestions)


def list_roles(project_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """List QE roles configured in superqode.yaml."""
    project_root = project_root or Path.cwd()
    data = _load_yaml_data(project_root)
    roles_data = _get_qe_role_map(data)

    roles = []
    for name, cfg in roles_data.items():
        if not isinstance(cfg, dict):
            continue
        roles.append(
            {
                "name": name,
                "type": cfg.get("role_type", ""),
                "description": cfg.get("description", ""),
                "focus_areas": cfg.get("focus_areas", []),
            }
        )
    return roles
