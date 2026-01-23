"""
Progress Panel Widget - Shows session progress.

Displays the current session progress with steps:
- Completed steps
- Current step (with spinner)
- Pending steps
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.box import ROUNDED


class StepStatus(Enum):
    """Status of a progress step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class ProgressStep:
    """Represents a single progress step."""

    name: str
    description: str = ""
    status: StepStatus = StepStatus.PENDING
    substeps: List[str] = field(default_factory=list)

    @property
    def status_icon(self) -> str:
        """Get status icon."""
        return {
            StepStatus.PENDING: "[dim]○[/dim]",
            StepStatus.IN_PROGRESS: "[yellow]⟳[/yellow]",
            StepStatus.COMPLETE: "[green]✓[/green]",
            StepStatus.SKIPPED: "[dim]⊘[/dim]",
            StepStatus.ERROR: "[red]✗[/red]",
        }.get(self.status, "?")

    @property
    def style(self) -> str:
        """Get text style based on status."""
        return {
            StepStatus.PENDING: "dim",
            StepStatus.IN_PROGRESS: "bold yellow",
            StepStatus.COMPLETE: "green",
            StepStatus.SKIPPED: "dim",
            StepStatus.ERROR: "red",
        }.get(self.status, "")


class ProgressPanel:
    """
    Widget for displaying session progress.

    Shows a panel with progress steps and their status.
    """

    def __init__(
        self,
        title: str = "Session Progress",
        role: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        """
        Initialize the progress panel.

        Args:
            title: Panel title
            role: Current role (e.g., "qe.security")
            mode: Current mode (e.g., "Deep Scan")
        """
        self.title = title
        self.role = role
        self.mode = mode
        self.steps: List[ProgressStep] = []
        self.console = Console()

    def add_step(self, name: str, description: str = "") -> ProgressStep:
        """Add a new step."""
        step = ProgressStep(name=name, description=description)
        self.steps.append(step)
        return step

    def start_step(self, step: ProgressStep) -> None:
        """Mark a step as in progress."""
        step.status = StepStatus.IN_PROGRESS

    def complete_step(self, step: ProgressStep) -> None:
        """Mark a step as complete."""
        step.status = StepStatus.COMPLETE

    def error_step(self, step: ProgressStep) -> None:
        """Mark a step as errored."""
        step.status = StepStatus.ERROR

    def skip_step(self, step: ProgressStep) -> None:
        """Mark a step as skipped."""
        step.status = StepStatus.SKIPPED

    def get_current_step(self) -> Optional[ProgressStep]:
        """Get the current in-progress step."""
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                return step
        return None

    def render(self) -> Panel:
        """Render the progress panel as a Rich Panel."""
        lines = []

        # Header with role and mode
        if self.role or self.mode:
            header_parts = []
            if self.role:
                header_parts.append(f"[cyan]Role:[/cyan] {self.role}")
            if self.mode:
                header_parts.append(f"[cyan]Mode:[/cyan] {self.mode}")
            lines.append(Text.from_markup("  ".join(header_parts)))
            lines.append(Text())  # Empty line

        # Progress steps
        if not self.steps:
            lines.append(Text("No steps defined", style="dim"))
        else:
            for step in self.steps:
                # Main step line
                step_text = Text()
                step_text.append(step.status_icon)
                step_text.append(" ")
                step_text.append(step.name, style=step.style)
                if step.description and step.status == StepStatus.IN_PROGRESS:
                    step_text.append(f" - {step.description}", style="dim")
                lines.append(step_text)

                # Substeps (indented)
                if step.substeps and step.status == StepStatus.IN_PROGRESS:
                    for substep in step.substeps[-3:]:  # Show last 3 substeps
                        lines.append(Text(f"    {substep}", style="dim"))

        content = Group(*lines)

        return Panel(
            content,
            title=f"[bold]{self.title}[/bold]",
            border_style="cyan",
            box=ROUNDED,
        )

    def print(self) -> None:
        """Print the progress panel to console."""
        self.console.print(self.render())


def create_qe_progress(role: str, mode: str) -> ProgressPanel:
    """
    Create a progress panel for a QE session.

    Pre-populates with standard QE steps.
    """
    panel = ProgressPanel(
        title="SuperQE Session",
        role=role,
        mode=mode,
    )

    panel.add_step("Initializing workspace", "Setting up ephemeral environment")
    panel.add_step("Running test discovery", "Finding test files and suites")
    panel.add_step("Executing tests", "Running smoke/sanity/regression")
    panel.add_step("Analyzing results", "Processing test outcomes")
    panel.add_step("Detecting issues", "Proactive vulnerability scanning")
    panel.add_step("Generating QR", "Creating quality report")
    panel.add_step("Cleaning up", "Reverting changes, preserving artifacts")

    return panel
