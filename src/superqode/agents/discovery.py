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

    # Merge with registry if requested
    if include_registry:
        # Import here to avoid circular dependency
        from .acp_registry import get_all_registry_agents

        # Get registry agents and merge
        registry_agents = get_all_registry_agents()

        # Convert registry agents to Agent format and merge
        for identity, metadata in registry_agents.items():
            # Skip if already in local agents
            if identity in agent_map:
                continue

            # Convert registry metadata to Agent format
            agent: "Agent" = {
                "identity": metadata["identity"],
                "name": metadata["name"],
                "short_name": metadata["short_name"],
                "url": metadata["url"],
                "protocol": "acp",
                "author_name": metadata["author_name"],
                "author_url": metadata["author_url"],
                "publisher_name": "SuperQode Team",
                "publisher_url": "https://github.com/SuperagenticAI/superqode",
                "type": "coding",
                "description": metadata["description"],
                "tags": [],
                "help": f"# {metadata['name']}\n\n{metadata['description']}\n\n## Installation\n\n{metadata['installation_instructions']}\n\nRun: `{metadata['installation_command']}`",
                "run_command": {"*": metadata["run_command"]},
                "actions": {
                    "*": {
                        "install": {
                            "command": metadata["installation_command"],
                            "description": f"Install {metadata['name']}",
                        }
                    }
                },
            }

            agent_map[identity] = agent

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
            agent_map = new_loop.run_until_complete(read_agents())
            return agent_map.get(identity)
        finally:
            new_loop.close()
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        agent_map = asyncio.run(read_agents())
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
            agents = new_loop.run_until_complete(read_agents())
            for agent in agents.values():
                if agent.get("short_name", "").lower() == short_name.lower():
                    return agent
            return None
        finally:
            new_loop.close()
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        agents = asyncio.run(read_agents())
        for agent in agents.values():
            if agent.get("short_name", "").lower() == short_name.lower():
                return agent
        return None
