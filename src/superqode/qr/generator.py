"""
QR Generator - Quality Report Generator.

Produces research-grade QA reports that transform findings
from "bug reports" into "evidence-backed decisions."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import json


class QRVerdict(Enum):
    """Overall QIR verdict."""

    PASS = "pass"  # No significant issues
    CONDITIONAL_PASS = "conditional"  # Warnings but acceptable
    FAIL = "fail"  # Critical issues found
    BLOCKED = "blocked"  # Could not complete analysis


class QRSection(Enum):
    """Sections of a QIR."""

    EXECUTIVE_SUMMARY = "executive_summary"
    SCOPE = "scope"
    METHODOLOGY = "methodology"
    FINDINGS = "findings"
    ROOT_CAUSE = "root_cause"
    SUGGESTED_FIXES = "suggested_fixes"
    GENERATED_TESTS = "generated_tests"
    BENCHMARKS = "benchmarks"
    RECOMMENDATIONS = "recommendations"
    APPENDIX = "appendix"


class FindingPriority(Enum):
    """
    Priority levels for findings.

    P0 - Drop everything. Blocking release/operations.
    P1 - Urgent. Should be addressed in next cycle.
    P2 - Normal. To be fixed eventually.
    P3 - Low. Nice to have.
    """

    P0 = 0  # Drop everything
    P1 = 1  # Urgent
    P2 = 2  # Normal
    P3 = 3  # Low/Nice to have


@dataclass
class Finding:
    """
    A single finding in the QIR.

    Enhanced with priorities and confidence scores for CI filtering.
    """

    id: str
    severity: str  # "critical", "high", "medium", "low", "info"
    category: str  # "security", "performance", "reliability", "maintainability"
    title: str
    description: str

    # Priority
    priority: FindingPriority = FindingPriority.P2

    # Confidence score (0.0-1.0) for filtering noise
    confidence_score: float = 0.8

    # Location
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    # Evidence and context
    evidence: Optional[str] = None
    evidence_snippet: Optional[str] = None  # Code snippet showing the issue
    reproduction_steps: List[str] = field(default_factory=list)

    # Fix information
    suggested_fix: Optional[str] = None
    suggested_fix_snippet: Optional[str] = None  # Code showing the fix
    patch_id: Optional[str] = None

    # Metadata
    found_by: Optional[str] = None  # QE role that found this
    references: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    @property
    def severity_icon(self) -> str:
        """Get emoji icon for severity."""
        icons = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🔵",
            "info": "⚪",
        }
        return icons.get(self.severity, "⚪")

    @property
    def priority_label(self) -> str:
        """Get priority label like [P0], [P1], etc."""
        return f"[P{self.priority.value}]"

    @property
    def location(self) -> str:
        """Get formatted location string."""
        if not self.file_path:
            return ""
        loc = self.file_path
        if self.line_start:
            loc += f":{self.line_start}"
            if self.line_end and self.line_end != self.line_start:
                loc += f"-{self.line_end}"
        return loc

    @property
    def full_title(self) -> str:
        """Get title with priority prefix."""
        return f"{self.priority_label} {self.title}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "severity": self.severity,
            "priority": self.priority.value,
            "confidence_score": self.confidence_score,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_range": {
                "start": self.line_start,
                "end": self.line_end,
            }
            if self.line_start
            else None,
            "location": self.location,
            "evidence": self.evidence,
            "suggested_fix": self.suggested_fix,
            "patch_id": self.patch_id,
            "found_by": self.found_by,
            "tags": self.tags,
        }


@dataclass
class TestArtifact:
    """A generated test artifact."""

    id: str
    test_type: str  # "unit", "integration", "api", "fuzz", etc.
    filename: str
    description: str
    target_file: Optional[str] = None
    coverage_added: Optional[float] = None


@dataclass
class PatchArtifact:
    """A suggested fix patch."""

    id: str
    filename: str
    description: str
    target_file: str
    lines_added: int = 0
    lines_removed: int = 0


@dataclass
class BenchmarkResult:
    """A benchmark or validation result."""

    name: str
    metric: str
    value: float
    unit: str
    baseline: Optional[float] = None
    threshold: Optional[float] = None
    passed: bool = True


@dataclass
class VerifiedFix:
    """A fix that has been verified through the suggestion workflow.

    Records the full proof chain:
    1. Original issue found
    2. Fix applied in sandbox
    3. Tests run before/after
    4. Proof of improvement
    5. Code reverted (always)
    """

    finding_id: str
    finding_title: str
    patch_id: str
    patch_file: str

    # Verification status
    fix_verified: bool = False
    is_improvement: bool = False

    # Test metrics
    tests_before_passed: int = 0
    tests_before_total: int = 0
    tests_after_passed: int = 0
    tests_after_total: int = 0

    # Coverage
    coverage_before: Optional[float] = None
    coverage_after: Optional[float] = None

    # Evidence
    verification_evidence: List[str] = field(default_factory=list)
    verification_duration_ms: int = 0

    # Confidence in the fix
    fix_confidence: float = 0.8

    @property
    def tests_fixed(self) -> int:
        """Number of tests that now pass after the fix."""
        return max(0, self.tests_after_passed - self.tests_before_passed)

    @property
    def tests_broken(self) -> int:
        """Number of tests broken by the fix (regressions)."""
        after_failed = self.tests_after_total - self.tests_after_passed
        before_failed = self.tests_before_total - self.tests_before_passed
        return max(0, after_failed - before_failed)

    @property
    def coverage_delta(self) -> Optional[float]:
        """Change in coverage."""
        if self.coverage_before is not None and self.coverage_after is not None:
            return self.coverage_after - self.coverage_before
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "finding_title": self.finding_title,
            "patch_id": self.patch_id,
            "patch_file": self.patch_file,
            "fix_verified": self.fix_verified,
            "is_improvement": self.is_improvement,
            "tests_fixed": self.tests_fixed,
            "tests_broken": self.tests_broken,
            "metrics": {
                "before": {
                    "tests_passed": self.tests_before_passed,
                    "tests_total": self.tests_before_total,
                    "coverage": self.coverage_before,
                },
                "after": {
                    "tests_passed": self.tests_after_passed,
                    "tests_total": self.tests_after_total,
                    "coverage": self.coverage_after,
                },
            },
            "coverage_delta": self.coverage_delta,
            "fix_confidence": self.fix_confidence,
            "verification_evidence": self.verification_evidence,
        }


@dataclass
class QRData:
    """All data for generating a QIR."""

    session_id: str
    mode: str
    started_at: datetime
    ended_at: Optional[datetime] = None

    # Scope
    target_description: str = ""
    files_analyzed: List[str] = field(default_factory=list)
    total_lines: int = 0

    # Methodology
    roles_used: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    methodology_notes: List[str] = field(default_factory=list)

    # Findings
    findings: List[Finding] = field(default_factory=list)

    # Artifacts
    generated_tests: List[TestArtifact] = field(default_factory=list)
    patches: List[PatchArtifact] = field(default_factory=list)

    # Benchmarks
    benchmarks: List[BenchmarkResult] = field(default_factory=list)
    coverage_before: Optional[float] = None
    coverage_after: Optional[float] = None

    # Verified fixes (when allow_suggestions is enabled)
    verified_fixes: List[VerifiedFix] = field(default_factory=list)
    allow_suggestions_enabled: bool = False

    # Meta
    blocked_operations: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """Get session duration."""
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def critical_count(self) -> int:
        """Count of critical findings."""
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def high_count(self) -> int:
        """Count of high severity findings."""
        return sum(1 for f in self.findings if f.severity == "high")

    @property
    def verdict(self) -> QRVerdict:
        """Determine overall verdict."""
        if self.errors:
            return QRVerdict.BLOCKED
        if self.critical_count > 0:
            return QRVerdict.FAIL
        if self.high_count > 0 or sum(1 for f in self.findings if f.severity == "medium") > 3:
            return QRVerdict.CONDITIONAL_PASS
        return QRVerdict.PASS


class QRGenerator:
    """
    Generates Quality Investigation Reports.

    Produces Markdown reports with optional JSON output for CI integration.
    """

    def __init__(self, data: QRData):
        self.data = data

    def generate_markdown(self) -> str:
        """Generate the full QIR in Markdown format."""
        sections = [
            self._header(),
            self._executive_summary(),
            self._scope(),
            self._methodology(),
            self._findings(),
            self._suggested_fixes(),
            self._fix_verification(),  # New: verification results
            self._generated_tests(),
            self._benchmarks(),
            self._recommendations(),
            self._appendix(),
            self._footer(),
        ]

        return "\n".join(filter(None, sections))

    def generate_json(self) -> Dict[str, Any]:
        """Generate QIR data as JSON for CI integration."""
        # Calculate confidence statistics
        confidence_scores = [f.confidence_score for f in self.data.findings]
        avg_confidence = (
            sum(confidence_scores) / len(confidence_scores) if confidence_scores else 1.0
        )

        # Priority breakdown
        priority_counts = {f"P{i}": 0 for i in range(4)}
        for f in self.data.findings:
            priority_counts[f"P{f.priority.value}"] += 1

        return {
            "version": "1.0",
            "schema": "superqode-qr-v1",
            "session_id": self.data.session_id,
            "mode": self.data.mode,
            "started_at": self.data.started_at.isoformat(),
            "ended_at": self.data.ended_at.isoformat() if self.data.ended_at else None,
            "duration_seconds": self.data.duration_seconds,
            # Verdict with confidence
            "verdict": self.data.verdict.value,
            "overall_correctness": "correct"
            if self.data.verdict == QRVerdict.PASS
            else "incorrect",
            "overall_confidence_score": avg_confidence,
            "overall_explanation": self._generate_verdict_explanation(),
            # Summary statistics
            "summary": {
                "total_findings": len(self.data.findings),
                "by_severity": {
                    "critical": self.data.critical_count,
                    "high": self.data.high_count,
                    "medium": sum(1 for f in self.data.findings if f.severity == "medium"),
                    "low": sum(1 for f in self.data.findings if f.severity == "low"),
                    "info": sum(1 for f in self.data.findings if f.severity == "info"),
                },
                "by_priority": priority_counts,
                "tests_generated": len(self.data.generated_tests),
                "patches_generated": len(self.data.patches),
            },
            # Detailed findings (CI-friendly format)
            "findings": [f.to_dict() for f in self.data.findings],
            # Coverage information
            "coverage": {
                "before": self.data.coverage_before,
                "after": self.data.coverage_after,
                "change": (self.data.coverage_after - self.data.coverage_before)
                if self.data.coverage_before and self.data.coverage_after
                else None,
            },
            # Generated artifacts
            "artifacts": {
                "tests": [
                    {
                        "filename": t.filename,
                        "type": t.test_type,
                        "target": t.target_file,
                    }
                    for t in self.data.generated_tests
                ],
                "patches": [
                    {
                        "filename": p.filename,
                        "target": p.target_file,
                        "lines_added": p.lines_added,
                        "lines_removed": p.lines_removed,
                    }
                    for p in self.data.patches
                ],
            },
            # Verified fixes (when allow_suggestions enabled)
            "verified_fixes": {
                "enabled": self.data.allow_suggestions_enabled,
                "total": len(self.data.verified_fixes),
                "verified": sum(1 for f in self.data.verified_fixes if f.fix_verified),
                "improvements": sum(1 for f in self.data.verified_fixes if f.is_improvement),
                "fixes": [vf.to_dict() for vf in self.data.verified_fixes],
            }
            if self.data.verified_fixes
            else None,
            # Metadata
            "metadata": {
                "roles_used": self.data.roles_used,
                "files_analyzed": len(self.data.files_analyzed),
                "total_lines": self.data.total_lines,
                "blocked_operations": len(self.data.blocked_operations),
                "errors": len(self.data.errors),
                "allow_suggestions": self.data.allow_suggestions_enabled,
            },
        }

    def _generate_verdict_explanation(self) -> str:
        """Generate a brief explanation for the verdict."""
        if self.data.verdict == QRVerdict.PASS:
            return "No significant issues were found during the investigation."
        elif self.data.verdict == QRVerdict.CONDITIONAL_PASS:
            return f"Found {self.data.high_count} high-severity issues that should be reviewed."
        elif self.data.verdict == QRVerdict.FAIL:
            return f"Found {self.data.critical_count} critical issues that require immediate attention."
        else:
            return f"Analysis could not complete due to {len(self.data.errors)} errors."

    def _header(self) -> str:
        """Generate report header."""
        return f"""# Quality Report (QR)

**Session ID**: `{self.data.session_id}`
**Mode**: {self.data.mode}
**Date**: {self.data.started_at.strftime("%Y-%m-%d %H:%M")}
**Duration**: {self.data.duration_seconds:.1f}s

---
"""

    def _executive_summary(self) -> str:
        """Generate executive summary section."""
        verdict = self.data.verdict

        verdict_display = {
            QRVerdict.PASS: "🟢 **PASS** - No significant issues found",
            QRVerdict.CONDITIONAL_PASS: "🟡 **CONDITIONAL PASS** - Issues found, review recommended",
            QRVerdict.FAIL: "🔴 **FAIL** - Critical issues require attention",
            QRVerdict.BLOCKED: "⚫ **BLOCKED** - Analysis could not complete",
        }

        lines = [
            "## Executive Summary",
            "",
            f"**Verdict**: {verdict_display[verdict]}",
            "",
            "### Findings Overview",
            "",
            "| Severity | Count | Action |",
            "|----------|-------|--------|",
            f"| 🔴 Critical | {self.data.critical_count} | Must fix |",
            f"| 🟠 High | {self.data.high_count} | Should fix |",
            f"| 🟡 Medium | {sum(1 for f in self.data.findings if f.severity == 'medium')} | Consider |",
            f"| 🔵 Low | {sum(1 for f in self.data.findings if f.severity == 'low')} | Optional |",
            f"| ⚪ Info | {sum(1 for f in self.data.findings if f.severity == 'info')} | Note |",
            "",
        ]

        # Coverage change
        if self.data.coverage_before is not None and self.data.coverage_after is not None:
            change = self.data.coverage_after - self.data.coverage_before
            change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
            lines.extend(
                [
                    "### Coverage Impact",
                    "",
                    f"- Before: {self.data.coverage_before:.1f}%",
                    f"- After: {self.data.coverage_after:.1f}%",
                    f"- Change: {change_str}",
                    "",
                ]
            )

        # Artifacts generated
        if self.data.generated_tests or self.data.patches:
            lines.extend(
                [
                    "### Generated Artifacts",
                    "",
                    f"- 📝 {len(self.data.patches)} suggested fixes",
                    f"- 🧪 {len(self.data.generated_tests)} new tests",
                    "",
                ]
            )

        return "\n".join(lines)

    def _scope(self) -> str:
        """Generate scope section."""
        lines = [
            "## Investigation Scope",
            "",
        ]

        if self.data.target_description:
            lines.extend(
                [
                    f"**Target**: {self.data.target_description}",
                    "",
                ]
            )

        lines.extend(
            [
                f"- Files analyzed: {len(self.data.files_analyzed)}",
                f"- Total lines: {self.data.total_lines:,}",
            ]
        )

        if self.data.files_analyzed:
            lines.extend(
                [
                    "",
                    "<details>",
                    "<summary>Files analyzed</summary>",
                    "",
                ]
            )
            for f in self.data.files_analyzed[:20]:  # Limit to 20
                lines.append(f"- `{f}`")
            if len(self.data.files_analyzed) > 20:
                lines.append(f"- ... and {len(self.data.files_analyzed) - 20} more")
            lines.extend(
                [
                    "",
                    "</details>",
                ]
            )

        lines.append("")
        return "\n".join(lines)

    def _methodology(self) -> str:
        """Generate methodology section."""
        lines = [
            "## Methodology",
            "",
        ]

        if self.data.roles_used:
            lines.append("**QE Roles Used**:")
            for role in self.data.roles_used:
                lines.append(f"- {role}")
            lines.append("")

        if self.data.tools_used:
            lines.append("**Tools/Techniques**:")
            for tool in self.data.tools_used:
                lines.append(f"- {tool}")
            lines.append("")

        if self.data.methodology_notes:
            lines.append("**Approach**:")
            for note in self.data.methodology_notes:
                lines.append(f"- {note}")
            lines.append("")

        return "\n".join(lines)

    def _findings(self) -> str:
        """Generate findings section."""
        if not self.data.findings:
            return """## Findings

✅ No issues found during this investigation.
"""

        lines = [
            "## Findings",
            "",
        ]

        # Group by severity
        for severity in ["critical", "high", "medium", "low", "info"]:
            severity_findings = [f for f in self.data.findings if f.severity == severity]
            if not severity_findings:
                continue

            severity_title = severity.title()
            lines.append(f"### {severity_title} ({len(severity_findings)})")
            lines.append("")

            for finding in severity_findings:
                lines.extend(self._render_finding(finding))
                lines.append("")

        return "\n".join(lines)

    def _render_finding(self, finding: Finding) -> List[str]:
        """Render a single finding."""
        lines = [
            f"#### {finding.severity_icon} {finding.title}",
            "",
        ]

        if finding.location:
            lines.append(f"**Location**: `{finding.location}`")
            lines.append("")

        lines.append(finding.description)
        lines.append("")

        if finding.evidence:
            lines.extend(
                [
                    "**Evidence**:",
                    "```",
                    finding.evidence,
                    "```",
                    "",
                ]
            )

        if finding.reproduction_steps:
            lines.append("**Reproduction Steps**:")
            for i, step in enumerate(finding.reproduction_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        if finding.patch_id:
            lines.append(f"💡 **Suggested Fix**: See patch `{finding.patch_id}`")
            lines.append("")

        if finding.references:
            lines.append("**References**:")
            for ref in finding.references:
                lines.append(f"- {ref}")
            lines.append("")

        return lines

    def _suggested_fixes(self) -> str:
        """Generate suggested fixes section."""
        if not self.data.patches:
            return ""

        lines = [
            "## Suggested Fixes",
            "",
            "The following patches have been generated and are available in `.superqode/qe-artifacts/patches/`:",
            "",
            "| Patch | Target | Changes | Description |",
            "|-------|--------|---------|-------------|",
        ]

        for patch in self.data.patches:
            changes = f"+{patch.lines_added}/-{patch.lines_removed}"
            lines.append(
                f"| `{patch.filename}` | `{patch.target_file}` | {changes} | {patch.description} |"
            )

        lines.extend(
            [
                "",
                "**To apply a patch**:",
                "```bash",
                "cd /path/to/project",
                "patch -p1 < .superqode/qe-artifacts/patches/<patch-file>.patch",
                "```",
                "",
            ]
        )

        return "\n".join(lines)

    def _fix_verification(self) -> str:
        """Generate fix verification section (when allow_suggestions is enabled)."""
        if not self.data.verified_fixes:
            return ""

        lines = [
            "## Fix Verification Results",
            "",
            "The following fixes were verified in sandbox environment.",
            "All changes have been **reverted** - patches preserved for your review.",
            "",
        ]

        # Summary table
        verified_count = sum(1 for f in self.data.verified_fixes if f.fix_verified)
        improvement_count = sum(1 for f in self.data.verified_fixes if f.is_improvement)

        lines.extend(
            [
                "### Summary",
                "",
                f"- Total fixes attempted: {len(self.data.verified_fixes)}",
                f"- Verified successful: {verified_count}",
                f"- Confirmed improvements: {improvement_count}",
                "",
                "### Verification Details",
                "",
                "| Finding | Fix Status | Tests Before | Tests After | Improvement |",
                "|---------|------------|--------------|-------------|-------------|",
            ]
        )

        for vf in self.data.verified_fixes:
            status = "✅ Verified" if vf.fix_verified else "❌ Failed"
            before = f"{vf.tests_before_passed}/{vf.tests_before_total}"
            after = f"{vf.tests_after_passed}/{vf.tests_after_total}"
            improvement = "✅ Yes" if vf.is_improvement else "❌ No"

            lines.append(
                f"| {vf.finding_title[:30]}... | {status} | {before} | {after} | {improvement} |"
            )

        lines.append("")

        # Detailed verification for improvements
        improvements = [vf for vf in self.data.verified_fixes if vf.is_improvement]
        if improvements:
            lines.extend(
                [
                    "### Recommended Fixes (Verified Improvements)",
                    "",
                ]
            )

            for vf in improvements:
                lines.extend(
                    [
                        f"#### {vf.finding_title}",
                        "",
                        f"**Patch**: `{vf.patch_file}`",
                        f"**Confidence**: {vf.fix_confidence:.0%}",
                        "",
                        "**Verification Evidence**:",
                        "",
                    ]
                )

                for evidence in vf.verification_evidence:
                    lines.append(f"- {evidence}")

                lines.append("")

                # Before/after comparison
                if vf.tests_fixed > 0:
                    lines.append(f"✅ **Fixed {vf.tests_fixed} failing test(s)**")

                if vf.coverage_delta and vf.coverage_delta > 0:
                    lines.append(f"✅ **Coverage improved by {vf.coverage_delta:.1f}%**")

                lines.extend(
                    [
                        "",
                        "---",
                        "",
                    ]
                )

        # Note about revert
        lines.extend(
            [
                "### Important",
                "",
                "🔄 **All changes have been reverted to preserve your original code.**",
                "",
                "The patches are available in `.superqode/qe-artifacts/patches/` for you to review and apply.",
                "",
            ]
        )

        return "\n".join(lines)

    def _generated_tests(self) -> str:
        """Generate tests section."""
        if not self.data.generated_tests:
            return ""

        lines = [
            "## Generated Tests",
            "",
            "The following tests have been generated and are available in `.superqode/qe-artifacts/generated-tests/`:",
            "",
        ]

        # Group by type
        by_type: Dict[str, List[TestArtifact]] = {}
        for test in self.data.generated_tests:
            by_type.setdefault(test.test_type, []).append(test)

        for test_type, tests in by_type.items():
            lines.append(f"### {test_type.title()} Tests ({len(tests)})")
            lines.append("")

            for test in tests:
                target = f" (for `{test.target_file}`)" if test.target_file else ""
                lines.append(f"- `{test.filename}`{target}: {test.description}")

            lines.append("")

        lines.extend(
            [
                "**To run generated tests**:",
                "```bash",
                "# Copy tests to your test directory",
                "cp .superqode/qe-artifacts/generated-tests/unit/* tests/",
                "",
                "# Run tests",
                "pytest tests/",
                "```",
                "",
            ]
        )

        return "\n".join(lines)

    def _benchmarks(self) -> str:
        """Generate benchmarks section."""
        if not self.data.benchmarks:
            return ""

        lines = [
            "## Benchmark Results",
            "",
            "| Metric | Value | Baseline | Status |",
            "|--------|-------|----------|--------|",
        ]

        for bench in self.data.benchmarks:
            status = "✅" if bench.passed else "❌"
            baseline = f"{bench.baseline}{bench.unit}" if bench.baseline else "-"
            lines.append(f"| {bench.name} | {bench.value}{bench.unit} | {baseline} | {status} |")

        lines.append("")
        return "\n".join(lines)

    def _recommendations(self) -> str:
        """Generate recommendations section."""
        lines = [
            "## Recommendations",
            "",
        ]

        # Priority actions based on findings
        if self.data.critical_count > 0:
            lines.extend(
                [
                    "### 🚨 Immediate Actions Required",
                    "",
                ]
            )
            for f in self.data.findings:
                if f.severity == "critical":
                    action = f"Apply patch `{f.patch_id}`" if f.patch_id else "Manual fix required"
                    lines.append(f"1. **{f.title}** - {action}")
            lines.append("")

        if self.data.high_count > 0:
            lines.extend(
                [
                    "### ⚠️ Should Address",
                    "",
                ]
            )
            for f in self.data.findings:
                if f.severity == "high":
                    lines.append(f"- {f.title}")
            lines.append("")

        # General recommendations
        lines.extend(
            [
                "### 📋 General",
                "",
            ]
        )

        if self.data.generated_tests:
            lines.append("- Review and integrate generated tests to improve coverage")

        if self.data.patches:
            lines.append("- Review suggested patches before applying")

        if self.data.coverage_after and self.data.coverage_after < 80:
            lines.append(
                f"- Consider increasing test coverage (currently {self.data.coverage_after:.1f}%)"
            )

        lines.append("")
        return "\n".join(lines)

    def _appendix(self) -> str:
        """Generate appendix section."""
        lines = []

        if self.data.blocked_operations:
            lines.extend(
                [
                    "## Appendix A: Blocked Operations",
                    "",
                    "The following operations were blocked to maintain repo integrity:",
                    "",
                ]
            )
            for op in self.data.blocked_operations:
                lines.append(f"- `{op}`")
            lines.append("")

        if self.data.errors:
            lines.extend(
                [
                    "## Appendix B: Errors",
                    "",
                    "The following errors occurred during the investigation:",
                    "",
                ]
            )
            for err in self.data.errors:
                lines.append(f"- {err}")
            lines.append("")

        return "\n".join(lines) if lines else ""

    def _footer(self) -> str:
        """Generate report footer."""
        return """---

*Generated by SuperQode - Agentic Quality Engineering*

All changes made during this investigation have been reverted.
Artifacts are preserved in `.superqode/qe-artifacts/` for review and integration.
"""

    def save(self, output_dir: Path, formats: List[str] = None) -> Dict[str, Path]:
        """
        Save QIR to files.

        Args:
            output_dir: Directory to save to
            formats: List of formats ("md", "json"). Default: both

        Returns:
            Dict mapping format to file path
        """
        formats = formats or ["md", "json"]
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = self.data.started_at.strftime("%Y-%m-%d")
        base_name = f"qr-{timestamp}-{self.data.session_id[:8]}"

        saved = {}

        if "md" in formats:
            md_path = output_dir / f"{base_name}.md"
            md_path.write_text(self.generate_markdown())
            saved["md"] = md_path

        if "json" in formats:
            json_path = output_dir / f"{base_name}.json"
            json_path.write_text(json.dumps(self.generate_json(), indent=2))
            saved["json"] = json_path

        return saved
