"""
E2E Test Framework Implementations.

Supports:
- Cypress
- Playwright
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


class CypressFramework(TestFramework):
    """Cypress E2E test framework."""

    NAME = "cypress"
    DISPLAY_NAME = "Cypress"
    LANGUAGE = "javascript"
    FILE_PATTERNS = ["cypress/e2e/**/*.cy.js", "cypress/e2e/**/*.cy.ts"]

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """Detect if Cypress is used."""
        if (project_root / "cypress.config.js").exists():
            return True
        if (project_root / "cypress.config.ts").exists():
            return True
        if (project_root / "cypress.json").exists():
            return True
        if (project_root / "cypress").is_dir():
            return True

        package_json = project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "cypress" in deps:
                    return True
            except Exception:
                pass

        return False

    async def discover(self) -> List[TestSuite]:
        """Discover Cypress tests."""
        suites = []
        for pattern in self.FILE_PATTERNS:
            for file_path in self.config.project_root.glob(pattern):
                suites.append(TestSuite(name=file_path.stem, file_path=str(file_path), tests=[]))
        return suites

    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """Execute Cypress tests."""
        started_at = datetime.now()

        command = ["npx", "cypress", "run", "--reporter", "json"]

        if self.config.parallel and self.config.workers > 1:
            command.extend(["--parallel", "--record"])

        if tests:
            command.extend(["--spec", ",".join(tests)])

        exit_code, stdout, stderr = await self.run_command(command)

        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()

        # Parse results from output
        test_results = []
        total = passed = failed = skipped = 0

        # Try to parse JSON output
        try:
            json_match = re.search(r'\{[\s\S]*"stats"[\s\S]*\}', stdout)
            if json_match:
                data = json.loads(json_match.group())
                stats = data.get("stats", {})
                total = stats.get("tests", 0)
                passed = stats.get("passes", 0)
                failed = stats.get("failures", 0)
                skipped = stats.get("pending", 0)
        except json.JSONDecodeError:
            # Fallback to regex parsing
            pass_match = re.search(r"(\d+) passing", stdout)
            fail_match = re.search(r"(\d+) failing", stdout)
            skip_match = re.search(r"(\d+) pending", stdout)

            if pass_match:
                passed = int(pass_match.group(1))
            if fail_match:
                failed = int(fail_match.group(1))
            if skip_match:
                skipped = int(skip_match.group(1))
            total = passed + failed + skipped

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
        """Parse Cypress output."""
        return []

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """Get Cypress command."""
        command = ["npx", "cypress", "run"]
        if tests:
            command.extend(["--spec", ",".join(tests)])
        return command


class PlaywrightFramework(TestFramework):
    """Playwright E2E test framework."""

    NAME = "playwright"
    DISPLAY_NAME = "Playwright"
    LANGUAGE = "javascript"
    FILE_PATTERNS = ["**/*.spec.ts", "**/*.spec.js", "tests/**/*.ts"]

    @classmethod
    def detect(cls, project_root: Path) -> bool:
        """Detect if Playwright is used."""
        if (project_root / "playwright.config.ts").exists():
            return True
        if (project_root / "playwright.config.js").exists():
            return True

        package_json = project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "@playwright/test" in deps:
                    return True
            except Exception:
                pass

        return False

    async def discover(self) -> List[TestSuite]:
        """Discover Playwright tests."""
        command = ["npx", "playwright", "test", "--list"]

        exit_code, stdout, stderr = await self.run_command(command, timeout=60)

        suites = {}
        for line in stdout.splitlines():
            line = line.strip()
            if " › " in line:
                parts = line.split(" › ")
                file_path = parts[0] if parts else ""
                test_name = " › ".join(parts[1:]) if len(parts) > 1 else ""

                if file_path not in suites:
                    suites[file_path] = []
                if test_name:
                    suites[file_path].append(test_name)

        return [
            TestSuite(name=Path(fp).stem, file_path=fp, tests=tests) for fp, tests in suites.items()
        ]

    async def execute(self, tests: Optional[List[str]] = None, **kwargs) -> ExecutionResult:
        """Execute Playwright tests."""
        started_at = datetime.now()

        command = ["npx", "playwright", "test", "--reporter=json"]

        if self.config.parallel and self.config.workers > 1:
            command.extend(["--workers", str(self.config.workers)])

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
            total = stats.get("expected", 0) + stats.get("unexpected", 0) + stats.get("skipped", 0)
            passed = stats.get("expected", 0)
            failed = stats.get("unexpected", 0)
            skipped = stats.get("skipped", 0)

            for suite in data.get("suites", []):
                for spec in suite.get("specs", []):
                    for test in spec.get("tests", []):
                        for result in test.get("results", []):
                            status = TestStatus.PASSED
                            if result.get("status") == "failed":
                                status = TestStatus.FAILED
                            elif result.get("status") == "skipped":
                                status = TestStatus.SKIPPED

                            test_results.append(
                                TestResult(
                                    name=spec.get("title", ""),
                                    status=status,
                                    duration_ms=result.get("duration", 0),
                                    file_path=spec.get("file"),
                                    error_message=result.get("error", {}).get("message"),
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
        """Parse Playwright output."""
        return []

    def get_command(self, tests: Optional[List[str]] = None) -> List[str]:
        """Get Playwright command."""
        command = ["npx", "playwright", "test"]
        if tests:
            command.extend(tests)
        return command
