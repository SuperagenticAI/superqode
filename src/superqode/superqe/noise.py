"""
Noise Controls - Minimal OSS implementation.

OSS keeps a no-op noise filter to preserve interfaces without proprietary logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NoiseConfig:
    """Configuration for noise controls."""

    min_confidence: float = 0.7
    deduplicate: bool = False
    similarity_threshold: float = 0.8
    suppress_known_risks: bool = False
    known_risk_patterns: List[str] = field(default_factory=list)
    min_severity: str = "low"
    max_findings_per_file: int = 0
    max_total_findings: int = 0
    apply_severity_rules: bool = False
    severity_rules_config: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NoiseConfig":
        return cls(
            min_confidence=data.get("min_confidence", 0.7),
            deduplicate=data.get("deduplicate", False),
            similarity_threshold=data.get("similarity_threshold", 0.8),
            suppress_known_risks=data.get("suppress_known_risks", False),
            known_risk_patterns=data.get("known_risk_patterns", []),
            min_severity=data.get("min_severity", "low"),
            max_findings_per_file=data.get("max_findings_per_file", 0),
            max_total_findings=data.get("max_total_findings", 0),
            apply_severity_rules=data.get("apply_severity_rules", False),
            severity_rules_config=data.get("severity_rules"),
        )


@dataclass
class Finding:
    """A QE finding with noise-control metadata."""

    id: str
    severity: str
    title: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[str] = None
    suggested_fix: Optional[str] = None
    confidence: float = 1.0
    category: str = ""
    rule_id: Optional[str] = None
    fingerprint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "evidence": self.evidence,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "category": self.category,
            "rule_id": self.rule_id,
            "fingerprint": self.fingerprint,
        }


class NoiseFilter:
    """No-op noise filter for OSS."""

    def __init__(self, config: Optional[NoiseConfig] = None, **_kwargs: Any):
        self.config = config or NoiseConfig()

    def apply(self, findings: List[Finding]) -> List[Finding]:
        return findings


def load_noise_config(_project_root) -> NoiseConfig:
    return NoiseConfig()
