"""
Python Test Framework Implementations.

Supports:
- pytest
- unittest
- nose2
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json
import re

from .base import (
    TestFramework,
    FrameworkConfig,
    TestResult,
    TestSuite,
    ExecutionResult,
    TestStatus,
)


class PytestFramework(TestFramework):
    """Pytest test framework."""

    NAME = "pytest"
    DISPLAY_NAME = "Pytest"
    LANGUAGE = "python"
    FILE_PATTERNS = ["**/test_*.py", "**/*_test.py"]

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """Detect if pytest is used."""
        # Check for pytest.ini, pyproject.toml with pytest, or conftest.py
        if (project_root / "pytest.ini").exists():
            return True
        if (project_root / "conftest.py").exists():
            return True

        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text()
            if "[tool.pytest" in content:
                return True

        # Check for test files
        for pattern in cls.FILE_PATTERNS:
            if list(project_root.glob(pattern)):
                return True

        return False

    async def discover(self) -> List[TestSuite]:
        """Discover pytest tests."""
        command = ["pytest", "--collect-only", "-q", str(self.config.project_root)]

        exit_code, stdout, stderr = await self.run_command(command, timeout=60)

        suites = []
        current_file = None
        tests = []

        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("="):
                continue

            # Parse collected test items
            if "::" in line:
                parts = line.split("::")
                file_path = parts[0]

                if file_path != current_file:
                    if current_file and tests:
                        suites.append(
                            TestSuite(
                                name=Path(current_file).stem, file_path=current_file, tests=tests
                            )
                        )
                    current_file = file_path
                    tests = []

                test_name = "::".join(parts[1:])
                tests.append(test_name)

        # Don't forget the last file
        if current_file and tests:
            suites.append(
                TestSuite(name=Path(current_file).stem, file_path=current_file, tests=tests)
            )

        return suites

    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """Execute pytest tests."""
        started_at = datetime.now()

        command = ["pytest"]

        # Add options
        if self.config.verbose:
            command.append("-v")
        if self.config.fail_fast:
            command.append("-x")
        if self.config.coverage:
            command.extend(["--cov", "--cov-report=json"])
        if self.config.parallel and self.config.workers > 1:
            command.extend(["-n", str(self.config.workers)])

        # JSON output for parsing
        command.append("--tb=short")
        command.append("-q")

        # Add extra args
        command.extend(self.config.extra_args)

        # Add specific tests
        if tests:
            command.extend(tests)
        else:
            command.append(str(self.config.project_root))

        exit_code, stdout, stderr = await self.run_command(command)

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()

        # Parse results
        test_results = self.parse_results(stdout)

        # Count results
        passed = sum(1 for r in test_results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in test_results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in test_results if r.status == TestStatus.SKIPPED)
        errors = sum(1 for r in test_results if r.status == TestStatus.ERROR)

        # Get coverage if available
        coverage = None
        if self.config.coverage:
            coverage_file = self.config.project_root / "coverage.json"
            if coverage_file.exists():
                try:
                    cov_data = json.loads(coverage_file.read_text())
                    coverage = cov_data.get("totals", {}).get("percent_covered", 0)
                except Exception:
                    pass

        return ExecutionResult(
            framework=self.NAME,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            total=len(test_results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            test_results=test_results,
            coverage_percentage=coverage,
            output=stdout,
            error_output=stderr,
        )

    def parse_results(self, output: str) -> List[TestResult]:
        """Parse pytest output."""
        results = []

        # Parse test results from output
        # Format: test_file.py::test_name PASSED/FAILED
        test_pattern = re.compile(
            r"(\S+::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)(?:\s+\[.*?\])?\s*(?:\((.+?)\))?"
        )

        for line in output.splitlines():
            match = test_pattern.search(line)
            if match:
                name = match.group(1)
                status_str = match.group(2)
                duration_str = match.group(3)

                status_map = {
                    "PASSED": TestStatus.PASSED,
                    "FAILED": TestStatus.FAILED,
                    "SKIPPED": TestStatus.SKIPPED,
                    "ERROR": TestStatus.ERROR,
                }
                status = status_map.get(status_str, TestStatus.ERROR)

                # Parse duration if available
                duration_ms = 0.0
                if duration_str:
                    try:
                        if "s" in duration_str:
                            duration_ms = float(duration_str.replace("s", "")) * 1000
                    except ValueError:
                        pass

                results.append(
                    TestResult(
                        name=name,
                        status=status,
                        duration_ms=duration_ms,
                    )
                )

        return results

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """Get pytest command."""
        command = ["pytest"]
        if tests:
            command.extend(tests)
        return command


class UnittestFramework(TestFramework):
    """Python unittest framework."""

    NAME = "unittest"
    DISPLAY_NAME = "Unittest"
    LANGUAGE = "python"
    FILE_PATTERNS = ["**/test_*.py", "**/*_test.py"]

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """Detect if unittest is used."""
        # Check for test files with unittest imports
        for pattern in cls.FILE_PATTERNS:
            for test_file in project_root.glob(pattern):
                try:
                    content = test_file.read_text()
                    if "import unittest" in content or "from unittest" in content:
                        return True
                except Exception:
                    pass
        return False

    async def discover(self) -> List[TestSuite]:
        """Discover unittest tests."""
        command = [
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(self.config.project_root),
            "-p",
            "test_*.py",
            "-v",
        ]

        # Just collect, don't run
        exit_code, stdout, stderr = await self.run_command(
            [
                "python",
                "-c",
                f"""
import unittest
import sys
loader = unittest.TestLoader()
suite = loader.discover('{self.config.project_root}', pattern='test_*.py')
for group in suite:
    for test_group in group:
        for test in test_group:
            print(str(test))
""",
            ],
            timeout=60,
        )

        suites_dict = {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            # Parse test name: test_method (module.TestClass)
            match = re.match(r"(\w+)\s+\((.+)\)", line)
            if match:
                method = match.group(1)
                module_class = match.group(2)

                if module_class not in suites_dict:
                    suites_dict[module_class] = []
                suites_dict[module_class].append(method)

        return [
            TestSuite(name=name, file_path=name.replace(".", "/") + ".py", tests=tests)
            for name, tests in suites_dict.items()
        ]

    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """Execute unittest tests."""
        started_at = datetime.now()

        command = ["python", "-m", "unittest"]

        if self.config.verbose:
            command.append("-v")
        if self.config.fail_fast:
            command.append("-f")

        if tests:
            command.extend(tests)
        else:
            command.extend(["discover", "-s", str(self.config.project_root), "-p", "test_*.py"])

        exit_code, stdout, stderr = await self.run_command(command)

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()

        test_results = self.parse_results(stdout + stderr)

        passed = sum(1 for r in test_results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in test_results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in test_results if r.status == TestStatus.SKIPPED)
        errors = sum(1 for r in test_results if r.status == TestStatus.ERROR)

        return ExecutionResult(
            framework=self.NAME,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            total=len(test_results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            test_results=test_results,
            output=stdout,
            error_output=stderr,
        )

    def parse_results(self, output: str) -> List[TestResult]:
        """Parse unittest output."""
        results = []

        # Parse verbose output: test_name (module.Class) ... ok/FAIL/ERROR
        pattern = re.compile(r"(\w+)\s+\((.+?)\)\s+\.\.\.\s+(ok|FAIL|ERROR|skipped)")

        for match in pattern.finditer(output):
            method = match.group(1)
            module_class = match.group(2)
            status_str = match.group(3)

            status_map = {
                "ok": TestStatus.PASSED,
                "FAIL": TestStatus.FAILED,
                "ERROR": TestStatus.ERROR,
                "skipped": TestStatus.SKIPPED,
            }
            status = status_map.get(status_str, TestStatus.ERROR)

            results.append(
                TestResult(
                    name=f"{module_class}.{method}",
                    status=status,
                    duration_ms=0,
                )
            )

        return results

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """Get unittest command."""
        command = ["python", "-m", "unittest"]
        if tests:
            command.extend(tests)
        return command
