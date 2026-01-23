"""
Workspace Manager - Ephemeral-Edit Workspace with Immutable Repo Guarantee.

The core orchestrator for SuperQode's QE sessions:
- Agents can freely modify/generate code
- All changes are tracked and reverted after session
- Artifacts (patches, tests, QIRs) are preserved
- Git operations are blocked

Usage:
    workspace = WorkspaceManager(project_root)

    async with workspace.qe_session("my-session") as session:
        # Agents can now modify files freely
        # Changes tracked, git blocked
        await run_qe_agents()

    # Session ends: all changes reverted, artifacts preserved
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import json
import logging

from .snapshot import SnapshotManager
from .artifacts import ArtifactManager, ArtifactType, Artifact
from .git_guard import GitGuard, GitOperationBlocked, check_git_command

logger = logging.getLogger(__name__)


class WorkspaceState(Enum):
    """State of the workspace."""

    IDLE = "idle"  # No active session
    ACTIVE = "active"  # QE session in progress
    REVERTING = "reverting"  # Reverting changes
    PRESERVING = "preserving"  # Preserving artifacts
    ERROR = "error"  # Error state


class QEMode(Enum):
    """QE execution mode."""

    QUICK_SCAN = "quick_scan"  # Fast, shallow, time-boxed
    DEEP_QE = "deep_qe"  # Full exploration, destructive allowed


@dataclass
class QESessionConfig:
    """Configuration for a QE session."""

    mode: QEMode = QEMode.QUICK_SCAN
    timeout_seconds: int = 60  # Quick scan default
    destructive_allowed: bool = False  # Can run stress tests etc.
    generate_tests: bool = True  # Generate new tests
    generate_patches: bool = True  # Generate fix suggestions
    roles: List[str] = field(default_factory=list)  # QE roles to run


@dataclass
class QESessionResult:
    """Result of a QE session."""

    session_id: str
    mode: QEMode
    started_at: datetime
    ended_at: datetime
    duration_seconds: float

    # Changes tracking
    files_modified: List[str]
    files_created: List[str]
    files_deleted: List[str]

    # Artifacts
    patches_generated: int
    tests_generated: int
    qir_generated: bool
    artifact_summary: Dict[str, int]

    # Findings
    findings_count: int
    critical_count: int
    warning_count: int

    # Status
    reverted: bool
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "session_id": self.session_id,
            "mode": self.mode.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "files_modified": self.files_modified,
            "files_created": self.files_created,
            "files_deleted": self.files_deleted,
            "patches_generated": self.patches_generated,
            "tests_generated": self.tests_generated,
            "qir_generated": self.qir_generated,
            "artifact_summary": self.artifact_summary,
            "findings_count": self.findings_count,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "reverted": self.reverted,
            "errors": self.errors,
        }


@dataclass
class Finding:
    """A finding from QE analysis."""

    id: str
    severity: str  # "critical", "warning", "info"
    title: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[str] = None
    suggested_fix: Optional[str] = None
    patch_artifact_id: Optional[str] = None
    work_log: Optional[List[str]] = None
    tool_calls: Optional[List[str]] = None


class WorkspaceManager:
    """
    Manages the ephemeral-edit workspace for QE sessions.

    Guarantees:
    - ❌ No commits
    - ❌ No pushes
    - ❌ No git operations (branching, merges, tagging)
    - ✅ All changes reverted after session
    - ✅ Artifacts preserved in .superqode/qe-artifacts/
    """

    SUPERQODE_DIR = ".superqode"
    STATE_FILE = "workspace-state.json"

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.superqode_dir = self.project_root / self.SUPERQODE_DIR

        # Components
        self.snapshot = SnapshotManager(self.project_root)
        self.artifacts = ArtifactManager(self.project_root)
        self.git_guard = GitGuard(enabled=True)

        # Session state
        self._state = WorkspaceState.IDLE
        self._session_id: Optional[str] = None
        self._session_start: Optional[datetime] = None
        self._session_config: Optional[QESessionConfig] = None
        self._findings: List[Finding] = []
        self._finding_counter = 0

    @property
    def state(self) -> WorkspaceState:
        """Current workspace state."""
        return self._state

    @property
    def session_id(self) -> Optional[str]:
        """Current session ID if active."""
        return self._session_id

    @property
    def is_active(self) -> bool:
        """Check if a QE session is active."""
        return self._state == WorkspaceState.ACTIVE

    def initialize(self) -> None:
        """Initialize the .superqode directory structure."""
        self.superqode_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        for subdir in ["qe-artifacts", "config", "history", "temp"]:
            (self.superqode_dir / subdir).mkdir(exist_ok=True)

        # Create .gitignore to exclude temp files
        gitignore_path = self.superqode_dir / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text("# SuperQode temporary files\ntemp/\n*.tmp\n*.log\n")

    def start_session(
        self,
        session_id: Optional[str] = None,
        config: Optional[QESessionConfig] = None,
    ) -> str:
        """
        Start a new QE session.

        Args:
            session_id: Optional session ID (auto-generated if not provided)
            config: Session configuration

        Returns:
            Session ID
        """
        if self._state != WorkspaceState.IDLE:
            raise RuntimeError(f"Cannot start session: workspace in {self._state.value} state")

        # Initialize directories
        self.initialize()

        # Generate session ID
        self._session_id = session_id or f"qe-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self._session_start = datetime.now()
        self._session_config = config or QESessionConfig()
        self._findings.clear()
        self._finding_counter = 0

        # Start snapshot tracking
        self.snapshot.start_session(self._session_id)

        # Initialize artifacts
        self.artifacts.initialize(self._session_id)

        # Clear git guard attempts
        self.git_guard.clear_blocked_attempts()

        # Update state
        self._state = WorkspaceState.ACTIVE
        self._save_state()

        logger.info(f"Started QE session: {self._session_id}")

        return self._session_id

    def end_session(self, generate_qir: bool = True) -> QESessionResult:
        """
        End the current QE session.

        - Generates QIR if requested
        - Reverts all file changes
        - Preserves artifacts

        Returns:
            QESessionResult with session summary
        """
        if self._state != WorkspaceState.ACTIVE:
            raise RuntimeError(f"No active session to end (state: {self._state.value})")

        session_end = datetime.now()
        errors = []

        # Get changes before reverting
        changes = self.snapshot.get_changes_summary()

        # Generate QIR if requested
        qir_generated = False
        if generate_qir:
            try:
                self._state = WorkspaceState.PRESERVING
                self._generate_qir()
                qir_generated = True
            except Exception as e:
                errors.append(f"QIR generation failed: {e}")
                logger.error(f"QIR generation failed: {e}")

        # Revert all changes
        self._state = WorkspaceState.REVERTING
        try:
            revert_result = self.snapshot.end_session(revert=True)
            reverted = True
        except Exception as e:
            errors.append(f"Revert failed: {e}")
            logger.error(f"Revert failed: {e}")
            reverted = False

        # Get artifact summary
        artifact_summary = self.artifacts.get_summary()

        # Build result
        result = QESessionResult(
            session_id=self._session_id,
            mode=self._session_config.mode,
            started_at=self._session_start,
            ended_at=session_end,
            duration_seconds=(session_end - self._session_start).total_seconds(),
            files_modified=changes.get("files_modified", []),
            files_created=changes.get("files_created", []),
            files_deleted=changes.get("files_deleted", []),
            patches_generated=len(self.artifacts.list_patches()),
            tests_generated=len(self.artifacts.list_generated_tests()),
            qir_generated=qir_generated,
            artifact_summary=artifact_summary.get("by_type", {}),
            findings_count=len(self._findings),
            critical_count=sum(1 for f in self._findings if f.severity == "critical"),
            warning_count=sum(1 for f in self._findings if f.severity == "warning"),
            reverted=reverted,
            errors=errors,
        )

        # Save result to history
        self._save_session_result(result)

        # Reset state
        self._state = WorkspaceState.IDLE
        self._session_id = None
        self._session_start = None
        self._session_config = None
        self._save_state()

        logger.info(f"Ended QE session: {result.session_id}")

        return result

    @asynccontextmanager
    async def qe_session(
        self,
        session_id: Optional[str] = None,
        config: Optional[QESessionConfig] = None,
    ):
        """
        Context manager for QE sessions.

        Usage:
            async with workspace.qe_session() as session:
                # Do QE work
                pass
            # Automatically reverted, artifacts preserved
        """
        sid = self.start_session(session_id, config)
        try:
            yield self
        finally:
            self.end_session(generate_qir=True)

    # =========================================================================
    # File Operations (with tracking)
    # =========================================================================

    def read_file(self, file_path: str) -> str:
        """Read a file (no tracking needed for reads)."""
        abs_path = self.project_root / file_path
        return abs_path.read_text()

    def write_file(self, file_path: str, content: str) -> None:
        """
        Write to a file (tracked for reversion).

        Captures original state before first write.
        """
        if not self.is_active:
            raise RuntimeError("No active QE session - cannot write files")

        # Capture original state before modification
        self.snapshot.capture_file(Path(file_path))

        # Create parent directories if needed
        abs_path = self.project_root / file_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        abs_path.write_text(content)

        # Record the modification
        self.snapshot.record_modification(Path(file_path))

    def delete_file(self, file_path: str) -> None:
        """
        Delete a file (tracked for reversion).
        """
        if not self.is_active:
            raise RuntimeError("No active QE session - cannot delete files")

        # Capture original state
        self.snapshot.capture_file(Path(file_path))

        # Delete the file
        abs_path = self.project_root / file_path
        if abs_path.exists():
            abs_path.unlink()
            self.snapshot.record_deletion(Path(file_path))

    def check_command(self, command: str) -> None:
        """
        Check if a shell command is allowed.

        Raises GitOperationBlocked for blocked git operations.
        """
        self.git_guard.check_command(command)

    # =========================================================================
    # Findings
    # =========================================================================

    def add_finding(
        self,
        severity: str,
        title: str,
        description: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        evidence: Optional[str] = None,
        suggested_fix: Optional[str] = None,
        work_log: Optional[List[str]] = None,
        tool_calls: Optional[List[str]] = None,
    ) -> Finding:
        """Add a finding from QE analysis."""
        self._finding_counter += 1
        finding = Finding(
            id=f"finding-{self._finding_counter:03d}",
            severity=severity,
            title=title,
            description=description,
            file_path=file_path,
            line_number=line_number,
            evidence=evidence,
            suggested_fix=suggested_fix,
            work_log=work_log,
            tool_calls=tool_calls,
        )
        self._findings.append(finding)

        # If there's a suggested fix, create a patch
        if suggested_fix and file_path:
            try:
                original = self.snapshot.get_original_content(Path(file_path))
                if original:
                    artifact = self.artifacts.save_patch(
                        original_file=file_path,
                        original_content=original.decode("utf-8"),
                        modified_content=suggested_fix,
                        description=title,
                    )
                    finding.patch_artifact_id = artifact.id
            except Exception as e:
                logger.warning(f"Failed to create patch artifact: {e}")

        return finding

    def get_findings(self, severity: Optional[str] = None) -> List[Finding]:
        """Get findings, optionally filtered by severity."""
        if severity:
            return [f for f in self._findings if f.severity == severity]
        return self._findings.copy()

    # =========================================================================
    # Artifacts
    # =========================================================================

    def save_generated_test(
        self,
        test_type: str,
        filename: str,
        content: str,
        description: str = "",
        target_file: Optional[str] = None,
    ) -> Artifact:
        """Save a generated test file to artifacts."""
        type_map = {
            "unit": ArtifactType.TEST_UNIT,
            "integration": ArtifactType.TEST_INTEGRATION,
            "api": ArtifactType.TEST_API,
            "contract": ArtifactType.TEST_CONTRACT,
            "fuzz": ArtifactType.TEST_FUZZ,
            "load": ArtifactType.TEST_LOAD,
            "regression": ArtifactType.TEST_REGRESSION,
            "e2e": ArtifactType.TEST_E2E,
            "security": ArtifactType.TEST_SECURITY,
        }

        artifact_type = type_map.get(test_type.lower(), ArtifactType.TEST_UNIT)

        return self.artifacts.save_generated_test(
            test_type=artifact_type,
            filename=filename,
            content=content,
            description=description,
            target_file=target_file,
        )

    def save_patch(
        self,
        original_file: str,
        original_content: str,
        modified_content: str,
        description: str = "",
    ) -> Artifact:
        """Save a patch file to artifacts."""
        return self.artifacts.save_patch(
            original_file=original_file,
            original_content=original_content,
            modified_content=modified_content,
            description=description,
        )

    # =========================================================================
    # QR Generation
    # =========================================================================

    def _generate_qir(self) -> Artifact:
        """Generate the Quality Report (QR)."""
        changes = self.snapshot.get_changes_summary()

        # Build QR content
        lines = [
            "# Quality Report (QR)",
            "",
            f"**Session ID**: `{self._session_id}`",
            f"**Mode**: {self._session_config.mode.value}",
            f"**Started**: {self._session_start.isoformat()}",
            f"**Duration**: {(datetime.now() - self._session_start).total_seconds():.1f}s",
            "",
        ]

        # Executive Summary
        critical_count = sum(1 for f in self._findings if f.severity == "critical")
        warning_count = sum(1 for f in self._findings if f.severity == "warning")
        info_count = sum(1 for f in self._findings if f.severity == "info")

        if critical_count > 0:
            verdict = "🔴 **FAIL** - Critical issues found"
        elif warning_count > 0:
            verdict = "🟡 **CONDITIONAL PASS** - Warnings found"
        else:
            verdict = "🟢 **PASS** - No significant issues"

        lines.extend(
            [
                "## Executive Summary",
                "",
                f"**Verdict**: {verdict}",
                "",
                f"| Severity | Count |",
                f"|----------|-------|",
                f"| 🔴 Critical | {critical_count} |",
                f"| 🟡 Warning | {warning_count} |",
                f"| 🔵 Info | {info_count} |",
                "",
            ]
        )

        # Scope
        lines.extend(
            [
                "## Investigation Scope",
                "",
                f"- Files analyzed: {changes.get('files_tracked', 0)}",
                f"- Files modified during QE: {len(changes.get('files_modified', []))}",
                f"- Files created during QE: {len(changes.get('files_created', []))}",
                "",
            ]
        )

        # Findings
        if self._findings:
            lines.extend(
                [
                    "## Findings",
                    "",
                ]
            )

            for finding in self._findings:
                severity_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(
                    finding.severity, "⚪"
                )
                lines.append(f"### {severity_icon} {finding.title}")
                lines.append("")

                if finding.file_path:
                    location = finding.file_path
                    if finding.line_number:
                        location += f":{finding.line_number}"
                    lines.append(f"**Location**: `{location}`")
                    lines.append("")

                lines.append(finding.description)
                lines.append("")

                if finding.evidence:
                    lines.append("**Evidence**:")
                    lines.append("```")
                    lines.append(finding.evidence)
                    lines.append("```")
                    lines.append("")

                # Include work log if available (from session findings)
                if hasattr(finding, "work_log") and finding.work_log:
                    lines.append("**Agent Analysis Process**:")
                    lines.append("```")
                    for step in finding.work_log[:5]:  # Show first 5 steps to keep QIR concise
                        lines.append(step)
                    if len(finding.work_log) > 5:
                        lines.append(f"... and {len(finding.work_log) - 5} more analysis steps")
                    lines.append("```")
                    lines.append("")

                # Include tool calls if available
                if hasattr(finding, "tool_calls") and finding.tool_calls:
                    lines.append(f"**Tools Used**: {', '.join(finding.tool_calls)}")
                    lines.append("")

                if finding.patch_artifact_id:
                    lines.append(f"**Suggested Fix**: See `{finding.patch_artifact_id}`")
                    lines.append("")
        else:
            lines.extend(
                [
                    "## Findings",
                    "",
                    "No issues found during this QE session.",
                    "",
                ]
            )

        # Generated Artifacts
        patches = self.artifacts.list_patches()
        tests = self.artifacts.list_generated_tests()

        if patches or tests:
            lines.extend(
                [
                    "## Generated Artifacts",
                    "",
                ]
            )

            if patches:
                lines.append("### Patches")
                lines.append("")
                for patch in patches:
                    lines.append(f"- `{patch.name}`: {patch.description}")
                lines.append("")

            if tests:
                lines.append("### Generated Tests")
                lines.append("")
                for test in tests:
                    lines.append(f"- `{test.name}` ({test.type.value}): {test.description}")
                lines.append("")

        # Git Operations Blocked
        blocked = self.git_guard.get_blocked_attempts()
        if blocked:
            lines.extend(
                [
                    "## Blocked Operations",
                    "",
                    "The following git operations were blocked to maintain repo integrity:",
                    "",
                ]
            )
            for attempt in blocked:
                lines.append(f"- `{attempt.command}`: {attempt.reason}")
            lines.append("")

        # Footer
        lines.extend(
            [
                "---",
                "",
                "*Generated by SuperQode - Agentic Quality Engineering*",
                "",
                f"All changes have been reverted. Artifacts preserved in `.superqode/qe-artifacts/`",
            ]
        )

        content = "\n".join(lines)

        # Save QIR
        metadata = {
            "session_id": self._session_id,
            "mode": self._session_config.mode.value,
            "findings_count": len(self._findings),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "patches_count": len(patches),
            "tests_count": len(tests),
        }

        return self.artifacts.save_qir(content, self._session_id, metadata)

    # =========================================================================
    # State Management
    # =========================================================================

    def _save_state(self) -> None:
        """Save current state to file."""
        state_file = self.superqode_dir / self.STATE_FILE
        state_file.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "state": self._state.value,
            "session_id": self._session_id,
            "session_start": self._session_start.isoformat() if self._session_start else None,
            "updated_at": datetime.now().isoformat(),
        }

        state_file.write_text(json.dumps(state, indent=2))

    def _save_session_result(self, result: QESessionResult) -> None:
        """Save session result to history."""
        history_file = self.superqode_dir / "history" / "sessions.jsonl"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        with open(history_file, "a") as f:
            f.write(json.dumps(result.to_dict()) + "\n")

    def get_session_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent session history."""
        history_file = self.superqode_dir / "history" / "sessions.jsonl"
        if not history_file.exists():
            return []

        sessions = []
        with open(history_file) as f:
            for line in f:
                try:
                    sessions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return sessions[-limit:]


# Global workspace instance
_workspace: Optional[WorkspaceManager] = None


def get_workspace(project_root: Optional[Path] = None) -> WorkspaceManager:
    """Get or create the global workspace manager."""
    global _workspace
    if _workspace is None:
        root = project_root or Path.cwd()
        _workspace = WorkspaceManager(root)
    return _workspace


def set_workspace(workspace: WorkspaceManager) -> None:
    """Set the global workspace manager."""
    global _workspace
    _workspace = workspace
