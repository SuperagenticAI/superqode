"""
Issue Discovery Timeline Widget.

A SuperQode-original widget showing issues discovered during QE sessions
in a chronological timeline format with severity indicators.

Design: Clean, scannable timeline that emphasizes issue severity
and provides quick access to details.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class IssueSeverity(Enum):
    """Severity level of an issue."""

    CRITICAL = "critical"  # Red - security, crash
    HIGH = "high"  # Orange - bugs, failures
    MEDIUM = "medium"  # Yellow - warnings
    LOW = "low"  # Green - suggestions
    INFO = "info"  # Blue - informational


class IssueCategory(Enum):
    """Category of the issue."""

    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    COVERAGE = "coverage"
    STYLE = "style"
    COMPLEXITY = "complexity"
    DEPENDENCY = "dependency"
    TEST = "test"
    OTHER = "other"


@dataclass
class DiscoveredIssue:
    """An issue discovered during QE analysis."""

    id: str
    severity: IssueSeverity
    category: IssueCategory
    title: str
    file_path: str = ""
    line_number: Optional[int] = None
    description: str = ""
    discovered_at: datetime = field(default_factory=datetime.now)
    discovered_by: str = ""  # Agent name
    verified: bool = False
    fixed: bool = False

    @property
    def location(self) -> str:
        """Get formatted location string."""
        if self.line_number:
            return f"{self.file_path}:{self.line_number}"
        return self.file_path


# Severity styling
SEVERITY_STYLES = {
    IssueSeverity.CRITICAL: {"color": "#ef4444", "icon": "🔴", "label": "CRITICAL"},
    IssueSeverity.HIGH: {"color": "#f97316", "icon": "🟠", "label": "HIGH"},
    IssueSeverity.MEDIUM: {"color": "#eab308", "icon": "🟡", "label": "MEDIUM"},
    IssueSeverity.LOW: {"color": "#22c55e", "icon": "🟢", "label": "LOW"},
    IssueSeverity.INFO: {"color": "#3b82f6", "icon": "🔵", "label": "INFO"},
}

CATEGORY_ICONS = {
    IssueCategory.BUG: "🐛",
    IssueCategory.SECURITY: "🔒",
    IssueCategory.PERFORMANCE: "⚡",
    IssueCategory.COVERAGE: "📊",
    IssueCategory.STYLE: "🎨",
    IssueCategory.COMPLEXITY: "🔄",
    IssueCategory.DEPENDENCY: "📦",
    IssueCategory.TEST: "🧪",
    IssueCategory.OTHER: "📝",
}


class IssueTimeline(Static):
    """Issue Discovery Timeline Widget.

    Displays issues discovered during QE sessions in chronological order
    with severity indicators and summary statistics.

    Usage:
        timeline = IssueTimeline()
        timeline.add_issue(DiscoveredIssue(
            id="issue-1",
            severity=IssueSeverity.HIGH,
            category=IssueCategory.BUG,
            title="NullRef in UserService.get()",
            file_path="src/api/user.py",
            line_number=45,
        ))
    """

    DEFAULT_CSS = """
    IssueTimeline {
        height: auto;
        border: solid #3f3f46;
        padding: 0 1;
        margin: 0 0 1 0;
        max-height: 20;
        overflow-y: auto;
    }
    """

    # Reactive state
    show_verified_only: reactive[bool] = reactive(False)
    show_category: reactive[Optional[IssueCategory]] = reactive(None)

    def __init__(
        self,
        title: str = "Discovery Timeline",
        max_visible: int = 10,
        compact: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self.max_visible = max_visible
        self.compact = compact
        self._issues: List[DiscoveredIssue] = []

    @property
    def issues(self) -> List[DiscoveredIssue]:
        """Get all issues."""
        return self._issues.copy()

    @property
    def filtered_issues(self) -> List[DiscoveredIssue]:
        """Get filtered issues based on current settings."""
        result = self._issues

        if self.show_verified_only:
            result = [i for i in result if i.verified]

        if self.show_category:
            result = [i for i in result if i.category == self.show_category]

        return result

    def add_issue(self, issue: DiscoveredIssue) -> None:
        """Add an issue to the timeline."""
        self._issues.append(issue)
        # Sort by time (newest first)
        self._issues.sort(key=lambda i: i.discovered_at, reverse=True)
        self.refresh()

    def mark_verified(self, issue_id: str) -> None:
        """Mark an issue as verified."""
        for issue in self._issues:
            if issue.id == issue_id:
                issue.verified = True
                break
        self.refresh()

    def mark_fixed(self, issue_id: str) -> None:
        """Mark an issue as fixed."""
        for issue in self._issues:
            if issue.id == issue_id:
                issue.fixed = True
                break
        self.refresh()

    def remove_issue(self, issue_id: str) -> None:
        """Remove an issue from the timeline."""
        self._issues = [i for i in self._issues if i.id != issue_id]
        self.refresh()

    def clear(self) -> None:
        """Clear all issues."""
        self._issues.clear()
        self.refresh()

    def get_summary(self) -> dict:
        """Get summary statistics."""
        counts = {sev: 0 for sev in IssueSeverity}
        for issue in self._issues:
            counts[issue.severity] += 1

        return {
            "total": len(self._issues),
            "verified": sum(1 for i in self._issues if i.verified),
            "fixed": sum(1 for i in self._issues if i.fixed),
            "by_severity": counts,
        }

    def _render_issue(self, issue: DiscoveredIssue) -> Text:
        """Render a single issue entry."""
        style = SEVERITY_STYLES[issue.severity]
        cat_icon = CATEGORY_ICONS.get(issue.category, "📝")

        result = Text()

        # Timestamp
        time_str = issue.discovered_at.strftime("%H:%M:%S")
        result.append(f"  {time_str}  ", style="#6b7280")

        # Severity indicator
        result.append(f"{style['icon']} ", style=style["color"])
        result.append(f"{style['label']:<8}", style=f"bold {style['color']}")

        # Title (truncate if too long)
        title = issue.title
        if len(title) > 40 and self.compact:
            title = title[:37] + "..."
        result.append(f"{title}", style="#e2e8f0")

        # Status badges
        if issue.verified:
            result.append(" ✓", style="bold #22c55e")
        if issue.fixed:
            result.append(" ✗", style="bold #3b82f6")

        return result

    def _render_summary_bar(self) -> Text:
        """Render the summary statistics bar."""
        summary = self.get_summary()
        counts = summary["by_severity"]

        result = Text()
        result.append("  Total: ", style="#6b7280")
        result.append(f"{summary['total']}", style="bold #e2e8f0")
        result.append(" issues", style="#6b7280")

        # Severity breakdown
        parts = []
        for sev in [
            IssueSeverity.CRITICAL,
            IssueSeverity.HIGH,
            IssueSeverity.MEDIUM,
            IssueSeverity.LOW,
        ]:
            if counts[sev] > 0:
                style = SEVERITY_STYLES[sev]
                parts.append(f"[{style['color']}]{counts[sev]} {style['label'].title()}[/]")

        if parts:
            result.append(" | ", style="#3f3f46")
            result.append_markup(" | ".join(parts))

        # Verified count
        if summary["verified"] > 0:
            result.append(" | ", style="#3f3f46")
            result.append(f"{summary['verified']} verified", style="#22c55e")

        return result

    def render(self) -> RenderableType:
        """Render the timeline."""
        content = Text()

        filtered = self.filtered_issues

        if not filtered:
            content.append("\n  No issues discovered yet\n", style="#6b7280")
        else:
            # Show issues (limited by max_visible)
            visible = filtered[: self.max_visible]

            for issue in visible:
                content.append(self._render_issue(issue))
                content.append("\n")

            # Show "more" indicator if truncated
            remaining = len(filtered) - len(visible)
            if remaining > 0:
                content.append(f"\n  ... and {remaining} more issues", style="#6b7280")
                content.append("\n")

        # Divider
        content.append("\n")
        content.append("  " + "═" * 50, style="#3f3f46")
        content.append("\n")

        # Summary bar
        content.append(self._render_summary_bar())
        content.append("\n")

        return Panel(
            content,
            title=f"[bold #f59e0b]{self.title}[/]",
            border_style="#3f3f46",
            padding=(0, 0),
        )


class CompactIssueTimeline(IssueTimeline):
    """Compact version of IssueTimeline for smaller spaces."""

    DEFAULT_CSS = """
    CompactIssueTimeline {
        height: auto;
        max-height: 8;
        border: solid #3f3f46;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("max_visible", 5)
        kwargs.setdefault("compact", True)
        super().__init__(**kwargs)

    def _render_issue(self, issue: DiscoveredIssue) -> Text:
        """Render a single issue in compact format."""
        style = SEVERITY_STYLES[issue.severity]

        result = Text()

        # Time (short format)
        time_str = issue.discovered_at.strftime("%H:%M")
        result.append(f"{time_str} ", style="#6b7280")

        # Severity dot
        result.append(f"{style['icon']} ", style=style["color"])

        # Title (shorter)
        title = issue.title
        if len(title) > 35:
            title = title[:32] + "..."
        result.append(title, style="#e2e8f0")

        return result
