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
    loop: Any  # AgentLoop; typed loosely to avoid an import cycle
    inbox: "asyncio.Queue[Optional[str]]" = field(default_factory=asyncio.Queue)
    status: str = "starting"  # starting | running | idle | closed | error
    last_result: str = ""
    created_at: float = field(default_factory=time.time)
    runner: Optional[asyncio.Task] = None
    idle_event: asyncio.Event = field(default_factory=asyncio.Event)


class PeerAgentManager:
    """Spawn, address, await, and close peer agents for one parent loop."""

    def __init__(self, loop_factory: Callable[[str], Any], max_agents: int = MAX_PEER_AGENTS):
        self._loop_factory = loop_factory
        self._max_agents = max_agents
        self._agents: Dict[str, PeerAgent] = {}

    # -- lookup -----------------------------------------------------------

    def resolve(self, target: str) -> Optional[PeerAgent]:
        target = (target or "").strip()
        if target in self._agents:
            return self._agents[target]
        normalized = _normalize_task_name(target)
        for agent in self._agents.values():
            if agent.task_name == normalized:
                return agent
        return None

    def list_agents(self) -> List[Dict[str, Any]]:
        return [
            {
                "agent_id": a.agent_id,
                "task_name": a.task_name,
                "status": a.status,
                "queued_inputs": a.inbox.qsize(),
                "last_result_preview": (a.last_result or "")[:120],
            }
            for a in self._agents.values()
        ]

    # -- lifecycle ---------------------------------------------------------

    async def spawn(self, task_name: str, message: str) -> PeerAgent:
        live = sum(1 for a in self._agents.values() if a.status != "closed")
        if live >= self._max_agents:
            raise RuntimeError(
                f"Too many live peer agents ({self._max_agents}). Close one first (list_agents/close_agent)."
            )
        normalized = _normalize_task_name(task_name)
        base = normalized
        suffix = 2
        while any(a.task_name == normalized for a in self._agents.values()):
            normalized = f"{base}_{suffix}"
            suffix += 1
        agent = PeerAgent(
            agent_id=uuid.uuid4().hex[:8],
            task_name=normalized,
            loop=self._loop_factory(normalized),
        )
        self._agents[agent.agent_id] = agent
        # Enqueue before starting the runner so wait() can never observe an
        # idle agent that hasn't processed its first message.
        await agent.inbox.put(message)
        agent.runner = asyncio.create_task(self._run_agent(agent))
        return agent

    async def _run_agent(self, agent: PeerAgent) -> None:
        while True:
            if agent.inbox.empty() and agent.status in ("idle", "error"):
                agent.idle_event.set()
            message = await agent.inbox.get()
            if message is None:
                break
            agent.idle_event.clear()
            agent.status = "running"
            agent.loop.reset_cancellation()
            try:
                response = await agent.loop.run(message)
                agent.last_result = (
                    response.content or getattr(response, "error", None) or ""
                ) or f"(stopped: {response.stopped_reason})"
            except Exception as e:  # peer crashes must not kill the parent
                agent.last_result = f"Peer agent error: {e}"
                agent.status = "error"
                continue
            agent.status = "idle"
        agent.status = "closed"
        agent.idle_event.set()

    async def send_input(self, target: str, message: str, interrupt: bool = False) -> str:
        agent = self.resolve(target)
        if agent is None:
            raise KeyError(f"No peer agent matching {target!r}")
        if agent.status == "closed":
            raise RuntimeError(f"Peer agent '{agent.task_name}' is closed.")
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
                "status": agent.status,
                "done": False,
                "result": "",
            }
        return {
            "agent_id": agent.agent_id,
            "task_name": agent.task_name,
            "status": agent.status,
            "done": True,
            "result": agent.last_result,
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
        return True

    async def close_all(self) -> None:
        for agent_id in list(self._agents):
            await self.close(agent_id)


__all__ = ["MAX_PEER_AGENTS", "PeerAgent", "PeerAgentManager"]
