"""Agent discovery system for SuperQode ACP integration."""

import asyncio
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import Agent

try:
    import tomllib
except ImportError:
    # Python < 3.12
    import tomli as tomllib


class AgentReadError(Exception):
    """Problem reading the agents."""


async def read_agents(include_registry: bool = False) -> dict[str, "Agent"]:
    """Read agent information from agents/data directory with enhanced error handling.

    Args:
        include_registry: If True, merge with registry agents. Default False for backward compatibility.

    Raises:
        AgentReadError: If the files could not be read.

    Returns:
        A mapping of identity on to Agent dict.
    """

    def read_agents_sync() -> tuple[list["Agent"], list[str]]:
        """Read agent information synchronously with error tracking.

        Stored in agents/data directory.

        Returns:
            Tuple of (agents_list, warnings_list)
        """
        agents: list["Agent"] = []
        warnings: list[str] = []

        # Define search paths
        search_paths = []

        # Add filesystem path (primary source)
        fs_data_dir = Path(__file__).parent / "data"
        if fs_data_dir.exists():
            search_paths.append(fs_data_dir)

        # Try package data as secondary source
        try:
            package_data_path = files("superqode.agents.data")
            # Convert to string path for Path constructor
            package_data_path = Path(str(package_data_path))
            if package_data_path.exists() and package_data_path not in search_paths:
                search_paths.append(package_data_path)
        except (ImportError, AttributeError, TypeError):
            pass  # Package data not available

        # Also check for user-defined agent directories
        user_agent_dir = Path.home() / ".superqode" / "agents"
        if user_agent_dir.exists():
            search_paths.append(user_agent_dir)

        if not search_paths:
            warnings.append("No agent data directories found")
            return agents, warnings

        # Read agents from all paths
        for search_path in search_paths:
            try:
                for file in search_path.iterdir():
                    if file.name.endswith(".toml") and file.is_file():
                        try:
                            agent: "Agent" = tomllib.load(file.open("rb"))
                            if agent.get("active", True):
                                # Validate required fields
                                required_fields = ["identity", "name", "short_name", "protocol"]
                                missing_fields = [
                                    field for field in required_fields if field not in agent
                                ]
                                if missing_fields:
                                    warnings.append(
                                        f"Agent {file.name}: missing required fields {missing_fields}"
                                    )
                                    continue

                                agents.append(agent)
                            else:
                                warnings.append(f"Agent {agent.get('name', file.name)} is disabled")
                        except tomllib.TOMLKitError as e:
                            warnings.append(f"Failed to parse {file.name}: {e}")
                        except Exception as e:
                            warnings.append(f"Error reading {file.name}: {e}")
            except Exception as e:
                warnings.append(f"Error reading directory {search_path}: {e}")

        return agents, warnings

    agents, warnings = await asyncio.to_thread(read_agents_sync)

    # Log warnings if any
    if warnings:
        import sys

        console = sys.modules.get("rich.console", None)
        if console:
            from rich.console import Console

            console = Console()
            for warning in warnings:
                console.print(f"[yellow]Warning: {warning}[/yellow]")

    agent_map = {agent["identity"]: agent for agent in agents}

    # Ensure the bundled catalog has stable terminal groups even before the
    # first network refresh.
    from superqode.providers.acp_registry import registry_catalog_tier

    for agent in agent_map.values():
        short_name = str(agent.get("short_name") or "")
        tier = str(agent.get("catalog_tier") or registry_catalog_tier("", short_name))
        agent["catalog_tier"] = tier  # type: ignore[typeddict-item]
        if tier == "featured":
            agent["recommended"] = True

    # Merge the cached official ACP registry when requested. Local TOML files
    # remain authoritative for commands, help text, and user-defined agents.
    if include_registry:
        from superqode.providers.acp_registry import (
            convert_registry_agent,
            get_acp_registry_agents,
        )

        registry_agents = await get_acp_registry_agents()
        identities_by_short_name = {
            str(agent.get("short_name", "")).casefold(): identity
            for identity, agent in agent_map.items()
        }
        for registry_agent in registry_agents:
            converted: "Agent" = convert_registry_agent(registry_agent)  # type: ignore[assignment]
            identity = converted["identity"]
            short_name = converted["short_name"].casefold()
            existing_identity = identity if identity in agent_map else identities_by_short_name.get(
                short_name
            )
            if existing_identity:
                existing = agent_map[existing_identity]
                existing["registry_id"] = converted.get("registry_id", "")
                existing["registry_version"] = converted.get("registry_version", "")
                existing["registry_source"] = converted.get("registry_source", "")
                existing["catalog_tier"] = converted.get("catalog_tier", "all")
                existing["recommended"] = converted.get("recommended", False)
                existing["tags"] = sorted(
                    set(existing.get("tags", [])) | set(converted.get("tags", []))
                )
                continue
            agent_map[identity] = converted
            identities_by_short_name[short_name] = identity

    if not agent_map:
        raise AgentReadError("No valid agents found in any data directory")

    return agent_map


async def get_agent_by_identity_async(
    identity: str, include_registry: bool = True
) -> "Agent | None":
    """Get a specific agent by identity (async version).

    Args:
        identity: The agent identity to look for.
        include_registry: If True, also check registry. Default True.

    Returns:
        The agent dict if found, None otherwise.
    """
    agent_map = await read_agents(include_registry=include_registry)
    return agent_map.get(identity)


async def get_agent_by_short_name_async(
    short_name: str, include_registry: bool = True
) -> "Agent | None":
    """Get a specific agent by short name (async version).

    Args:
        short_name: The agent short name to look for.
        include_registry: If True, also check registry. Default True.

    Returns:
        The agent dict if found, None otherwise.
    """
    agents = await read_agents(include_registry=include_registry)

    for agent in agents.values():
        if agent.get("short_name", "").lower() == short_name.lower():
            return agent

    return None


def get_agent_by_identity(identity: str) -> "Agent | None":
    """Get a specific agent by identity.

    Args:
        identity: The agent identity to look for.

    Returns:
        The agent dict if found, None otherwise.
    """
    import asyncio

    try:
        # Try to get the current event loop
        loop = asyncio.get_running_loop()
        # If we're in an async context, we need to handle this differently
        # For now, create a new event loop
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            agent_map = new_loop.run_until_complete(read_agents(include_registry=True))
            return agent_map.get(identity)
        finally:
            new_loop.close()
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        agent_map = asyncio.run(read_agents(include_registry=True))
        return agent_map.get(identity)


def get_agent_by_short_name(short_name: str) -> "Agent | None":
    """Get a specific agent by short name.

    Args:
        short_name: The agent short name to look for.

    Returns:
        The agent dict if found, None otherwise.
    """
    import asyncio

    try:
        # Try to get the current event loop
        loop = asyncio.get_running_loop()
        # If we're in an async context, we need to handle this differently
        # For now, create a new event loop
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            agents = new_loop.run_until_complete(read_agents(include_registry=True))
            for agent in agents.values():
                if agent.get("short_name", "").lower() == short_name.lower():
                    return agent
            return None
        finally:
            new_loop.close()
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        agents = asyncio.run(read_agents(include_registry=True))
        for agent in agents.values():
            if agent.get("short_name", "").lower() == short_name.lower():
                return agent
        return None
