"""
TODO Management Tools - Task planning and tracking.

Helps models plan and track multi-step tasks with status updates.
"""

import json
import re
from typing import Any, Dict, List

from .base import Tool, ToolResult, ToolContext

# Session-based in-memory storage: session_id -> list of todo items
_todo_store: Dict[str, List[Dict[str, Any]]] = {}


def _todo_path(ctx: ToolContext):
    safe_session_id = re.sub(r"[^A-Za-z0-9_.:-]+", "_", getattr(ctx, "session_id", "") or "default")
    return ctx.working_directory / ".superqode" / "todos" / f"{safe_session_id}.json"


def _load_todos(ctx: ToolContext) -> List[Dict[str, Any]]:
    session_id = getattr(ctx, "session_id", None) or ""
    if session_id in _todo_store:
        return _todo_store[session_id]

    path = _todo_path(ctx)
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    todos = [item for item in loaded if isinstance(item, dict)]
    _todo_store[session_id] = todos
    return todos


def _save_todos(ctx: ToolContext, todos: List[Dict[str, Any]]) -> None:
    session_id = getattr(ctx, "session_id", None) or ""
    _todo_store[session_id] = todos
    path = _todo_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(todos, indent=2), encoding="utf-8")


class TodoWriteTool(Tool):
    """Create or update the TODO list for the current session."""

    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return (
            "Create and manage a structured task list for the current coding session. "
            "Use for complex multi-step tasks (3+ steps), non-trivial work, or when the user "
            "provides multiple tasks. Track progress with status: pending, in_progress, completed, cancelled. "
            "Mark tasks in_progress when starting and completed when done. Keep only ONE in_progress at a time."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The full list of todo items (replaces existing list)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique identifier for the todo item",
                            },
                            "content": {
                                "type": "string",
                                "description": "Brief description of the task",
                            },
                            "status": {
                                "type": "string",
                                "description": "Current status: pending, in_progress, completed, cancelled",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                            },
                            "priority": {
                                "type": "string",
                                "description": "Priority: high, medium, low (default: medium)",
                                "enum": ["high", "medium", "low"],
                            },
                        },
                        "required": ["id", "content", "status"],
                    },
                }
            },
            "required": ["todos"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        todos = args.get("todos", [])
        # Normalize: ensure each item has id, content, status; optional priority
        normalized = []
        for t in todos:
            item = {
                "id": str(t.get("id", "")),
                "content": str(t.get("content", "")),
                "status": str(t.get("status", "pending")).lower(),
                "priority": str(t.get("priority", "medium")).lower(),
            }
            if item["status"] not in ("pending", "in_progress", "completed", "cancelled"):
                item["status"] = "pending"
            if item["priority"] not in ("high", "medium", "low"):
                item["priority"] = "medium"
            normalized.append(item)
        _save_todos(ctx, normalized)
        pending = sum(1 for t in normalized if t["status"] not in ("completed", "cancelled"))
        return ToolResult(
            success=True,
            output=f"Todo list updated. {len(normalized)} items, {pending} pending.",
            metadata={"todos": normalized, "count": len(normalized), "persisted": True},
        )


class TodoReadTool(Tool):
    """Read the current TODO list for the session."""

    @property
    def name(self) -> str:
        return "todo_read"

    @property
    def description(self) -> str:
        return (
            "Read the current todo list for the session. Use at the start of work, before starting "
            "new tasks, or when uncertain about next steps. Returns items with id, content, status, priority. "
            "If no todos exist, returns an empty list. Leave parameters empty."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        todos = _load_todos(ctx)
        return ToolResult(
            success=True,
            output=json.dumps(todos, indent=2),
            metadata={"todos": todos, "count": len(todos), "persisted": True},
        )
