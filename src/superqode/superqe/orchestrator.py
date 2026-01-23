"""
QE Orchestrator - High-level interface for running QE sessions.

Provides:
- Simple API for CLI and CI integration
- Pre-configured quick scan and deep QE modes
- Role-based execution (--role flag)
- Noise controls integration
- Output formatting for different contexts
"""

import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import logging
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from .session import QESession, QESessionConfig, QESessionResult
from .noise import NoiseFilter, NoiseConfig, load_noise_config, Finding as NoiseFinding
from .roles import get_role, list_roles, RoleResult, RoleType
from .verifier import FixVerifier, FixVerifierConfig, VerificationResult, VerificationStatus
from superqode.execution.modes import QEMode
from superqode.enterprise import require_enterprise
from superqode.workspace import prepare_qe_worktree, GitWorktreeManager, WorktreeInfo

logger = logging.getLogger(__name__)
console = Console()


class SuggestionMode:
    """
    Manages the suggestion workflow when allow_suggestions is enabled.

    The workflow:
    1. Agent finds bug and suggests fix
    2. Fix is applied in sandbox
    3. Tests run to verify fix
    4. Results compared (before/after)
    5. Evidence collected for QIR
    6. Changes reverted (always)
    7. Patches preserved for user decision
    """

    def __init__(
        self,
        project_root: Path,
        verifier_config: Optional[FixVerifierConfig] = None,
    ):
        self.project_root = project_root
        self.verifier = FixVerifier(project_root, verifier_config)
        self.verified_fixes: List[VerificationResult] = []

    def verify_finding_fix(
        self,
        finding: Dict[str, Any],
        apply_fix_fn: Optional[Callable[[str], bool]] = None,
    ) -> Optional[VerificationResult]:
        """
        Verify a suggested fix for a finding.

        Args:
            finding: Finding dict with suggested_fix
            apply_fix_fn: Optional function to apply the fix

        Returns:
            VerificationResult if fix was verified, None if no fix available
        """
        suggested_fix = finding.get("suggested_fix")
        if not suggested_fix:
            return None

        result = self.verifier.verify_fix(
            finding_id=finding.get("id", "unknown"),
            patch_content=suggested_fix,
            target_file=Path(finding.get("file_path", "")) if finding.get("file_path") else None,
            apply_patch_fn=apply_fix_fn,
        )

        self.verified_fixes.append(result)
        return result

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all verified fixes."""
        return {
            "total": len(self.verified_fixes),
            "verified": sum(
                1 for f in self.verified_fixes if f.status == VerificationStatus.PASSED
            ),
            "improvements": sum(1 for f in self.verified_fixes if f.is_improvement),
            "failed": sum(1 for f in self.verified_fixes if f.status == VerificationStatus.FAILED),
        }


class QEOrchestrator:
    """
    High-level orchestrator for QE sessions.

    Usage:
        orchestrator = QEOrchestrator(Path("."))

        # Quick scan (pre-commit, fast CI)
        result = await orchestrator.quick_scan()

        # Deep QE (pre-release, nightly CI)
        result = await orchestrator.deep_qe()

        # Run specific roles
        result = await orchestrator.run_roles(["api_tester", "security_tester"])
    """

    def __init__(
        self,
        project_root: Path,
        verbose: bool = False,
        output_format: str = "rich",  # "rich", "json", "jsonl", "plain"
        use_worktree: bool = False,
        allow_suggestions: bool = False,  # Enable suggestion workflow
    ):
        self.project_root = project_root.resolve()
        self.verbose = verbose
        self.output_format = output_format
        self.use_worktree = use_worktree
        self.allow_suggestions = allow_suggestions
        self._current_session: Optional[QESession] = None

        # Load noise configuration
        self.noise_config = load_noise_config(self.project_root)
        self.noise_filter = NoiseFilter(self.noise_config)

        # Suggestion mode (initialized when allow_suggestions is True)
        self._suggestion_mode: Optional[SuggestionMode] = None
        if allow_suggestions:
            if require_enterprise("Fix suggestions and verification"):
                self._suggestion_mode = SuggestionMode(self.project_root)
            else:
                self.allow_suggestions = False

    async def quick_scan(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> QESessionResult:
        """
        Run a quick scan QE session.

        - Time-boxed (60 seconds default)
        - Shallow exploration
        - High-risk paths only
        - Minimal QIR

        Best for: Pre-commit, developer laptop, fast CI feedback
        """
        config = QESessionConfig.quick_scan()
        return await self._run_session(config, on_progress)

    async def deep_qe(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> QESessionResult:
        """
        Run a deep QE session.

        - Full sandbox
        - Destructive testing allowed
        - Failure simulation hooks
        - Full Investigation Reports

        Best for: Pre-release, nightly CI, compliance evidence
        """
        config = QESessionConfig.deep_qe()
        config.verbose = self.verbose  # Pass verbose flag from orchestrator

        # Override agent roles with YAML configuration if specified
        yaml_agent_roles = self._get_deep_analysis_roles_from_yaml()
        if yaml_agent_roles:
            config.agent_roles = yaml_agent_roles

        return await self._run_session(config, on_progress)

    def _get_deep_analysis_roles_from_yaml(self) -> Optional[List[str]]:
        """
        Get deep analysis roles from YAML configuration.

        Returns:
            List of role names if configured, None to use defaults.
            Empty list means use all enabled QE roles that have implementations.
        """
        try:
            from superqode.config import load_config
            from superqode.superqe.roles import ROLE_REGISTRY, load_role_config_from_yaml, RoleType

            config = load_config()

            if (
                hasattr(config, "team")
                and config.team
                and hasattr(config.team, "modes")
                and config.team.modes
                and "qe" in config.team.modes
            ):
                qe_mode = config.team.modes["qe"]
                implemented_roles = set(ROLE_REGISTRY.keys())
                execution_roles = {
                    name
                    for name in implemented_roles
                    if (load_role_config_from_yaml(name, self.project_root) or {}).get("role_type")
                    == RoleType.EXECUTION.value
                }

                if hasattr(qe_mode, "deep_analysis_roles") and qe_mode.deep_analysis_roles:
                    # Return configured roles that have implementations
                    configured_roles = [
                        role
                        for role in qe_mode.deep_analysis_roles
                        if role in implemented_roles and role not in execution_roles
                    ]
                    return configured_roles if configured_roles else None
                elif hasattr(qe_mode, "roles") and qe_mode.roles:
                    # If deep_analysis_roles is empty but roles exist,
                    # return all enabled QE roles that have implementations
                    enabled_implemented_roles = []
                    for role_name, role_config in qe_mode.roles.items():
                        if (
                            getattr(role_config, "enabled", True)
                            and role_name in implemented_roles
                            and role_name not in execution_roles
                        ):
                            enabled_implemented_roles.append(role_name)
                    return enabled_implemented_roles if enabled_implemented_roles else None

        except Exception as e:
            logger.debug(f"Failed to load deep analysis roles from YAML: {e}")

        return None  # Use hardcoded defaults

    async def run(
        self,
        config: Optional[QESessionConfig] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> QESessionResult:
        """Run a QE session with custom configuration."""
        config = config or QESessionConfig()
        config.verbose = self.verbose  # Pass verbose flag from orchestrator
        return await self._run_session(config, on_progress)

    async def run_roles(
        self,
        role_names: List[str],
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> QESessionResult:
        """
        Run specific QE roles.

        Args:
            role_names: List of role names (e.g., ["api_tester", "security_tester"])
            on_progress: Optional progress callback

        Returns:
            Combined QESessionResult from all roles
        """
        from datetime import datetime
        import time

        started_at = datetime.now()
        start_time = time.monotonic()

        all_findings = []
        all_errors = []
        total_tests = 0
        tests_passed = 0
        tests_failed = 0
        tests_skipped = 0
        verified_fixes = []

        # Run each role
        total_roles = len(role_names)
        for idx, role_name in enumerate(role_names, 1):
            try:
                role_start_time = time.monotonic()
                if self.output_format == "rich":
                    console.print(f"[cyan]Running role: {role_name} ({idx}/{total_roles})[/cyan]")
                elif self.verbose:
                    print(f"Running role: {role_name} ({idx}/{total_roles})")

                role = get_role(
                    role_name,
                    self.project_root,
                    allow_suggestions=self.allow_suggestions,
                )
                result = await role.run()

                role_duration = time.monotonic() - role_start_time
                if self.output_format == "rich":
                    console.print(f"[dim]✓ {role_name} completed in {role_duration:.1f}s[/dim]")
                elif self.verbose:
                    print(f"✓ {role_name} completed in {role_duration:.1f}s")

                # Aggregate results
                if result.role_type == RoleType.EXECUTION:
                    total_tests += result.tests_run
                    tests_passed += result.tests_passed
                    tests_failed += result.tests_failed
                    tests_skipped += result.tests_skipped

                # Convert findings to common format
                for finding in result.findings:
                    all_findings.append(finding)

                all_errors.extend(result.errors)

            except Exception as e:
                all_errors.append(f"Role {role_name} failed: {e}")
                logger.exception(f"Role {role_name} failed")

        # Apply noise filter to findings
        filtered_findings = self._apply_noise_filter(all_findings)

        # Process suggestions if enabled
        if self.allow_suggestions and self._suggestion_mode:
            verified_fixes = await self._process_suggestions(filtered_findings)

        # Build result
        duration = time.monotonic() - start_time
        ended_at = datetime.now()

        # Create a synthetic result
        from .session import QESessionResult, QEStatus

        result = QESessionResult(
            session_id=f"roles-{started_at.strftime('%Y%m%d-%H%M%S')}",
            mode=QEMode.QUICK_SCAN,  # Default
            status=QEStatus.COMPLETED if not all_errors else QEStatus.FAILED,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            findings=filtered_findings,
            total_tests=total_tests,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            tests_skipped=tests_skipped,
            errors=all_errors,
            verified_fixes=verified_fixes,
            allow_suggestions_enabled=self.allow_suggestions,
        )

        if self.output_format == "rich":
            self._display_result(result)

        return result

    async def _process_suggestions(
        self,
        findings: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Process suggestions for findings with suggested_fix.

        When allow_suggestions is enabled, this:
        1. Finds all findings with suggested fixes
        2. Verifies each fix in sandbox
        3. Collects before/after evidence
        4. Returns verification results

        All changes are automatically reverted by the workspace manager.
        """
        if not self._suggestion_mode:
            return []

        verified = []

        for finding in findings:
            if not finding.get("suggested_fix"):
                continue

            if self.verbose and self.output_format == "rich":
                console.print(
                    f"[yellow]Verifying fix for: {finding.get('title', 'unknown')}[/yellow]"
                )

            result = self._suggestion_mode.verify_finding_fix(finding)
            if result:
                verified.append(
                    {
                        "finding_id": finding.get("id"),
                        "finding_title": finding.get("title"),
                        "status": result.status.value,
                        "is_improvement": result.is_improvement,
                        "confidence": result.confidence_score,
                        "tests_fixed": result.tests_fixed,
                        "tests_broken": result.tests_broken,
                        "evidence": result.evidence,
                    }
                )

        # Log summary
        if self.verbose and self.output_format == "rich" and verified:
            summary = self._suggestion_mode.get_summary()
            console.print(
                f"[green]Suggestion verification complete: "
                f"{summary['verified']}/{summary['total']} verified, "
                f"{summary['improvements']} improvements[/green]"
            )

        return verified

    def _apply_noise_filter(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply noise filter to findings."""
        if not findings:
            return []

        # Convert dict findings to Finding objects
        noise_findings = []
        for f in findings:
            nf = NoiseFinding(
                id=f.get("id", ""),
                severity=f.get("severity", "info"),
                title=f.get("title", ""),
                description=f.get("description", ""),
                file_path=f.get("file_path"),
                line_number=f.get("line_number"),
                evidence=f.get("evidence"),
                suggested_fix=f.get("suggested_fix"),
                confidence=f.get("confidence", 1.0),
                category=f.get("category", ""),
                rule_id=f.get("rule_id"),
            )
            noise_findings.append(nf)

        # Apply filter
        filtered = self.noise_filter.apply(noise_findings)

        # Convert back to dicts
        return [f.to_dict() for f in filtered]

    async def _run_session(
        self,
        config: QESessionConfig,
        on_progress: Optional[Callable[[str], None]],
    ) -> QESessionResult:
        """Internal method to run a session with progress reporting."""
        worktree_info: Optional[WorktreeInfo] = None
        session_root = self.project_root

        if self.use_worktree:
            try:
                session_id = f"qe-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                worktree_info = await prepare_qe_worktree(self.project_root, session_id)
                session_root = worktree_info.path

                # Keep artifacts in the original repo by linking .superqode into the worktree.
                original_superqode = self.project_root / ".superqode"
                original_superqode.mkdir(parents=True, exist_ok=True)
                worktree_superqode = session_root / ".superqode"
                if worktree_superqode.exists() or worktree_superqode.is_symlink():
                    if worktree_superqode.is_dir() and not worktree_superqode.is_symlink():
                        shutil.rmtree(worktree_superqode)
                    else:
                        worktree_superqode.unlink()
                os.symlink(original_superqode, worktree_superqode, target_is_directory=True)
            except Exception as exc:
                if worktree_info is not None:
                    manager = GitWorktreeManager(self.project_root)
                    try:
                        await manager.remove_worktree(worktree_info, force=True)
                    except Exception as cleanup_exc:
                        logger.warning(
                            "Failed to clean up worktree %s: %s",
                            worktree_info.path,
                            cleanup_exc,
                        )
                logger.warning(
                    "Worktree isolation unavailable (%s). Falling back to snapshot isolation.", exc
                )
                session_root = self.project_root
                worktree_info = None

        session = QESession(session_root, config)
        self._current_session = session

        try:
            if self.output_format == "rich":
                result = await self._run_with_rich_progress(session)
            else:
                result = await session.run()
        finally:
            if worktree_info is not None:
                manager = GitWorktreeManager(self.project_root)
                try:
                    await manager.remove_worktree(worktree_info, force=True)
                except Exception as exc:
                    logger.warning("Failed to clean up worktree %s: %s", worktree_info.path, exc)

        self._run_superopt_hook(result)
        return result

    def _run_superopt_hook(self, result: QESessionResult) -> None:
        """Run SuperOpt command hook if enabled."""
        from superqode.optimization import load_optimize_config

        config = load_optimize_config(self.project_root)
        if not config.enabled:
            return

        artifacts_dir = self.project_root / ".superqode" / "qe-artifacts" / "superopt"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        trace_path = artifacts_dir / f"trace-{result.session_id}.json"
        output_path = artifacts_dir / "env.json"
        trace_path.write_text(json.dumps(result.to_dict(), indent=2))

        if config.command:
            command = config.command
        else:
            command = (
                "python -m superqode.integrations.superopt_runner "
                f"--trace {trace_path} --out {output_path} --project-root {self.project_root}"
            )

        command = command.format(
            trace_path=trace_path,
            output_path=output_path,
            project_root=self.project_root,
            session_id=result.session_id,
        )

        try:
            subprocess.run(
                command,
                cwd=self.project_root,
                shell=True,
                check=True,
                timeout=config.timeout_seconds,
            )
        except subprocess.SubprocessError as exc:
            logger.warning("SuperOpt hook failed: %s", exc)

    async def _run_with_rich_progress(self, session: QESession) -> QESessionResult:
        """Run session with rich console progress output."""
        mode_name = "Quick Scan" if session.config.mode == QEMode.QUICK_SCAN else "Deep QE"

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"[cyan]SuperQode {mode_name}...", total=None)

            result = await session.run()

            progress.update(task, completed=True)

        # Display results
        self._display_result(result)

        return result

    def _display_result(self, result: QESessionResult) -> None:
        """Display session result in rich format."""
        # Header
        mode_emoji = "⚡" if result.mode == QEMode.QUICK_SCAN else "🔬"
        mode_name = "Quick Scan" if result.mode == QEMode.QUICK_SCAN else "Deep QE"

        console.print()
        console.print(
            Panel(
                Text(
                    f"{mode_emoji} SuperQode {mode_name} Complete", justify="center", style="bold"
                ),
                subtitle=f"Session: {result.session_id}",
            )
        )
        console.print()

        # Verdict
        console.print(f"[bold]Verdict:[/bold] {result.verdict}")
        console.print(f"[dim]Duration: {result.duration_seconds:.1f}s[/dim]")
        console.print()

        # Test Summary Table
        table = Table(title="Test Results", show_header=True, header_style="bold")
        table.add_column("Suite", style="cyan")
        table.add_column("Total", justify="right")
        table.add_column("Passed", justify="right", style="green")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Skipped", justify="right", style="yellow")
        table.add_column("Status", justify="center")

        for name, suite_result in [
            ("Smoke", result.smoke_result),
            ("Sanity", result.sanity_result),
            ("Regression", result.regression_result),
        ]:
            if suite_result:
                status = "✅" if suite_result.success else "❌"
                table.add_row(
                    name,
                    str(suite_result.total_tests),
                    str(suite_result.passed),
                    str(suite_result.failed),
                    str(suite_result.skipped),
                    status,
                )
            else:
                table.add_row(name, "-", "-", "-", "-", "⏭️ Skipped")

        # Total row
        table.add_section()
        total_status = "✅" if result.tests_failed == 0 else "❌"
        table.add_row(
            "[bold]Total[/bold]",
            f"[bold]{result.total_tests}[/bold]",
            f"[bold green]{result.tests_passed}[/bold green]",
            f"[bold red]{result.tests_failed}[/bold red]",
            f"[bold yellow]{result.tests_skipped}[/bold yellow]",
            total_status,
        )

        console.print(table)
        console.print()

        # Findings
        if result.findings:
            console.print("[bold]AI Analysis Findings:[/bold]")
            for finding in result.findings:
                title = self._format_finding_text(finding.get("title", "Unknown"), 120)
                description = self._format_finding_text(finding.get("description", ""), 180)
                severity_style = {
                    "critical": "bold red",
                    "warning": "yellow",
                    "info": "blue",
                }.get(finding.get("severity", "info"), "white")

                console.print(
                    f"  [{severity_style}]{finding.get('severity', '').upper()}[/{severity_style}]: "
                    f"{title}"
                )
                if description and description != title:
                    console.print(f"    [dim]{description}[/dim]")
                if finding.get("file_path"):
                    console.print(
                        f"    [dim]Location: {finding['file_path']}"
                        f"{':' + str(finding['line_number']) if finding.get('line_number') else ''}[/dim]"
                    )

                # Show tool calls if available
                if finding.get("tool_calls"):
                    console.print(
                        f"    [dim]🔧 Tools Used: {', '.join(finding['tool_calls'])}[/dim]"
                    )

                # Show work log summary if available
                if finding.get("work_log") and len(finding["work_log"]) > 0:
                    console.print(
                        f"    [dim]📋 Agent performed {len(finding['work_log'])} analysis steps[/dim]"
                    )
            console.print()

        # Artifacts
        if result.patches_generated > 0 or result.tests_generated > 0:
            console.print("[bold]Generated Artifacts:[/bold]")
            if result.patches_generated > 0:
                console.print(f"  📝 Patches: {result.patches_generated}")
            if result.tests_generated > 0:
                console.print(f"  🧪 Tests: {result.tests_generated}")
            console.print()

        # QIR location
        if result.qr_path:
            console.print("[bold green]📋 Quality Report (QR) generated![/bold green]")
            console.print(f"[green]📄 View detailed findings: {result.qr_path}[/green]")
            console.print(
                f"[dim]💡 QR contains evidence-based analysis with {len(result.findings)} findings[/dim]"
            )
            console.print(f"[dim]🔍 Agent work logs available in the QR for transparency[/dim]")
        elif len(result.findings) > 0:
            console.print("[yellow]⚠️  Findings detected but QR generation failed[/yellow]")
            console.print("[dim]Check .superqode/qe-artifacts/qr/ for reports[/dim]")

        # Errors
        if result.errors:
            console.print("[bold red]Errors:[/bold red]")
            for error in result.errors:
                console.print(f"  ⚠️ {error}")
            console.print()

    def cancel(self) -> None:
        """Cancel the currently running session."""
        if self._current_session:
            self._current_session.cancel()

    def export_json(self, result: QESessionResult) -> str:
        """Export result as JSON string."""
        return json.dumps(result.to_dict(), indent=2)

    @staticmethod
    def _format_finding_text(text: str, max_len: int) -> str:
        """Clean and truncate finding text for console output."""
        if not text:
            return ""
        cleaned = text.replace("\\n", " ").replace("\n", " ").replace("\r", " ")
        cleaned = " ".join(cleaned.split())
        if cleaned.lower().startswith("description:"):
            cleaned = cleaned[len("description:") :].strip()
        return (cleaned[: max_len - 1] + "…") if len(cleaned) > max_len else cleaned

    def export_junit(self, result: QESessionResult) -> str:
        """Export result as JUnit XML for CI integration."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<testsuites name="SuperQode QE" tests="{result.total_tests}" '
            f'failures="{result.tests_failed}" errors="0" '
            f'time="{result.duration_seconds:.3f}">',
        ]

        for name, suite_result in [
            ("smoke", result.smoke_result),
            ("sanity", result.sanity_result),
            ("regression", result.regression_result),
        ]:
            if suite_result:
                lines.append(
                    f'  <testsuite name="{name}" tests="{suite_result.total_tests}" '
                    f'failures="{suite_result.failed}" errors="{suite_result.errors}" '
                    f'skipped="{suite_result.skipped}" time="{suite_result.duration_seconds:.3f}">'
                )

                for test in suite_result.tests:
                    lines.append(
                        f'    <testcase name="{test.name}" time="{test.duration_seconds:.3f}"'
                    )

                    if test.status.value == "failed":
                        lines.append(">")
                        error_msg = test.error_message or "Test failed"
                        lines.append(
                            f'      <failure message="{error_msg[:100]}">{error_msg}</failure>'
                        )
                        lines.append("    </testcase>")
                    elif test.status.value == "skipped":
                        lines.append(">")
                        lines.append("      <skipped/>")
                        lines.append("    </testcase>")
                    else:
                        lines.append("/>")

                lines.append("  </testsuite>")

        lines.append("</testsuites>")
        return "\n".join(lines)


# Convenience functions for CLI
async def run_quick_scan(
    project_root: Path,
    verbose: bool = False,
) -> QESessionResult:
    """Run a quick scan QE session."""
    orchestrator = QEOrchestrator(project_root, verbose=verbose)
    return await orchestrator.quick_scan()


async def run_deep_qe(
    project_root: Path,
    verbose: bool = False,
) -> QESessionResult:
    """Run a deep QE session."""
    orchestrator = QEOrchestrator(project_root, verbose=verbose)
    return await orchestrator.deep_qe()
