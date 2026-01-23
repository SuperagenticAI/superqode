"""Minimal fix verifier for OSS (no automation)."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class VerificationStatus(Enum):
    """Status of fix verification."""

    SKIPPED = "skipped"


@dataclass
class TestMetrics:
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0
    coverage_percent: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "coverage_percent": self.coverage_percent,
        }


@dataclass
class VerificationResult:
    status: VerificationStatus
    finding_id: str
    before_metrics: Optional[TestMetrics] = None
    after_metrics: Optional[TestMetrics] = None
    tests_fixed: int = 0
    tests_broken: int = 0
    coverage_delta: float = 0.0
    evidence: List[str] = field(default_factory=list)
    patch_file: Optional[str] = None
    verification_duration_ms: int = 0
    error_message: Optional[str] = None

    @property
    def is_improvement(self) -> bool:
        return False

    @property
    def confidence_score(self) -> float:
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "finding_id": self.finding_id,
            "before_metrics": self.before_metrics.to_dict() if self.before_metrics else None,
            "after_metrics": self.after_metrics.to_dict() if self.after_metrics else None,
            "tests_fixed": self.tests_fixed,
            "tests_broken": self.tests_broken,
            "coverage_delta": self.coverage_delta,
            "is_improvement": self.is_improvement,
            "confidence_score": self.confidence_score,
            "evidence": self.evidence,
            "patch_file": self.patch_file,
            "verification_duration_ms": self.verification_duration_ms,
            "error_message": self.error_message,
        }


@dataclass
class FixVerifierConfig:
    test_command: str = "pytest"
    test_args: List[str] = field(default_factory=list)
    coverage_command: Optional[str] = None
    timeout_seconds: int = 300
    require_no_regressions: bool = True
    min_improvement_threshold: float = 0.0


class FixVerifier:
    """OSS placeholder verifier."""

    def __init__(self, project_root: Path, config: Optional[FixVerifierConfig] = None):
        self.project_root = Path(project_root)
        self.config = config or FixVerifierConfig()

    def verify_fix(
        self,
        finding_id: str,
        patch_content: str,
        target_file: Optional[Path] = None,
        apply_patch_fn=None,
    ) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.SKIPPED, finding_id=finding_id)
