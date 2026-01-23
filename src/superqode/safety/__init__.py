"""
Safety warning system for SuperQode.

Provides warnings about destructive QE actions, token consumption,
and sandbox environment recommendations.
"""

from .warnings import (
    SafetyWarning,
    WarningType,
    WarningSeverity,
    get_safety_warnings,
    get_production_warnings,
    show_safety_warnings,
    get_warning_acknowledgment,
    should_skip_warnings,
    mark_warnings_acknowledged,
)

from .sandbox import (
    SandboxDetector,
    SandboxStatus,
    detect_sandbox_environment,
    get_sandbox_recommendations,
)

__all__ = [
    # Warning system
    "SafetyWarning",
    "WarningType",
    "WarningSeverity",
    "show_safety_warnings",
    "get_warning_acknowledgment",
    "should_skip_warnings",
    "mark_warnings_acknowledged",
    # Sandbox detection
    "SandboxDetector",
    "SandboxStatus",
    "detect_sandbox_environment",
    "get_sandbox_recommendations",
]
