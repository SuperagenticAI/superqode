"""
Safety warning system for SuperQode QE sessions.

Provides prominent warnings about destructive actions, token consumption,
and sandbox environment requirements.
"""

import os
import json
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Confirm, Prompt

_console = Console()


class WarningType(Enum):
    """Types of safety warnings."""

    SANDBOX_ENVIRONMENT = "sandbox"
    DESTRUCTIVE_ACTIONS = "destructive"
    TOKEN_CONSUMPTION = "tokens"
    PRODUCTION_CODE = "production"


class WarningSeverity(Enum):
    """Severity levels for warnings."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class SafetyWarning:
    """A safety warning with content and metadata."""

    type: WarningType
    severity: WarningSeverity
    title: str
    message: str
    recommendations: List[str]
    requires_acknowledgment: bool = True
    skippable_after_first: bool = True


# Predefined safety warnings
SANDBOX_WARNING = SafetyWarning(
    type=WarningType.SANDBOX_ENVIRONMENT,
    severity=WarningSeverity.CRITICAL,
    title="⚠️  Use Sandbox Environment",
    message="QE agents can modify/delete code files and execute shell commands. Use isolated environments, never run on production code.",
    recommendations=[
        "Use git worktrees or Docker containers for isolation",
        "Backup important files first",
    ],
    requires_acknowledgment=True,
    skippable_after_first=True,
)

DESTRUCTIVE_WARNING = SafetyWarning(
    type=WarningType.DESTRUCTIVE_ACTIONS,
    severity=WarningSeverity.WARNING,
    title="⚠️  QE May Break Code",
    message="QE agents intentionally break and test code aggressively. Changes are temporary but can introduce bugs or delete files.",
    recommendations=[
        "Use version control - all changes will be reverted",
        "Monitor system resources during testing",
    ],
    requires_acknowledgment=True,
    skippable_after_first=True,
)

TOKEN_WARNING = SafetyWarning(
    type=WarningType.TOKEN_CONSUMPTION,
    severity=WarningSeverity.INFO,
    title="ℹ️  API Token Usage",
    message="QE sessions consume API tokens. Monitor your usage and set spending limits if needed.",
    recommendations=[
        "Check your API provider dashboard for usage",
        "Set spending limits on your accounts",
    ],
    requires_acknowledgment=False,
    skippable_after_first=True,
)

PRODUCTION_WARNING = SafetyWarning(
    type=WarningType.PRODUCTION_CODE,
    severity=WarningSeverity.CRITICAL,
    title="🚨 Production Code Detected",
    message="Running QE on production code is dangerous. QE agents will break and test code aggressively. Stop and use a sandbox environment.",
    recommendations=[
        "Create a sandbox environment first",
        "Use git worktrees or Docker for isolation",
    ],
    requires_acknowledgment=True,
    skippable_after_first=False,  # Never skip production warnings
)


def get_safety_warnings() -> List[SafetyWarning]:
    """Get the standard set of safety warnings."""
    return [
        SANDBOX_WARNING,
        DESTRUCTIVE_WARNING,
        TOKEN_WARNING,
    ]


def get_production_warnings() -> List[SafetyWarning]:
    """Get warnings for production-like environments."""
    return [
        PRODUCTION_WARNING,
        SANDBOX_WARNING,
        DESTRUCTIVE_WARNING,
        TOKEN_WARNING,
    ]


def show_safety_warnings(
    warnings: List[SafetyWarning], force_display: bool = False, console: Optional[Console] = None
) -> None:
    """Display safety warnings to the user."""
    if console is None:
        console = _console

    for warning in warnings:
        if not force_display and should_skip_warnings(warning):
            continue

        # Create warning panel
        warning_text = Text()
        warning_text.append(f"{warning.title}\n\n", style="bold red")
        warning_text.append(warning.message, style="white")
        warning_text.append("\n\nRecommendations:\n", style="bold yellow")

        for i, rec in enumerate(warning.recommendations, 1):
            warning_text.append(f"{i}. {rec}\n", style="dim cyan")

        # Choose border color based on severity
        border_color = {
            WarningSeverity.INFO: "blue",
            WarningSeverity.WARNING: "yellow",
            WarningSeverity.CRITICAL: "red",
        }[warning.severity]

        panel = Panel(
            warning_text, title=f"⚠️  Safety Warning", border_style=border_color, padding=(1, 2)
        )

        console.print(panel)
        console.print()  # Add spacing


def get_warning_acknowledgment(
    warnings: List[SafetyWarning], console: Optional[Console] = None
) -> bool:
    """Get user acknowledgment for warnings that require it."""
    if console is None:
        console = _console

    requires_ack = [w for w in warnings if w.requires_acknowledgment]

    if not requires_ack:
        return True  # No acknowledgment required

    # Show acknowledgment prompt
    ack_text = Text()
    ack_text.append("The above warnings require your acknowledgment.\n\n", style="yellow")
    ack_text.append("Do you understand these risks and want to continue? ", style="white")
    ack_text.append("(yes/no): ", style="bold cyan")

    console.print(ack_text)

    try:
        response = Prompt.ask("", choices=["yes", "no"], default="no")
        acknowledged = response.lower() == "yes"

        if acknowledged:
            # Mark warnings as acknowledged for future skipping
            for warning in requires_ack:
                if warning.skippable_after_first:
                    mark_warnings_acknowledged(warning)

        return acknowledged

    except KeyboardInterrupt:
        console.print("\nOperation cancelled.", style="yellow")
        return False


def should_skip_warnings(warning: SafetyWarning) -> bool:
    """Check if a warning should be skipped (already acknowledged)."""
    if not warning.skippable_after_first:
        return False  # Never skip critical warnings

    # Check acknowledgment file
    ack_file = _get_acknowledgment_file()
    if not ack_file.exists():
        return False

    try:
        with open(ack_file, "r") as f:
            data = json.load(f)

        acknowledged = data.get("acknowledged_warnings", [])
        return warning.type.value in acknowledged

    except (json.JSONDecodeError, KeyError):
        return False


def mark_warnings_acknowledged(warning: SafetyWarning) -> None:
    """Mark a warning as acknowledged for future skipping."""
    ack_file = _get_acknowledgment_file()
    ack_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data
    data = {}
    if ack_file.exists():
        try:
            with open(ack_file, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            pass

    # Update acknowledged warnings
    if "acknowledged_warnings" not in data:
        data["acknowledged_warnings"] = []

    warning_key = warning.type.value
    if warning_key not in data["acknowledged_warnings"]:
        data["acknowledged_warnings"].append(warning_key)

    # Save updated data
    with open(ack_file, "w") as f:
        json.dump(data, f, indent=2)


def _get_acknowledgment_file() -> Path:
    """Get the path to the warning acknowledgment file."""
    config_dir = Path.home() / ".superqode"
    return config_dir / "safety_acknowledgments.json"


def clear_warning_acknowledgments() -> None:
    """Clear all warning acknowledgments (for testing/debugging)."""
    ack_file = _get_acknowledgment_file()
    if ack_file.exists():
        ack_file.unlink()
