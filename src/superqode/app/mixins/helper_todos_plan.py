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
            elif (
                pending
                and getattr(self, "_pending_plan_content", "").strip()
                and pending_status in ("approved", "executing")
            ):
                state = pending_status
            elif getattr(self, "_active_plan_mode_for_current_message", False):
                state = "active"
            elif getattr(self, "_plan_mode_enabled", False):
                state = "ON"
            self.query_one("#status-bar", ColorfulStatusBar).plan_state = state
        except Exception:  # noqa: BLE001
            pass
        self._refresh_plan_review_panel()
        self._refresh_prompt_mode_label()

    def _refresh_plan_review_panel(self) -> None:
        """Render the persistent decision card for a completed planning turn."""
        try:
            panel = self.query_one("#plan-review-panel", Static)
        except Exception:
            return

        content = str(getattr(self, "_pending_plan_content", "") or "").strip()
        status = str(getattr(self, "_pending_plan_status", "") or "")
        request = " ".join(str(getattr(self, "_pending_plan_request", "") or "").split())
        if not content or status not in ("pending", "approved", "executing"):
            panel.update("")
            panel.remove_class("visible")
            return

        from superqode.app.mixins.clickable_commands import command_link

        state_label = {
            "pending": "READY FOR REVIEW",
            "approved": "APPROVED",
            "executing": "EXECUTING",
        }[status]
        state_color = THEME["warning"] if status == "pending" else THEME["success"]
        text = Text()
        text.append("  ◆ PLAN ", style=f"bold {THEME['purple']}")
        text.append(state_label, style=f"bold {state_color}")
        text.append("\n")
        if request:
            goal = request if len(request) <= 100 else request[:97].rstrip() + "…"
            text.append("  Goal  ", style=THEME["muted"])
            text.append(goal, style=THEME["text"])
            text.append("\n")

        if status == "pending":
            text.append("  [", style=THEME["dim"])
            text.append(
                "Approve ↗",
                style=f"bold {THEME['success']} {command_link('plan-approve')}",
            )
            text.append("]  [", style=THEME["dim"])
            text.append(
                "Edit ↗",
                style=f"bold {THEME['cyan']} {command_link('plan-edit')}",
            )
            text.append("]  [", style=THEME["dim"])
            text.append(
                "Reject ↗",
                style=f"bold {THEME['error']} {command_link('plan-reject')}",
            )
            text.append("]", style=THEME["dim"])
            text.append("   Alt+A · Alt+E · Alt+R", style=THEME["muted"])
        else:
            text.append(
                "  The approved plan is preserved as execution context.", style=THEME["muted"]
            )
        panel.update(text)
        panel.add_class("visible")

    def _capture_plan_artifact(self, response_text: str) -> bool:
        """Remember the exact planning response that the user will approve."""
        if not getattr(self, "_active_plan_mode_for_current_message", False):
            return False
        content = str(response_text or "").strip()
        if not content:
            return False
        self._pending_plan_content = content
        self._pending_plan_status = "pending"
        self._refresh_plan_status_badge()
        return True

    def _approved_plan_execution_prompt(self, request: str, plan: str) -> str:
        """Bind execution to the reviewed plan instead of asking the model to re-plan."""
        return (
            "Implement the approved plan below. Treat it as the execution contract: "
            "follow its steps, affected files, risks, and verification strategy. "
            "If repository reality requires a material deviation, explain it before "
            "changing scope.\n\n"
            f"ORIGINAL REQUEST\n{request.strip()}\n\n"
            f"APPROVED PLAN\n{plan.strip()}"
        )

    def _mark_approved_plan_executed(self) -> None:
        if getattr(self, "_pending_plan_status", "") != "executing":
            return
        self._pending_plan_status = "executed"
        self._approved_plan_for_next_run = ""
        self._refresh_plan_status_badge()

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
