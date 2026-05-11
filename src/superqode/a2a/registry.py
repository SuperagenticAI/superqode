"""
A2A Agent Registry - Discover and manage A2A agents.

Provides agent discovery from URLs, known endpoints, and custom registries.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

from ..a2a.client import A2AClient
from ..a2a.types import AgentCard


@dataclass
class A2AAgentEntry:
    """An entry in the A2A registry."""

    name: str
    url: str
    description: str = ""
    version: str = "1.0"
    skills: List[Dict[str, str]] = field(default_factory=list)
    verified: bool = False


class A2ARegistry:
    """Registry for managing A2A agent connections.

    Usage:
        registry = A2ARegistry()

        # Add agent
        await registry.add("gemini", "http://localhost:8000")

        # Discover all
        agents = await registry.discover_all()

        # Get by skill
        testers = registry.get_by_skill("testing")
    """

    def __init__(self, config_path: Optional[str] = None):
        self._agents: Dict[str, A2AAgentEntry] = {}
        self._config_path = config_path or ".superqode/a2a_agents.json"

    async def add(self, name: str, url: str, description: str = "") -> bool:
        """Add an agent to the registry.

        Args:
            name: Unique name for the agent
            url: A2A server URL
            description: Optional description

        Returns:
            True if agent is reachable, False otherwise
        """
        try:
            client = A2AClient(url)
            card = await client.get_agent_card()
            await client.close()

            entry = A2AAgentEntry(
                name=name,
                url=url,
                description=card.description,
                version=card.version,
                skills=[
                    {"id": s.id, "name": s.name, "description": s.description} for s in card.skills
                ],
                verified=True,
            )

            self._agents[name] = entry
            return True

        except Exception as e:
            # Add unverified entry anyway
            entry = A2AAgentEntry(
                name=name,
                url=url,
                description=description or "Unverified agent",
                verified=False,
            )
            self._agents[name] = entry
            return False

    async def remove(self, name: str) -> bool:
        """Remove an agent from the registry."""
        if name in self._agents:
            del self._agents[name]
            return True
        return False

    async def discover_from_url(self, url: str) -> Optional[A2AAgentEntry]:
        """Discover an agent from a URL."""
        try:
            client = A2AClient(url)
            card = await client.get_agent_card()
            await client.close()

            entry = A2AAgentEntry(
                name=card.name,
                url=url,
                description=card.description,
                version=card.version,
                skills=[{"id": s.id, "name": s.name} for s in card.skills],
                verified=True,
            )

            self._agents[card.name] = entry
            return entry

        except Exception:
            return None

    async def discover_all(self) -> List[A2AAgentEntry]:
        """Discover all registered agents."""
        verified = []
        unverified = []

        for entry in self._agents.values():
            if not entry.verified:
                try:
                    client = A2AClient(entry.url)
                    card = await client.get_agent_card()
                    await client.close()
                    entry.verified = True
                    entry.description = card.description
                except Exception:
                    pass

            if entry.verified:
                verified.append(entry)
            else:
                unverified.append(entry)

        return verified + unverified

    def get(self, name: str) -> Optional[A2AAgentEntry]:
        """Get an agent by name."""
        return self._agents.get(name)

    def get_by_skill(self, skill_name: str) -> List[A2AAgentEntry]:
        """Find agents that have a specific skill."""
        skill_lower = skill_name.lower()
        matches = []

        for entry in self._agents.values():
            for skill in entry.skills:
                if (
                    skill_name.lower() in skill.get("name", "").lower()
                    or skill_name.lower() in skill.get("id", "").lower()
                ):
                    matches.append(entry)
                    break

        return matches

    def list_all(self) -> List[A2AAgentEntry]:
        """List all agents in the registry."""
        return list(self._agents.values())

    def save(self) -> None:
        """Save registry to file."""
        import json

        data = {
            name: {
                "url": entry.url,
                "description": entry.description,
                "version": entry.version,
                "skills": entry.skills,
            }
            for name, entry in self._agents.items()
        }

        path = Path(self._config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def load(self) -> None:
        """Load registry from file."""
        import json

        path = Path(self._config_path)
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text())
            for name, info in data.items():
                self._agents[name] = A2AAgentEntry(
                    name=name,
                    url=info["url"],
                    description=info.get("description", ""),
                    version=info.get("version", "1.0"),
                    skills=info.get("skills", []),
                )
        except Exception:
            pass


# Known public A2A agents (placeholder - would come from actual registry)
KNOWN_A2A_AGENTS = {
    "gemini-cli": "http://localhost:8080",
    "claude-code": "http://localhost:8081",
    "codex": "http://localhost:8082",
}


async def discover_known_agents() -> Dict[str, A2AAgentEntry]:
    """Discover known public A2A agents."""
    discovered = {}

    for name, url in KNOWN_A2A_AGENTS.items():
        try:
            client = A2AClient(url)
            card = await client.get_agent_card()
            await client.close()

            discovered[name] = A2AAgentEntry(
                name=card.name,
                url=url,
                description=card.description,
                skills=[{"id": s.id, "name": s.name} for s in card.skills],
                verified=True,
            )
        except Exception:
            pass

    return discovered
