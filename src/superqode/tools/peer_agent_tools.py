"""Peer-agent tools: spawn_agent / send_input / wait_agent / list_agents / close_agent.

Codex-parity multi-agent surface. Peers are long-lived AgentLoops owned by
the top-level loop's :class:`~superqode.agent.peer_agents.PeerAgentManager`;
``send_input`` to a busy peer steers its live run, ``interrupt=true``
cancels and redirects it. Only the top-level agent gets these tools — peers
cannot spawn peers.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import Tool, ToolContext, ToolResult

_NO_MANAGER_ERROR = (
    "Peer agents are not available here (sub-agents cannot spawn peers; "
    "only the top-level agent can)."
)


def _manager(ctx: ToolContext):
    return getattr(ctx, "peer_manager", None)


class SpawnAgentTool(Tool):
    """Start a long-lived peer agent working on a task."""

    @property
    def name(self) -> str:
        return "spawn_agent"

    @property
    def description(self) -> str:
        return (
            "Spawn a peer agent that works on a task in parallel and stays "
            "alive for follow-ups. Returns its agent_id and task_name. Use "
            "send_input to message it, wait_agent to collect its result, "
            "close_agent when finished. Prefer one agent per independent "
            "workstream."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_name": {
                    "type": "string",
                    "description": "Short name (lowercase, digits, underscores), e.g. 'fix_tests'.",
                },
                "message": {
                    "type": "string",
                    "description": "The task brief for the new agent.",
                },
            },
            "required": ["task_name", "message"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = _manager(ctx)
        if manager is None:
            return ToolResult(success=False, output="", error=_NO_MANAGER_ERROR)
        message = str(args.get("message") or "").strip()
        if not message:
            return ToolResult(success=False, output="", error="'message' is required")
        try:
            agent = await manager.spawn(str(args.get("task_name") or "agent"), message)
        except RuntimeError as e:
            return ToolResult(success=False, output="", error=str(e))
        return ToolResult(
            success=True,
            output=(
                f"Spawned peer agent '{agent.task_name}' (id {agent.agent_id}). "
                "It is working now; use wait_agent to collect its result."
            ),
            metadata={"agent_id": agent.agent_id, "task_name": agent.task_name},
        )


class SendInputTool(Tool):
    """Send a message to an existing peer agent."""

    @property
    def name(self) -> str:
        return "send_input"

    @property
    def description(self) -> str:
        return (
            "Send a message to a peer agent (by agent_id or task_name). If it "
            "is busy, the message is delivered into its live run; set "
            "interrupt=true to abort its current work and redirect it "
            "immediately. Reuse an agent when the new task depends on its "
            "existing context."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "agent_id or task_name from spawn_agent.",
                },
                "message": {"type": "string", "description": "The message to deliver."},
                "interrupt": {
                    "type": "boolean",
                    "description": "Abort current work and redirect immediately (default false).",
                },
            },
            "required": ["agent", "message"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = _manager(ctx)
        if manager is None:
            return ToolResult(success=False, output="", error=_NO_MANAGER_ERROR)
        try:
            mode = await manager.send_input(
                str(args.get("agent") or ""),
                str(args.get("message") or ""),
                interrupt=bool(args.get("interrupt", False)),
            )
        except (KeyError, RuntimeError) as e:
            return ToolResult(success=False, output="", error=str(e))
        notes = {
            "steered": "delivered into its live run",
            "interrupted": "current work aborted; redirected",
            "queued": "queued; it will start on it now",
        }
        return ToolResult(
            success=True,
            output=f"Message {notes.get(mode, mode)} ({mode}).",
            metadata={"delivery": mode},
        )


class WaitAgentTool(Tool):
    """Wait for a peer agent to finish its current work and get the result."""

    @property
    def name(self) -> str:
        return "wait_agent"

    @property
    def description(self) -> str:
        return (
            "Wait for a peer agent (by agent_id or task_name) to go idle and "
            "return its latest result. Returns status=running on timeout - "
            "do other work and wait again."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "agent_id or task_name from spawn_agent.",
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "Max seconds to wait (default 60).",
                },
            },
            "required": ["agent"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = _manager(ctx)
        if manager is None:
            return ToolResult(success=False, output="", error=_NO_MANAGER_ERROR)
        try:
            timeout = float(args.get("timeout_s") or 60)
        except (TypeError, ValueError):
            timeout = 60.0
        try:
            outcome = await manager.wait(str(args.get("agent") or ""), timeout_s=timeout)
        except KeyError as e:
            return ToolResult(success=False, output="", error=str(e))
        if not outcome["done"]:
            return ToolResult(
                success=True,
                output=(
                    f"Agent '{outcome['task_name']}' is still {outcome['status']} after "
                    f"{int(timeout)}s. Do other work and call wait_agent again."
                ),
                metadata=outcome,
            )
        return ToolResult(
            success=True,
            output=f"Agent '{outcome['task_name']}' ({outcome['status']}):\n{outcome['result']}",
            metadata=outcome,
        )


class ListAgentsTool(Tool):
    """List peer agents and their statuses."""

    read_only = True

    @property
    def name(self) -> str:
        return "list_agents"

    @property
    def description(self) -> str:
        return "List peer agents with their agent_id, task_name, and status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = _manager(ctx)
        if manager is None:
            return ToolResult(success=False, output="", error=_NO_MANAGER_ERROR)
        agents = manager.list_agents()
        if not agents:
            return ToolResult(success=True, output="No peer agents.", metadata={"agents": []})
        rows = [
            f"{a['agent_id']}  {a['task_name']:<20}  {a['status']:<8}  {a['last_result_preview']}"
            for a in agents
        ]
        return ToolResult(
            success=True,
            output="agent_id  task_name  status  last_result\n" + "\n".join(rows),
            metadata={"agents": agents},
        )


class CloseAgentTool(Tool):
    """Close a peer agent."""

    @property
    def name(self) -> str:
        return "close_agent"

    @property
    def description(self) -> str:
        return "Close a peer agent (by agent_id or task_name) when its work is done."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "agent_id or task_name from spawn_agent.",
                },
            },
            "required": ["agent"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = _manager(ctx)
        if manager is None:
            return ToolResult(success=False, output="", error=_NO_MANAGER_ERROR)
        target = str(args.get("agent") or "")
        closed = await manager.close(target)
        if not closed:
            return ToolResult(success=False, output="", error=f"No peer agent matching {target!r}")
        return ToolResult(success=True, output=f"Closed peer agent {target}.")


__all__ = [
    "CloseAgentTool",
    "ListAgentsTool",
    "SendInputTool",
    "SpawnAgentTool",
    "WaitAgentTool",
]
