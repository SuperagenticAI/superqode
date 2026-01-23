"""
Execution module - Hard-constrained test execution roles.

These are "dumb runners" that execute existing tests without
discovery, inference, or generation.

Roles:
- Smoke Tester: Runs smoke tests, fail-fast, no discovery
- Sanity Tester: Runs sanity tests, verifies recent changes
- Regression Tester: Runs full regression suite, detects flakes
"""

from .runner import (
    TestRunner,
    SmokeRunner,
    SanityRunner,
    RegressionRunner,
    TestResult,
    TestSuiteResult,
)
from .linter import LinterRunner, LinterRunResult
from .modes import ExecutionMode, QuickScanConfig, DeepQEConfig

__all__ = [
    "TestRunner",
    "SmokeRunner",
    "SanityRunner",
    "RegressionRunner",
    "TestResult",
    "TestSuiteResult",
    "LinterRunner",
    "LinterRunResult",
    "ExecutionMode",
    "QuickScanConfig",
    "DeepQEConfig",
]
