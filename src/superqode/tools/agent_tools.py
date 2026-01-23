"""
Agent Tools - Sub-agent spawning and coordination.

Provides tools for:
- Spawning sub-agents for parallel work
- Task distribution and coordination
- Result collection and merging

This enables the main agent to delegate independent tasks
to sub-agents that run in parallel, improving efficiency
for complex multi-step operations.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import Tool, ToolResult, ToolContext


class SubTaskStatus(Enum):
    """Status of a sub-task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubTask:
    """A sub-task delegated to a sub-agent."""

    id: str
    description: str
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubAgentContext:
    """Context for sub-agent execution."""

    parent_session_id: str
    working_directory: Path
    task: SubTask
    shared_memory: Dict[str, Any] = field(default_factory=dict)


class SubAgentTool(Tool):
    """
    Spawn a sub-agent to handle an independent task.

    Use this when you need to:
    - Perform independent operations in parallel
    - Delegate a self-contained task
    - Explore multiple approaches simultaneously

    The sub-agent has access to the same tools as the parent,
    but operates in an isolated context to prevent conflicts.

    Example uses:
    - "Research how function X is used while I modify function Y"
    - "Run tests in the background while I continue coding"
    - "Search for patterns in multiple directories simultaneously"
    """

    # Track active sub-tasks
    _active_tasks: Dict[str, SubTask] = {}
    _task_results: Dict[str, SubTask] = {}

    @property
    def name(self) -> str:
        return "agent"

    @property
    def description(self) -> str:
        return "Spawn a sub-agent to handle an independent task in parallel. Use for tasks that don't depend on each other."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the task for the sub-agent to perform",
                },
                "action": {
                    "type": "string",
                    "enum": ["spawn", "status", "wait", "cancel"],
                    "description": "Action: spawn (create sub-agent), status (check task), wait (wait for completion), cancel (stop task)",
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (required for status/wait/cancel actions)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds for wait action (default: 60)",
                },
                "context": {
                    "type": "object",
                    "description": "Additional context to pass to sub-agent",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: restrict sub-agent to these tools only (permission filtering)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        action = args.get("action", "spawn")

        if action == "spawn":
            return await self._spawn_subtask(args, ctx)
        elif action == "status":
            return self._get_status(args)
        elif action == "wait":
            return await self._wait_for_task(args)
        elif action == "cancel":
            return self._cancel_task(args)
        else:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")

    async def _spawn_subtask(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Spawn a new sub-agent task."""
        task_description = args.get("task", "")
        additional_context = args.get("context", {}) or {}
        allowed_tools = args.get("allowed_tools")

        # Recursive delegation limit (max depth 3)
        depth = getattr(ctx, "delegation_depth", 0)
        if depth >= 3:
            return ToolResult(
                success=False,
                output="",
                error="Recursive delegation limit reached (max depth 3)",
            )

        if not task_description:
            return ToolResult(
                success=False, output="", error="Task description is required for spawn action"
            )

        # Merge metadata: delegation_depth, allowed_tools for child session
        child_depth = depth + 1
        additional_context["delegation_depth"] = child_depth
        if allowed_tools is not None:
            additional_context["allowed_tools"] = list(allowed_tools)

        # Create task
        task_id = f"subtask-{uuid.uuid4().hex[:8]}"
        task = SubTask(
            id=task_id,
            description=task_description,
            status=SubTaskStatus.PENDING,
            metadata=additional_context,
        )

        self._active_tasks[task_id] = task

        # Start the sub-task execution in background
        asyncio.create_task(self._execute_subtask(task, ctx))

        return ToolResult(
            success=True,
            output=f"Sub-agent spawned with task ID: {task_id}\n\n"
            f"Task: {task_description}\n\n"
            f"Use agent(action='status', task_id='{task_id}') to check progress\n"
            f"Use agent(action='wait', task_id='{task_id}') to wait for completion",
            metadata={
                "task_id": task_id,
                "child_session_id": task_id,
                "parent_session_id": getattr(ctx, "session_id", ""),
                "delegation_depth": child_depth,
                "status": "pending",
            },
        )

    async def _execute_subtask(self, task: SubTask, parent_ctx: ToolContext) -> None:
        """Execute a sub-task (runs in background)."""
        task.status = SubTaskStatus.RUNNING
        task.started_at = datetime.now()

        try:
            # Create sub-agent context
            sub_ctx = SubAgentContext(
                parent_session_id=parent_ctx.session_id,
                working_directory=parent_ctx.working_directory,
                task=task,
                shared_memory=task.metadata,
            )

            # Try to get the agent loop for execution
            result = await self._run_sub_agent(task.description, sub_ctx)

            task.status = SubTaskStatus.COMPLETED
            task.result = result
            task.completed_at = datetime.now()

        except asyncio.CancelledError:
            task.status = SubTaskStatus.CANCELLED
            task.error = "Task was cancelled"
            task.completed_at = datetime.now()

        except Exception as e:
            task.status = SubTaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()

        finally:
            # Move to completed tasks
            self._task_results[task.id] = task
            self._active_tasks.pop(task.id, None)

    async def _run_sub_agent(self, task_description: str, sub_ctx: SubAgentContext) -> str:
        """
        Run the sub-agent.

        This is a simplified implementation that simulates sub-agent execution.
        In a full implementation, this would create a new AgentLoop instance
        with its own message history but shared tools.
        """
        # For now, we provide a simplified execution model
        # In a full implementation, this would spawn a real agent loop

        # Simulate some processing time
        await asyncio.sleep(0.1)

        # Return a placeholder result
        # A full implementation would actually run the agent
        return (
            f"Sub-agent completed task: {task_description}\n\n"
            f"[Note: Full sub-agent execution requires integration with AgentLoop]"
        )

    def _get_status(self, args: Dict[str, Any]) -> ToolResult:
        """Get status of a sub-task."""
        task_id = args.get("task_id", "")

        if not task_id:
            # Return status of all tasks
            active = list(self._active_tasks.values())
            completed = list(self._task_results.values())

            output_lines = ["=== Active Tasks ==="]
            for task in active:
                output_lines.append(f"[{task.id}] {task.status.value}: {task.description[:50]}...")

            if not active:
                output_lines.append("(none)")

            output_lines.append("\n=== Completed Tasks ===")
            for task in completed[-5:]:  # Last 5
                status_icon = "✓" if task.status == SubTaskStatus.COMPLETED else "✗"
                output_lines.append(f"[{task.id}] {status_icon} {task.description[:50]}...")

            if not completed:
                output_lines.append("(none)")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"active_count": len(active), "completed_count": len(completed)},
            )

        # Get specific task
        task = self._active_tasks.get(task_id) or self._task_results.get(task_id)

        if not task:
            return ToolResult(success=False, output="", error=f"Task not found: {task_id}")

        output_lines = [
            f"Task ID: {task.id}",
            f"Status: {task.status.value}",
            f"Description: {task.description}",
        ]

        if task.started_at:
            output_lines.append(f"Started: {task.started_at.isoformat()}")
        if task.completed_at:
            output_lines.append(f"Completed: {task.completed_at.isoformat()}")
        if task.result:
            output_lines.append(f"\nResult:\n{task.result}")
        if task.error:
            output_lines.append(f"\nError: {task.error}")

        return ToolResult(
            success=True, output="\n".join(output_lines), metadata={"status": task.status.value}
        )

    async def _wait_for_task(self, args: Dict[str, Any]) -> ToolResult:
        """Wait for a sub-task to complete."""
        task_id = args.get("task_id", "")
        timeout = args.get("timeout", 60)

        if not task_id:
            return ToolResult(success=False, output="", error="task_id is required for wait action")

        # Check if already completed
        if task_id in self._task_results:
            task = self._task_results[task_id]
            return self._format_completed_task(task)

        # Check if active
        if task_id not in self._active_tasks:
            return ToolResult(success=False, output="", error=f"Task not found: {task_id}")

        # Wait for completion
        start_time = asyncio.get_event_loop().time()

        while task_id in self._active_tasks:
            if asyncio.get_event_loop().time() - start_time > timeout:
                return ToolResult(
                    success=False, output="", error=f"Timeout waiting for task {task_id}"
                )

            await asyncio.sleep(0.5)

        # Task completed
        if task_id in self._task_results:
            task = self._task_results[task_id]
            return self._format_completed_task(task)

        return ToolResult(
            success=False, output="", error=f"Task {task_id} disappeared unexpectedly"
        )

    def _format_completed_task(self, task: SubTask) -> ToolResult:
        """Format a completed task result."""
        if task.status == SubTaskStatus.COMPLETED:
            return ToolResult(
                success=True,
                output=f"Task {task.id} completed successfully.\n\n{task.result or '(no output)'}",
                metadata={"task_id": task.id, "status": "completed"},
            )
        else:
            return ToolResult(
                success=False,
                output=task.result or "",
                error=f"Task {task.id} failed: {task.error}",
                metadata={"task_id": task.id, "status": task.status.value},
            )

    def _cancel_task(self, args: Dict[str, Any]) -> ToolResult:
        """Cancel a running sub-task."""
        task_id = args.get("task_id", "")

        if not task_id:
            return ToolResult(
                success=False, output="", error="task_id is required for cancel action"
            )

        if task_id not in self._active_tasks:
            if task_id in self._task_results:
                return ToolResult(
                    success=False, output="", error=f"Task {task_id} already completed"
                )
            return ToolResult(success=False, output="", error=f"Task not found: {task_id}")

        # Mark as cancelled
        task = self._active_tasks[task_id]
        task.status = SubTaskStatus.CANCELLED
        task.error = "Cancelled by user"
        task.completed_at = datetime.now()

        self._task_results[task_id] = task
        self._active_tasks.pop(task_id, None)

        return ToolResult(
            success=True,
            output=f"Task {task_id} cancelled",
            metadata={"task_id": task_id, "status": "cancelled"},
        )


class TaskCoordinatorTool(Tool):
    """
    Coordinate multiple sub-agents working on related tasks.

    Higher-level tool for managing multiple sub-agents:
    - Spawn multiple tasks at once
    - Wait for all to complete
    - Collect and merge results
    """

    @property
    def name(self) -> str:
        return "coordinate"

    @property
    def description(self) -> str:
        return "Coordinate multiple sub-agents. Spawn tasks in parallel and collect results."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "Array of task descriptions to run in parallel",
                    "items": {"type": "string"},
                },
                "wait": {
                    "type": "boolean",
                    "description": "Wait for all tasks to complete (default: true)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds for waiting (default: 120)",
                },
            },
            "required": ["tasks"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        tasks = args.get("tasks", [])
        wait = args.get("wait", True)
        timeout = args.get("timeout", 120)

        if not tasks:
            return ToolResult(success=False, output="", error="No tasks provided")

        # Create sub-agent tool
        sub_agent = SubAgentTool()

        # Spawn all tasks
        task_ids = []
        for task_desc in tasks:
            result = await sub_agent.execute({"action": "spawn", "task": task_desc}, ctx)
            if result.success and result.metadata:
                task_ids.append(result.metadata.get("task_id"))

        if not wait:
            return ToolResult(
                success=True,
                output=f"Spawned {len(task_ids)} tasks:\n"
                + "\n".join(f"  - {tid}" for tid in task_ids),
                metadata={"task_ids": task_ids},
            )

        # Wait for all tasks
        results = []
        for task_id in task_ids:
            result = await sub_agent.execute(
                {"action": "wait", "task_id": task_id, "timeout": timeout}, ctx
            )
            results.append(
                {
                    "task_id": task_id,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                }
            )

        # Format combined results
        output_lines = [f"Completed {len(results)} tasks:\n"]

        for r in results:
            status = "✓" if r["success"] else "✗"
            output_lines.append(f"{status} [{r['task_id']}]")
            if r["output"]:
                # Indent output
                for line in r["output"].split("\n")[:5]:
                    output_lines.append(f"    {line}")
            if r["error"]:
                output_lines.append(f"    Error: {r['error']}")
            output_lines.append("")

        all_success = all(r["success"] for r in results)

        return ToolResult(
            success=all_success,
            output="\n".join(output_lines),
            error=None if all_success else "Some tasks failed",
            metadata={
                "task_ids": task_ids,
                "success_count": sum(1 for r in results if r["success"]),
                "failure_count": sum(1 for r in results if not r["success"]),
            },
        )
