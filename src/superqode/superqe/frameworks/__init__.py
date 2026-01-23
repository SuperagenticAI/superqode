"""
Multi-Framework Test Execution Module.

Supports running tests across multiple frameworks:
- Python: pytest, unittest, nose2
- JavaScript: Jest, Mocha, Vitest, Jasmine, AVA
- E2E: Cypress, Playwright
- Performance: k6, JMeter

Provides unified interface for:
- Test discovery
- Parallel execution (10,000+ concurrent tests)
- Result aggregation
- Framework detection
"""

from .base import (
    TestFramework,
    FrameworkConfig,
    TestResult,
    TestSuite,
    ExecutionResult,
)
from .registry import (
    FrameworkRegistry,
    get_framework,
    detect_framework,
    list_frameworks,
)
from .executor import (
    MultiFrameworkExecutor,
    ExecutorConfig,
    execute_tests,
)

# Framework implementations
from .python import PytestFramework, UnittestFramework
from .javascript import JestFramework, MochaFramework, VitestFramework
from .e2e import CypressFramework, PlaywrightFramework

__all__ = [
    # Base
    "TestFramework",
    "FrameworkConfig",
    "TestResult",
    "TestSuite",
    "ExecutionResult",
    # Registry
    "FrameworkRegistry",
    "get_framework",
    "detect_framework",
    "list_frameworks",
    # Executor
    "MultiFrameworkExecutor",
    "ExecutorConfig",
    "execute_tests",
    # Implementations
    "PytestFramework",
    "UnittestFramework",
    "JestFramework",
    "MochaFramework",
    "VitestFramework",
    "CypressFramework",
    "PlaywrightFramework",
]
