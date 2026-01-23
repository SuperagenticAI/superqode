"""
Memory Store - Persistent storage for QE learnings.

Stores project-specific memory that persists across QE sessions:
- Issue patterns (recurring issues)
- False positive suppressions
- Successful fix patterns
- File risk scores
- Role effectiveness metrics

Storage locations:
- ~/.superqode/memory/project-{hash}.json  (per-project, user-local)
- .superqode/memory.json                   (team-shared, in repo)
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class IssuePattern:
    """A recurring issue pattern detected across sessions."""

    fingerprint: str  # Hash of title + category
    title: str
    category: str
    severity: str
    occurrences: int = 1
    first_seen: str = ""  # ISO timestamp
    last_seen: str = ""  # ISO timestamp
    files_affected: List[str] = field(default_factory=list)
    avg_confidence: float = 0.8

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IssuePattern":
        return cls(**data)


@dataclass
class Suppression:
    """A false positive suppression rule."""

    id: str
    pattern: str  # What to match (title, rule_id, or fingerprint)
    pattern_type: str  # "title", "rule_id", "fingerprint", "file_pattern"
    reason: str
    created_at: str  # ISO timestamp
    created_by: str  # User or "system"
    expires_at: Optional[str] = None  # Optional expiration
    scope: str = "project"  # "project" or "global"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Suppression":
        return cls(**data)

    def is_expired(self) -> bool:
        """Check if suppression has expired."""
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now() > expires
        except ValueError:
            return False


@dataclass
class FixPattern:
    """A successful fix pattern that can be reused."""

    id: str
    issue_fingerprint: str  # Links to IssuePattern
    issue_title: str
    fix_description: str
    patch_template: Optional[str] = None
    success_rate: float = 1.0
    times_applied: int = 1
    times_succeeded: int = 1
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FixPattern":
        return cls(**data)


@dataclass
class RoleMetrics:
    """Effectiveness metrics for a QE role."""

    role_name: str
    sessions_run: int = 0
    total_findings: int = 0
    confirmed_findings: int = 0  # User validated as true positives
    false_positives: int = 0
    avg_session_duration_seconds: float = 0.0
    accuracy_rate: float = 1.0  # confirmed / (confirmed + false_positives)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoleMetrics":
        return cls(**data)

    def update_accuracy(self) -> None:
        """Recalculate accuracy rate."""
        total = self.confirmed_findings + self.false_positives
        if total > 0:
            self.accuracy_rate = self.confirmed_findings / total
        else:
            self.accuracy_rate = 1.0


@dataclass
class QEMemory:
    """
    Complete memory store for a project.

    Contains all learnings from past QE sessions.
    """

    project_id: str  # Hash of project root path
    project_name: str
    created_at: str
    updated_at: str

    # Learnings
    issue_patterns: List[IssuePattern] = field(default_factory=list)
    suppressions: List[Suppression] = field(default_factory=list)
    fix_patterns: List[FixPattern] = field(default_factory=list)

    # Risk analysis
    file_risk_map: Dict[str, float] = field(default_factory=dict)

    # Role effectiveness
    role_metrics: Dict[str, RoleMetrics] = field(default_factory=dict)

    # Statistics
    total_sessions: int = 0
    total_findings: int = 0
    total_suppressions_applied: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "issue_patterns": [p.to_dict() for p in self.issue_patterns],
            "suppressions": [s.to_dict() for s in self.suppressions],
            "fix_patterns": [f.to_dict() for f in self.fix_patterns],
            "file_risk_map": self.file_risk_map,
            "role_metrics": {k: v.to_dict() for k, v in self.role_metrics.items()},
            "total_sessions": self.total_sessions,
            "total_findings": self.total_findings,
            "total_suppressions_applied": self.total_suppressions_applied,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QEMemory":
        return cls(
            project_id=data.get("project_id", ""),
            project_name=data.get("project_name", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            issue_patterns=[IssuePattern.from_dict(p) for p in data.get("issue_patterns", [])],
            suppressions=[Suppression.from_dict(s) for s in data.get("suppressions", [])],
            fix_patterns=[FixPattern.from_dict(f) for f in data.get("fix_patterns", [])],
            file_risk_map=data.get("file_risk_map", {}),
            role_metrics={
                k: RoleMetrics.from_dict(v) for k, v in data.get("role_metrics", {}).items()
            },
            total_sessions=data.get("total_sessions", 0),
            total_findings=data.get("total_findings", 0),
            total_suppressions_applied=data.get("total_suppressions_applied", 0),
        )

    def get_active_suppressions(self) -> List[Suppression]:
        """Get non-expired suppressions."""
        return [s for s in self.suppressions if not s.is_expired()]

    def get_file_risk(self, file_path: str) -> float:
        """Get risk score for a file (0.0 to 1.0)."""
        return self.file_risk_map.get(file_path, 0.5)

    def update_file_risk(self, file_path: str, finding_severity: str) -> None:
        """Update risk score based on a new finding."""
        severity_weights = {
            "critical": 0.3,
            "high": 0.2,
            "medium": 0.1,
            "low": 0.05,
            "info": 0.02,
        }
        delta = severity_weights.get(finding_severity, 0.05)
        current = self.file_risk_map.get(file_path, 0.5)
        # Increase risk, cap at 1.0
        self.file_risk_map[file_path] = min(1.0, current + delta)


class MemoryStore:
    """
    Manages persistence and retrieval of QE memory.

    Storage strategy:
    1. User-local: ~/.superqode/memory/project-{hash}.json
    2. Team-shared: .superqode/memory.json (committed to repo)

    The two are merged, with user-local taking precedence for conflicts.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.project_id = self._compute_project_id()
        self.project_name = project_root.name

        # Storage paths
        self._user_dir = Path.home() / ".superqode" / "memory"
        self._user_file = self._user_dir / f"project-{self.project_id}.json"
        self._team_file = project_root / ".superqode" / "memory.json"

        self._memory: Optional[QEMemory] = None

    def _compute_project_id(self) -> str:
        """Compute a stable ID for the project."""
        return hashlib.sha256(str(self.project_root).encode()).hexdigest()[:16]

    def load(self) -> QEMemory:
        """Load memory from storage, merging user and team files."""
        if self._memory is not None:
            return self._memory

        user_memory = self._load_file(self._user_file)
        team_memory = self._load_file(self._team_file)

        if user_memory and team_memory:
            # Merge: user takes precedence
            self._memory = self._merge_memories(user_memory, team_memory)
        elif user_memory:
            self._memory = user_memory
        elif team_memory:
            self._memory = team_memory
        else:
            # Create new memory
            now = datetime.now().isoformat()
            self._memory = QEMemory(
                project_id=self.project_id,
                project_name=self.project_name,
                created_at=now,
                updated_at=now,
            )

        return self._memory

    def _load_file(self, path: Path) -> Optional[QEMemory]:
        """Load memory from a single file."""
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
            return QEMemory.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load memory from {path}: {e}")
            return None

    def _merge_memories(self, user: QEMemory, team: QEMemory) -> QEMemory:
        """Merge user and team memories."""
        # Start with team as base
        merged = QEMemory.from_dict(team.to_dict())

        # Add user suppressions (these are personal)
        user_supp_ids = {s.id for s in user.suppressions}
        team_supp_ids = {s.id for s in team.suppressions}
        for supp in user.suppressions:
            if supp.id not in team_supp_ids:
                merged.suppressions.append(supp)

        # Merge issue patterns (combine occurrences)
        user_patterns = {p.fingerprint: p for p in user.issue_patterns}
        for pattern in merged.issue_patterns:
            if pattern.fingerprint in user_patterns:
                up = user_patterns[pattern.fingerprint]
                pattern.occurrences = max(pattern.occurrences, up.occurrences)
                pattern.last_seen = max(pattern.last_seen, up.last_seen)

        # Use user's role metrics (more recent)
        merged.role_metrics.update(user.role_metrics)

        # Use user's file risk map
        merged.file_risk_map.update(user.file_risk_map)

        return merged

    def save(self, to_team: bool = False) -> None:
        """
        Save memory to storage.

        Args:
            to_team: If True, also save to team file (.superqode/memory.json)
        """
        if self._memory is None:
            return

        self._memory.updated_at = datetime.now().isoformat()
        data = json.dumps(self._memory.to_dict(), indent=2)

        # Always save to user file
        self._user_dir.mkdir(parents=True, exist_ok=True)
        self._user_file.write_text(data)
        logger.debug(f"Saved memory to {self._user_file}")

        # Optionally save to team file
        if to_team:
            self._team_file.parent.mkdir(parents=True, exist_ok=True)
            # Filter out user-specific data for team file
            team_data = self._prepare_team_data()
            self._team_file.write_text(json.dumps(team_data, indent=2))
            logger.debug(f"Saved team memory to {self._team_file}")

    def _prepare_team_data(self) -> Dict[str, Any]:
        """Prepare memory data for team sharing (remove personal data)."""
        if self._memory is None:
            return {}

        data = self._memory.to_dict()
        # Keep only team-scope suppressions
        data["suppressions"] = [s for s in data["suppressions"] if s.get("scope") == "team"]
        return data

    def add_suppression(
        self,
        pattern: str,
        pattern_type: str,
        reason: str,
        scope: str = "project",
        expires_in_days: Optional[int] = None,
    ) -> Suppression:
        """Add a new suppression rule."""
        memory = self.load()

        now = datetime.now()
        supp_id = hashlib.sha256(
            f"{pattern}:{pattern_type}:{now.isoformat()}".encode()
        ).hexdigest()[:12]

        expires_at = None
        if expires_in_days:
            from datetime import timedelta

            expires_at = (now + timedelta(days=expires_in_days)).isoformat()

        suppression = Suppression(
            id=supp_id,
            pattern=pattern,
            pattern_type=pattern_type,
            reason=reason,
            created_at=now.isoformat(),
            created_by=os.environ.get("USER", "unknown"),
            expires_at=expires_at,
            scope=scope,
        )

        memory.suppressions.append(suppression)
        self.save(to_team=(scope == "team"))

        return suppression

    def remove_suppression(self, suppression_id: str) -> bool:
        """Remove a suppression by ID."""
        memory = self.load()
        original_count = len(memory.suppressions)
        memory.suppressions = [s for s in memory.suppressions if s.id != suppression_id]
        if len(memory.suppressions) < original_count:
            self.save()
            return True
        return False

    def record_finding(
        self,
        title: str,
        category: str,
        severity: str,
        file_path: Optional[str],
        confidence: float,
    ) -> None:
        """Record a finding to update patterns and risk scores."""
        memory = self.load()

        # Compute fingerprint
        fingerprint = hashlib.sha256(f"{title}:{category}".encode()).hexdigest()[:16]

        now = datetime.now().isoformat()

        # Update or create pattern
        existing = next(
            (p for p in memory.issue_patterns if p.fingerprint == fingerprint),
            None,
        )

        if existing:
            existing.occurrences += 1
            existing.last_seen = now
            existing.avg_confidence = (
                existing.avg_confidence * (existing.occurrences - 1) + confidence
            ) / existing.occurrences
            if file_path and file_path not in existing.files_affected:
                existing.files_affected.append(file_path)
        else:
            pattern = IssuePattern(
                fingerprint=fingerprint,
                title=title,
                category=category,
                severity=severity,
                occurrences=1,
                first_seen=now,
                last_seen=now,
                files_affected=[file_path] if file_path else [],
                avg_confidence=confidence,
            )
            memory.issue_patterns.append(pattern)

        # Update file risk
        if file_path:
            memory.update_file_risk(file_path, severity)

        memory.total_findings += 1

    def record_session(
        self,
        roles_used: List[str],
        findings_count: int,
        duration_seconds: float,
    ) -> None:
        """Record a completed QE session."""
        memory = self.load()
        memory.total_sessions += 1

        # Update role metrics
        for role in roles_used:
            if role not in memory.role_metrics:
                memory.role_metrics[role] = RoleMetrics(role_name=role)

            metrics = memory.role_metrics[role]
            metrics.sessions_run += 1
            # Rolling average of duration
            metrics.avg_session_duration_seconds = (
                metrics.avg_session_duration_seconds * (metrics.sessions_run - 1) + duration_seconds
            ) / metrics.sessions_run

    def get_suppressions_for_finding(
        self,
        title: str,
        rule_id: Optional[str],
        fingerprint: Optional[str],
        file_path: Optional[str],
    ) -> List[Suppression]:
        """Get suppressions that match a finding."""
        memory = self.load()
        matches = []

        for supp in memory.get_active_suppressions():
            if supp.pattern_type == "title" and supp.pattern.lower() in title.lower():
                matches.append(supp)
            elif supp.pattern_type == "rule_id" and rule_id == supp.pattern:
                matches.append(supp)
            elif supp.pattern_type == "fingerprint" and fingerprint == supp.pattern:
                matches.append(supp)
            elif supp.pattern_type == "file_pattern" and file_path:
                import fnmatch

                if fnmatch.fnmatch(file_path, supp.pattern):
                    matches.append(supp)

        return matches

    def should_suppress(
        self,
        title: str,
        rule_id: Optional[str] = None,
        fingerprint: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> bool:
        """Check if a finding should be suppressed."""
        matches = self.get_suppressions_for_finding(title, rule_id, fingerprint, file_path)
        if matches:
            memory = self.load()
            memory.total_suppressions_applied += 1
            return True
        return False

    def get_high_risk_files(self, threshold: float = 0.7) -> List[tuple]:
        """Get files with risk score above threshold."""
        memory = self.load()
        high_risk = [
            (path, score) for path, score in memory.file_risk_map.items() if score >= threshold
        ]
        return sorted(high_risk, key=lambda x: x[1], reverse=True)

    def get_recurring_issues(self, min_occurrences: int = 2) -> List[IssuePattern]:
        """Get issues that have occurred multiple times."""
        memory = self.load()
        return [p for p in memory.issue_patterns if p.occurrences >= min_occurrences]
