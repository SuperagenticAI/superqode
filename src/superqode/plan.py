"""
SuperQode Plan Widget - Task Planning & Progress Display

A beautiful task plan visualization with:
- Priority levels with color coding
- Status tracking (pending, in_progress, completed, failed)
- Progress animations
- Gradient styling
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Callable
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.box import ROUNDED, SIMPLE


class TaskStatus(Enum):
    """Task status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskPriority(Enum):
    """Task priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PlanTask:
    """A single task in the plan."""

    id: str
    content: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    parent_id: Optional[str] = None
    subtasks: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# SuperQode plan colors
PLAN_COLORS = {
    # Status colors
    "pending": "#71717a",
    "in_progress": "#06b6d4",
    "completed": "#22c55e",
    "failed": "#ef4444",
    "skipped": "#52525b",
    # Priority colors
    "low": "#3b82f6",
    "medium": "#f59e0b",
    "high": "#f97316",
    "critical": "#ef4444",
    # UI colors
    "header": "#a855f7",
    "border": "#2a2a2a",
    "progress_bar": "#ec4899",
}

# Status icons
STATUS_ICONS = {
    TaskStatus.PENDING: "⏳",
    TaskStatus.IN_PROGRESS: "🔄",
    TaskStatus.COMPLETED: "✅",
    TaskStatus.FAILED: "❌",
    TaskStatus.SKIPPED: "⏭️",
}

# Priority icons
PRIORITY_ICONS = {
    TaskPriority.LOW: "🔵",
    TaskPriority.MEDIUM: "🟡",
    TaskPriority.HIGH: "🟠",
    TaskPriority.CRITICAL: "🔴",
}


class PlanManager:
    """Manages task plans and progress tracking."""

    def __init__(self):
        self.tasks: List[PlanTask] = []
        self.current_plan_name: str = "Agent Plan"
        self._task_counter = 0

    def _generate_id(self) -> str:
        """Generate a unique task ID."""
        self._task_counter += 1
        return f"task_{self._task_counter}"

    def add_task(
        self,
        content: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parent_id: Optional[str] = None,
    ) -> PlanTask:
        """Add a new task to the plan."""
        task = PlanTask(
            id=self._generate_id(), content=content, priority=priority, parent_id=parent_id
        )
        self.tasks.append(task)

        # Link to parent if specified
        if parent_id:
            for t in self.tasks:
                if t.id == parent_id:
                    t.subtasks.append(task.id)
                    break

        return task

    def update_status(self, task_id: str, status: TaskStatus) -> bool:
        """Update a task's status."""
        for task in self.tasks:
            if task.id == task_id:
                task.status = status
                if status == TaskStatus.COMPLETED:
                    task.completed_at = datetime.now()
                return True
        return False

    def start_task(self, task_id: str) -> bool:
        """Mark a task as in progress."""
        return self.update_status(task_id, TaskStatus.IN_PROGRESS)

    def complete_task(self, task_id: str) -> bool:
        """Mark a task as completed."""
        return self.update_status(task_id, TaskStatus.COMPLETED)

    def fail_task(self, task_id: str) -> bool:
        """Mark a task as failed."""
        return self.update_status(task_id, TaskStatus.FAILED)

    def get_progress(self) -> tuple:
        """Get progress statistics."""
        total = len(self.tasks)
        if total == 0:
            return 0, 0, 0.0

        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        in_progress = sum(1 for t in self.tasks if t.status == TaskStatus.IN_PROGRESS)
        percentage = (completed / total) * 100

        return completed, total, percentage

    def get_current_task(self) -> Optional[PlanTask]:
        """Get the currently active task."""
        for task in self.tasks:
            if task.status == TaskStatus.IN_PROGRESS:
                return task
        return None

    def get_next_task(self) -> Optional[PlanTask]:
        """Get the next pending task."""
        # Sort by priority (critical first)
        priority_order = {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.MEDIUM: 2,
            TaskPriority.LOW: 3,
        }

        pending = [t for t in self.tasks if t.status == TaskStatus.PENDING]
        if not pending:
            return None

        pending.sort(key=lambda t: priority_order.get(t.priority, 2))
        return pending[0]

    def clear(self) -> None:
        """Clear all tasks."""
        self.tasks.clear()
        self._task_counter = 0

    def from_list(self, items: List[str], priority: TaskPriority = TaskPriority.MEDIUM) -> None:
        """Create tasks from a list of strings."""
        self.clear()
        for item in items:
            self.add_task(item, priority)


def render_plan(manager: PlanManager, console: Console, show_completed: bool = True) -> None:
    """Render the task plan with beautiful styling."""
    if not manager.tasks:
        console.print("  [dim]No plan yet[/dim]")
        return

    # Progress header
    completed, total, percentage = manager.get_progress()

    header = Text()
    header.append(f" 📋 ", style="bold")
    header.append(manager.current_plan_name, style="bold white")
    header.append("  ", style="")
    header.append(f"{completed}/{total}", style=f"bold {PLAN_COLORS['completed']}")
    header.append(f" ({percentage:.0f}%)", style="dim")

    console.print(Panel(header, border_style=PLAN_COLORS["header"], box=ROUNDED, padding=(0, 1)))

    # Progress bar
    bar_width = 40
    filled = int((percentage / 100) * bar_width)
    empty = bar_width - filled

    bar = Text()
    bar.append("  ", style="")
    bar.append("█" * filled, style=PLAN_COLORS["progress_bar"])
    bar.append("░" * empty, style="dim")
    bar.append(f" {percentage:.0f}%", style="bold white")
    console.print(bar)
    console.print()

    # Task list
    for i, task in enumerate(manager.tasks):
        if not show_completed and task.status == TaskStatus.COMPLETED:
            continue

        render_task(task, console, index=i + 1)


def render_task(task: PlanTask, console: Console, index: int = 0, indent: int = 0) -> None:
    """Render a single task."""
    status_icon = STATUS_ICONS.get(task.status, "○")
    priority_icon = PRIORITY_ICONS.get(task.priority, "")
    status_color = PLAN_COLORS.get(task.status.value, PLAN_COLORS["pending"])

    # Build task line
    line = Text()
    line.append("  " * indent, style="")

    # Index
    if index > 0:
        line.append(f"{index:>2}. ", style="dim")

    # Status icon
    line.append(f"{status_icon} ", style=status_color)

    # Priority indicator (only for non-completed)
    if task.status != TaskStatus.COMPLETED and task.priority in (
        TaskPriority.HIGH,
        TaskPriority.CRITICAL,
    ):
        line.append(f"{priority_icon} ", style="")

    # Content with strikethrough for completed
    if task.status == TaskStatus.COMPLETED:
        line.append(task.content, style=f"strike {status_color}")
    elif task.status == TaskStatus.IN_PROGRESS:
        line.append(task.content, style=f"bold {status_color}")
    elif task.status == TaskStatus.FAILED:
        line.append(task.content, style=f"{status_color}")
    else:
        line.append(task.content, style="white")

    # Duration for completed tasks
    if task.completed_at and task.created_at:
        duration = (task.completed_at - task.created_at).total_seconds()
        if duration < 60:
            dur_str = f"{duration:.1f}s"
        else:
            dur_str = f"{duration / 60:.1f}m"
        line.append(f" ({dur_str})", style="dim")

    console.print(line)


def render_plan_compact(manager: PlanManager, console: Console) -> None:
    """Render a compact one-line plan summary."""
    if not manager.tasks:
        return

    completed, total, percentage = manager.get_progress()
    current = manager.get_current_task()

    line = Text()
    line.append("📋 ", style="")
    line.append(f"{completed}/{total}", style=f"bold {PLAN_COLORS['completed']}")

    if current:
        line.append(" │ ", style="dim")
        line.append("🔄 ", style=PLAN_COLORS["in_progress"])
        content = current.content[:40] + "..." if len(current.content) > 40 else current.content
        line.append(content, style=PLAN_COLORS["in_progress"])

    console.print(line)


def render_current_task(manager: PlanManager, console: Console) -> None:
    """Render just the current task with emphasis."""
    current = manager.get_current_task()
    if not current:
        next_task = manager.get_next_task()
        if next_task:
            console.print(f"  [dim]Next:[/dim] {next_task.content}")
        else:
            console.print("  [green]✅ All tasks completed![/green]")
        return

    line = Text()
    line.append("  🔄 ", style=f"bold {PLAN_COLORS['in_progress']}")
    line.append("Current: ", style="bold white")
    line.append(current.content, style=f"bold {PLAN_COLORS['in_progress']}")

    console.print(line)
