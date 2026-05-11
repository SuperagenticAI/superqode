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
    # 14 OFFICIAL ACP AGENTS (Agent Client Protocol)
    # =========================================================================
    "opencode": AgentDef(
        id="opencode",
        name="OpenCode",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Open-source AI coding agent built for the terminal",
        auth_info="Managed by opencode via /connect",
        setup_command="npm install -g opencode-ai",
        docs_url="https://opencode.ai/docs",
        capabilities=["File editing", "Shell commands", "MCP tools", "75+ providers"],
        connection_type="stdio",
        command="opencode acp",
    ),
    "gemini": AgentDef(
        id="gemini",
        name="Gemini CLI",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Google's reference ACP implementation",
        auth_info="GEMINI_API_KEY or GOOGLE_API_KEY",
        setup_command="npm install -g @anthropic-ai/gemini-cli",
        docs_url="https://github.com/google-gemini/gemini-cli",
        capabilities=["Large codebases", "Multimodal input", "2M context"],
        connection_type="stdio",
        command="gemini --experimental-acp",
    ),
    "claude": AgentDef(
        id="claude",
        name="Claude Code",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Anthropic's official CLI coding agent",
        auth_info="ANTHROPIC_API_KEY",
        setup_command="npm install -g @anthropic-ai/claude-code",
        docs_url="https://claude.ai/code",
        capabilities=["File editing", "Shell commands", "Extended thinking"],
        connection_type="stdio",
        command="claude --acp",
    ),
    "codex": AgentDef(
        id="codex",
        name="Codex",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="OpenAI's code generation agent",
        auth_info="OPENAI_API_KEY",
        setup_command="npm install -g @openai/codex",
        docs_url="https://github.com/openai/codex",
        capabilities=["Code generation", "File editing", "Shell commands"],
        connection_type="stdio",
        command="codex --acp",
    ),
    "junie": AgentDef(
        id="junie",
        name="JetBrains Junie",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="JetBrains' AI agent for IDE ecosystem",
        auth_info="JetBrains account (optional)",
        setup_command="npm install -g @jetbrains/junie",
        docs_url="https://www.jetbrains.com/junie/",
        capabilities=["IDE integration", "Code analysis", "Refactoring"],
        connection_type="stdio",
        command="junie --acp",
    ),
    "goose": AgentDef(
        id="goose",
        name="Goose",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Block's developer agent with MCP support",
        auth_info="Configure via goose configure",
        setup_command="pipx install goose-ai",
        docs_url="https://github.com/block/goose",
        capabilities=["Task automation", "MCP tools", "Multi-provider"],
        connection_type="stdio",
        command="goose mcp",
    ),
    "kimi": AgentDef(
        id="kimi",
        name="Kimi CLI",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Moonshot AI's CLI agent",
        auth_info="MOONSHOT_API_KEY",
        setup_command="npm install -g kimi-cli",
        docs_url="https://moonshot.cn/",
        capabilities=["Development workflows", "Long context"],
        connection_type="stdio",
        command="kimi --acp",
    ),
    "stakpak": AgentDef(
        id="stakpak",
        name="Stakpak",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="ACP-compatible code assistance agent",
        auth_info="API key via config",
        setup_command="pip install stakpak",
        docs_url="https://stakpak.dev",
        capabilities=["Code assistance", "Collaboration"],
        connection_type="stdio",
        command="stakpak --acp",
    ),
    "vtcode": AgentDef(
        id="vtcode",
        name="VT Code",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Versatile coding agent",
        auth_info="API key via config",
        setup_command="npm install -g vtcode",
        docs_url="https://vtcode.dev",
        capabilities=["Code editing", "Multi-environment"],
        connection_type="stdio",
        command="vtcode --acp",
    ),
    "auggie": AgentDef(
        id="auggie",
        name="Augment Code",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="AI-powered coding with deep codebase understanding",
        auth_info="AUGMENT_API_KEY",
        setup_command="npm install -g @anthropic-ai/auggie",
        docs_url="https://augmentcode.com/",
        capabilities=["Code analysis", "Modifications", "Tool execution"],
        connection_type="stdio",
        command="auggie --acp",
    ),
    "code-assistant": AgentDef(
        id="code-assistant",
        name="Code Assistant",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="AI coding assistant built in Rust",
        auth_info="API key via config",
        setup_command="cargo install code-assistant",
        docs_url="https://codeassistant.dev",
        capabilities=["Code analysis", "Autonomous modifications"],
        connection_type="stdio",
        command="code-assistant --acp",
    ),
    "cagent": AgentDef(
        id="cagent",
        name="cagent",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Multi-agent runtime orchestration",
        auth_info="API key via config",
        setup_command="pip install cagent",
        docs_url="https://cagent.dev",
        capabilities=["Multi-agent", "Orchestration", "Customizable"],
        connection_type="stdio",
        command="cagent --acp",
    ),
    "fast-agent": AgentDef(
        id="fast-agent",
        name="fast-agent",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Sophisticated agent workflows in minutes",
        auth_info="API key via config",
        setup_command="uv tool install fast-agent-mcp",
        docs_url="https://github.com/evalstate/fast-agent",
        capabilities=["Workflows", "MCP native", "Fast setup"],
        connection_type="stdio",
        command="fast-agent-acp",
    ),
    "llmling-agent": AgentDef(
        id="llmling-agent",
        name="LLMling-Agent",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="LLM-powered agent framework",
        auth_info="API key via config",
        setup_command="pip install llmling-agent",
        docs_url="https://github.com/phil65/llmling-agent",
        capabilities=["Structured interactions", "Framework"],
        connection_type="stdio",
        command="llmling-agent --acp",
    ),
    "amp": AgentDef(
        id="amp",
        name="Amp",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="AI coding agent by Ampcode with full ACP support",
        auth_info="Managed via amp login",
        setup_command="uv tool install acp-amp",
        docs_url="https://ampcode.com",
        capabilities=["File editing", "Shell commands", "MCP tools", "Multi-turn"],
        connection_type="stdio",
        command="acp-amp",
    ),
    # =========================================================================
    # ADDITIONAL ACP REGISTRY AGENTS (New from registry)
    # =========================================================================
    "cline": AgentDef(
        id="cline",
        name="Cline",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Autonomous coding agent CLI - capable of creating/editing files, running commands, using the browser",
        auth_info="ANTHROPIC_API_KEY or OPENAI_API_KEY",
        setup_command="npm install -g cline",
        docs_url="https://cline.bot/cli",
        capabilities=["File editing", "Shell commands", "Browser", "Multi-file edits"],
        connection_type="stdio",
        command="cline",
    ),
    "cursor": AgentDef(
        id="cursor",
        name="Cursor",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Cursor's AI coding agent with advanced code understanding",
        auth_info="CURSOR_API_KEY",
        setup_command="npm install -g cursor-agent",
        docs_url="https://cursor.com/docs/cli/acp",
        capabilities=["Code completion", "Edit generation", "Chat", "Terminal"],
        connection_type="stdio",
        command="cursor agent acp",
    ),
    "factory": AgentDef(
        id="factory",
        name="Factory Droid",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="AI coding agent powered by Factory AI",
        auth_info="FACTORY_API_KEY",
        setup_command="npm install -g droid",
        docs_url="https://factory.ai/product/cli",
        capabilities=["Code analysis", "Autonomous modifications", "Code review"],
        connection_type="stdio",
        command="droid",
    ),
    "dirac": AgentDef(
        id="dirac",
        name="Dirac",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Reduces API costs by 50%+, produces better work. Hash-anchored parallel edits, AST manipulation",
        auth_info="OPENAI_API_KEY or ANTHROPIC_API_KEY",
        setup_command="npm install -g dirac-cli",
        docs_url="https://dirac.run",
        capabilities=["Cost optimization", "Fast edits", "AST manipulation", "Parallel edits"],
        connection_type="stdio",
        command="dirac",
    ),
    "deepagents": AgentDef(
        id="deepagents",
        name="DeepAgents",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.COMING_SOON,
        description="Python library for building agents with LangGraph - not a standalone CLI",
        auth_info="OPENAI_API_KEY or ANTHROPIC_API_KEY",
        setup_command="pip install deepagents",
        docs_url="https://docs.langchain.com/oss/python/deepagents/overview",
        capabilities=["LangGraph integration", "Sub-agent spawning", "Build custom agents"],
        connection_type="stdio",
        command="",  # No CLI - library only
    ),
    "codebuddy": AgentDef(
        id="codebuddy",
        name="Codebuddy",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.COMING_SOON,
        description="Tencent Cloud's official intelligent coding tool (desktop app, not CLI)",
        auth_info="TENCENT_CLOUD_API_KEY",
        setup_command="See https://www.codebuddy.cn/cli/",
        docs_url="https://www.codebuddy.cn/cli/",
        capabilities=["Code generation", "Code completion", "Analysis"],
        connection_type="stdio",
        command="",  # Unverified CLI
    ),
    "cortex": AgentDef(
        id="cortex",
        name="Cortex Code",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Snowflake's Cortex Code coding agent",
        auth_info="SNOWFLAKE_ACCOUNT",
        setup_command="pip install snowflake-cortex-code",
        docs_url="https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code",
        capabilities=["SQL generation", "Data analysis", "Code generation"],
        connection_type="stdio",
        command="cortex-code --acp",
    ),
    "agoragentic": AgentDef(
        id="agoragentic",
        name="Agoragentic",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Agent marketplace with 174+ AI capabilities, settled in USDC on Base L2",
        auth_info="USDC payment required for premium",
        setup_command="npm install -g agoragentic",
        docs_url="https://agoragentic.com",
        capabilities=["Marketplace", "174+ agents", "Payment integration"],
        connection_type="stdio",
        command="agoragentic --acp",
    ),
    "autohand": AgentDef(
        id="autohand",
        name="Autohand Code",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="AI coding agent powered by Autohand AI",
        auth_info="AUTOHAND_API_KEY",
        setup_command="npm install -g autohand-code",
        docs_url="https://www.autohand.ai/cli/",
        capabilities=["Code editing", "Shell commands", "File management"],
        connection_type="stdio",
        command="autohand --acp",
    ),
    "corust": AgentDef(
        id="corust",
        name="Corust Agent",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Co-building with a seasoned Rust partner",
        auth_info="CORUST_API_KEY",
        setup_command="npm install -g corust-agent",
        docs_url="https://corust.ai/",
        capabilities=["Rust development", "Code generation", "Analysis"],
        connection_type="stdio",
        command="corust --acp",
    ),
    "crow": AgentDef(
        id="crow",
        name="crow-cli",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Minimal ACP Native Coding Agent",
        auth_info="OPENAI_API_KEY",
        setup_command="npm install -g crow-ai-cli",
        docs_url="https://crow-ai.dev",
        capabilities=["Minimal", "Fast", "Simple"],
        connection_type="stdio",
        command="crow --acp",
    ),
    "dimcode": AgentDef(
        id="dimcode",
        name="DimCode",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="A coding agent that puts leading models at your command",
        auth_info="API key via config",
        setup_command="npm install -g dimcode",
        docs_url="https://dimcode.dev/docs/acp.html",
        capabilities=["Model selection", "Code editing", "Shell commands"],
        connection_type="stdio",
        command="dimcode --acp",
    ),
    "mistral-vibe": AgentDef(
        id="mistral-vibe",
        name="Mistral Vibe",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="Mistral's open-source CLI coding agent powered by Devstral 2 (free during promotional period)",
        auth_info="MISTRAL_API_KEY (configure via 'vibe configure')",
        setup_command="pip install mistral-vibe",
        docs_url="https://docs.mistral.ai/mistral-vibe/introduction",
        capabilities=[
            "File editing",
            "Shell commands",
            "MCP tools",
            "256K context",
            "Devstral 2 (free)",
        ],
        connection_type="stdio",
        command="vibe-acp",
    ),
    "pi": AgentDef(
        id="pi",
        name="Pi (earendil)",
        protocol=AgentProtocol.ACP,
        status=AgentStatus.SUPPORTED,
        description="TypeScript coding agent from earendil-works (47k stars) - use via ACP adapter",
        auth_info="API key for your chosen provider (OpenAI, Anthropic, Google, DeepSeek)",
        setup_command="npm install -g @earendil-works/pi-coding-agent && npm install -g pi-acp",
        docs_url="https://pi.dev",
        capabilities=["File editing", "Shell commands", "Multi-provider", "Extensions", "Skills"],
        connection_type="stdio",
        command="pi-acp",
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
