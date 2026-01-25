"""
SuperQode App Models - Agent data structures and helpers.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import shutil
from dataclasses import dataclass
from enum import Enum

from .constants import AGENT_COLORS, AGENT_ICONS, THEME


class AgentStatus(Enum):
    """Status of an agent installation."""

    INSTALLED = "installed"
    AVAILABLE = "available"
    RECOMMENDED = "recommended"


@dataclass
class AgentInfo:
    """Information about a coding agent."""

    identity: str
    name: str
    short_name: str
    description: str
    author: str
    status: AgentStatus

    @property
    def color(self) -> str:
        return AGENT_COLORS.get(self.short_name, THEME["purple"])

    @property
    def icon(self) -> str:
        return AGENT_ICONS.get(self.short_name, "🤖")

    @property
    def is_ready(self) -> bool:
        return self.status == AgentStatus.INSTALLED

    @property
    def status_icon(self) -> str:
        if self.is_ready:
            return "✅"
        elif self.status == AgentStatus.RECOMMENDED:
            return "⭐"
        return "○"


def check_installed(name: str) -> bool:
    """Check if an agent is installed on the system."""
    # Map agent short names to their CLI commands
    cmd_map = {
        # 14 Official ACP Agents
        "gemini": "gemini",
        "claude": "claude",
        "claude-code": "claude",
        "codex": "codex",
        "junie": "junie",
        "goose": "goose",
        "kimi": "kimi",
        "opencode": "opencode",
        "stakpak": "stakpak",
        "vtcode": "vtcode",
        "auggie": "auggie",
        "code-assistant": "code-assistant",
        "cagent": "cagent",
        "fast-agent": "fast-agent",
        "llmling-agent": "llmling-agent",
    }
    return shutil.which(cmd_map.get(name, name)) is not None


def load_agents_sync() -> list[AgentInfo]:
    """Load agents list synchronously."""
    agents = []
    try:
        from superqode.agents.discovery import read_agents

        def _read():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(read_agents())
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor() as ex:
            agent_map = ex.submit(_read).result(timeout=10)

        for identity, data in agent_map.items():
            short = data.get("short_name", "").lower()
            installed = check_installed(short)
            recommended = data.get("recommended", False)

            agents.append(
                AgentInfo(
                    identity=identity,
                    name=data.get("name", "Unknown"),
                    short_name=short,
                    description=data.get("description", "")[:80],
                    author=data.get("author_name", ""),
                    status=AgentStatus.INSTALLED
                    if installed
                    else (AgentStatus.RECOMMENDED if recommended else AgentStatus.AVAILABLE),
                )
            )
    except Exception:
        pass

    agents.sort(key=lambda a: (0 if a.is_ready else 1, a.name))
    return agents
