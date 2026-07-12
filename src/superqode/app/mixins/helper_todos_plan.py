"""Todo list and plan-manager synchronization."""

from __future__ import annotations
from typing import Any
from textual.widgets import Static
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.plan import (
    TaskStatus,
    TaskPriority,
)


class HelperTodosPlanMixin:
    """Todo list and plan-manager synchronization."""

    def _refresh_plan_status_badge(self) -> None:
        """Show whether plan mode is active or awaiting a decision."""
        try:
            from superqode.app.widgets import ColorfulStatusBar

            state = ""
            pending = getattr(self, "_pending_plan_request", "").strip()
            pending_status = getattr(self, "_pending_plan_status", "")
            if pending and pending_status == "pending":
                state = "pending"
            elif getattr(self, "_active_plan_mode_for_current_message", False):
                state = "active"
            elif getattr(self, "_plan_mode_enabled", False):
                state = "ON"
            self.query_one("#status-bar", ColorfulStatusBar).plan_state = state
        except Exception:  # noqa: BLE001
            pass
        self._refresh_prompt_mode_label()
    def _set_todos(self, todos: list) -> None:
        """Update the pinned live todo/plan panel from the latest todo data."""
        try:
            panel = self.query_one("#todo-panel", Static)
        except Exception:
            return
        items = [t for t in (todos or []) if isinstance(t, dict)]
        self._sync_plan_manager_from_todos(items)
        # Hide once every task is finished (or there are none) to avoid clutter.
        active = [t for t in items if t.get("status") not in ("completed", "cancelled")]
        if not items or not active:
            panel.update("")
            panel.remove_class("visible")
            return

        status_icons = {
            "completed": ("✅", THEME["success"]),
            "in_progress": ("🔄", THEME["cyan"]),
            "pending": ("⏳", THEME["muted"]),
            "cancelled": ("❌", THEME["error"]),
        }
        done = sum(1 for t in items if t.get("status") == "completed")
        t = Text()
        t.append("  📋 Plan  ", style=f"bold {THEME['purple']}")
        t.append(f"{done}/{len(items)} done\n", style=THEME["muted"])
        for index, todo in enumerate(items[:6], 1):
            status = todo.get("status", "pending")
            icon, color = status_icons.get(status, ("○", THEME["muted"]))
            content = " ".join(str(todo.get("content", "")).split())
            if len(content) > 70:
                content = content[:67].rstrip() + "..."
            text_style = THEME["dim"] if status in ("completed", "cancelled") else THEME["text"]
            t.append(f"  {icon} ", style=color)
            t.append(content, style=text_style)
            t.append("\n", style="")
        if len(items) > 6:
            t.append(f"  +{len(items) - 6} more\n", style=THEME["dim"])
        panel.update(t)
        panel.add_class("visible")
    def _sync_plan_manager_from_todos(self, todos: list[dict]) -> None:
        """Mirror live todo_write/SDK plan updates into :plan state."""
        self._plan_manager.clear()
        if not todos:
            return
        self._plan_manager.current_plan_name = "Agent Plan"
        status_map = {
            "pending": TaskStatus.PENDING,
            "in_progress": TaskStatus.IN_PROGRESS,
            "completed": TaskStatus.COMPLETED,
            "cancelled": TaskStatus.FAILED,
            "canceled": TaskStatus.FAILED,
            "failed": TaskStatus.FAILED,
            "skipped": TaskStatus.SKIPPED,
        }
        priority_map = {
            "low": TaskPriority.LOW,
            "medium": TaskPriority.MEDIUM,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL,
        }
        for index, todo in enumerate(todos, 1):
            content = " ".join(str(todo.get("content") or todo.get("text") or "").split())
            if not content:
                continue
            priority = priority_map.get(str(todo.get("priority") or "medium").lower())
            task = self._plan_manager.add_task(content, priority=priority or TaskPriority.MEDIUM)
            task.id = str(todo.get("id") or index)
            status = status_map.get(
                str(todo.get("status") or "pending").lower(), TaskStatus.PENDING
            )
            self._plan_manager.update_status(task.id, status)
    def _set_todos_from_input(self, tool_input: dict) -> None:
        """Update the todo panel from a todo_write tool input payload."""
        if isinstance(tool_input, dict):
            todos = tool_input.get("todos")
            if isinstance(todos, list):
                self._set_todos(todos)
    def _is_todo_list(self, data: Any) -> bool:
        """Check if data looks like a TODO list."""
        if not isinstance(data, list) or not data:
            return False
        first = data[0]
        if not isinstance(first, dict):
            return False
        return any(k in first for k in ("status", "title", "priority", "completed"))
