"""
Base classes for test framework support.

Provides abstract interfaces for:
- Test discovery
- Test execution
- Result parsing
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio


class TestStatus(str, Enum):
    """Status of a test execution."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    PENDING = "pending"


@dataclass
class FrameworkConfig:
    """Configuration for a test framework."""

    project_root: Path = field(default_factory=Path.cwd)
    test_pattern: str = "**/test_*.py"
    timeout_seconds: int = 300
    parallel: bool = True
    workers: int = 4
    verbose: bool = False
    coverage: bool = False
    fail_fast: bool = False
    retry_count: int = 0
    env: Dict[str, str] = field(default_factory=dict)
    extra_args: List[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Result of a single test execution."""

    name: str
    status: TestStatus
    duration_ms: float
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestSuite:
    """A collection of tests."""

    name: str
    file_path: str
    tests: List[str] = field(default_factory=list)
    setup_file: Optional[str] = None
    teardown_file: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Result of executing tests."""

    framework: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    test_results: List[TestResult] = field(default_factory=list)
    coverage_percentage: Optional[float] = None
    output: str = ""
    error_output: str = ""

    @property
    def success(self) -> bool:
        """Did all tests pass?"""
        return self.failed == 0 and self.errors == 0

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate."""
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "framework": self.framework,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "success": self.success,
            "pass_rate": self.pass_rate,
            "coverage": self.coverage_percentage,
        }


class TestFramework(ABC):
    """
    Abstract base class for test frameworks.

    Implement this class to add support for a new test framework.
    """

    # Framework metadata - override in subclasses
    NAME = "base"
    DISPLAY_NAME = "Base Framework"
    LANGUAGE = "unknown"
    FILE_PATTERNS = ["**/test_*.py"]

    def __init__(self, config: Optional[FrameworkConfig] = None):
        """Initialize the framework."""
        self.config = config or FrameworkConfig()

    @abstractmethod
    async def discover(self) -> List[TestSuite]:
        """
        Discover tests in the project.

        Returns:
            List of TestSuite objects found
        """
        pass

    @abstractmethod
    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """
        Execute tests.

        Args:
            tests: Specific tests to run (None = all)
            **kwargs: Framework-specific options

        Returns:
            ExecutionResult with all test results
        """
        pass

    @abstractmethod
    def parse_results(self, output: str) -> List[TestResult]:
        """
        Parse test output into structured results.

        Args:
            output: Raw output from test runner

        Returns:
            List of TestResult objects
        """
        pass

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """
        Get the command to run tests.

        Args:
            tests: Specific tests to run

        Returns:
            Command as list of strings
        """
        raise NotImplementedError

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """
        Detect if this framework is used in the project.

        Args:
            project_root: Root directory of the project

        Returns:
            True if framework is detected
        """
        return False

    async def run_command(
        self, command: List[str], timeout: Optional[int] = None
    ) -> tuple[int, str, str]:
        """
        Run a shell command.

        Args:
            command: Command to run
            timeout: Timeout in seconds

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        timeout = timeout or self.config.timeout_seconds

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.config.project_root),
            env={**dict(__import__("os").environ), **self.config.env},
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return (
                process.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            process.kill()
            return (-1, "", f"Command timed out after {timeout}s")
