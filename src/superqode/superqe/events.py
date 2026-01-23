"""
JSONL Event Streaming - CI-friendly event output for QE sessions.

Code  `code exec --json` mode.

Event types:
- qe.started / qe.completed / qe.failed
- test.suite.started / test.suite.completed
- test.started / test.completed / test.failed
- finding.detected
- artifact.generated
- agent.started / agent.completed
- workspace.snapshot / workspace.reverted

Usage:
    # Stream to stdout
    emitter = QEEventEmitter(sys.stdout)
    emitter.emit_qe_started(session_id, mode)

    # Stream to file
    with open("events.jsonl", "w") as f:
        emitter = QEEventEmitter(f)
        ...

Output format (JSONL):
    {"type":"qe.started","session_id":"qe-001","mode":"quick","timestamp":"..."}
    {"type":"test.completed","name":"test_auth","status":"passed","duration":0.5}
    {"type":"finding.detected","id":"F001","severity":"high","title":"SQL injection"}
    {"type":"qe.completed","verdict":"pass","findings_count":0,"duration":45.2}
"""

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from io import TextIOBase
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO, Union
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """QE event types."""

    # Session lifecycle
    QE_STARTED = "qe.started"
    QE_COMPLETED = "qe.completed"
    QE_FAILED = "qe.failed"

    # Turn/Phase
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"

    # Tests
    TEST_SUITE_STARTED = "test.suite.started"
    TEST_SUITE_COMPLETED = "test.suite.completed"
    TEST_STARTED = "test.started"
    TEST_COMPLETED = "test.completed"
    TEST_FAILED = "test.failed"
    TEST_SKIPPED = "test.skipped"

    # Findings
    FINDING_DETECTED = "finding.detected"
    FINDING_UPDATED = "finding.updated"

    # Artifacts
    ARTIFACT_GENERATED = "artifact.generated"
    PATCH_CREATED = "patch.created"
    TEST_GENERATED = "test.generated"

    # Agents
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"

    # Workspace
    WORKSPACE_SNAPSHOT = "workspace.snapshot"
    WORKSPACE_REVERTED = "workspace.reverted"
    WORKSPACE_CHANGE = "workspace.change"

    # Git operations
    GIT_BLOCKED = "git.blocked"

    # Progress
    PROGRESS = "progress"
    MESSAGE = "message"


@dataclass
class QEEvent:
    """A QE event for JSONL streaming."""

    type: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Convert to JSON string."""
        output = {"type": self.type, "timestamp": self.timestamp}
        output.update(self.data)
        return json.dumps(output, default=str)

    @classmethod
    def create(cls, event_type: EventType, **kwargs) -> "QEEvent":
        """Create an event with the given type and data."""
        return cls(type=event_type.value, data=kwargs)


class QEEventEmitter:
    """
    Emits JSONL events for QE sessions.

    Provides CI-friendly streaming output that can be:
    - Piped to other tools
    - Parsed for test reporting
    - Used for real-time monitoring
    """

    def __init__(
        self,
        output: Optional[TextIO] = None,
        enabled: bool = True,
        min_level: str = "info",
    ):
        """
        Initialize the event emitter.

        Args:
            output: Output stream (default: sys.stdout)
            enabled: Whether to emit events
            min_level: Minimum event level to emit ("debug", "info", "warning", "error")
        """
        self.output = output or sys.stdout
        self.enabled = enabled
        self.min_level = min_level
        self._handlers: List[Callable[[QEEvent], None]] = []

    def emit(self, event: QEEvent) -> None:
        """Emit an event."""
        if not self.enabled:
            return

        try:
            self.output.write(event.to_json() + "\n")
            self.output.flush()
        except Exception as e:
            logger.warning(f"Failed to emit event: {e}")

        # Call registered handlers
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                logger.warning(f"Event handler failed: {e}")

    def add_handler(self, handler: Callable[[QEEvent], None]) -> None:
        """Add an event handler."""
        self._handlers.append(handler)

    def remove_handler(self, handler: Callable[[QEEvent], None]) -> None:
        """Remove an event handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    # =========================================================================
    # Session Lifecycle Events
    # =========================================================================

    def emit_qe_started(
        self,
        session_id: str,
        mode: str,
        project_root: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> None:
        """Emit QE session started event."""
        self.emit(
            QEEvent.create(
                EventType.QE_STARTED,
                session_id=session_id,
                mode=mode,
                project_root=project_root,
                roles=roles or [],
            )
        )

    def emit_qe_completed(
        self,
        session_id: str,
        verdict: str,
        findings_count: int,
        duration_seconds: float,
        tests_generated: int = 0,
        patches_generated: int = 0,
    ) -> None:
        """Emit QE session completed event."""
        self.emit(
            QEEvent.create(
                EventType.QE_COMPLETED,
                session_id=session_id,
                verdict=verdict,
                findings_count=findings_count,
                duration_seconds=duration_seconds,
                tests_generated=tests_generated,
                patches_generated=patches_generated,
            )
        )

    def emit_qe_failed(
        self,
        session_id: str,
        error: str,
        duration_seconds: float,
    ) -> None:
        """Emit QE session failed event."""
        self.emit(
            QEEvent.create(
                EventType.QE_FAILED,
                session_id=session_id,
                error=error,
                duration_seconds=duration_seconds,
            )
        )

    # =========================================================================
    # Test Events
    # =========================================================================

    def emit_test_suite_started(
        self,
        suite_name: str,
        test_count: Optional[int] = None,
    ) -> None:
        """Emit test suite started event."""
        self.emit(
            QEEvent.create(
                EventType.TEST_SUITE_STARTED,
                suite=suite_name,
                test_count=test_count,
            )
        )

    def emit_test_suite_completed(
        self,
        suite_name: str,
        passed: int,
        failed: int,
        skipped: int,
        duration_seconds: float,
    ) -> None:
        """Emit test suite completed event."""
        self.emit(
            QEEvent.create(
                EventType.TEST_SUITE_COMPLETED,
                suite=suite_name,
                passed=passed,
                failed=failed,
                skipped=skipped,
                duration_seconds=duration_seconds,
            )
        )

    def emit_test_completed(
        self,
        name: str,
        status: str,  # "passed", "failed", "skipped", "error"
        duration_seconds: float,
        message: Optional[str] = None,
    ) -> None:
        """Emit individual test completed event."""
        event_type = {
            "passed": EventType.TEST_COMPLETED,
            "failed": EventType.TEST_FAILED,
            "skipped": EventType.TEST_SKIPPED,
            "error": EventType.TEST_FAILED,
        }.get(status, EventType.TEST_COMPLETED)

        self.emit(
            QEEvent.create(
                event_type,
                name=name,
                status=status,
                duration_seconds=duration_seconds,
                message=message,
            )
        )

    # =========================================================================
    # Finding Events
    # =========================================================================

    def emit_finding_detected(
        self,
        finding_id: str,
        severity: str,
        priority: int,
        title: str,
        location: Optional[str] = None,
        confidence: float = 1.0,
        category: Optional[str] = None,
        found_by: Optional[str] = None,
    ) -> None:
        """Emit finding detected event."""
        self.emit(
            QEEvent.create(
                EventType.FINDING_DETECTED,
                id=finding_id,
                severity=severity,
                priority=priority,
                title=title,
                location=location,
                confidence_score=confidence,
                category=category,
                found_by=found_by,
            )
        )

    # =========================================================================
    # Artifact Events
    # =========================================================================

    def emit_artifact_generated(
        self,
        artifact_type: str,
        filename: str,
        description: Optional[str] = None,
    ) -> None:
        """Emit artifact generated event."""
        self.emit(
            QEEvent.create(
                EventType.ARTIFACT_GENERATED,
                artifact_type=artifact_type,
                filename=filename,
                description=description,
            )
        )

    def emit_patch_created(
        self,
        patch_id: str,
        filename: str,
        target_file: str,
        lines_added: int,
        lines_removed: int,
    ) -> None:
        """Emit patch created event."""
        self.emit(
            QEEvent.create(
                EventType.PATCH_CREATED,
                patch_id=patch_id,
                filename=filename,
                target_file=target_file,
                lines_added=lines_added,
                lines_removed=lines_removed,
            )
        )

    def emit_test_generated(
        self,
        test_id: str,
        filename: str,
        test_type: str,
        target_file: Optional[str] = None,
    ) -> None:
        """Emit test generated event."""
        self.emit(
            QEEvent.create(
                EventType.TEST_GENERATED,
                test_id=test_id,
                filename=filename,
                test_type=test_type,
                target_file=target_file,
            )
        )

    # =========================================================================
    # Agent Events
    # =========================================================================

    def emit_agent_started(
        self,
        agent_id: str,
        role: str,
        model: Optional[str] = None,
    ) -> None:
        """Emit agent started event."""
        self.emit(
            QEEvent.create(
                EventType.AGENT_STARTED,
                agent_id=agent_id,
                role=role,
                model=model,
            )
        )

    def emit_agent_completed(
        self,
        agent_id: str,
        role: str,
        findings_count: int,
        duration_seconds: float,
    ) -> None:
        """Emit agent completed event."""
        self.emit(
            QEEvent.create(
                EventType.AGENT_COMPLETED,
                agent_id=agent_id,
                role=role,
                findings_count=findings_count,
                duration_seconds=duration_seconds,
            )
        )

    # =========================================================================
    # Workspace Events
    # =========================================================================

    def emit_workspace_snapshot(
        self,
        session_id: str,
        files_count: int,
        snapshot_type: str = "full",  # "full", "incremental"
    ) -> None:
        """Emit workspace snapshot event."""
        self.emit(
            QEEvent.create(
                EventType.WORKSPACE_SNAPSHOT,
                session_id=session_id,
                files_count=files_count,
                snapshot_type=snapshot_type,
            )
        )

    def emit_workspace_reverted(
        self,
        session_id: str,
        files_restored: int,
        files_deleted: int,
    ) -> None:
        """Emit workspace reverted event."""
        self.emit(
            QEEvent.create(
                EventType.WORKSPACE_REVERTED,
                session_id=session_id,
                files_restored=files_restored,
                files_deleted=files_deleted,
            )
        )

    def emit_git_blocked(
        self,
        command: str,
        reason: str,
    ) -> None:
        """Emit git operation blocked event."""
        self.emit(
            QEEvent.create(
                EventType.GIT_BLOCKED,
                command=command,
                reason=reason,
            )
        )

    # =========================================================================
    # Progress Events
    # =========================================================================

    def emit_progress(
        self,
        phase: str,
        current: int,
        total: int,
        message: Optional[str] = None,
    ) -> None:
        """Emit progress event."""
        self.emit(
            QEEvent.create(
                EventType.PROGRESS,
                phase=phase,
                current=current,
                total=total,
                percentage=round(current / total * 100, 1) if total > 0 else 0,
                message=message,
            )
        )

    def emit_message(
        self,
        level: str,  # "debug", "info", "warning", "error"
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a log message event."""
        self.emit(
            QEEvent.create(
                EventType.MESSAGE,
                level=level,
                message=message,
                context=context,
            )
        )


class QEEventCollector:
    """
    Collects events in memory for later processing.

    Useful for generating summary reports after QE completion.
    """

    def __init__(self):
        self.events: List[QEEvent] = []

    def collect(self, event: QEEvent) -> None:
        """Add event to collection."""
        self.events.append(event)

    def get_findings(self) -> List[Dict[str, Any]]:
        """Get all finding events."""
        return [e.data for e in self.events if e.type == EventType.FINDING_DETECTED.value]

    def get_tests(self) -> List[Dict[str, Any]]:
        """Get all test events."""
        return [
            e.data
            for e in self.events
            if e.type
            in (
                EventType.TEST_COMPLETED.value,
                EventType.TEST_FAILED.value,
                EventType.TEST_SKIPPED.value,
            )
        ]

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics from collected events."""
        tests = self.get_tests()
        findings = self.get_findings()

        return {
            "total_events": len(self.events),
            "tests": {
                "total": len(tests),
                "passed": sum(1 for t in tests if t.get("status") == "passed"),
                "failed": sum(1 for t in tests if t.get("status") == "failed"),
                "skipped": sum(1 for t in tests if t.get("status") == "skipped"),
            },
            "findings": {
                "total": len(findings),
                "by_severity": {
                    severity: sum(1 for f in findings if f.get("severity") == severity)
                    for severity in ["critical", "high", "medium", "low", "info"]
                },
            },
        }

    def to_jsonl(self) -> str:
        """Export all events as JSONL string."""
        return "\n".join(e.to_json() for e in self.events)

    def save(self, path: Path) -> None:
        """Save events to JSONL file."""
        path.write_text(self.to_jsonl())


# =============================================================================
# Global Event Emitter
# =============================================================================

_global_emitter: Optional[QEEventEmitter] = None


def get_event_emitter() -> Optional[QEEventEmitter]:
    """Get the global event emitter."""
    return _global_emitter


def set_event_emitter(emitter: QEEventEmitter) -> None:
    """Set the global event emitter."""
    global _global_emitter
    _global_emitter = emitter


def emit_event(event_type: EventType, **kwargs) -> None:
    """Emit an event using the global emitter if set."""
    emitter = get_event_emitter()
    if emitter:
        emitter.emit(QEEvent.create(event_type, **kwargs))
