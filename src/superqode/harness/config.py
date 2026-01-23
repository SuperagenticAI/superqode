"""
Harness Configuration - YAML-driven validation settings.

All configuration comes from superqode.yaml, no external files.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ValidationCategory(Enum):
    """Category of validation."""

    STRUCTURAL = "structural"  # JSON, YAML, TOML parsing
    FUNCTIONAL = "functional"  # Type checking, linting
    STYLISTIC = "stylistic"  # Formatting, style rules


@dataclass
class ToolConfig:
    """Configuration for a validation tool."""

    name: str
    enabled: bool = True
    args: List[str] = field(default_factory=list)
    timeout_seconds: int = 10
    category: ValidationCategory = ValidationCategory.FUNCTIONAL


@dataclass
class LanguageValidatorConfig:
    """Configuration for a language's validators."""

    enabled: bool = True
    tools: List[ToolConfig] = field(default_factory=list)
    extensions: List[str] = field(default_factory=list)


@dataclass
class StructuralValidatorConfig:
    """Configuration for structural validators."""

    enabled: bool = True
    formats: List[str] = field(default_factory=lambda: ["json", "yaml", "toml"])


@dataclass
class CustomHarnessStep:
    """Custom harness step defined by user command."""

    name: str
    command: str
    enabled: bool = True
    timeout_seconds: int = 300


@dataclass
class HarnessConfig:
    """
    Complete harness configuration from superqode.yaml.

    Supports:
    - Structural validators (JSON, YAML, TOML)
    - Language-specific validators (Python, JS, Go, etc.)
    - Custom tool configurations
    - Timeout and retry settings
    """

    enabled: bool = True
    timeout_seconds: int = 30
    fail_on_error: bool = False  # Should harness failures block QE?

    # Structural validators
    structural: StructuralValidatorConfig = field(default_factory=StructuralValidatorConfig)

    # Language validators
    python: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".py", ".pyi"],
            tools=[
                ToolConfig(name="ruff", args=["check", "--quiet"]),
                ToolConfig(name="mypy", args=["--no-error-summary"], timeout_seconds=20),
            ],
        )
    )

    javascript: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".js", ".jsx", ".mjs", ".cjs"],
            tools=[
                ToolConfig(name="eslint", args=["--max-warnings", "0"]),
            ],
        )
    )

    typescript: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".ts", ".tsx"],
            tools=[
                ToolConfig(name="tsc", args=["--noEmit"], timeout_seconds=30),
                ToolConfig(name="eslint", args=["--max-warnings", "0"]),
            ],
        )
    )

    go: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".go"],
            tools=[
                ToolConfig(name="go", args=["vet"]),
                ToolConfig(name="golangci-lint", args=["run"], timeout_seconds=20),
            ],
        )
    )

    rust: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".rs"],
            tools=[
                ToolConfig(name="cargo", args=["check", "--quiet"], timeout_seconds=30),
            ],
        )
    )

    shell: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".sh", ".bash"],
            tools=[
                ToolConfig(name="shellcheck", args=["-f", "gcc"]),
            ],
        )
    )

    yaml_lint: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".yml", ".yaml"],
            tools=[
                ToolConfig(
                    name="yamllint", args=["-f", "parsable"], category=ValidationCategory.STYLISTIC
                ),
            ],
        )
    )

    markdown: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[".md"],
            tools=[
                ToolConfig(name="markdownlint", args=[], category=ValidationCategory.STYLISTIC),
            ],
        )
    )

    dockerfile: LanguageValidatorConfig = field(
        default_factory=lambda: LanguageValidatorConfig(
            enabled=True,
            extensions=[],  # Matched by filename
            tools=[
                ToolConfig(name="hadolint", args=[]),
            ],
        )
    )

    # Custom command-based steps (BYOH)
    custom_steps: List[CustomHarnessStep] = field(default_factory=list)

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "HarnessConfig":
        """Create HarnessConfig from YAML dict (superqode.qe.harness section)."""
        if not data:
            return cls()

        config = cls(
            enabled=data.get("enabled", True),
            timeout_seconds=data.get("timeout_seconds", 30),
            fail_on_error=data.get("fail_on_error", False),
        )

        # Parse structural config
        if "structural" in data:
            config.structural = StructuralValidatorConfig(
                enabled=data["structural"].get("enabled", True),
                formats=data["structural"].get("formats", ["json", "yaml", "toml"]),
            )

        # Parse language configs
        for lang in [
            "python",
            "javascript",
            "typescript",
            "go",
            "rust",
            "shell",
            "yaml_lint",
            "markdown",
            "dockerfile",
        ]:
            yaml_key = lang.replace("_", "-")
            if yaml_key in data or lang in data:
                lang_data = data.get(yaml_key) or data.get(lang, {})
                lang_config = getattr(config, lang)

                if isinstance(lang_data, dict):
                    lang_config.enabled = lang_data.get("enabled", True)

                    if "extensions" in lang_data:
                        lang_config.extensions = lang_data["extensions"]

                    if "tools" in lang_data:
                        lang_config.tools = []
                        for tool_data in lang_data["tools"]:
                            if isinstance(tool_data, str):
                                # Simple string: just tool name
                                lang_config.tools.append(ToolConfig(name=tool_data))
                            elif isinstance(tool_data, dict):
                                lang_config.tools.append(
                                    ToolConfig(
                                        name=tool_data.get("name", tool_data.get("tool", "")),
                                        enabled=tool_data.get("enabled", True),
                                        args=tool_data.get("args", []),
                                        timeout_seconds=tool_data.get("timeout", 10),
                                    )
                                )

        # Parse custom steps
        custom_steps_data = data.get("custom_steps") or data.get("custom-steps") or []
        for step_data in custom_steps_data:
            if isinstance(step_data, str):
                config.custom_steps.append(
                    CustomHarnessStep(
                        name=step_data,
                        command=step_data,
                    )
                )
            elif isinstance(step_data, dict):
                config.custom_steps.append(
                    CustomHarnessStep(
                        name=step_data.get("name", step_data.get("command", "custom-step")),
                        command=step_data.get("command", ""),
                        enabled=step_data.get("enabled", True),
                        timeout_seconds=step_data.get("timeout", 300),
                    )
                )

        return config

    def get_validators_for_file(self, file_path: Path) -> List["LanguageValidatorConfig"]:
        """Get all applicable validators for a file."""
        validators = []
        ext = file_path.suffix.lower()
        filename = file_path.name.lower()

        # Check each language
        for lang in [
            "python",
            "javascript",
            "typescript",
            "go",
            "rust",
            "shell",
            "yaml_lint",
            "markdown",
            "dockerfile",
        ]:
            lang_config = getattr(self, lang)
            if not lang_config.enabled:
                continue

            # Check extension match
            if ext in lang_config.extensions:
                validators.append(lang_config)

            # Special case: Dockerfile
            if lang == "dockerfile" and (
                filename == "dockerfile" or filename.startswith("dockerfile.")
            ):
                validators.append(lang_config)

        return validators


def load_harness_config(project_root: Path) -> HarnessConfig:
    """
    Load harness configuration from superqode.yaml.

    Looks for: superqode.qe.harness section
    """
    import yaml

    yaml_path = project_root / "superqode.yaml"
    if not yaml_path.exists():
        logger.debug("No superqode.yaml found, using default harness config")
        return HarnessConfig()

    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        # Navigate to superqode.qe.harness
        harness_data = data.get("superqode", {}).get("qe", {}).get("harness", {})

        return HarnessConfig.from_yaml_dict(harness_data)

    except Exception as e:
        logger.warning(f"Failed to load harness config: {e}")
        return HarnessConfig()
