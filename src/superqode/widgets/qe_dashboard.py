"""
QE Dashboard Widget - Quality Metrics Visualization.

A SuperQode-original widget showing real-time quality metrics
during QE sessions. Displays coverage, complexity, tech debt,
and active analysis progress.

Design: Distinctive SuperQode visualization that doesn't copy
from other coding agent tools.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
from textual.reactive import reactive
from textual.widgets import Static
from textual.timer import Timer


class MetricStatus(Enum):
    """Status indicator for quality metrics."""

    EXCELLENT = "excellent"  # Green
    GOOD = "good"  # Blue
    WARNING = "warning"  # Yellow
    CRITICAL = "critical"  # Red
    UNKNOWN = "unknown"  # Gray


@dataclass
class QualityMetric:
    """A single quality metric."""

    name: str
    value: float  # 0.0 to 100.0
    label: str = ""  # e.g., "82%", "Low", "A"
    status: MetricStatus = MetricStatus.UNKNOWN
    trend: str = ""  # "↑", "↓", "→"

    @classmethod
    def coverage(cls, value: float) -> "QualityMetric":
        """Create a coverage metric."""
        if value >= 80:
            status = MetricStatus.EXCELLENT
        elif value >= 60:
            status = MetricStatus.GOOD
        elif value >= 40:
            status = MetricStatus.WARNING
        else:
            status = MetricStatus.CRITICAL
        return cls("Coverage", value, f"{value:.0f}%", status)

    @classmethod
    def complexity(cls, value: float) -> "QualityMetric":
        """Create a complexity metric (lower is better)."""
        if value <= 10:
            status, label = MetricStatus.EXCELLENT, "Low"
        elif value <= 20:
            status, label = MetricStatus.GOOD, "Medium"
        elif value <= 30:
            status, label = MetricStatus.WARNING, "High"
        else:
            status, label = MetricStatus.CRITICAL, "Very High"
        return cls("Complexity", value, label, status)

    @classmethod
    def tech_debt(cls, value: float) -> "QualityMetric":
        """Create a tech debt metric (lower is better)."""
        if value <= 15:
            status = MetricStatus.EXCELLENT
        elif value <= 30:
            status = MetricStatus.GOOD
        elif value <= 50:
            status = MetricStatus.WARNING
        else:
            status = MetricStatus.CRITICAL
        return cls("Tech Debt", value, f"{value:.0f}%", status)

    @classmethod
    def test_health(cls, value: float) -> "QualityMetric":
        """Create a test health metric."""
        if value >= 90:
            status = MetricStatus.EXCELLENT
        elif value >= 75:
            status = MetricStatus.GOOD
        elif value >= 50:
            status = MetricStatus.WARNING
        else:
            status = MetricStatus.CRITICAL
        return cls("Test Health", value, f"{value:.0f}%", status)


@dataclass
class AnalysisTask:
    """An active analysis task."""

    file_path: str
    description: str
    progress: float = 0.0  # 0.0 to 1.0
    started_at: datetime = field(default_factory=datetime.now)


# Color palette for SuperQode branding
METRIC_COLORS = {
    MetricStatus.EXCELLENT: "#22c55e",  # Green
    MetricStatus.GOOD: "#3b82f6",  # Blue
    MetricStatus.WARNING: "#eab308",  # Yellow
    MetricStatus.CRITICAL: "#ef4444",  # Red
    MetricStatus.UNKNOWN: "#6b7280",  # Gray
}


class QEDashboard(Static):
    """Quality Engineering Dashboard Widget.

    Displays real-time quality metrics and active analysis progress
    in a compact, informative panel.

    Usage:
        dashboard = QEDashboard()
        dashboard.update_metric(QualityMetric.coverage(82))
        dashboard.set_active_analysis("src/api/handlers.py", "Checking boundaries...")
    """

    DEFAULT_CSS = """
    QEDashboard {
        height: auto;
        border: solid #3f3f46;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    # Reactive state
    metrics: reactive[List[QualityMetric]] = reactive(list)
    active_task: reactive[Optional[AnalysisTask]] = reactive(None)
    is_analyzing: reactive[bool] = reactive(False)

    def __init__(
        self,
        title: str = "Quality Pulse",
        compact: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self.compact = compact
        self._animation_frame = 0
        self._timer: Optional[Timer] = None

        # Default metrics
        self._metrics: List[QualityMetric] = [
            QualityMetric.coverage(0),
            QualityMetric.complexity(0),
            QualityMetric.tech_debt(0),
            QualityMetric.test_health(0),
        ]

    def on_mount(self) -> None:
        """Start animation timer when mounted."""
        self._timer = self.set_interval(0.1, self._tick, pause=True)

    def _tick(self) -> None:
        """Animation tick."""
        self._animation_frame += 1
        if self.active_task:
            self.refresh()

    def update_metric(self, metric: QualityMetric) -> None:
        """Update a specific metric by name."""
        for i, m in enumerate(self._metrics):
            if m.name == metric.name:
                self._metrics[i] = metric
                break
        else:
            self._metrics.append(metric)
        self.refresh()

    def set_metrics(
        self,
        coverage: Optional[float] = None,
        complexity: Optional[float] = None,
        tech_debt: Optional[float] = None,
        test_health: Optional[float] = None,
    ) -> None:
        """Convenience method to set multiple metrics at once."""
        if coverage is not None:
            self.update_metric(QualityMetric.coverage(coverage))
        if complexity is not None:
            self.update_metric(QualityMetric.complexity(complexity))
        if tech_debt is not None:
            self.update_metric(QualityMetric.tech_debt(tech_debt))
        if test_health is not None:
            self.update_metric(QualityMetric.test_health(test_health))

    def set_active_analysis(
        self,
        file_path: str,
        description: str,
        progress: float = 0.0,
    ) -> None:
        """Set the current active analysis task."""
        self.active_task = AnalysisTask(
            file_path=file_path,
            description=description,
            progress=progress,
        )
        self.is_analyzing = True
        if self._timer:
            self._timer.resume()
        self.refresh()

    def update_progress(self, progress: float, description: str = "") -> None:
        """Update the progress of the active analysis."""
        if self.active_task:
            self.active_task.progress = progress
            if description:
                self.active_task.description = description
            self.refresh()

    def clear_analysis(self) -> None:
        """Clear the active analysis task."""
        self.active_task = None
        self.is_analyzing = False
        if self._timer:
            self._timer.pause()
        self.refresh()

    def _render_progress_bar(self, value: float, width: int = 10) -> Text:
        """Render a progress bar with Unicode blocks."""
        filled = int(value / 100 * width)
        empty = width - filled

        bar = Text()
        bar.append("█" * filled, style="bold #22c55e")
        bar.append("░" * empty, style="#3f3f46")
        return bar

    def _render_metric(self, metric: QualityMetric) -> Text:
        """Render a single metric."""
        color = METRIC_COLORS[metric.status]

        result = Text()
        result.append(f"{metric.name}: ", style="#a1a1aa")
        result.append(self._render_progress_bar(metric.value))
        result.append(f" {metric.label}", style=f"bold {color}")

        if metric.trend:
            result.append(f" {metric.trend}", style="#6b7280")

        return result

    def _get_analysis_spinner(self) -> str:
        """Get animated spinner character."""
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        return spinners[self._animation_frame % len(spinners)]

    def render(self) -> RenderableType:
        """Render the dashboard."""
        content = Text()

        # Metrics row (2x2 grid in compact mode)
        if self.compact:
            # Compact: 2 metrics per row
            for i in range(0, len(self._metrics), 2):
                row_metrics = self._metrics[i : i + 2]
                for j, metric in enumerate(row_metrics):
                    content.append(self._render_metric(metric))
                    if j < len(row_metrics) - 1:
                        content.append("   ")
                content.append("\n")
        else:
            # Full: All metrics visible
            for metric in self._metrics:
                content.append(self._render_metric(metric))
                content.append("\n")

        # Active analysis section
        if self.active_task:
            content.append("\n")

            # File being analyzed
            spinner = self._get_analysis_spinner()
            content.append(f"{spinner} ", style="bold #3b82f6")
            content.append("Active Analysis: ", style="#a1a1aa")

            # Truncate path if too long
            path = self.active_task.file_path
            if len(path) > 35:
                path = "..." + path[-32:]
            content.append(path, style="bold #e2e8f0")
            content.append("\n")

            # Description
            content.append("  ├─ ", style="#3f3f46")
            content.append(self.active_task.description, style="#a1a1aa")
            content.append("\n")

            # Progress bar
            progress_pct = int(self.active_task.progress * 100)
            bar_width = 30
            filled = int(self.active_task.progress * bar_width)

            content.append("  └─ [", style="#3f3f46")
            content.append("█" * filled, style="bold #3b82f6")
            content.append("░" * (bar_width - filled), style="#27272a")
            content.append(f"] {progress_pct}%", style="#3f3f46")

        return Panel(
            content,
            title=f"[bold #3b82f6]{self.title}[/]",
            border_style="#3f3f46",
            padding=(0, 1),
        )
