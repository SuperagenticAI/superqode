"""
JavaScript Test Framework Implementations.

Supports:
- Jest
- Mocha
- Vitest
- Jasmine
- AVA
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


class JestFramework(TestFramework):
    """Jest test framework."""

    NAME = "jest"
    DISPLAY_NAME = "Jest"
    LANGUAGE = "javascript"
    FILE_PATTERNS = ["**/*.test.js", "**/*.test.ts", "**/*.spec.js", "**/*.spec.ts"]

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """Detect if Jest is used."""
        # Check package.json
        package_json = project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "jest" in deps:
                    return True
                # Check scripts
                scripts = data.get("scripts", {})
                if any("jest" in str(v) for v in scripts.values()):
                    return True
            except Exception:
                pass

        # Check for jest.config.js
        if (project_root / "jest.config.js").exists():
            return True
        if (project_root / "jest.config.ts").exists():
            return True

        return False

    async def discover(self) -> List[TestSuite]:
        """Discover Jest tests."""
        command = ["npx", "jest", "--listTests", "--json"]

        exit_code, stdout, stderr = await self.run_command(command, timeout=60)

        suites = []
        try:
            test_files = json.loads(stdout)
            for file_path in test_files:
                suites.append(
                    TestSuite(
                        name=Path(file_path).stem,
                        file_path=file_path,
                        tests=[],  # Jest doesn't list individual tests easily
                    )
                )
        except json.JSONDecodeError:
            pass

        return suites

    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """Execute Jest tests."""
        started_at = datetime.now()

        command = ["npx", "jest", "--json"]

        if self.config.verbose:
            command.append("--verbose")
        if self.config.fail_fast:
            command.append("--bail")
        if self.config.coverage:
            command.append("--coverage")
        if self.config.parallel and self.config.workers > 1:
            command.extend(["--maxWorkers", str(self.config.workers)])

        if tests:
            command.extend(tests)

        exit_code, stdout, stderr = await self.run_command(command)

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()

        # Parse JSON output
        test_results = []
        total = passed = failed = skipped = 0
        coverage = None

        try:
            # Find JSON in output (Jest outputs JSON after other text)
            json_match = re.search(r'\{[\s\S]*"numTotalTests"[\s\S]*\}', stdout)
            if json_match:
                data = json.loads(json_match.group())

                total = data.get("numTotalTests", 0)
                passed = data.get("numPassedTests", 0)
                failed = data.get("numFailedTests", 0)
                skipped = data.get("numPendingTests", 0)

                # Parse individual test results
                for result in data.get("testResults", []):
                    for assertion in result.get("assertionResults", []):
                        status_map = {
                            "passed": TestStatus.PASSED,
                            "failed": TestStatus.FAILED,
                            "pending": TestStatus.SKIPPED,
                            "skipped": TestStatus.SKIPPED,
                        }
                        status = status_map.get(assertion.get("status", "failed"), TestStatus.ERROR)

                        test_results.append(
                            TestResult(
                                name=assertion.get("fullName", ""),
                                status=status,
                                duration_ms=assertion.get("duration", 0),
                                file_path=result.get("name"),
                                error_message="\n".join(assertion.get("failureMessages", [])),
                            )
                        )

                # Get coverage if available
                cov_data = data.get("coverageMap", {})
                if cov_data:
                    # Calculate overall coverage
                    total_statements = 0
                    covered_statements = 0
                    for file_cov in cov_data.values():
                        s = file_cov.get("s", {})
                        total_statements += len(s)
                        covered_statements += sum(1 for v in s.values() if v > 0)
                    if total_statements > 0:
                        coverage = (covered_statements / total_statements) * 100

        except json.JSONDecodeError:
            pass

        return ExecutionResult(
            framework=self.NAME,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=0,
            test_results=test_results,
            coverage_percentage=coverage,
            output=stdout,
            error_output=stderr,
        )

    def parse_results(self, output: str) -> List[TestResult]:
        """Parse Jest output."""
        # Handled in execute() with JSON parsing
        return []

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """Get Jest command."""
        command = ["npx", "jest"]
        if tests:
            command.extend(tests)
        return command


class MochaFramework(TestFramework):
    """Mocha test framework."""

    NAME = "mocha"
    DISPLAY_NAME = "Mocha"
    LANGUAGE = "javascript"
    FILE_PATTERNS = ["**/*.test.js", "**/*.spec.js", "test/**/*.js"]

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """Detect if Mocha is used."""
        package_json = project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "mocha" in deps:
                    return True
            except Exception:
                pass

        if (project_root / ".mocharc.js").exists():
            return True
        if (project_root / ".mocharc.json").exists():
            return True

        return False

    async def discover(self) -> List[TestSuite]:
        """Discover Mocha tests."""
        suites = []
        for pattern in self.FILE_PATTERNS:
            for file_path in self.config.project_root.glob(pattern):
                suites.append(TestSuite(name=file_path.stem, file_path=str(file_path), tests=[]))
        return suites

    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """Execute Mocha tests."""
        started_at = datetime.now()

        command = ["npx", "mocha", "--reporter", "json"]

        if self.config.fail_fast:
            command.append("--bail")
        if self.config.parallel and self.config.workers > 1:
            command.extend(["--parallel", "--jobs", str(self.config.workers)])

        if tests:
            command.extend(tests)

        exit_code, stdout, stderr = await self.run_command(command)

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()

        test_results = []
        total = passed = failed = skipped = 0

        try:
            data = json.loads(stdout)
            stats = data.get("stats", {})
            total = stats.get("tests", 0)
            passed = stats.get("passes", 0)
            failed = stats.get("failures", 0)
            skipped = stats.get("pending", 0)

            for test in data.get("passes", []):
                test_results.append(
                    TestResult(
                        name=test.get("fullTitle", ""),
                        status=TestStatus.PASSED,
                        duration_ms=test.get("duration", 0),
                        file_path=test.get("file"),
                    )
                )

            for test in data.get("failures", []):
                test_results.append(
                    TestResult(
                        name=test.get("fullTitle", ""),
                        status=TestStatus.FAILED,
                        duration_ms=test.get("duration", 0),
                        file_path=test.get("file"),
                        error_message=test.get("err", {}).get("message"),
                        stack_trace=test.get("err", {}).get("stack"),
                    )
                )

            for test in data.get("pending", []):
                test_results.append(
                    TestResult(
                        name=test.get("fullTitle", ""),
                        status=TestStatus.SKIPPED,
                        duration_ms=0,
                        file_path=test.get("file"),
                    )
                )

        except json.JSONDecodeError:
            pass

        return ExecutionResult(
            framework=self.NAME,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=0,
            test_results=test_results,
            output=stdout,
            error_output=stderr,
        )

    def parse_results(self, output: str) -> List[TestResult]:
        """Parse Mocha output."""
        return []

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """Get Mocha command."""
        command = ["npx", "mocha"]
        if tests:
            command.extend(tests)
        return command


class VitestFramework(TestFramework):
    """Vitest test framework."""

    NAME = "vitest"
    DISPLAY_NAME = "Vitest"
    LANGUAGE = "javascript"
    FILE_PATTERNS = ["**/*.test.ts", "**/*.spec.ts", "**/*.test.js", "**/*.spec.js"]

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """Detect if Vitest is used."""
        package_json = project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "vitest" in deps:
                    return True
            except Exception:
                pass

        if (project_root / "vitest.config.ts").exists():
            return True
        if (project_root / "vitest.config.js").exists():
            return True

        return False

    async def discover(self) -> List[TestSuite]:
        """Discover Vitest tests."""
        suites = []
        for pattern in self.FILE_PATTERNS:
            for file_path in self.config.project_root.glob(pattern):
                suites.append(TestSuite(name=file_path.stem, file_path=str(file_path), tests=[]))
        return suites

    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """Execute Vitest tests."""
        started_at = datetime.now()

        command = ["npx", "vitest", "run", "--reporter=json"]

        if self.config.coverage:
            command.append("--coverage")

        if tests:
            command.extend(tests)

        exit_code, stdout, stderr = await self.run_command(command)

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()

        test_results = []
        total = passed = failed = skipped = 0

        try:
            # Find JSON output
            json_match = re.search(r'\{[\s\S]*"numTotalTests"[\s\S]*\}', stdout)
            if json_match:
                data = json.loads(json_match.group())
                total = data.get("numTotalTests", 0)
                passed = data.get("numPassedTests", 0)
                failed = data.get("numFailedTests", 0)
                skipped = data.get("numPendingTests", 0)
        except json.JSONDecodeError:
            pass

        return ExecutionResult(
            framework=self.NAME,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=0,
            test_results=test_results,
            output=stdout,
            error_output=stderr,
        )

    def parse_results(self, output: str) -> List[TestResult]:
        """Parse Vitest output."""
        return []

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """Get Vitest command."""
        command = ["npx", "vitest", "run"]
        if tests:
            command.extend(tests)
        return command
