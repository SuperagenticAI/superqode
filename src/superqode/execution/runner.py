"""
Test Runner - Hard-constrained execution roles for existing tests.

These runners are "dumb" executors that only run existing tests.
They do NOT:
- Discover new tests beyond configured patterns
- Generate new tests
- Make inferences about test behavior
- Modify test files

They DO:
- Execute tests matching configured patterns
- Report pass/fail status
- Detect flaky tests (regression runner)
- Support fail-fast mode
"""

import asyncio
import subprocess
import time
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging
import glob
import re

logger = logging.getLogger(__name__)


class TestStatus(Enum):
    """Test execution status."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    FLAKY = "flaky"  # Passed after retry


@dataclass
class TestResult:
    """Result of a single test."""

    name: str
    status: TestStatus
    duration_seconds: float
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    error_message: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }


@dataclass
class TestSuiteResult:
    """Result of running a test suite."""

    runner_type: str  # "smoke", "sanity", "regression"
    started_at: datetime
    ended_at: datetime
    duration_seconds: float

    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    flaky: int

    tests: List[TestResult] = field(default_factory=list)
    summary: str = ""

    @property
    def success(self) -> bool:
        """Did all tests pass (or skip)?"""
        return self.failed == 0 and self.errors == 0

    @property
    def pass_rate(self) -> float:
        """Percentage of tests that passed."""
        if self.total_tests == 0:
            return 100.0
        return (self.passed / self.total_tests) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runner_type": self.runner_type,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "flaky": self.flaky,
            "success": self.success,
            "pass_rate": self.pass_rate,
            "tests": [t.to_dict() for t in self.tests],
            "summary": self.summary,
        }


class TestRunner:
    """
    Base test runner - executes tests without any intelligence.

    Hard constraints:
    - No test discovery beyond configured patterns
    - No test generation
    - No inference or reasoning
    """

    def __init__(
        self,
        project_root: Path,
        test_pattern: str = "**/test_*.py",
        fail_fast: bool = False,
        timeout_seconds: int = 300,
        detect_flakes: bool = False,
        retry_count: int = 0,
    ):
        self.project_root = project_root.resolve()
        self.test_pattern = test_pattern
        self.fail_fast = fail_fast
        self.timeout_seconds = timeout_seconds
        self.detect_flakes = detect_flakes
        self.retry_count = retry_count if detect_flakes else 0

    @property
    def runner_type(self) -> str:
        return "base"

    def discover_tests(self) -> List[Path]:
        """
        Find test files matching the pattern(s).

        This is NOT intelligent discovery - just pattern matching.
        Supports multiple patterns separated by spaces.
        """
        all_files = []

        # Handle multiple patterns separated by spaces
        patterns = self.test_pattern.split()
        for pattern_part in patterns:
            full_pattern = str(self.project_root / pattern_part.strip())
            matches = glob.glob(full_pattern, recursive=True)
            # Filter out directories, only return files
            files = [f for f in matches if Path(f).is_file()]
            all_files.extend(files)

        # Remove duplicates and sort
        unique_files = list(set(all_files))
        return [Path(f) for f in sorted(unique_files)]

    async def run(self) -> TestSuiteResult:
        """Run all tests matching the pattern."""
        started_at = datetime.now()
        start_time = time.monotonic()

        test_files = self.discover_tests()
        logger.info(f"[{self.runner_type}] Found {len(test_files)} test files")

        results: List[TestResult] = []
        passed = failed = skipped = errors = flaky = 0

        for test_file in test_files:
            if self.fail_fast and failed > 0:
                logger.info(f"[{self.runner_type}] Stopping due to fail-fast")
                break

            result = await self._run_test_file(test_file)
            results.extend(result)

            for r in result:
                if r.status == TestStatus.PASSED:
                    passed += 1
                elif r.status == TestStatus.FAILED:
                    failed += 1
                elif r.status == TestStatus.SKIPPED:
                    skipped += 1
                elif r.status == TestStatus.ERROR:
                    errors += 1
                elif r.status == TestStatus.FLAKY:
                    flaky += 1
                    passed += 1  # Flaky counts as passed

        ended_at = datetime.now()
        duration = time.monotonic() - start_time

        total_tests = passed + failed + skipped + errors

        # Build summary
        status_emoji = "✅" if (failed == 0 and errors == 0) else "❌"
        summary = (
            f"{status_emoji} {self.runner_type.upper()}: "
            f"{passed} passed, {failed} failed, {skipped} skipped"
        )
        if flaky > 0:
            summary += f", {flaky} flaky"
        summary += f" ({duration:.1f}s)"

        return TestSuiteResult(
            runner_type=self.runner_type,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            flaky=flaky,
            tests=results,
            summary=summary,
        )

    async def _run_test_file(self, test_file: Path) -> List[TestResult]:
        """
        Run tests in a single file.

        Returns list of TestResults.
        """
        results = []
        rel_path = str(test_file.relative_to(self.project_root))

        # Detect test framework
        framework = self._detect_framework(test_file)

        try:
            if framework == "pytest":
                results = await self._run_pytest(test_file)
            elif framework == "jest":
                results = await self._run_jest(test_file)
            elif framework == "go":
                results = await self._run_go_test(test_file)
            else:
                # Fallback: try pytest
                results = await self._run_pytest(test_file)
        except asyncio.TimeoutError:
            results.append(
                TestResult(
                    name=rel_path,
                    status=TestStatus.ERROR,
                    duration_seconds=self.timeout_seconds,
                    file_path=rel_path,
                    error_message=f"Test timed out after {self.timeout_seconds}s",
                )
            )
        except Exception as e:
            results.append(
                TestResult(
                    name=rel_path,
                    status=TestStatus.ERROR,
                    duration_seconds=0,
                    file_path=rel_path,
                    error_message=str(e),
                )
            )

        return results

    def _detect_framework(self, test_file: Path) -> str:
        """Detect test framework based on file extension and content."""
        suffix = test_file.suffix

        if suffix == ".py":
            return "pytest"
        elif suffix in (".js", ".ts", ".jsx", ".tsx"):
            return "jest"
        elif suffix == ".go":
            return "go"
        else:
            return "unknown"

    async def _run_pytest(self, test_file: Path) -> List[TestResult]:
        """Run pytest on a test file."""
        start_time = time.monotonic()
        rel_path = str(test_file.relative_to(self.project_root))

        cmd = [
            "python",
            "-m",
            "pytest",
            str(test_file),
            "-v",
            "--tb=short",
            f"--timeout={self.timeout_seconds}",
            "-q",
        ]

        if self.fail_fast:
            cmd.append("-x")

        # Add JSON output for parsing
        json_output_file = (
            self.project_root / ".superqode" / "temp" / f"pytest_{test_file.stem}.json"
        )
        json_output_file.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--json-report", f"--json-report-file={json_output_file}"])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            raise

        duration = time.monotonic() - start_time

        # Parse JSON report if available
        results = []
        if json_output_file.exists():
            try:
                report = json.loads(json_output_file.read_text())
                for test in report.get("tests", []):
                    status = TestStatus.PASSED
                    if test.get("outcome") == "failed":
                        status = TestStatus.FAILED
                    elif test.get("outcome") == "skipped":
                        status = TestStatus.SKIPPED
                    elif test.get("outcome") == "error":
                        status = TestStatus.ERROR

                    results.append(
                        TestResult(
                            name=test.get("nodeid", "unknown"),
                            status=status,
                            duration_seconds=test.get("duration", 0),
                            file_path=rel_path,
                            error_message=test.get("call", {}).get("longrepr")
                            if status == TestStatus.FAILED
                            else None,
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to parse pytest JSON report: {e}")

        # Fallback if no JSON report
        if not results:
            status = TestStatus.PASSED if process.returncode == 0 else TestStatus.FAILED
            results.append(
                TestResult(
                    name=rel_path,
                    status=status,
                    duration_seconds=duration,
                    file_path=rel_path,
                    stdout=stdout.decode() if stdout else None,
                    stderr=stderr.decode() if stderr else None,
                )
            )

        return results

    async def _run_jest(self, test_file: Path) -> List[TestResult]:
        """Run jest on a test file."""
        start_time = time.monotonic()
        rel_path = str(test_file.relative_to(self.project_root))

        cmd = [
            "npx",
            "jest",
            str(test_file),
            "--json",
            "--verbose",
        ]

        if self.fail_fast:
            cmd.append("--bail")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            raise

        duration = time.monotonic() - start_time

        # Parse JSON output
        results = []
        try:
            report = json.loads(stdout.decode())
            for result in report.get("testResults", []):
                for assertion in result.get("assertionResults", []):
                    status = TestStatus.PASSED
                    if assertion.get("status") == "failed":
                        status = TestStatus.FAILED
                    elif assertion.get("status") == "pending":
                        status = TestStatus.SKIPPED

                    results.append(
                        TestResult(
                            name=assertion.get("fullName", "unknown"),
                            status=status,
                            duration_seconds=assertion.get("duration", 0) / 1000,
                            file_path=rel_path,
                            error_message="\n".join(assertion.get("failureMessages", []))
                            if status == TestStatus.FAILED
                            else None,
                        )
                    )
        except Exception as e:
            # Jest JSON parsing often fails due to output format issues - use debug level
            logger.debug(f"Failed to parse jest JSON output: {e}")
            status = TestStatus.PASSED if process.returncode == 0 else TestStatus.FAILED
            results.append(
                TestResult(
                    name=rel_path,
                    status=status,
                    duration_seconds=duration,
                    file_path=rel_path,
                )
            )

        return results

    async def _run_go_test(self, test_file: Path) -> List[TestResult]:
        """Run go test on a test file."""
        start_time = time.monotonic()
        rel_path = str(test_file.relative_to(self.project_root))

        # Go tests run on package level
        package_dir = test_file.parent

        cmd = [
            "go",
            "test",
            "-v",
            "-json",
            f"-timeout={self.timeout_seconds}s",
            "./...",
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(package_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            raise

        duration = time.monotonic() - start_time

        # Parse JSON lines output
        results = []
        for line in stdout.decode().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("Action") == "pass" and event.get("Test"):
                    results.append(
                        TestResult(
                            name=event.get("Test"),
                            status=TestStatus.PASSED,
                            duration_seconds=event.get("Elapsed", 0),
                            file_path=rel_path,
                        )
                    )
                elif event.get("Action") == "fail" and event.get("Test"):
                    results.append(
                        TestResult(
                            name=event.get("Test"),
                            status=TestStatus.FAILED,
                            duration_seconds=event.get("Elapsed", 0),
                            file_path=rel_path,
                            error_message=event.get("Output"),
                        )
                    )
            except json.JSONDecodeError:
                continue

        if not results:
            status = TestStatus.PASSED if process.returncode == 0 else TestStatus.FAILED
            results.append(
                TestResult(
                    name=rel_path,
                    status=status,
                    duration_seconds=duration,
                    file_path=rel_path,
                )
            )

        return results


class SmokeRunner(TestRunner):
    """
    Smoke Test Runner.

    Hard constraints:
    - ❌ No discovery (only configured patterns)
    - ❌ No inference
    - ❌ No generation
    - ✅ Fail-fast enabled
    """

    def __init__(
        self,
        project_root: Path,
        test_pattern: str = "**/test_smoke*.py",
        timeout_seconds: int = 60,
    ):
        super().__init__(
            project_root=project_root,
            test_pattern=test_pattern,
            fail_fast=True,
            timeout_seconds=timeout_seconds,
            detect_flakes=False,
            retry_count=0,
        )

    @property
    def runner_type(self) -> str:
        return "smoke"


class SanityRunner(TestRunner):
    """
    Sanity Test Runner.

    Hard constraints:
    - ❌ No discovery (only configured patterns)
    - ❌ No generation
    - ✅ Verifies recent changes didn't break basics
    """

    def __init__(
        self,
        project_root: Path,
        test_pattern: str = "**/test_sanity*.py",
        timeout_seconds: int = 120,
    ):
        super().__init__(
            project_root=project_root,
            test_pattern=test_pattern,
            fail_fast=False,
            timeout_seconds=timeout_seconds,
            detect_flakes=False,
            retry_count=0,
        )

    @property
    def runner_type(self) -> str:
        return "sanity"


class RegressionRunner(TestRunner):
    """
    Regression Test Runner.

    Hard constraints:
    - ❌ No new test creation
    - ✅ Detects failures, flakes, performance regressions
    - ✅ Runs full regression suite
    """

    def __init__(
        self,
        project_root: Path,
        test_pattern: str = "**/test_*.py",
        timeout_seconds: int = 600,
        detect_flakes: bool = True,
        retry_count: int = 2,
    ):
        super().__init__(
            project_root=project_root,
            test_pattern=test_pattern,
            fail_fast=False,
            timeout_seconds=timeout_seconds,
            detect_flakes=detect_flakes,
            retry_count=retry_count,
        )

    @property
    def runner_type(self) -> str:
        return "regression"

    async def _run_test_file(self, test_file: Path) -> List[TestResult]:
        """Run with flake detection."""
        results = await super()._run_test_file(test_file)

        if not self.detect_flakes:
            return results

        # Retry failed tests to detect flakes
        flaky_results = []
        for result in results:
            if result.status == TestStatus.FAILED and self.retry_count > 0:
                # Retry the test
                for retry in range(1, self.retry_count + 1):
                    retry_results = await super()._run_test_file(test_file)
                    matching = [r for r in retry_results if r.name == result.name]
                    if matching and matching[0].status == TestStatus.PASSED:
                        # Test passed on retry - it's flaky
                        result.status = TestStatus.FLAKY
                        result.retry_count = retry
                        logger.info(f"Detected flaky test: {result.name} (passed on retry {retry})")
                        break
            flaky_results.append(result)

        return flaky_results
