"""
QE Session - Orchestrates a complete QE run.

A QE session encompasses:
1. Workspace setup (ephemeral edit mode)
2. Test execution (smoke/sanity/regression)
3. Patch validation via harness
4. Agent-driven analysis (if enabled)
5. Artifact generation (patches, tests, QIR)
6. Cleanup (revert all changes, preserve artifacts)

Aligned with PRD:
> "SuperQode never edits, rewrites, or commits code."
> "All fixes are suggested, validated, and proven, never auto-applied."
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from superqode.workspace.manager import WorkspaceManager, QESessionConfig as WorkspaceConfig
from superqode.workspace.manager import QEMode as WorkspaceQEMode
from superqode.execution.runner import (
    TestRunner,
    SmokeRunner,
    SanityRunner,
    RegressionRunner,
    TestSuiteResult,
)
from superqode.execution.modes import (
    QEMode,
    QuickScanConfig,
    DeepQEConfig,
    get_qe_mode_config,
)
from superqode.harness import PatchHarness, HarnessResult
from superqode.guidance import QEGuidance, GuidanceMode, load_guidance_config

logger = logging.getLogger(__name__)


class QEStatus(Enum):
    """Status of a QE session."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QESessionConfig:
    """Configuration for a QE session."""

    mode: QEMode = QEMode.QUICK_SCAN

    # Test patterns (multi-language support - includes standard naming)
    smoke_pattern: str = "**/*smoke*"
    sanity_pattern: str = "**/*sanity*"
    regression_pattern: str = "**/*test* **/*spec* **/test_*"

    # Which test types to run
    run_smoke: bool = True
    run_sanity: bool = True
    run_regression: bool = True

    # Agent-driven analysis
    run_agent_analysis: bool = True
    agent_roles: List[str] = field(default_factory=list)

    # Generation options
    generate_tests: bool = False
    generate_patches: bool = False

    # Execution limits
    timeout_seconds: int = 300
    fail_fast: bool = False
    verbose: bool = False

    # QIR options
    generate_qir: bool = True

    @classmethod
    def quick_scan(cls) -> "QESessionConfig":
        """Create a quick scan configuration."""
        config = get_qe_mode_config(QEMode.QUICK_SCAN)
        return cls(
            mode=QEMode.QUICK_SCAN,
            run_smoke=config.run_smoke,
            run_sanity=config.run_sanity,
            run_regression=config.run_regression,
            run_agent_analysis=False,  # Quick scan skips deep analysis
            generate_tests=config.generate_tests,
            generate_patches=config.generate_patches,
            timeout_seconds=config.timeout_seconds,
            fail_fast=config.fail_fast,
        )

    @classmethod
    def deep_qe(cls) -> "QESessionConfig":
        """Create a deep QE configuration."""
        config = get_qe_mode_config(QEMode.DEEP_QE)
        return cls(
            mode=QEMode.DEEP_QE,
            run_smoke=config.run_smoke,
            run_sanity=config.run_sanity,
            run_regression=config.run_regression,
            run_agent_analysis=True,
            generate_tests=config.generate_tests,
            generate_patches=config.generate_patches,
            timeout_seconds=config.timeout_seconds,
            fail_fast=config.fail_fast,
        )


@dataclass
class QESessionResult:
    """Result of a QE session."""

    session_id: str
    mode: QEMode
    status: QEStatus

    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Test results
    smoke_result: Optional[TestSuiteResult] = None
    sanity_result: Optional[TestSuiteResult] = None
    regression_result: Optional[TestSuiteResult] = None

    # Agent analysis results
    findings: List[Dict[str, Any]] = field(default_factory=list)

    # Verified fixes (when suggestions are enabled)
    verified_fixes: List[Dict[str, Any]] = field(default_factory=list)
    allow_suggestions_enabled: bool = False

    # Artifacts
    patches_generated: int = 0
    tests_generated: int = 0
    qr_path: Optional[str] = None

    # Summary
    total_tests: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0

    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Did the QE session pass?"""
        # Success requires completed status, no failed tests, AND at least some tests exist
        return self.status == QEStatus.COMPLETED and self.tests_failed == 0 and self.total_tests > 0

    @property
    def verdict(self) -> str:
        """Human-readable verdict."""
        if self.status == QEStatus.FAILED:
            return "🔴 FAILED - Session error"
        elif self.status == QEStatus.CANCELLED:
            return "⚪ CANCELLED"
        elif self.tests_failed > 0:
            return f"🔴 FAIL - {self.tests_failed} tests failed"
        elif self.total_tests == 0:
            return "🟠 NO TESTS DETECTED - Add tests for proper validation"
        elif len([f for f in self.findings if f.get("severity") == "critical"]) > 0:
            return "🔴 FAIL - Critical issues found"
        elif len([f for f in self.findings if f.get("severity") == "warning"]) > 0:
            return "🟡 CONDITIONAL PASS - Warnings found"
        else:
            return "🟢 PASS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": self.mode.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "verdict": self.verdict,
            "smoke_result": self.smoke_result.to_dict() if self.smoke_result else None,
            "sanity_result": self.sanity_result.to_dict() if self.sanity_result else None,
            "regression_result": self.regression_result.to_dict()
            if self.regression_result
            else None,
            "findings": self.findings,
            "patches_generated": self.patches_generated,
            "tests_generated": self.tests_generated,
            "qr_path": self.qr_path,
            "total_tests": self.total_tests,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "tests_skipped": self.tests_skipped,
            "errors": self.errors,
        }


class QESession:
    """
    Orchestrates a complete QE session.

    A session:
    1. Sets up ephemeral workspace
    2. Runs configured test suites
    3. Validates patches via harness
    4. Optionally runs agent-driven analysis (with guidance prompts)
    5. Generates artifacts
    6. Cleans up (reverts changes, preserves artifacts)

    PRD alignment:
    - Never modifies production code
    - Produces QIRs (Quality Investigation Reports)
    - All fixes are suggested and validated, never auto-applied
    """

    def __init__(
        self,
        project_root: Path,
        config: Optional[QESessionConfig] = None,
    ):
        self.project_root = project_root.resolve()
        self.config = config or QESessionConfig()

        self.workspace = WorkspaceManager(self.project_root)
        self._session_id: Optional[str] = None
        self._result: Optional[QESessionResult] = None
        self._cancelled = False

        # Initialize harness and guidance
        self.harness = PatchHarness(self.project_root)
        guidance_config = load_guidance_config(self.project_root)
        guidance_mode = (
            GuidanceMode.QUICK_SCAN
            if self.config.mode == QEMode.QUICK_SCAN
            else GuidanceMode.DEEP_QE
        )
        self.guidance = QEGuidance(config=guidance_config, mode=guidance_mode)

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def result(self) -> Optional[QESessionResult]:
        return self._result

    async def run(self) -> QESessionResult:
        """
        Run the complete QE session.

        Returns QESessionResult with all findings and artifacts.
        """
        started_at = datetime.now()
        start_time = time.monotonic()

        # Initialize result
        self._result = QESessionResult(
            session_id="",
            mode=self.config.mode,
            status=QEStatus.RUNNING,
            started_at=started_at,
        )

        try:
            # Start workspace session
            workspace_config = WorkspaceConfig(
                mode=WorkspaceQEMode.QUICK_SCAN
                if self.config.mode == QEMode.QUICK_SCAN
                else WorkspaceQEMode.DEEP_QE,
                timeout_seconds=self.config.timeout_seconds,
                generate_tests=self.config.generate_tests,
                generate_patches=self.config.generate_patches,
            )

            self._session_id = self.workspace.start_session(config=workspace_config)
            self._result.session_id = self._session_id

            logger.info(f"Started QE session: {self._session_id}")

            # Run test suites
            await self._run_tests()

            # Run linting if configured
            await self._run_lint_role()

            # Check if cancelled
            if self._cancelled:
                self._result.status = QEStatus.CANCELLED
                return self._finalize_result(start_time)

            # Run agent analysis (if enabled and in deep mode)
            if self.config.run_agent_analysis and self.config.mode == QEMode.DEEP_QE:
                try:
                    if self.config.verbose:
                        print("🤖 Starting AI agent analysis...")
                    await self._run_agent_analysis()
                    if self.config.verbose:
                        print("✅ AI agent analysis completed")
                except Exception as e:
                    if self.config.verbose:
                        print(f"❌ Agent analysis failed: {e}")
                    logger.error(f"Agent analysis failed: {e}")
                    # Continue with session even if agent analysis fails

            # Mark completed
            self._result.status = QEStatus.COMPLETED

        except asyncio.TimeoutError:
            self._result.status = QEStatus.FAILED
            self._result.errors.append(f"Session timed out after {self.config.timeout_seconds}s")
            logger.error(f"QE session timed out: {self._session_id}")

        except Exception as e:
            self._result.status = QEStatus.FAILED
            self._result.errors.append(str(e))
            logger.exception(f"QE session failed: {self._session_id}")

        finally:
            return self._finalize_result(start_time)

    async def _run_tests(self) -> None:
        """Run configured test suites."""
        # Smoke tests
        if self.config.run_smoke:
            logger.info("Running smoke tests...")
            runner = SmokeRunner(
                self.project_root,
                test_pattern=self.config.smoke_pattern,
                timeout_seconds=min(60, self.config.timeout_seconds),
            )
            self._result.smoke_result = await runner.run()
            self._update_test_counts(self._result.smoke_result)

            # Fail fast if smoke tests fail in quick scan mode
            if (
                self.config.fail_fast
                and self._result.smoke_result
                and not self._result.smoke_result.success
            ):
                logger.info("Smoke tests failed, stopping due to fail-fast")
                return

        # Sanity tests
        if self.config.run_sanity:
            logger.info("Running sanity tests...")
            runner = SanityRunner(
                self.project_root,
                test_pattern=self.config.sanity_pattern,
                timeout_seconds=min(120, self.config.timeout_seconds),
            )
            self._result.sanity_result = await runner.run()
            self._update_test_counts(self._result.sanity_result)

            if (
                self.config.fail_fast
                and self._result.sanity_result
                and not self._result.sanity_result.success
            ):
                logger.info("Sanity tests failed, stopping due to fail-fast")
                return

        # Check if any tests were found so far
        total_tests_found = (
            self._result.smoke_result.total_tests if self._result.smoke_result else 0
        ) + (self._result.sanity_result.total_tests if self._result.sanity_result else 0)

        # Fallback: If no smoke/sanity tests found in quick scan, run regression tests
        # This ensures users get immediate feedback even with non-standard test naming
        should_run_regression = self.config.run_regression
        if (
            not should_run_regression
            and self.config.mode == QEMode.QUICK_SCAN
            and total_tests_found == 0
        ):
            logger.info(
                "No smoke/sanity tests found, falling back to regression tests for immediate feedback"
            )
            should_run_regression = True

        if should_run_regression:
            logger.info("Running regression tests...")
            mode_config = get_qe_mode_config(self.config.mode)
            detect_flakes = getattr(mode_config, "detect_flakes", False)
            retry_count = getattr(mode_config, "retry_count", 0)

            runner = RegressionRunner(
                self.project_root,
                test_pattern=self.config.regression_pattern,
                timeout_seconds=self.config.timeout_seconds,
                detect_flakes=detect_flakes,
                retry_count=retry_count,
            )
            self._result.regression_result = await runner.run()
            self._update_test_counts(self._result.regression_result)

    def _update_test_counts(self, suite_result: TestSuiteResult) -> None:
        """Update total test counts from a suite result."""
        self._result.total_tests += suite_result.total_tests
        self._result.tests_passed += suite_result.passed
        self._result.tests_failed += suite_result.failed
        self._result.tests_skipped += suite_result.skipped

    async def _run_lint_role(self) -> None:
        """Run the lint tester role if it is configured in YAML."""
        from superqode.superqe.roles import get_role, RoleType

        try:
            role = get_role("lint_tester", self.project_root, allow_suggestions=False)
        except ValueError:
            return

        if role.role_type != RoleType.EXECUTION:
            return

        result = await role.run()
        self._result.findings.extend(result.findings)
        self._result.errors.extend(result.errors)

    async def _run_agent_analysis(self) -> None:
        """Run agent-driven QE analysis with specialized QE agents."""
        logger.info("Running AI-powered agent analysis...")

        if not self.config.agent_roles:
            logger.info("No agent roles configured, skipping agent analysis")
            return

        # Early validation - check if OpenCode is available
        import shutil

        if not shutil.which("opencode"):
            logger.warning("OpenCode not found - agent analysis will use fallback mode")
            # Continue with fallback findings instead of failing

        for role_name in self.config.agent_roles:
            if self._cancelled:
                logger.info("Analysis cancelled by user")
                break

            try:
                # Map QE role name to OpenCode agent name
                from .acp_runner import get_opencode_agent_for_role

                agent_name = get_opencode_agent_for_role(role_name)
                logger.info(f"Running QE role '{role_name}' using agent '{agent_name}'")

                # Run real ACP agent analysis using OpenCode
                try:
                    from .acp_runner import ACPQERunner, ACPRunnerConfig, get_qe_prompt

                    # Create ACP runner configuration
                    acp_config = ACPRunnerConfig(
                        agent_command="opencode run --format json",  # Use consistent command
                        model=None,  # Will use default from OpenCode
                        timeout_seconds=min(180, self.config.timeout_seconds),  # Shorter for QE
                        verbose=self.config.verbose,
                        allow_suggestions=self.config.generate_patches,
                    )

                    # Create and run ACP agent
                    runner = ACPQERunner(self.project_root, acp_config)

                    # Get the appropriate QE prompt for this role
                    prompt = get_qe_prompt(role_name, acp_config.allow_suggestions)

                    # Run the actual AI analysis
                    result = await runner.run(prompt, role_name)

                    # Convert ACP findings to session format
                    sample_findings = []
                    for acp_finding in result.findings:
                        finding_dict = {
                            "id": acp_finding.id,
                            "severity": acp_finding.severity,
                            "title": acp_finding.title,
                            "description": acp_finding.description,
                            "file_path": acp_finding.file_path,
                            "line_number": acp_finding.line_number,
                            "evidence": acp_finding.evidence,
                            "suggested_fix": acp_finding.suggested_fix,
                            "confidence": acp_finding.confidence,
                            "category": acp_finding.category,
                            "agent": role_name,
                            "work_log": self._extract_work_log_from_acp_output(
                                result.agent_output, result.tool_calls
                            ),
                            "tool_calls": [
                                tc.get("title", tc.get("id", "unknown")) for tc in result.tool_calls
                            ],
                        }
                        sample_findings.append(finding_dict)

                    # If no findings extracted, create a summary finding
                    if not sample_findings:
                        sample_findings = [
                            {
                                "id": f"{role_name}-summary",
                                "severity": "info",
                                "title": f"🤖 AI {role_name.replace('-', ' ').title()} Analysis Complete",
                                "description": f"OpenCode AI agent completed {role_name} analysis. The agent processed the codebase and provided analysis insights.",
                                "file_path": None,
                                "line_number": None,
                                "evidence": f"Agent output: {result.agent_output[:200]}..."
                                if result.agent_output
                                else "Analysis completed without specific findings",
                                "suggested_fix": None,
                                "confidence": 0.8,
                                "category": role_name,
                                "agent": role_name,
                                "work_log": self._extract_work_log_from_acp_output(
                                    result.agent_output, result.tool_calls
                                ),
                                "tool_calls": [
                                    tc.get("title", tc.get("id", "unknown"))
                                    for tc in result.tool_calls
                                ],
                            }
                        ]

                    if result.errors:
                        logger.warning(f"ACP agent errors: {result.errors}")

                except Exception as e:
                    logger.error(f"ACP agent analysis failed: {e}")
                    # Fallback to basic analysis if ACP fails
                    sample_findings = [
                        {
                            "id": f"{role_name}-fallback",
                            "severity": "info",
                            "title": f"🤖 {role_name.replace('-', ' ').title()} Analysis (ACP Unavailable)",
                            "description": f"AI-powered {role_name} analysis is available but requires OpenCode to be installed and configured.",
                            "file_path": None,
                            "line_number": None,
                            "evidence": f"Install OpenCode to enable real AI analysis: npm i -g opencode-ai",
                            "suggested_fix": None,
                            "confidence": 0.5,
                            "category": role_name,
                            "agent": role_name,
                            "work_log": ["ACP agent connection attempted but failed"],
                            "tool_calls": [],
                        }
                    ]

                # Add sample findings to results
                self._result.findings.extend(sample_findings)

                # Also add findings to workspace for QIR generation
                # Add findings to workspace for QIR generation
                for finding in sample_findings:
                    self.workspace.add_finding(
                        severity=finding["severity"],
                        title=finding["title"],
                        description=finding["description"],
                        file_path=finding.get("file_path"),
                        line_number=finding.get("line_number"),
                        evidence=finding.get("evidence", ""),
                        suggested_fix=finding.get("suggested_fix", ""),
                        work_log=finding.get("work_log"),
                        tool_calls=finding.get("tool_calls"),
                    )

                logger.info(
                    f"QE agent {role_name} completed: {len(sample_findings)} AI-powered findings generated"
                )

            except Exception as e:
                logger.error(f"QE agent {role_name} failed: {e}")
                # Continue with other agents even if one fails
                continue

        logger.info(f"Agent analysis complete: {len(self._result.findings)} total findings")

    def _extract_work_log_from_acp_output(
        self, agent_output: str, tool_calls: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract work log from ACP agent output and tool calls."""
        work_log = []

        # Add initialization
        work_log.append("🤖 ACP Agent initialized and connected to OpenCode")

        # Add tool calls as work steps
        for tool_call in tool_calls:
            title = tool_call.get("title", tool_call.get("id", "unknown"))
            status = tool_call.get("status", "executed")
            work_log.append(f"🔧 Tool Call: {title} - {status}")

        # Extract reasoning and analysis steps from agent output
        lines = agent_output.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for reasoning patterns
            if any(
                keyword in line.lower()
                for keyword in [
                    "analyzing",
                    "checking",
                    "reviewing",
                    "examining",
                    "scanning",
                    "parsing",
                ]
            ):
                work_log.append(f"🧠 Reasoning: {line}")

            # Look for findings
            elif any(
                keyword in line.lower()
                for keyword in ["found", "detected", "identified", "issue", "problem", "warning"]
            ):
                work_log.append(f"⚠️ Analysis: {line}")

            # Look for completion
            elif any(
                keyword in line.lower() for keyword in ["complete", "finished", "done", "summary"]
            ):
                work_log.append(f"📊 Analysis: {line}")
                break

        # Add completion if we have findings
        if work_log:
            work_log.append("✅ ACP Agent analysis completed")

        return work_log

    async def validate_patches(
        self,
        changes: Dict[Path, str],
    ) -> HarnessResult:
        """
        Validate patches before including in QIR.

        This is called automatically for any suggested fixes.
        """
        logger.info(f"Validating {len(changes)} file changes via harness...")
        result = await self.harness.validate_changes(changes)

        if result.success:
            logger.info(f"Harness validation passed ({result.files_validated} files)")
        else:
            logger.warning(
                f"Harness validation found {result.error_count} errors, "
                f"{result.warning_count} warnings"
            )

        return result

    def _finalize_result(self, start_time: float) -> QESessionResult:
        """Finalize the session result and cleanup."""
        ended_at = datetime.now()
        duration = time.monotonic() - start_time

        self._result.ended_at = ended_at
        self._result.duration_seconds = duration

        # End workspace session (reverts changes, generates QIR)
        try:
            ws_result = self.workspace.end_session(generate_qir=self.config.generate_qir)
            self._result.patches_generated = ws_result.patches_generated
            self._result.tests_generated = ws_result.tests_generated
            self._result.errors.extend(ws_result.errors)

            # Set QIR path if generated
            if ws_result.qir_generated:
                qir_artifacts = self.workspace.artifacts.list_qirs()
                if qir_artifacts:
                    # Get the most recent QIR
                    latest_qir = max(qir_artifacts, key=lambda a: a.created_at)
                    self._result.qr_path = str(latest_qir.path)

            # Merge agent findings with workspace findings
            workspace_findings = [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "title": f.title,
                    "description": f.description,
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                }
                for f in self.workspace.get_findings()
            ]

            # Combine agent findings (added during analysis) with workspace findings
            self._result.findings.extend(workspace_findings)
        except Exception as e:
            self._result.errors.append(f"Cleanup failed: {e}")
            logger.error(f"Failed to finalize session: {e}")

        logger.info(
            f"QE session completed: {self._result.session_id} - "
            f"{self._result.verdict} ({duration:.1f}s)"
        )

        return self._result

    def cancel(self) -> None:
        """Cancel the running session."""
        self._cancelled = True
        logger.info(f"QE session cancellation requested: {self._session_id}")
