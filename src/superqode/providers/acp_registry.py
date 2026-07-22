"""Official Agent Client Protocol registry integration.

The ACP registry is the upstream source for agent metadata and distribution
manifests. SuperQode keeps a local cache and always has a bundled catalog for
offline use. Network access only occurs when callers explicitly request a
refresh, which keeps startup and the TUI deterministic.
"""

from __future__ import annotations

import json
import logging
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REGISTRY_CDN_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
CACHE_FILE = Path.home() / ".superqode" / "acp_registry_cache.json"
CACHE_TTL = timedelta(hours=1)

# The default picker remains intentionally small. Installed agents are always
# shown, even when they are not in one of these curated groups.
FEATURED_AGENT_IDS = frozenset(
    {
        "amp-acp",
        "amp",
        "claude-acp",
        "claude",
        "cline",
        "codex-acp",
        "codex",
        "copilot",
        "cursor",
        "github-copilot-cli",
        "goose",
        "grok-build",
        "grok",
        "harn",
        "kilo",
        "kimi",
        "opencode",
        "pi-acp",
        "pi",
        "qwen-code",
        "qwen",
    }
)
ENTERPRISE_AGENT_IDS = frozenset(
    {
        "auggie",
        "cortex",
        "cortex-code",
        "droid",
        "devin",
        "factory-droid",
        "junie",
        "poolside",
    }
)

# Registry ids do not always match the command users type. These aliases also
# keep existing SuperQode commands stable as upstream manifests evolve.
REGISTRY_SHORT_NAMES: dict[str, str] = {
    "amp-acp": "amp",
    "claude-acp": "claude",
    "codebuddy-code": "codebuddy",
    "codex-acp": "codex",
    "cortex-code": "cortex",
    "corust-agent": "corust",
    "crow-cli": "crow",
    "factory-droid": "droid",
    "github-copilot-cli": "copilot",
    "glm-acp-agent": "glm",
    "grok-build": "grok",
    "minion-code": "minion",
    "pi-acp": "pi",
    "qwen-code": "qwen",
}

REGISTRY_IDENTITIES: dict[str, str] = {
    "amp-acp": "ampcode.com",
    "auggie": "augmentcode.com",
    "claude-acp": "claude.com",
    "cline": "cline.bot",
    "codebuddy-code": "codebuddy.tencent.com",
    "codex-acp": "codex.openai.com",
    "cortex-code": "cortex.snowflake.com",
    "cursor": "cursor.com",
    "deepagents": "deepagents.langchain.com",
    "devin": "devin.ai",
    "dirac": "dirac.run",
    "factory-droid": "factory.ai",
    "fast-agent": "fastagent.ai",
    "gemini": "geminicli.com",
    "github-copilot-cli": "copilot.github.com",
    "goose": "goose.block.xyz",
    "grok-build": "x.ai",
    "harn": "harnlang.com",
    "junie": "junie.jetbrains.com",
    "kimi": "kimi.moonshot.cn",
    "kilo": "kilo.ai",
    "mistral-vibe": "mistral-vibe.mistral.ai",
    "opencode": "opencode.ai",
    "pi-acp": "pi.dev",
    "poolside": "poolside.ai",
    "qoder": "qoder.com",
    "qwen-code": "qwenlm.github.io",
    "sigit": "sigit.dev",
    "stakpak": "stakpak.dev",
    "vtcode": "vtcode.dev",
    "glm-acp-agent": "glm.z.ai",
}

# Commands verified against the current upstream registry. Binary manifests use
# downloaded paths that are meaningful to registry clients, so SuperQode keeps
# stable PATH-based equivalents for terminal users.
REGISTRY_RUN_COMMANDS: dict[str, str] = {
    "auggie": "auggie --acp",
    "claude-acp": "claude-agent-acp",
    "cline": "cline --acp",
    "codex-acp": "codex-acp",
    "cortex-code": "cortex acp serve",
    "cursor": "cursor-agent acp",
    "devin": "devin acp",
    "factory-droid": "droid exec --output-format acp-daemon",
    "gemini": "gemini --acp",
    "github-copilot-cli": "copilot --acp",
    "goose": "goose acp",
    "grok-build": "grok agent stdio",
    "harn": "harn serve acp",
    "junie": "junie --acp=true",
    "kilo": "kilo acp",
    "kimi": "kimi acp",
    "mistral-vibe": "vibe-acp",
    "opencode": "opencode acp",
    "pi-acp": "pi-acp",
    "poolside": "pool acp",
    "qwen-code": "qwen --acp --experimental-skills",
    "stakpak": "stakpak acp",
    "vtcode": "vtcode acp",
}

_cached_agents: list[dict[str, Any]] | None = None
_cache_time: datetime | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _load_cache(*, allow_stale: bool) -> list[dict[str, Any]] | None:
    """Load the on-disk registry cache."""
    global _cached_agents, _cache_time

    if not CACHE_FILE.exists():
        return None
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        agents = payload.get("agents", [])
        cached_at = _parse_time(str(payload.get("cached_at", "2000-01-01T00:00:00+00:00")))
        if not isinstance(agents, list):
            return None
        if not allow_stale and _now() - cached_at >= CACHE_TTL:
            return None
        _cached_agents = agents
        _cache_time = cached_at
        return agents
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load ACP registry cache: %s", exc)
        return None


def _save_cache(agents: list[dict[str, Any]]) -> None:
    """Persist a successful registry response."""
    global _cached_agents, _cache_time

    cached_at = _now()
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(
                {"version": 1, "cached_at": cached_at.isoformat(), "agents": agents},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to save ACP registry cache: %s", exc)
    _cached_agents = agents
    _cache_time = cached_at


async def fetch_registry_from_cdn() -> list[dict[str, Any]] | None:
    """Fetch and validate the official registry index."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(REGISTRY_CDN_URL)
            response.raise_for_status()
            payload = response.json()
        agents = payload.get("agents", [])
        if not isinstance(agents, list) or not agents:
            logger.warning("ACP registry returned no agents")
            return None
        return [agent for agent in agents if isinstance(agent, dict) and agent.get("id")]
    except Exception as exc:
        logger.warning("Failed to refresh ACP registry: %s", exc)
        return None


def _bundled_fallback() -> list[dict[str, Any]]:
    """Convert the bundled SuperQode catalog into registry-shaped records."""
    from superqode.agents.acp_registry import get_all_registry_agents

    records: list[dict[str, Any]] = []
    for metadata in get_all_registry_agents().values():
        records.append(
            {
                "id": metadata["short_name"],
                "name": metadata["name"],
                "description": metadata["description"],
                "website": metadata["url"],
                "authors": [metadata["author_name"]] if metadata["author_name"] else [],
                "source": "bundled",
                "_superqode": {
                    "identity": metadata["identity"],
                    "short_name": metadata["short_name"],
                    "run_command": metadata["run_command"],
                    "installation_command": metadata["installation_command"],
                    "installation_instructions": metadata["installation_instructions"],
                },
            }
        )
    return records


async def get_acp_registry_agents(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Return the official, cached, or bundled ACP catalog.

    Normal reads do not access the network. ``force_refresh=True`` fetches the
    official index, updates the cache, and falls back to a stale cache or the
    bundled catalog when the network is unavailable.
    """
    global _cached_agents, _cache_time

    if force_refresh:
        refreshed = await fetch_registry_from_cdn()
        if refreshed:
            _save_cache(refreshed)
            return refreshed
        stale = _load_cache(allow_stale=True)
        return stale or _bundled_fallback()

    if _cached_agents is not None and _cache_time is not None:
        if _now() - _cache_time < CACHE_TTL:
            return _cached_agents
    cached = _load_cache(allow_stale=False)
    if cached:
        return cached
    stale = _load_cache(allow_stale=True)
    return stale or _bundled_fallback()


async def get_agent_info(agent_id: str) -> dict[str, Any] | None:
    """Return one registry entry by id or stable SuperQode alias."""
    wanted = agent_id.casefold()
    for agent in await get_acp_registry_agents():
        registry_id = str(agent.get("id", ""))
        short_name = registry_short_name(registry_id)
        if wanted in {registry_id.casefold(), short_name.casefold()}:
            return agent
    return None


def clear_cache() -> None:
    """Clear the in-memory and on-disk registry cache."""
    global _cached_agents, _cache_time
    _cached_agents = None
    _cache_time = None
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to clear ACP registry cache: %s", exc)


def registry_short_name(registry_id: str) -> str:
    """Return the stable SuperQode command name for a registry id."""
    return REGISTRY_SHORT_NAMES.get(registry_id, registry_id)


def registry_catalog_tier(registry_id: str, short_name: str = "") -> str:
    """Classify an agent for the terminal picker."""
    candidates = {registry_id, short_name}
    if candidates & FEATURED_AGENT_IDS:
        return "featured"
    if candidates & ENTERPRISE_AGENT_IDS:
        return "enterprise"
    return "all"


def _package_without_version(package: str) -> str:
    if package.startswith("@"):
        version_separator = package.rfind("@")
        return package[:version_separator] if version_separator > package.find("/") else package
    return package.split("@", 1)[0]


def _distribution_commands(agent: dict[str, Any]) -> tuple[str, str]:
    """Return a runnable command and an optional install command."""
    registry_id = str(agent.get("id", ""))
    if registry_id in REGISTRY_RUN_COMMANDS:
        command = REGISTRY_RUN_COMMANDS[registry_id]
    else:
        command = ""

    distribution = agent.get("distribution", {})
    if not isinstance(distribution, dict):
        return command, ""

    npx = distribution.get("npx")
    if isinstance(npx, dict) and isinstance(npx.get("package"), str):
        package = npx["package"]
        args = [str(arg) for arg in npx.get("args", [])]
        launcher = shlex.join(["npx", "-y", package, *args])
        return command or launcher, f"npm install -g {_package_without_version(package)}"

    uvx = distribution.get("uvx")
    if isinstance(uvx, dict) and isinstance(uvx.get("package"), str):
        package = uvx["package"]
        args = [str(arg) for arg in uvx.get("args", [])]
        launcher = shlex.join(["uvx", package, *args])
        return command or launcher, f"uv tool install {_package_without_version(package)}"

    return command, ""


def convert_registry_agent(registry_agent: dict[str, Any]) -> dict[str, Any]:
    """Convert an upstream manifest to SuperQode's ``Agent`` mapping."""
    registry_id = str(registry_agent.get("id", "")).strip()
    bundled = registry_agent.get("_superqode", {})
    if not isinstance(bundled, dict):
        bundled = {}

    short_name = str(bundled.get("short_name") or registry_short_name(registry_id))
    identity = str(
        bundled.get("identity")
        or REGISTRY_IDENTITIES.get(registry_id)
        or f"{registry_id}.registry.agentclientprotocol.com"
    )
    command, install_command = _distribution_commands(registry_agent)
    command = str(bundled.get("run_command") or command)
    install_command = str(bundled.get("installation_command") or install_command)
    tier = registry_catalog_tier(registry_id, short_name)
    source = str(registry_agent.get("source") or "official-registry")
    authors = registry_agent.get("authors", [])
    author_name = str(authors[0]) if isinstance(authors, list) and authors else ""
    url = str(
        registry_agent.get("website")
        or registry_agent.get("repository")
        or "https://agentclientprotocol.com/registry"
    )
    name = str(registry_agent.get("name") or short_name)
    description = str(registry_agent.get("description") or "ACP-compatible coding agent.")
    instructions = str(bundled.get("installation_instructions") or "")
    if not instructions:
        instructions = (
            f"See {url} for authentication and installation details. "
            "Run `superqode agents refresh` to update registry metadata."
        )

    tags = ["official-acp", "registry", tier]
    return {
        "identity": identity,
        "name": name,
        "short_name": short_name,
        "url": url,
        "protocol": "acp",
        "author_name": author_name,
        "author_url": url,
        "publisher_name": "Agent Client Protocol Registry",
        "publisher_url": "https://github.com/agentclientprotocol/registry",
        "type": "coding",
        "description": description,
        "tags": tags,
        "recommended": tier == "featured",
        "catalog_tier": tier,
        "registry_id": registry_id,
        "registry_version": str(registry_agent.get("version") or ""),
        "registry_source": source,
        "help": f"# {name}\n\n{description}\n\n## Installation\n\n{instructions}",
        "run_command": {"*": command},
        "actions": {
            "*": {
                "install": {
                    "command": install_command,
                    "description": f"Install {name}",
                }
            }
        },
    }


def convert_to_agentdef(registry_agent: dict[str, Any]) -> dict[str, Any]:
    """Return the legacy ``AgentDef``-shaped mapping for older callers."""
    converted = convert_registry_agent(registry_agent)
    install = converted["actions"]["*"]["install"]["command"]
    return {
        "id": converted["short_name"],
        "name": converted["name"],
        "protocol": "acp",
        "status": "supported" if converted["run_command"]["*"] else "coming_soon",
        "description": converted["description"],
        "auth_info": "Authentication is managed by the ACP agent",
        "setup_command": install,
        "docs_url": converted["url"],
        "capabilities": ["ACP"],
        "connection_type": "stdio",
        "command": converted["run_command"]["*"],
        "source": converted["registry_source"],
        "catalog_tier": converted["catalog_tier"],
    }


__all__ = [
    "CACHE_FILE",
    "ENTERPRISE_AGENT_IDS",
    "FEATURED_AGENT_IDS",
    "REGISTRY_CDN_URL",
    "clear_cache",
    "convert_registry_agent",
    "convert_to_agentdef",
    "fetch_registry_from_cdn",
    "get_acp_registry_agents",
    "get_agent_info",
    "registry_catalog_tier",
    "registry_short_name",
]
