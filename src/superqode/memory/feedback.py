"""
Feedback Collection - Collect user validation for findings.

Enables users to mark findings as:
- Valid (true positive)
- False positive (suppress in future)
- Fixed (can learn fix pattern)

This feedback improves future QE runs by:
- Reducing false positives via suppressions
- Improving role accuracy metrics
- Learning successful fix patterns
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from .store import MemoryStore, Suppression

logger = logging.getLogger(__name__)


class FeedbackType(Enum):
    """Types of feedback for findings."""

    VALID = "valid"  # True positive, confirmed issue
    FALSE_POSITIVE = "false_positive"  # Should be suppressed
    FIXED = "fixed"  # Issue was fixed
    WONT_FIX = "wont_fix"  # Acknowledged but won't fix
    DUPLICATE = "duplicate"  # Same as another finding


@dataclass
class FindingFeedback:
    """Feedback for a specific finding."""

    finding_id: str
    finding_title: str
    feedback_type: FeedbackType
    reason: str
    created_at: str
    created_by: str

    # For false positives
    suppress_scope: str = "project"  # "project", "team", or "global"
    suppress_pattern_type: str = "fingerprint"  # How to match in future

    # For fixes
    fix_description: Optional[str] = None
    patch_file: Optional[str] = None

    # For duplicates
    duplicate_of: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "finding_title": self.finding_title,
            "feedback_type": self.feedback_type.value,
            "reason": self.reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "suppress_scope": self.suppress_scope,
            "suppress_pattern_type": self.suppress_pattern_type,
            "fix_description": self.fix_description,
            "patch_file": self.patch_file,
            "duplicate_of": self.duplicate_of,
        }


class FeedbackCollector:
    """
    Collects and processes user feedback on findings.

    Integrates with MemoryStore to persist learnings.
    """

    def __init__(self, project_root: Path, enable_ml: bool = False):
        self.project_root = project_root
        self.memory_store = MemoryStore(project_root)
        self._pending_feedback: List[FindingFeedback] = []
        self._predictor = None

        if enable_ml:
            logger.debug("ML predictor not available in OSS build")

    def mark_valid(
        self,
        finding_id: str,
        finding_title: str,
        category: str,
        severity: str,
        role_name: str,
        reason: str = "",
    ) -> FindingFeedback:
        """Mark a finding as a valid true positive."""
        import os

        feedback = FindingFeedback(
            finding_id=finding_id,
            finding_title=finding_title,
            feedback_type=FeedbackType.VALID,
            reason=reason or "Confirmed as valid issue",
            created_at=datetime.now().isoformat(),
            created_by=os.environ.get("USER", "unknown"),
        )

        # Update role metrics
        memory = self.memory_store.load()
        if role_name in memory.role_metrics:
            memory.role_metrics[role_name].confirmed_findings += 1
            memory.role_metrics[role_name].update_accuracy()

        self.memory_store.save()
        self._pending_feedback.append(feedback)

        logger.info(f"Marked finding {finding_id} as valid")
        return feedback

    def mark_false_positive(
        self,
        finding_id: str,
        finding_title: str,
        finding_fingerprint: Optional[str],
        role_name: str,
        reason: str,
        scope: str = "project",
        pattern_type: str = "fingerprint",
        expires_in_days: Optional[int] = None,
    ) -> tuple:
        """
        Mark a finding as a false positive and create suppression.

        Returns:
            Tuple of (FindingFeedback, Suppression)
        """
        import os

        feedback = FindingFeedback(
            finding_id=finding_id,
            finding_title=finding_title,
            feedback_type=FeedbackType.FALSE_POSITIVE,
            reason=reason,
            created_at=datetime.now().isoformat(),
            created_by=os.environ.get("USER", "unknown"),
            suppress_scope=scope,
            suppress_pattern_type=pattern_type,
        )

        # Determine pattern to suppress
        if pattern_type == "fingerprint" and finding_fingerprint:
            pattern = finding_fingerprint
        elif pattern_type == "title":
            pattern = finding_title
        else:
            pattern = finding_fingerprint or finding_title

        # Create suppression
        suppression = self.memory_store.add_suppression(
            pattern=pattern,
            pattern_type=pattern_type,
            reason=reason,
            scope=scope,
            expires_in_days=expires_in_days,
        )

        # Update role metrics
        memory = self.memory_store.load()
        if role_name in memory.role_metrics:
            memory.role_metrics[role_name].false_positives += 1
            memory.role_metrics[role_name].update_accuracy()

        self.memory_store.save(to_team=(scope == "team"))
        self._pending_feedback.append(feedback)

        logger.info(
            f"Marked finding {finding_id} as false positive, created suppression {suppression.id}"
        )
        return feedback, suppression

    def mark_fixed(
        self,
        finding_id: str,
        finding_title: str,
        finding_fingerprint: Optional[str],
        fix_description: str,
        patch_file: Optional[str] = None,
    ) -> FindingFeedback:
        """Mark a finding as fixed and optionally record the fix pattern."""
        import os
        import hashlib

        feedback = FindingFeedback(
            finding_id=finding_id,
            finding_title=finding_title,
            feedback_type=FeedbackType.FIXED,
            reason="Issue was fixed",
            created_at=datetime.now().isoformat(),
            created_by=os.environ.get("USER", "unknown"),
            fix_description=fix_description,
            patch_file=patch_file,
        )

        # Record fix pattern if we have details
        if finding_fingerprint and fix_description:
            from .store import FixPattern

            memory = self.memory_store.load()
            fix_id = hashlib.sha256(
                f"{finding_fingerprint}:{datetime.now().isoformat()}".encode()
            ).hexdigest()[:12]

            fix_pattern = FixPattern(
                id=fix_id,
                issue_fingerprint=finding_fingerprint,
                issue_title=finding_title,
                fix_description=fix_description,
                patch_template=self._read_patch(patch_file) if patch_file else None,
                created_at=datetime.now().isoformat(),
            )
            memory.fix_patterns.append(fix_pattern)
            self.memory_store.save()

        self._pending_feedback.append(feedback)
        logger.info(f"Marked finding {finding_id} as fixed")
        return feedback

    def mark_wont_fix(
        self,
        finding_id: str,
        finding_title: str,
        reason: str,
    ) -> FindingFeedback:
        """Mark a finding as acknowledged but won't fix."""
        import os

        feedback = FindingFeedback(
            finding_id=finding_id,
            finding_title=finding_title,
            feedback_type=FeedbackType.WONT_FIX,
            reason=reason,
            created_at=datetime.now().isoformat(),
            created_by=os.environ.get("USER", "unknown"),
        )

        self._pending_feedback.append(feedback)
        logger.info(f"Marked finding {finding_id} as won't fix: {reason}")
        return feedback

    def mark_duplicate(
        self,
        finding_id: str,
        finding_title: str,
        duplicate_of: str,
    ) -> FindingFeedback:
        """Mark a finding as a duplicate of another."""
        import os

        feedback = FindingFeedback(
            finding_id=finding_id,
            finding_title=finding_title,
            feedback_type=FeedbackType.DUPLICATE,
            reason=f"Duplicate of {duplicate_of}",
            created_at=datetime.now().isoformat(),
            created_by=os.environ.get("USER", "unknown"),
            duplicate_of=duplicate_of,
        )

        self._pending_feedback.append(feedback)
        logger.info(f"Marked finding {finding_id} as duplicate of {duplicate_of}")
        return feedback

    def _read_patch(self, patch_file: str) -> Optional[str]:
        """Read patch content if file exists."""
        try:
            path = Path(patch_file)
            if path.exists():
                return path.read_text()
            # Try relative to project
            path = self.project_root / patch_file
            if path.exists():
                return path.read_text()
        except Exception as e:
            logger.warning(f"Could not read patch file: {e}")
        return None

    def get_pending_feedback(self) -> List[FindingFeedback]:
        """Get feedback collected in this session."""
        return self._pending_feedback.copy()

    def clear_pending(self) -> None:
        """Clear pending feedback after processing."""
        self._pending_feedback.clear()

    def get_role_accuracy(self, role_name: str) -> Optional[float]:
        """Get accuracy rate for a role."""
        memory = self.memory_store.load()
        if role_name in memory.role_metrics:
            return memory.role_metrics[role_name].accuracy_rate
        return None

    def _add_ml_training(
        self,
        finding_id: str,
        finding_title: str,
        severity: str,
        is_true_positive: bool,
    ) -> None:
        """Add feedback to ML predictor training data."""
        if not self._predictor:
            return

        # Create a minimal finding-like object for the predictor
        return None

    def get_ml_stats(self) -> Optional[Dict[str, Any]]:
        """Get ML predictor statistics (not available in OSS build)."""
        return None

    def get_suppression_stats(self) -> Dict[str, Any]:
        """Get statistics about suppressions."""
        memory = self.memory_store.load()
        active = memory.get_active_suppressions()
        by_scope = {"project": 0, "team": 0, "global": 0}
        by_type = {"title": 0, "rule_id": 0, "fingerprint": 0, "file_pattern": 0}

        for supp in active:
            by_scope[supp.scope] = by_scope.get(supp.scope, 0) + 1
            by_type[supp.pattern_type] = by_type.get(supp.pattern_type, 0) + 1

        return {
            "total_active": len(active),
            "total_applied": memory.total_suppressions_applied,
            "by_scope": by_scope,
            "by_type": by_type,
        }
