"""Long-lived peer agents.

The existing SubAgentTool delegates one task and returns one result. Peer
agents are different: they stay alive across the parent's turns, hold their
own conversation context, and are addressable — the parent can send
follow-up input (optionally interrupting current work), wait for results,
list, and close them.

Built on existing loop machinery rather than new plumbing:

- each peer is a fresh :class:`AgentLoop` running inside an asyncio task;
- ``send_input`` to a *busy* peer uses in-run steering, so the message lands
  between that agent's tool calls instead of after its run;
- ``send_input(interrupt=True)`` cancels the current run and starts a new
  one with the message;
- peers cannot spawn peers (the hierarchy stays one level deep).
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

MAX_PEER_AGENTS = 8

_TASK_NAME_RE = re.compile(r"[^a-z0-9_]+")


def _normalize_task_name(name: str) -> str:
    cleaned = _TASK_NAME_RE.sub("_", (name or "").strip().lower()).strip("_")
    return cleaned or "agent"


@dataclass
class PeerAgent:
    agent_id: str
    task_name: str
    session_id: str
    loop: Any  # AgentLoop; typed loosely to avoid an import cycle
    inbox: "asyncio.Queue[Optional[str]]" = field(default_factory=asyncio.Queue)
    status: str = "starting"  # starting | running | idle | closed | error
    last_result: str = ""
    pending_approvals: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    runner: Optional[asyncio.Task] = None
    idle_event: asyncio.Event = field(default_factory=asyncio.Event)


class PeerAgentManager:
    """Spawn, address, await, and close peer agents for one parent loop."""

    def __init__(
        self,
        loop_factory: Callable[[str, str | None], Any],
        max_agents: int = MAX_PEER_AGENTS,
        parent_session_id: str | None = None,
        storage_dir: str = ".superqode/sessions",
    ):
        self._loop_factory = loop_factory
        self._max_agents = max_agents
        self._parent_session_id = parent_session_id
        self._storage_dir = storage_dir
        self._agents: Dict[str, PeerAgent] = {}

    # -- lookup -----------------------------------------------------------

    def resolve(self, target: str) -> Optional[PeerAgent]:
        target = (target or "").strip()
        if target in self._agents:
            return self._agents[target]
        normalized = _normalize_task_name(target)
        for agent in self._agents.values():
            if agent.task_name == normalized or agent.session_id == target:
                return agent
        return None

    def list_agents(self) -> List[Dict[str, Any]]:
        return [
            {
                "agent_id": a.agent_id,
                "task_name": a.task_name,
                "session_id": a.session_id,
                "status": a.status,
                "queued_inputs": a.inbox.qsize(),
                "last_result_preview": (a.last_result or "")[:120],
                "pending_approvals": [dict(item) for item in a.pending_approvals],
            }
            for a in self._agents.values()
        ]

    # -- lifecycle ---------------------------------------------------------

    async def spawn(
        self,
        task_name: str,
        message: str,
        *,
        session_id: str | None = None,
    ) -> PeerAgent:
        agent = self._create_agent(task_name, session_id=session_id)
        # Enqueue before starting the runner so wait() can never observe an
        # idle agent that hasn't processed its first message.
        await agent.inbox.put(message)
        agent.runner = asyncio.create_task(self._run_agent(agent))
        return agent

    async def resume(self, task_name: str, *, session_id: str | None = None) -> PeerAgent:
        agent = self._create_agent(task_name, session_id=session_id)
        agent.status = "idle"
        agent.idle_event.set()
        agent.runner = asyncio.create_task(self._run_agent(agent))
        return agent

    def _create_agent(self, task_name: str, *, session_id: str | None = None) -> PeerAgent:
        live = sum(1 for a in self._agents.values() if a.status != "closed")
        if live >= self._max_agents:
            raise RuntimeError(
                f"Too many live peer agents ({self._max_agents}). Close one first (list_agents/close_agent)."
            )
        if session_id:
            existing = self.resolve(session_id)
            if existing is not None and existing.status != "closed":
                raise RuntimeError(
                    f"Peer agent session {session_id!r} is already active as '{existing.task_name}'."
                )
        normalized = _normalize_task_name(task_name)
        base = normalized
        suffix = 2
        while any(a.task_name == normalized for a in self._agents.values()):
            normalized = f"{base}_{suffix}"
            suffix += 1
        loop = self._loop_factory(normalized, session_id)
        resolved_session_id = str(getattr(loop, "session_id", None) or session_id or normalized)
        agent = PeerAgent(
            agent_id=uuid.uuid4().hex[:8],
            task_name=normalized,
            session_id=resolved_session_id,
            loop=loop,
        )
        self._agents[agent.agent_id] = agent
        self._record_graph(
            agent,
            status=agent.status,
            kind="sub_agent",
            agent_id=task_name,
            agent_name=task_name,
            title=task_name,
        )
        return agent

    async def _run_agent(self, agent: PeerAgent) -> None:
        while True:
            if agent.inbox.empty() and agent.status in ("idle", "error", "needs_approval"):
                agent.idle_event.set()
            message = await agent.inbox.get()
            if message is None:
                break
            agent.idle_event.clear()
            agent.status = "running"
            self._record_graph(agent, status=agent.status)
            agent.loop.reset_cancellation()
            try:
                response = await agent.loop.run(message)
                agent.pending_approvals = _pending_approvals(agent.loop)
                agent.last_result = (
                    response.content or getattr(response, "error", None) or ""
                ) or f"(stopped: {response.stopped_reason})"
            except Exception as e:  # peer crashes must not kill the parent
                agent.last_result = f"Peer agent error: {e}"
                agent.status = "error"
                self._record_graph(
                    agent,
                    status=agent.status,
                    last_result_preview=agent.last_result[:240],
                    pending_approvals_count=len(agent.pending_approvals),
                )
                continue
            agent.status = (
                "needs_approval"
                if response.stopped_reason == "needs_approval" and agent.pending_approvals
                else "idle"
            )
            self._record_graph(
                agent,
                status=agent.status,
                last_result_preview=agent.last_result[:240],
                pending_approvals_count=len(agent.pending_approvals),
            )
        agent.status = "closed"
        self._record_graph(agent, status=agent.status, closed=True)
        agent.idle_event.set()

    async def send_input(self, target: str, message: str, interrupt: bool = False) -> str:
        agent = self.resolve(target)
        if agent is None:
            raise KeyError(f"No peer agent matching {target!r}")
        if agent.status == "closed":
            raise RuntimeError(f"Peer agent '{agent.task_name}' is closed.")
        if agent.status == "needs_approval" and not interrupt:
            raise RuntimeError(
                f"Peer agent '{agent.task_name}' is waiting for approval. "
                "Approve or reject it before sending more input."
            )
        if agent.status == "running" and not interrupt:
            # Steer the live run: lands between the peer's tool calls.
            agent.loop.steer(message)
            return "steered"
        if agent.status == "running" and interrupt:
            agent.loop.cancel()
            agent.idle_event.clear()
            await agent.inbox.put(message)
            return "interrupted"
        agent.idle_event.clear()
        await agent.inbox.put(message)
        return "queued"

    async def wait(self, target: str, timeout_s: float = 60.0) -> Dict[str, Any]:
        agent = self.resolve(target)
        if agent is None:
            raise KeyError(f"No peer agent matching {target!r}")
        try:
            await asyncio.wait_for(agent.idle_event.wait(), timeout=max(0.1, timeout_s))
        except asyncio.TimeoutError:
            return {
                "agent_id": agent.agent_id,
                "task_name": agent.task_name,
                "session_id": agent.session_id,
                "status": agent.status,
                "done": False,
                "result": "",
                "pending_approvals": [dict(item) for item in agent.pending_approvals],
            }
        return {
            "agent_id": agent.agent_id,
            "task_name": agent.task_name,
            "session_id": agent.session_id,
            "status": agent.status,
            "done": True,
            "result": agent.last_result,
            "pending_approvals": [dict(item) for item in agent.pending_approvals],
        }

    async def approve(self, target: str, index: int = 0, always: bool = False) -> Dict[str, Any]:
        agent = self.resolve(target)
        if agent is None:
            raise KeyError(f"No peer agent matching {target!r}")
        if not agent.pending_approvals:
            raise RuntimeError(f"Peer agent '{agent.task_name}' has no pending approval.")
        response = await _approve_loop_pending(agent.loop, index=index, always=always)
        agent.pending_approvals = _pending_approvals(agent.loop)
        agent.last_result = response.content or response.error or ""
        agent.status = "needs_approval" if agent.pending_approvals else "idle"
        self._record_graph(
            agent,
            status=agent.status,
            last_result_preview=agent.last_result[:240],
            pending_approvals_count=len(agent.pending_approvals),
        )
        agent.idle_event.set()
        return {
            "agent_id": agent.agent_id,
            "task_name": agent.task_name,
            "session_id": agent.session_id,
            "status": agent.status,
            "result": agent.last_result,
            "pending_approvals": [dict(item) for item in agent.pending_approvals],
        }

    async def reject(
        self,
        target: str,
        index: int = 0,
        message: str | None = None,
        always: bool = False,
    ) -> Dict[str, Any]:
        agent = self.resolve(target)
        if agent is None:
            raise KeyError(f"No peer agent matching {target!r}")
        if not agent.pending_approvals:
            raise RuntimeError(f"Peer agent '{agent.task_name}' has no pending approval.")
        response = await _reject_loop_pending(
            agent.loop,
            index=index,
            message=message,
            always=always,
        )
        agent.pending_approvals = _pending_approvals(agent.loop)
        agent.last_result = response.content or response.error or ""
        agent.status = "needs_approval" if agent.pending_approvals else "idle"
        self._record_graph(
            agent,
            status=agent.status,
            last_result_preview=agent.last_result[:240],
            pending_approvals_count=len(agent.pending_approvals),
        )
        agent.idle_event.set()
        return {
            "agent_id": agent.agent_id,
            "task_name": agent.task_name,
            "session_id": agent.session_id,
            "status": agent.status,
            "result": agent.last_result,
            "pending_approvals": [dict(item) for item in agent.pending_approvals],
        }

    async def close(self, target: str) -> bool:
        agent = self.resolve(target)
        if agent is None:
            return False
        agent.loop.cancel()
        await agent.inbox.put(None)
        if agent.runner is not None:
            try:
                await asyncio.wait_for(agent.runner, timeout=10)
            except asyncio.TimeoutError:
                agent.runner.cancel()
        agent.status = "closed"
        self._record_graph(agent, status=agent.status, closed=True)
        return True

    async def close_all(self) -> None:
        for agent_id in list(self._agents):
            await self.close(agent_id)

    def update_graph_metadata(self, target: str, **updates: Any) -> None:
        agent = self.resolve(target)
        if agent is not None:
            self._record_graph(agent, **updates)

    def _record_graph(self, agent: PeerAgent, **updates: Any) -> None:
        try:
            from superqode.session.switchboard import SessionGraphStore

            metadata = None
            manager = getattr(agent.loop, "_session_manager", None)
            if manager is not None:
                metadata = manager.get_session_info(agent.session_id)
            SessionGraphStore(self._storage_dir).upsert(
                agent.session_id,
                metadata=metadata,
                parent_session_id=self._parent_session_id,
                kind="sub_agent",
                agent_id=updates.pop("agent_id", agent.task_name),
                agent_name=updates.pop("agent_name", agent.task_name),
                title=updates.pop("title", agent.task_name),
                **updates,
            )
        except Exception:
            pass


def _pending_approvals(loop: Any) -> List[Dict[str, Any]]:
    pending = getattr(loop, "_pending_approval", None)
    if not pending:
        return []
    return [
        {
            "index": 0,
            "tool_name": pending.get("tool_name"),
            "arguments": dict(pending.get("arguments") or {}),
            "tool_call_id": pending.get("tool_call_id"),
        }
    ]


async def _approve_loop_pending(loop: Any, index: int = 0, always: bool = False) -> Any:
    if index != 0 or not getattr(loop, "_pending_approval", None):
        raise RuntimeError("No pending approval to approve")
    pending = dict(loop._pending_approval)
    tool_name = str(pending.get("tool_name") or "")
    arguments = dict(pending.get("arguments") or {})
    tool_call_id = pending.get("tool_call_id")
    if tool_call_id:
        loop._approved_tool_call_ids.add(str(tool_call_id))
    if always and getattr(loop.config, "harness_spec", None) is not None:
        from ..harness.approval_memory import remember_approval_decision

        remember_approval_decision(
            loop.config.harness_spec,
            tool_name=tool_name,
            arguments=arguments,
            action="allow",
        )
    loop._pending_approval = None
    result = await loop._execute_tool(
        tool_name,
        arguments,
        tool_call_id=str(tool_call_id) if tool_call_id else None,
    )
    if not always and tool_call_id:
        loop._approved_tool_call_ids.discard(str(tool_call_id))
    if loop.on_tool_result:
        loop.on_tool_result(tool_name, result)
    from .loop import AgentResponse

    return AgentResponse(
        content=result.to_message(),
        messages=[],
        tool_calls_made=1 if result.success else 0,
        iterations=0,
        stopped_reason="complete" if result.success else "error",
        error=result.error,
    )


async def _reject_loop_pending(
    loop: Any,
    index: int = 0,
    message: str | None = None,
    always: bool = False,
) -> Any:
    if index != 0 or not getattr(loop, "_pending_approval", None):
        raise RuntimeError("No pending approval to reject")
    pending = dict(loop._pending_approval)
    loop._pending_approval = None
    tool_name = str(pending.get("tool_name") or "")
    if always and getattr(loop.config, "harness_spec", None) is not None:
        from ..harness.approval_memory import remember_approval_decision

        remember_approval_decision(
            loop.config.harness_spec,
            tool_name=tool_name,
            arguments=dict(pending.get("arguments") or {}),
            action="deny",
        )
    from .loop import AgentResponse

    reason = message or f"Permission rejected for tool: {tool_name}"
    return AgentResponse(
        content=reason,
        messages=[],
        tool_calls_made=0,
        iterations=0,
        stopped_reason="complete",
    )


__all__ = ["MAX_PEER_AGENTS", "PeerAgent", "PeerAgentManager"]
