"""
Agent Registry for SuperQode.

This module defines all supported coding agents with their configuration,
connection methods, and capabilities. Agents are organized by protocol
(ACP vs External).

SECURITY PRINCIPLE: SuperQode NEVER stores agent credentials.
Each agent manages its own authentication.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import Agent

from .acp_registry import (
    get_all_registry_agents,
    get_registry_agent,
    get_registry_agent_by_short_name,
    AgentMetadata,
)


class AgentProtocol(Enum):
    """Agent communication protocol."""

    ACP = "acp"  # Agent Client Protocol (standard)
    EXTERNAL = "external"  # Non-ACP agents via adapters (future)


class AgentStatus(Enum):
    """Agent support status."""

    SUPPORTED = "supported"
    COMING_SOON = "coming_soon"
    EXPERIMENTAL = "experimental"


@dataclass
class AgentDef:
    """Definition of a coding agent."""

    id: str
    name: str
    protocol: AgentProtocol
    status: AgentStatus
    description: str
    auth_info: str
    setup_command: str
    docs_url: str
    capabilities: List[str] = field(default_factory=list)
    connection_type: str = "stdio"  # "stdio" | "http" | "cli"
    command: Optional[str] = None  # CLI command to start agent
    default_port: Optional[int] = None  # For HTTP connections


# =============================================================================
# AGENT REGISTRY
# =============================================================================

AGENTS: Dict[str, AgentDef] = {
    # =========================================================================
    # ACP AGENTS (Agent Client Protocol)
    # =========================================================================
    "opencode": AgentDef(
        id="opencode",
        name="OpenCode",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="AI-powered coding agent with full file/shell capabilities",
        auth_info="~/.local/share/opencode/auth.json (managed by opencode)",
        setup_command="Run 'opencode' and use /connect to configure providers",
        docs_url="https://opencode.ai/docs",
        capabilities=[
            "File reading/writing",
            "Shell command execution",
            "MCP tool integration",
            "Multi-step reasoning",
            "Context management",
            "75+ LLM providers",
        ],
        connection_type="stdio",
        command="opencode",
    ),
    "aider": AgentDef(
        id="aider",
        name="Aider",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.COMING_SOON,
        description="AI pair programming in your terminal",
        auth_info="Environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)",
        setup_command="pip install aider-chat && export OPENAI_API_KEY=xxx",
        docs_url="https://aider.chat/docs",
        capabilities=[
            "File editing",
            "Git integration",
            "Multi-file changes",
            "Code refactoring",
        ],
        connection_type="stdio",
        command="aider",
    ),
    # =========================================================================
    # EXTERNAL AGENTS (Non-ACP, Future)
    # =========================================================================
    "claude-code": AgentDef(
        id="claude-code",
        name="Claude Code",
        protocol=AgentProtocol.EXTERNAL,
        status=AgentStatus.COMING_SOON,
        description="Anthropic's official coding agent",
        auth_info="Anthropic account (OAuth via claude.ai)",
        setup_command="Install Claude Code CLI and authenticate",
        docs_url="https://claude.ai/code",
        capabilities=[
            "File editing",
            "Shell commands",
            "Project understanding",
            "Multi-file refactoring",
            "Extended thinking",
        ],
        connection_type="cli",
        command="claude",
    ),
    "cursor": AgentDef(
        id="cursor",
        name="Cursor",
        protocol=AgentProtocol.EXTERNAL,
        status=AgentStatus.COMING_SOON,
        description="AI-first code editor",
        auth_info="Cursor account",
        setup_command="Install Cursor and sign in",
        docs_url="https://cursor.sh/docs",
        capabilities=[
            "IDE integration",
            "Code completion",
            "Chat with codebase",
            "Multi-file editing",
        ],
        connection_type="cli",
    ),
    "amp": AgentDef(
        id="amp",
        name="Amp",
        protocol=AgentProtocol.EXTERNAL,
        status=AgentStatus.COMING_SOON,
        description="Sourcegraph's coding agent",
        auth_info="Sourcegraph account",
        setup_command="Install Amp CLI",
        docs_url="https://sourcegraph.com/amp",
        capabilities=[
            "Codebase search",
            "Multi-repo support",
            "Code intelligence",
            "Large codebase navigation",
        ],
        connection_type="cli",
        command="amp",
    ),
    "codex": AgentDef(
        id="codex",
        name="OpenAI Codex CLI",
        protocol=AgentProtocol.EXTERNAL,
        status=AgentStatus.COMING_SOON,
        description="OpenAI's coding agent",
        auth_info="OpenAI account (OPENAI_API_KEY)",
        setup_command="npm install -g @openai/codex",
        docs_url="https://openai.com/codex",
        capabilities=[
            "Code generation",
            "File editing",
            "Shell commands",
            "Sandboxed execution",
        ],
        connection_type="cli",
        command="codex",
    ),
    "gemini-code": AgentDef(
        id="gemini-code",
        name="Gemini Code Assist",
        protocol=AgentProtocol.EXTERNAL,
        status=AgentStatus.COMING_SOON,
        description="Google's coding assistant",
        auth_info="Google Cloud account",
        setup_command="Install Google Cloud CLI and authenticate",
        docs_url="https://cloud.google.com/gemini/docs/codeassist",
        capabilities=[
            "Code completion",
            "Code generation",
            "Code explanation",
            "IDE integration",
        ],
        connection_type="cli",
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_agent(agent_id: str) -> Optional[AgentDef]:
    """Get an agent definition by ID."""
    return AGENTS.get(agent_id)


def get_supported_agents() -> Dict[str, AgentDef]:
    """Get all supported agents."""
    return {k: v for k, v in AGENTS.items() if v.status == AgentStatus.SUPPORTED}


def get_acp_agents() -> Dict[str, AgentDef]:
    """Get all ACP protocol agents."""
    return {k: v for k, v in AGENTS.items() if v.protocol == AgentProtocol.ACP}


def get_external_agents() -> Dict[str, AgentDef]:
    """Get all external (non-ACP) agents."""
    return {k: v for k, v in AGENTS.items() if v.protocol == AgentProtocol.EXTERNAL}


def get_all_agent_ids() -> List[str]:
    """Get all agent IDs."""
    return list(AGENTS.keys())


def is_agent_available(agent_id: str) -> bool:
    """Check if an agent is available (supported status)."""
    agent = AGENTS.get(agent_id)
    return agent is not None and agent.status == AgentStatus.SUPPORTED


# =============================================================================
# NEW: ACP Agent Discovery Functions (for TOML-based agents)
# =============================================================================


async def get_all_acp_agents() -> dict[str, "Agent"]:
    """Get all ACP agents, merging local TOML files with registry.

    Returns:
        Dictionary mapping agent identity to Agent dict.
        Local agents take precedence over registry agents.
    """
    from .discovery import read_agents

    # Get local agents first (without registry to avoid circular import)
    local_agents = await read_agents(include_registry=False)

    # Get registry agents
    registry_agents = get_all_registry_agents()

    # Convert registry agents to Agent format and merge
    for identity, metadata in registry_agents.items():
        # Skip if already in local agents
        if identity in local_agents:
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

        local_agents[identity] = agent

    return local_agents


async def get_agent_metadata(agent_id: str) -> "Agent | None":
    """Get agent metadata by identity or short name.

    Args:
        agent_id: Agent identity or short name.

    Returns:
        Agent dict if found, None otherwise.
    """
    all_agents = await get_all_acp_agents()

    # Try by identity first
    if agent_id in all_agents:
        return all_agents[agent_id]

    # Try by short name
    for agent in all_agents.values():
        if agent.get("short_name", "").lower() == agent_id.lower():
            return agent

    return None


def get_agent_installation_info(agent: "Agent") -> dict[str, str]:
    """Get installation information for an agent.

    Args:
        agent: Agent dict.

    Returns:
        Dictionary with installation command and instructions.
    """
    # Check if agent has actions
    actions = agent.get("actions", {})
    install_action = None

    # Try to get install action
    for os_actions in actions.values():
        if isinstance(os_actions, dict) and "install" in os_actions:
            install_action = os_actions["install"]
            break

    if install_action:
        return {
            "command": install_action.get("command", ""),
            "description": install_action.get("description", "Install agent"),
            "instructions": agent.get("help", "").split("## Installation")[-1].strip()
            if "## Installation" in agent.get("help", "")
            else "",
        }

    # Fallback to registry if available
    registry_agent = get_registry_agent(agent["identity"])
    if registry_agent:
        return {
            "command": registry_agent["installation_command"],
            "description": f"Install {registry_agent['name']}",
            "instructions": registry_agent["installation_instructions"],
        }

    return {
        "command": "",
        "description": "Installation not available",
        "instructions": "No installation instructions available for this agent.",
    }


async def sync_agents_from_zed() -> dict[str, "Agent"]:
    """Attempt to sync agents from zed.dev/acp (currently uses registry as fallback).

    Returns:
        Dictionary of agents from registry.
    """
    # For now, return registry agents
    # In the future, this could fetch from an API or scrape the website
    return await get_all_acp_agents()
