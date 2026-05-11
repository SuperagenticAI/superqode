"""
ACP Agent Registry Discovery - Dynamically fetch all ACP-compatible agents.

This module fetches the official list of ACP agents from the registry CDN,
which is auto-updated hourly. This replaces hardcoded agent lists.

Official Registry: https://agentclientprotocol.com/registry
Registry CDN: https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json
GitHub: https://github.com/agentclientprotocol/registry

Usage:
    from superqode.providers.acp_registry import get_acp_registry_agents

    agents = await get_acp_registry_agents()
    for agent in agents:
        print(f"{agent['name']}: {agent['description']}")
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Registry CDN URL
REGISTRY_CDN_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
REGISTRY_GITHUB_API = "https://api.github.com/repos/agentclientprotocol/registry/contents"

# Local cache
CACHE_FILE = Path.home() / ".superqode" / "acp_registry_cache.json"
CACHE_TTL = timedelta(hours=1)  # Registry is updated hourly

_cached_agents: Optional[List[Dict]] = None
_cache_time: Optional[datetime] = None


async def fetch_registry_from_cdn() -> Optional[List[Dict]]:
    """Fetch agents from official CDN."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                REGISTRY_CDN_URL, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    agents = data.get("agents", [])
                    logger.info(f"Fetched {len(agents)} agents from ACP registry CDN")
                    return agents
                else:
                    logger.warning(f"Registry CDN returned {resp.status}")

    except ImportError:
        # Fallback to httpx
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(REGISTRY_CDN_URL)
                if resp.status_code == 200:
                    data = resp.json()
                    agents = data.get("agents", [])
                    logger.info(f"Fetched {len(agents)} agents from ACP registry CDN")
                    return agents
        except Exception as e:
            logger.warning(f"httpx fetch failed: {e}")

    except Exception as e:
        logger.warning(f"Failed to fetch from CDN: {e}")

    return None


async def fetch_registry_from_github() -> Optional[List[Dict]]:
    """Fallback: Fetch agent list from GitHub API."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                REGISTRY_GITHUB_API, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    folders = await resp.json()

                    # Folders to skip (non-agents)
                    skip_folders = {
                        ".github",
                        ".git",
                        "scripts",
                        "docs",
                        "examples",
                        "tests",
                        "test",
                        ".github",
                        "protocol-matrix",
                        "protocol_matrix",
                    }

                    agents = []
                    for folder in folders:
                        if folder.get("type") == "dir":
                            agent_id = folder["name"]
                            # Skip hidden folders and non-agents (case insensitive)
                            if agent_id.lower() in skip_folders:
                                continue
                            if agent_id.startswith("."):
                                continue

                            # Could fetch each agent.json here for more details
                            agents.append(
                                {
                                    "id": agent_id,
                                    "name": agent_id.replace("-", " ").replace("_", " ").title(),
                                    "source": "github",
                                }
                            )

                    logger.info(f"Fetched {len(agents)} agent folders from GitHub")
                    return agents

    except Exception as e:
        logger.warning(f"Failed to fetch from GitHub: {e}")

    return None


def _load_cache() -> Optional[List[Dict]]:
    """Load cached agents from file."""
    global _cached_agents, _cache_time

    if CACHE_FILE.exists():
        try:
            import json

            with open(CACHE_FILE) as f:
                data = json.load(f)
                cached = data.get("agents", [])
                cached_time = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))

                if datetime.now() - cached_time < CACHE_TTL:
                    _cached_agents = cached
                    _cache_time = cached_time
                    logger.debug(f"Using cached registry ({len(cached)} agents)")
                    return cached

        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")

    return None


def _save_cache(agents: List[Dict]) -> None:
    """Save agents to cache file."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

        import json

        with open(CACHE_FILE, "w") as f:
            json.dump(
                {
                    "agents": agents,
                    "cached_at": datetime.now().isoformat(),
                },
                f,
            )

        logger.debug(f"Saved {len(agents)} agents to cache")

    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


async def get_acp_registry_agents(force_refresh: bool = False) -> List[Dict]:
    """
    Get list of ACP agents from official registry.

    This fetches from the official ACP registry which is auto-updated hourly.
    Falls back to cache, then GitHub if needed.

    Args:
        force_refresh: If True, bypass cache and fetch fresh data

    Returns:
        List of agent dictionaries with metadata
    """
    global _cached_agents, _cache_time

    # Check cache first
    if not force_refresh and _cached_agents and _cache_time:
        if datetime.now() - _cache_time < CACHE_TTL:
            return _cached_agents

    # Try loading from file cache
    if not force_refresh:
        cached = _load_cache()
        if cached:
            return cached

    # Fetch from CDN
    agents = await fetch_registry_from_cdn()

    # Fallback to GitHub
    if not agents:
        agents = await fetch_registry_from_github()

    # Use hardcoded fallback if all else fails
    if not agents:
        logger.warning("All registry sources failed, using fallback")
        agents = _get_hardcoded_fallback()

    # Update cache
    if agents:
        _cached_agents = agents
        _cache_time = datetime.now()
        _save_cache(agents)

    return agents


def _get_hardcoded_fallback() -> List[Dict]:
    """Hardcoded fallback if all API sources fail."""
    return [
        {"id": "opencode", "name": "OpenCode", "source": "fallback"},
        {"id": "claude-code", "name": "Claude Code", "source": "fallback"},
        {"id": "gemini-cli", "name": "Gemini CLI", "source": "fallback"},
        {"id": "codex", "name": "Codex CLI", "source": "fallback"},
    ]


async def get_agent_info(agent_id: str) -> Optional[Dict]:
    """Get detailed info for a specific agent from registry."""
    agents = await get_acp_registry_agents()

    for agent in agents:
        if agent.get("id") == agent_id:
            return agent

    return None


def clear_cache() -> None:
    """Clear the registry cache to force refresh."""
    global _cached_agents, _cache_time
    _cached_agents = None
    _cache_time = None

    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
        logger.info("Cleared ACP registry cache")


# ============================================================================
# CONVERSION TO AGENTDEF FORMAT
# ============================================================================


def convert_to_agentdef(registry_agent: Dict) -> Dict:
    """
    Convert registry agent format to our AgentDef format.

    Args:
        registry_agent: Agent from registry

    Returns:
        Dictionary suitable for AgentDef
    """
    agent_id = registry_agent.get("id", "")
    name = registry_agent.get("name", agent_id.replace("-", " ").title())

    # Determine distribution method
    distribution = registry_agent.get("distribution", {})
    install_command = ""

    if "npx" in distribution:
        pkg = distribution["npx"]
        install_command = f"npx -y {pkg}"
    elif "uvx" in distribution:
        pkg = distribution["uvx"]
        install_command = f"uvx {pkg}"
    elif "binary" in distribution:
        # Binary distribution - OS-specific
        install_command = f"Download from {registry_agent.get('website', '')}"

    # Determine connection type
    connection_type = "stdio"
    command = f"{agent_id} --acp"

    # Auth methods
    auth_methods = registry_agent.get("authMethods", [])
    if "terminal" in auth_methods:
        command = f"{agent_id} --terminal-login"

    return {
        "id": agent_id,
        "name": name,
        "protocol": "acp",
        "status": "supported",
        "description": registry_agent.get("description", ""),
        "auth_info": f"Auth: {', '.join(auth_methods)}" if auth_methods else "Check documentation",
        "setup_command": install_command,
        "docs_url": registry_agent.get("website", ""),
        "capabilities": registry_agent.get("capabilities", []),
        "connection_type": connection_type,
        "command": command,
        "source": "registry",
    }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "get_acp_registry_agents",
    "get_agent_info",
    "convert_to_agentdef",
    "clear_cache",
    "REGISTRY_CDN_URL",
]
