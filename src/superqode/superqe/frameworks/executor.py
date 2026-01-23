"""
Multi-Framework Executor - Execute tests across multiple frameworks.

Provides:
- Parallel execution across frameworks
- Result aggregation
- Unified reporting
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio

from .base import FrameworkConfig, ExecutionResult
from .registry import detect_framework, get_framework


@dataclass
class ExecutorConfig:
    """Configuration for multi-framework execution."""

    project_root: Path = field(default_factory=Path.cwd)
    parallel_frameworks: bool = True
    timeout_seconds: int = 600
    fail_fast: bool = False
    coverage: bool = False
    workers_per_framework: int = 4


@dataclass
class MultiFrameworkResult:
    """Result of multi-framework test execution."""

    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    framework_results: Dict[str, ExecutionResult] = field(default_factory=dict)
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def success(self) -> bool:
        """Did all frameworks pass?"""
        return all(r.success for r in self.framework_results.values())

    @property
    def frameworks_run(self) -> List[str]:
        """List of frameworks that were run."""
        return list(self.framework_results.keys())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "frameworks": {
                name: result.to_dict() for name, result in self.framework_results.items()
            },
        }


class MultiFrameworkExecutor:
    """
    Executor for running tests across multiple frameworks.

    Supports parallel execution of up to 10,000+ concurrent tests
    by distributing work across frameworks and workers.
    """

    def __init__(self, config: Optional[ExecutorConfig] = None):
        """Initialize the executor."""
        self.config = config or ExecutorConfig()

    async def execute(
        self,
        frameworks: Optional[List[str]] = None,
        tests: Optional[Dict[str, List[str]]] = None,
        **kwargs,
    ) -> MultiFrameworkResult:
        """
        Execute tests across frameworks.

        Args:
            frameworks: List of framework names to run (None = auto-detect)
            tests: Dict of framework name to test list
            **kwargs: Additional options

        Returns:
            MultiFrameworkResult with aggregated results
        """
        started_at = datetime.now()

        result = MultiFrameworkResult(started_at=started_at)

        # Get frameworks to run
        framework_instances = []

        if frameworks:
            for name in frameworks:
                fw_config = FrameworkConfig(
                    project_root=self.config.project_root,
                    parallel=True,
                    workers=self.config.workers_per_framework,
                    timeout_seconds=self.config.timeout_seconds,
                    fail_fast=self.config.fail_fast,
                    coverage=self.config.coverage,
                )
                fw = get_framework(name, fw_config)
                if fw:
                    framework_instances.append(fw)
        else:
            # Auto-detect frameworks
            fw_config = FrameworkConfig(
                project_root=self.config.project_root,
                parallel=True,
                workers=self.config.workers_per_framework,
            )
            framework_instances = detect_framework(self.config.project_root, fw_config)

        if not framework_instances:
            result.ended_at = datetime.now()
            return result

        # Execute frameworks
        if self.config.parallel_frameworks:
            # Run all frameworks in parallel
            tasks = []
            for fw in framework_instances:
                fw_tests = tests.get(fw.NAME) if tests else None
                tasks.append(self._run_framework(fw, fw_tests))

            fw_results = await asyncio.gather(*tasks, return_exceptions=True)

            for fw, fw_result in zip(framework_instances, fw_results):
                if isinstance(fw_result, Exception):
                    # Create error result
                    result.framework_results[fw.NAME] = ExecutionResult(
                        framework=fw.NAME,
                        started_at=started_at,
                        ended_at=datetime.now(),
                        errors=1,
                        error_output=str(fw_result),
                    )
                else:
                    result.framework_results[fw.NAME] = fw_result
        else:
            # Run frameworks sequentially
            for fw in framework_instances:
                if self.config.fail_fast and result.failed > 0:
                    break

                fw_tests = tests.get(fw.NAME) if tests else None
                try:
                    fw_result = await self._run_framework(fw, fw_tests)
                    result.framework_results[fw.NAME] = fw_result
                except Exception as e:
                    result.framework_results[fw.NAME] = ExecutionResult(
                        framework=fw.NAME,
                        started_at=started_at,
                        ended_at=datetime.now(),
                        errors=1,
                        error_output=str(e),
                    )

        # Aggregate results
        for fw_result in result.framework_results.values():
            result.total += fw_result.total
            result.passed += fw_result.passed
            result.failed += fw_result.failed
            result.skipped += fw_result.skipped
            result.errors += fw_result.errors

        result.ended_at = datetime.now()
        result.duration_seconds = (result.ended_at - started_at).total_seconds()

        return result

    async def _run_framework(self, framework, tests: Optional[List[str]] = None) -> ExecutionResult:
        """Run a single framework."""
        return await framework.execute(tests=tests)

    async def discover_all(self) -> Dict[str, List[str]]:
        """Discover tests across all detected frameworks."""
        fw_config = FrameworkConfig(project_root=self.config.project_root)
        frameworks = detect_framework(self.config.project_root, fw_config)

        results = {}
        for fw in frameworks:
            suites = await fw.discover()
            tests = []
            for suite in suites:
                tests.extend(suite.tests)
            results[fw.NAME] = tests

        return results


async def execute_tests(
    project_root: Optional[Path] = None,
    frameworks: Optional[List[str]] = None,
    parallel: bool = True,
    coverage: bool = False,
    **kwargs,
) -> MultiFrameworkResult:
    """
    Execute tests across frameworks.

    Args:
        project_root: Project root directory
        frameworks: Frameworks to run (None = auto-detect)
        parallel: Run frameworks in parallel
        coverage: Collect coverage data
        **kwargs: Additional options

    Returns:
        MultiFrameworkResult
    """
    config = ExecutorConfig(
        project_root=project_root or Path.cwd(),
        parallel_frameworks=parallel,
        coverage=coverage,
    )

    executor = MultiFrameworkExecutor(config)
    return await executor.execute(frameworks=frameworks, **kwargs)
