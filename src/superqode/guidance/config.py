"""
QE Guidance Configuration - YAML-driven settings for time-constrained QE.

All configuration comes from superqode.yaml, aligned with PRD:
> "SuperQode operationalizes SuperQE—where autonomous agents aggressively test software,
>  propose fixes, prove improvements, and report findings with research-grade rigor."
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class GuidanceMode(Enum):
    """QE guidance mode."""

    QUICK_SCAN = "quick_scan"
    DEEP_QE = "deep_qe"


@dataclass
class AntiPatternConfig:
    """Configuration for anti-pattern detection."""

    enabled: bool = True
    patterns: List[str] = field(
        default_factory=lambda: [
            "skip_verification",
            "unconditional_success",
            "broad_exception_swallow",
            "weaken_tests",
            "silent_fallback",
            "guess_expected_output",
        ]
    )


@dataclass
class ModeGuidanceConfig:
    """Configuration for a specific QE mode."""

    timeout_seconds: int = 60
    verification_first: bool = True
    fail_fast: bool = False
    exploration_allowed: bool = False
    destructive_testing: bool = False

    # What the agent should focus on
    focus_areas: List[str] = field(default_factory=list)

    # What the agent should NOT do
    forbidden_actions: List[str] = field(default_factory=list)


@dataclass
class GuidanceConfig:
    """
    Complete QE guidance configuration from superqode.yaml.

    Defines:
    - Mode-specific timeouts and constraints
    - Verification-first workflow requirements
    - Anti-pattern detection rules
    """

    enabled: bool = True

    # Mode-specific configurations
    quick_scan: ModeGuidanceConfig = field(
        default_factory=lambda: ModeGuidanceConfig(
            timeout_seconds=60,
            verification_first=True,
            fail_fast=True,
            exploration_allowed=False,
            destructive_testing=False,
            focus_areas=[
                "Run smoke tests first",
                "Validate critical paths",
                "Check for obvious errors",
                "Verify basic functionality",
            ],
            forbidden_actions=[
                "Long-running performance tests",
                "Extensive code generation",
                "Deep exploration without quick feedback",
            ],
        )
    )

    deep_qe: ModeGuidanceConfig = field(
        default_factory=lambda: ModeGuidanceConfig(
            timeout_seconds=1800,
            verification_first=True,
            fail_fast=False,
            exploration_allowed=True,
            destructive_testing=True,
            focus_areas=[
                "Comprehensive test coverage",
                "Edge case exploration",
                "Security vulnerability scanning",
                "Performance and load testing",
                "Chaos and stress testing",
            ],
            forbidden_actions=[
                "Modifying production code",
                "Committing changes to git",
                "Accessing external networks without approval",
            ],
        )
    )

    # Anti-pattern detection
    anti_patterns: AntiPatternConfig = field(default_factory=AntiPatternConfig)

    # QIR (Quality Investigation Report) settings
    qir_format: str = "markdown"  # "markdown", "json", "both"
    require_proof: bool = True  # Must have verification before success

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "GuidanceConfig":
        """Create GuidanceConfig from YAML dict (superqode.qe.guidance section)."""
        if not data:
            return cls()

        config = cls(
            enabled=data.get("enabled", True),
            qir_format=data.get("qir_format", "markdown"),
            require_proof=data.get("require_proof", True),
        )

        # Parse quick_scan config
        if "quick_scan" in data:
            qs = data["quick_scan"]
            config.quick_scan = ModeGuidanceConfig(
                timeout_seconds=qs.get("timeout_seconds", 60),
                verification_first=qs.get("verification_first", True),
                fail_fast=qs.get("fail_fast", True),
                exploration_allowed=qs.get("exploration_allowed", False),
                destructive_testing=qs.get("destructive_testing", False),
                focus_areas=qs.get("focus_areas", config.quick_scan.focus_areas),
                forbidden_actions=qs.get("forbidden_actions", config.quick_scan.forbidden_actions),
            )

        # Parse deep_qe config
        if "deep_qe" in data:
            dq = data["deep_qe"]
            config.deep_qe = ModeGuidanceConfig(
                timeout_seconds=dq.get("timeout_seconds", 1800),
                verification_first=dq.get("verification_first", True),
                fail_fast=dq.get("fail_fast", False),
                exploration_allowed=dq.get("exploration_allowed", True),
                destructive_testing=dq.get("destructive_testing", True),
                focus_areas=dq.get("focus_areas", config.deep_qe.focus_areas),
                forbidden_actions=dq.get("forbidden_actions", config.deep_qe.forbidden_actions),
            )

        # Parse anti-patterns config
        if "anti_patterns" in data:
            ap = data["anti_patterns"]
            config.anti_patterns = AntiPatternConfig(
                enabled=ap.get("enabled", True),
                patterns=ap.get("patterns", config.anti_patterns.patterns),
            )

        return config

    def get_mode_config(self, mode: GuidanceMode) -> ModeGuidanceConfig:
        """Get configuration for a specific mode."""
        if mode == GuidanceMode.QUICK_SCAN:
            return self.quick_scan
        else:
            return self.deep_qe


def load_guidance_config(project_root: Path) -> GuidanceConfig:
    """
    Load guidance configuration from superqode.yaml.

    Looks for: superqode.qe.guidance section
    """
    import yaml

    yaml_path = project_root / "superqode.yaml"
    if not yaml_path.exists():
        logger.debug("No superqode.yaml found, using default guidance config")
        return GuidanceConfig()

    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        # Navigate to superqode.qe.guidance
        guidance_data = data.get("superqode", {}).get("qe", {}).get("guidance", {})

        return GuidanceConfig.from_yaml_dict(guidance_data)

    except Exception as e:
        logger.warning(f"Failed to load guidance config: {e}")
        return GuidanceConfig()
