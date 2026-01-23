"""
QIR Templates for different QE modes and scenarios.
"""

from enum import Enum
from typing import Dict, List


class QRTemplate(Enum):
    """Pre-defined QIR templates for different scenarios."""

    QUICK_SCAN = "quick_scan"
    DEEP_QE = "deep_qe"
    SECURITY_AUDIT = "security_audit"
    PERFORMANCE_REVIEW = "performance_review"
    REGRESSION_CHECK = "regression_check"


# Template configurations
TEMPLATES: Dict[QRTemplate, Dict] = {
    QRTemplate.QUICK_SCAN: {
        "name": "Quick Scan Report",
        "sections": ["executive_summary", "findings", "recommendations"],
        "findings_limit": 10,
        "include_evidence": False,
        "include_patches": False,
        "methodology_notes": [
            "Time-boxed shallow analysis",
            "Focus on high-risk paths",
            "Static analysis and linting",
        ],
    },
    QRTemplate.DEEP_QE: {
        "name": "Deep QE Investigation Report",
        "sections": [
            "executive_summary",
            "scope",
            "methodology",
            "findings",
            "root_cause",
            "suggested_fixes",
            "generated_tests",
            "benchmarks",
            "recommendations",
            "appendix",
        ],
        "findings_limit": None,
        "include_evidence": True,
        "include_patches": True,
        "methodology_notes": [
            "Full codebase exploration",
            "Destructive testing enabled",
            "Test generation for uncovered code",
            "Security vulnerability scanning",
            "Performance profiling",
        ],
    },
    QRTemplate.SECURITY_AUDIT: {
        "name": "Security Audit Report",
        "sections": [
            "executive_summary",
            "scope",
            "methodology",
            "findings",
            "suggested_fixes",
            "recommendations",
            "appendix",
        ],
        "findings_limit": None,
        "include_evidence": True,
        "include_patches": True,
        "methodology_notes": [
            "OWASP Top 10 vulnerability check",
            "Dependency vulnerability scan",
            "Authentication/authorization review",
            "Input validation analysis",
            "Secrets detection",
        ],
        "severity_filter": ["critical", "high"],  # Focus on security-relevant
    },
    QRTemplate.PERFORMANCE_REVIEW: {
        "name": "Performance Review Report",
        "sections": [
            "executive_summary",
            "scope",
            "methodology",
            "benchmarks",
            "findings",
            "recommendations",
        ],
        "findings_limit": None,
        "include_evidence": True,
        "include_patches": False,
        "methodology_notes": [
            "Load testing",
            "Memory profiling",
            "CPU profiling",
            "Database query analysis",
            "Network latency measurement",
        ],
    },
    QRTemplate.REGRESSION_CHECK: {
        "name": "Regression Check Report",
        "sections": ["executive_summary", "findings", "recommendations"],
        "findings_limit": None,
        "include_evidence": True,
        "include_patches": False,
        "methodology_notes": [
            "Existing test suite execution",
            "Flaky test detection",
            "Coverage comparison",
            "Performance regression detection",
        ],
    },
}


def get_template(template: QRTemplate) -> Dict:
    """Get configuration for a QIR template."""
    return TEMPLATES.get(template, TEMPLATES[QRTemplate.DEEP_QE])


def get_template_by_mode(mode: str) -> Dict:
    """Get template configuration by mode name."""
    mode_map = {
        "quick_scan": QRTemplate.QUICK_SCAN,
        "quick": QRTemplate.QUICK_SCAN,
        "deep_qe": QRTemplate.DEEP_QE,
        "deep": QRTemplate.DEEP_QE,
        "security": QRTemplate.SECURITY_AUDIT,
        "performance": QRTemplate.PERFORMANCE_REVIEW,
        "regression": QRTemplate.REGRESSION_CHECK,
    }
    template = mode_map.get(mode.lower(), QRTemplate.DEEP_QE)
    return TEMPLATES[template]
