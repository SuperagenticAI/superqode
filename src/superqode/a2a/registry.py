"""
A2A Agent Registry - Discover and manage A2A agents.

Provides agent discovery from URLs, known endpoints, and custom registries.

Routing identity is the normalized agent URL (origin-bound). The Agent Card
``name`` field is presentational metadata, not a stable routing key. Storing
or looking up peers by remote card name alone enables name-collision
wrong-peer dispatch (see arXiv:2609.27624).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..a2a.client import A2AClient
from ..a2a.connection import normalize_url


@dataclass
class A2AAgentEntry:
    """An entry in the A2A registry."""

    name: str
    url: str
    description: str = ""
    version: str = "1.0"
    skills: List[Dict[str, str]] = field(default_factory=list)
    verified: bool = False


class AmbiguousAgentName(ValueError):
    """More than one registered URL shares the same presentational name."""


class A2ARegistry:
    """Registry for managing A2A agent connections.

    Entries are keyed by normalized URL. ``name`` is a local presentational
    alias (user-chosen on :meth:`add`, or the card name on discover). Looking
    up by alias rejects collisions instead of silently picking one peer.

    Usage:
        registry = A2ARegistry()

        # Add agent (local alias + URL)
        await registry.add("gemini", "http://localhost:8000")

        # Discover all
        agents = await registry.discover_all()

        # Get by skill
        testers = registry.get_by_skill("testing")
    """

    def __init__(self, config_path: Optional[str] = None):
        # Stable identity: normalized URL -> entry
        self._agents: Dict[str, A2AAgentEntry] = {}
        self._config_path = config_path or ".superqode/a2a_agents.json"

    def _key(self, url: str) -> str:
        return normalize_url(url)

    def _entries_named(self, name: str) -> List[A2AAgentEntry]:
        return [entry for entry in self._agents.values() if entry.name == name]

    def _require_unique_alias(self, name: str, url: str) -> None:
        """Reject a presentational name already bound to a different URL."""
        key = self._key(url)
        clashes = [entry for entry in self._entries_named(name) if self._key(entry.url) != key]
        if clashes:
            urls = ", ".join(sorted({self._key(e.url) for e in clashes} | {key}))
            raise AmbiguousAgentName(
                f"Agent name {name!r} is already bound to another URL; "
                f"route by URL instead. Conflicting URLs: {urls}"
            )

    def _put(self, entry: A2AAgentEntry) -> A2AAgentEntry:
        key = self._key(entry.url)
        entry.url = key
        self._require_unique_alias(entry.name, key)
        self._agents[key] = entry
        return entry

    async def add(self, name: str, url: str, description: str = "") -> bool:
        """Add an agent to the registry.

        Args:
            name: Local presentational alias for the agent (not a remote identity)
            url: A2A server URL (stable routing key)
            description: Optional description

        Returns:
            True if agent is reachable, False otherwise
        """
        key = self._key(url)
        try:
            client = A2AClient(url)
            card = await client.get_agent_card()
            await client.close()

            entry = A2AAgentEntry(
                name=name,
                url=key,
                description=card.description,
                version=card.version,
                skills=[
                    {"id": s.id, "name": s.name, "description": s.description} for s in card.skills
                ],
                verified=True,
            )
            self._put(entry)
            return True

        except AmbiguousAgentName:
            raise
        except Exception:
            entry = A2AAgentEntry(
                name=name,
                url=key,
                description=description or "Unverified agent",
                verified=False,
            )
            self._put(entry)
            return False

    async def remove(self, name: str) -> bool:
        """Remove the unique agent with this presentational name."""
        matches = self._entries_named(name)
        if not matches:
            # Also accept a URL passed as the selector.
            key = self._key(name)
            if key in self._agents:
                del self._agents[key]
                return True
            return False
        if len(matches) > 1:
            raise AmbiguousAgentName(
                f"Agent name {name!r} matches {len(matches)} URLs; remove by URL instead."
            )
        del self._agents[self._key(matches[0].url)]
        return True

    def remove_by_url(self, url: str) -> bool:
        """Remove an agent by its stable URL identity."""
        key = self._key(url)
        if key in self._agents:
            del self._agents[key]
            return True
        return False

    async def discover_from_url(self, url: str) -> Optional[A2AAgentEntry]:
        """Discover an agent from a URL.

        The registry key is the URL. The card ``name`` is stored only as a
        presentational alias and must not collide with another URL's alias.
        """
        key = self._key(url)
        try:
            client = A2AClient(url)
            card = await client.get_agent_card()
            await client.close()

            display = (card.name or "").strip() or key
            entry = A2AAgentEntry(
                name=display,
                url=key,
                description=card.description,
                version=card.version,
                skills=[{"id": s.id, "name": s.name} for s in card.skills],
                verified=True,
            )
            return self._put(entry)

        except AmbiguousAgentName:
            raise
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
        """Get an agent by presentational name, or by URL.

        Raises:
            AmbiguousAgentName: if more than one URL shares the same name.
        """
        key = self._key(name)
        if key in self._agents:
            return self._agents[key]
        matches = self._entries_named(name)
        if not matches:
            return None
        if len(matches) > 1:
            urls = ", ".join(sorted(self._key(e.url) for e in matches))
            raise AmbiguousAgentName(
                f"Agent name {name!r} matches multiple URLs ({urls}); "
                f"route by URL instead of card name."
            )
        return matches[0]

    def get_by_url(self, url: str) -> Optional[A2AAgentEntry]:
        """Get an agent by its stable URL identity."""
        return self._agents.get(self._key(url))

    def get_by_skill(self, skill_name: str) -> List[A2AAgentEntry]:
        """Find agents that have a specific skill."""
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
        """Save registry to file (URL-keyed; name is presentational)."""
        import json

        data = {
            self._key(entry.url): {
                "name": entry.name,
                "url": self._key(entry.url),
                "description": entry.description,
                "version": entry.version,
                "skills": entry.skills,
            }
            for entry in self._agents.values()
        }

        path = Path(self._config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def load(self) -> None:
        """Load registry from file.

        Supports the current URL-keyed format and the older name-keyed format
        (top-level key was the alias, with ``url`` inside each object).
        """
        import json

        path = Path(self._config_path)
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text())
            self._agents.clear()
            for top_key, info in data.items():
                if not isinstance(info, dict):
                    continue
                url = str(info.get("url") or top_key)
                name = str(info.get("name") or top_key)
                entry = A2AAgentEntry(
                    name=name,
                    url=self._key(url),
                    description=info.get("description", ""),
                    version=info.get("version", "1.0"),
                    skills=info.get("skills", []),
                )
                # Skip colliding aliases from corrupt files rather than crash load.
                try:
                    self._put(entry)
                except AmbiguousAgentName:
                    # Prefer the URL identity; drop the colliding presentational alias.
                    entry.name = self._key(url)
                    self._agents[self._key(url)] = entry
        except Exception:
            pass


# Known public A2A agents (placeholder - would come from actual registry)
KNOWN_A2A_AGENTS = {
    "gemini-cli": "http://localhost:8080",
    "claude-code": "http://localhost:8081",
    "codex": "http://localhost:8082",
}


async def discover_known_agents() -> Dict[str, A2AAgentEntry]:
    """Discover known public A2A agents.

    Returned dict keys are local known-agent aliases, not remote card names.
    """
    discovered = {}

    for name, url in KNOWN_A2A_AGENTS.items():
        try:
            client = A2AClient(url)
            card = await client.get_agent_card()
            await client.close()

            discovered[name] = A2AAgentEntry(
                name=name,
                url=normalize_url(url),
                description=card.description,
                skills=[{"id": s.id, "name": s.name} for s in card.skills],
                verified=True,
            )
        except Exception:
            pass

    return discovered
