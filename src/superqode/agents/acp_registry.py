"""Curated list of all ACP agents from zed.dev/acp.

This registry contains metadata for all known ACP agents, including those
not yet in local TOML files. This allows the system to show all available
agents and provide installation instructions.
"""

from typing import TypedDict, Literal

AgentStatus = Literal["available", "coming-soon", "deprecated"]


class AgentMetadata(TypedDict):
    """Metadata for an ACP agent."""

    identity: str
    name: str
    short_name: str
    url: str
    author_name: str
    author_url: str
    description: str
    run_command: str
    status: AgentStatus
    installation_command: str
    installation_instructions: str
    requirements: list[str]


ACP_AGENTS_REGISTRY: dict[str, AgentMetadata] = {
    "codex.openai.com": {
        "identity": "codex.openai.com",
        "name": "Codex",
        "short_name": "codex",
        "url": "https://openai.com/codex",
        "author_name": "OpenAI",
        "author_url": "https://openai.com",
        "description": "OpenAI's code generation agent with streaming terminal output and community adapters.",
        "run_command": "codex-acp",
        "status": "available",
        "installation_command": "npm install -g @zed-industries/codex-acp",
        "installation_instructions": "Install Codex ACP adapter via npm. Requires Node.js and npm.",
        "requirements": ["node", "npm"],
    },
    "stakpak.ai": {
        "identity": "stakpak.ai",
        "name": "Stakpak",
        "short_name": "stakpak",
        "url": "https://github.com/stakpak/stakpak",
        "author_name": "Stakpak",
        "author_url": "https://github.com/stakpak",
        "description": "An ACP-compatible agent focused on providing comprehensive code assistance and collaboration features.",
        "run_command": "stakpak",
        "status": "available",
        "installation_command": "pip install stakpak",
        "installation_instructions": "Install Stakpak via pip. Requires Python 3.8+.",
        "requirements": ["python3", "pip"],
    },
    "vtcode.ai": {
        "identity": "vtcode.ai",
        "name": "VT Code",
        "short_name": "vtcode",
        "url": "https://github.com/vtcode/vtcode",
        "author_name": "VT Code",
        "author_url": "https://github.com/vtcode",
        "description": "A versatile coding agent implementing ACP for seamless integration with compatible development environments.",
        "run_command": "vtcode-acp",
        "status": "available",
        "installation_command": "npm install -g vtcode-acp",
        "installation_instructions": "Install VT Code ACP adapter via npm. Requires Node.js and npm.",
        "requirements": ["node", "npm"],
    },
    "codeassistant.ai": {
        "identity": "codeassistant.ai",
        "name": "Code Assistant",
        "short_name": "codeassistant",
        "url": "https://github.com/codeassistant/codeassistant",
        "author_name": "Code Assistant",
        "author_url": "https://github.com/codeassistant",
        "description": "An AI coding assistant built in Rust for autonomous code analysis and modification.",
        "run_command": "code-assistant",
        "status": "available",
        "installation_command": "cargo install code-assistant",
        "installation_instructions": "Install Code Assistant via Cargo. Requires Rust toolchain.",
        "requirements": ["rust", "cargo"],
    },
    "cagent.ai": {
        "identity": "cagent.ai",
        "name": "cagent",
        "short_name": "cagent",
        "url": "https://github.com/cagent/cagent",
        "author_name": "cagent",
        "author_url": "https://github.com/cagent",
        "description": "A powerful, easy-to-use, customizable multi-agent runtime that orchestrates AI agents.",
        "run_command": "cagent",
        "status": "available",
        "installation_command": "pip install cagent",
        "installation_instructions": "Install cagent via pip. Requires Python 3.8+.",
        "requirements": ["python3", "pip"],
    },
    "fastagent.ai": {
        "identity": "fastagent.ai",
        "name": "fast-agent",
        "short_name": "fastagent",
        "url": "https://github.com/fastagent/fast-agent",
        "author_name": "fast-agent",
        "author_url": "https://github.com/fastagent",
        "description": "Create and interact with sophisticated Agents and Workflows in minutes.",
        "run_command": "fast-agent",
        "status": "available",
        "installation_command": "npm install -g fast-agent",
        "installation_instructions": "Install fast-agent via npm. Requires Node.js and npm.",
        "requirements": ["node", "npm"],
    },
    "llmlingagent.ai": {
        "identity": "llmlingagent.ai",
        "name": "LLMling-Agent",
        "short_name": "llmlingagent",
        "url": "https://github.com/llmling/llmling-agent",
        "author_name": "LLMling",
        "author_url": "https://github.com/llmling",
        "description": "A framework for creating and managing LLM-powered agents to provide structured interactions.",
        "run_command": "llmling-agent",
        "status": "available",
        "installation_command": "pip install llmling-agent",
        "installation_instructions": "Install LLMling-Agent via pip. Requires Python 3.8+.",
        "requirements": ["python3", "pip"],
    },
}


def get_all_registry_agents() -> dict[str, AgentMetadata]:
    """Get all agents from the registry.

    Returns:
        Dictionary mapping agent identity to metadata.
    """
    return ACP_AGENTS_REGISTRY.copy()


def get_registry_agent(identity: str) -> AgentMetadata | None:
    """Get a specific agent from the registry.

    Args:
        identity: Agent identity to look up.

    Returns:
        Agent metadata if found, None otherwise.
    """
    return ACP_AGENTS_REGISTRY.get(identity)


def get_registry_agent_by_short_name(short_name: str) -> AgentMetadata | None:
    """Get a registry agent by short name.

    Args:
        short_name: Agent short name to look up.

    Returns:
        Agent metadata if found, None otherwise.
    """
    for agent in ACP_AGENTS_REGISTRY.values():
        if agent["short_name"].lower() == short_name.lower():
            return agent
    return None
