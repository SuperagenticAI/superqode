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
    # =========================================================================
    # TIER 1: Major ACP-Compatible Coding Agents
    # =========================================================================
    "claude.com": {
        "identity": "claude.com",
        "name": "Claude Code",
        "short_name": "claude",
        "url": "https://claude.ai/code",
        "author_name": "Anthropic",
        "author_url": "https://www.anthropic.com/",
        "description": "Anthropic's official CLI coding agent. Unleash Claude's raw power directly in your terminal.",
        "run_command": "claude-code-acp",
        "status": "available",
        "installation_command": "curl -fsSL https://claude.ai/install.sh | bash && npm install -g @zed-industries/claude-code-acp",
        "installation_instructions": "1. Install Claude Code CLI using the official installer\n2. Install the ACP adapter via npm\n3. Authenticate with your Anthropic account",
        "requirements": ["node", "npm", "Anthropic account"],
    },
    "opencode.ai": {
        "identity": "opencode.ai",
        "name": "OpenCode",
        "short_name": "opencode",
        "url": "https://opencode.ai/",
        "author_name": "SST",
        "author_url": "https://sst.dev/",
        "description": "Open-source AI coding agent built for the terminal with client/server architecture and native ACP support.",
        "run_command": "opencode acp",
        "status": "available",
        "installation_command": "npm i -g opencode-ai",
        "installation_instructions": "Install OpenCode via npm. Supports 75+ LLM providers.",
        "requirements": ["node", "npm"],
    },
    "geminicli.com": {
        "identity": "geminicli.com",
        "name": "Gemini CLI",
        "short_name": "gemini",
        "url": "https://github.com/anthropics/gemini-cli",
        "author_name": "Google",
        "author_url": "https://google.com",
        "description": "Google's Gemini AI in your terminal with experimental ACP support.",
        "run_command": "gemini --experimental-acp",
        "status": "available",
        "installation_command": "npm install -g @anthropics/gemini-cli",
        "installation_instructions": "Install Gemini CLI. Requires Google Cloud authentication for full features.",
        "requirements": ["node", "npm", "Google Cloud account (optional)"],
    },
    "codex.openai.com": {
        "identity": "codex.openai.com",
        "name": "Codex",
        "short_name": "codex",
        "url": "https://openai.com/codex",
        "author_name": "OpenAI",
        "author_url": "https://openai.com",
        "description": "OpenAI's code generation agent with streaming terminal output and ACP adapter.",
        "run_command": "codex-acp",
        "status": "available",
        "installation_command": "npm install -g @zed-industries/codex-acp",
        "installation_instructions": "Install Codex ACP adapter via npm. Requires OpenAI API key.",
        "requirements": ["node", "npm", "OPENAI_API_KEY"],
    },
    "goose.ai": {
        "identity": "goose.ai",
        "name": "Goose",
        "short_name": "goose",
        "url": "https://github.com/block/goose",
        "author_name": "Block",
        "author_url": "https://block.xyz/",
        "description": "Block's developer agent that automates engineering tasks. Extensible with MCP.",
        "run_command": "goose",
        "status": "available",
        "installation_command": "pipx install goose-ai",
        "installation_instructions": "Install Goose via pipx for isolated environment. Configure providers via goose configure.",
        "requirements": ["python3.10+", "pipx"],
    },
    "augmentcode.com": {
        "identity": "augmentcode.com",
        "name": "Augment Code (Auggie)",
        "short_name": "auggie",
        "url": "https://augmentcode.com/",
        "author_name": "Augment",
        "author_url": "https://augmentcode.com/",
        "description": "AI-powered coding agent with deep codebase understanding and ACP support.",
        "run_command": "auggie --acp",
        "status": "available",
        "installation_command": "npm install -g @augmentcode/auggie",
        "installation_instructions": "Install Auggie via npm. Sign up at augmentcode.com for API access.",
        "requirements": ["node", "npm", "Augment account"],
    },
    "openhands.ai": {
        "identity": "openhands.ai",
        "name": "OpenHands",
        "short_name": "openhands",
        "url": "https://github.com/All-Hands-AI/OpenHands",
        "author_name": "All Hands AI",
        "author_url": "https://all-hands.dev/",
        "description": "Open-source AI software developer platform. Previously OpenDevin.",
        "run_command": "openhands-acp",
        "status": "available",
        "installation_command": "pip install openhands-ai && pip install openhands-acp-adapter",
        "installation_instructions": "Install OpenHands and ACP adapter. Requires LLM provider API key.",
        "requirements": ["python3.10+", "pip", "docker (recommended)"],
    },
    # =========================================================================
    # TIER 2: Community and Specialized Agents
    # =========================================================================
    "stakpak.ai": {
        "identity": "stakpak.ai",
        "name": "Stakpak",
        "short_name": "stakpak",
        "url": "https://github.com/stakpak/stakpak",
        "author_name": "Stakpak",
        "author_url": "https://github.com/stakpak",
        "description": "An ACP-compatible agent focused on comprehensive code assistance and collaboration.",
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
        "description": "A versatile coding agent implementing ACP for seamless development environment integration.",
        "run_command": "vtcode-acp",
        "status": "available",
        "installation_command": "npm install -g vtcode-acp",
        "installation_instructions": "Install VT Code ACP adapter via npm.",
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
        "description": "A powerful, customizable multi-agent runtime that orchestrates AI agents.",
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
        "url": "https://github.com/evalstate/fast-agent",
        "author_name": "fast-agent",
        "author_url": "https://github.com/evalstate",
        "description": "Create and interact with sophisticated Agents and Workflows in minutes. MCP native.",
        "run_command": "fast-agent-acp",
        "status": "available",
        "installation_command": "uv pip install fast-agent-mcp",
        "installation_instructions": "Install fast-agent via uv (recommended) or pip. Native MCP support.",
        "requirements": ["python3.10+", "uv or pip"],
    },
    "llmlingagent.ai": {
        "identity": "llmlingagent.ai",
        "name": "LLMling-Agent",
        "short_name": "llmlingagent",
        "url": "https://github.com/llmling/llmling-agent",
        "author_name": "LLMling",
        "author_url": "https://github.com/llmling",
        "description": "A framework for creating and managing LLM-powered agents with structured interactions.",
        "run_command": "llmling-agent",
        "status": "available",
        "installation_command": "pip install llmling-agent",
        "installation_instructions": "Install LLMling-Agent via pip.",
        "requirements": ["python3", "pip"],
    },
    # =========================================================================
    # TIER 3: Enterprise and IDE-Integrated (Coming Soon)
    # =========================================================================
    "copilot.github.com": {
        "identity": "copilot.github.com",
        "name": "GitHub Copilot",
        "short_name": "copilot",
        "url": "https://github.com/features/copilot",
        "author_name": "GitHub",
        "author_url": "https://github.com",
        "description": "GitHub's AI pair programmer. ACP adapter in development.",
        "run_command": "copilot-acp",
        "status": "coming-soon",
        "installation_command": "npm install -g @github/copilot-acp",
        "installation_instructions": "GitHub Copilot ACP adapter is coming soon. Requires Copilot subscription.",
        "requirements": ["node", "npm", "GitHub Copilot subscription"],
    },
    "cursor.sh": {
        "identity": "cursor.sh",
        "name": "Cursor",
        "short_name": "cursor",
        "url": "https://cursor.sh/",
        "author_name": "Anysphere",
        "author_url": "https://anysphere.inc/",
        "description": "AI-first code editor with built-in agent capabilities. ACP support planned.",
        "run_command": "cursor --acp",
        "status": "coming-soon",
        "installation_command": "brew install --cask cursor",
        "installation_instructions": "Download Cursor from cursor.sh. ACP mode is in development.",
        "requirements": ["Cursor subscription"],
    },
    "amp.sourcegraph.com": {
        "identity": "amp.sourcegraph.com",
        "name": "Amp (Sourcegraph)",
        "short_name": "amp",
        "url": "https://sourcegraph.com/amp",
        "author_name": "Sourcegraph",
        "author_url": "https://sourcegraph.com/",
        "description": "Sourcegraph's coding agent for large codebases. ACP support planned.",
        "run_command": "amp --acp",
        "status": "coming-soon",
        "installation_command": "brew install sourcegraph/amp/amp",
        "installation_instructions": "Amp ACP mode is in development. Currently IDE-integrated only.",
        "requirements": ["Sourcegraph account"],
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
