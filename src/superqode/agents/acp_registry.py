"""Curated list of 14 official ACP agents.

This registry contains metadata for all official ACP-compatible agents.
These are the agents that implement the Agent Client Protocol.
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


# 14 Official ACP Agents
ACP_AGENTS_REGISTRY: dict[str, AgentMetadata] = {
    # =========================================================================
    # 1. Gemini CLI - Google's Reference ACP Implementation
    # =========================================================================
    "geminicli.com": {
        "identity": "geminicli.com",
        "name": "Gemini CLI",
        "short_name": "gemini",
        "url": "https://github.com/google-gemini/gemini-cli",
        "author_name": "Google",
        "author_url": "https://google.com",
        "description": "Google's reference ACP implementation. Query and edit large codebases, generate apps from images or PDFs.",
        "run_command": "gemini --experimental-acp",
        "status": "available",
        "installation_command": "npm install -g @anthropic-ai/gemini-cli",
        "installation_instructions": "Install Gemini CLI via npm. Set GEMINI_API_KEY or GOOGLE_API_KEY.",
        "requirements": ["node", "npm", "GEMINI_API_KEY or GOOGLE_API_KEY"],
    },
    # =========================================================================
    # 2. Claude Code - Anthropic's Claude via Zed SDK Adapter
    # =========================================================================
    "claude.com": {
        "identity": "claude.com",
        "name": "Claude Code",
        "short_name": "claude",
        "url": "https://claude.ai/code",
        "author_name": "Anthropic",
        "author_url": "https://www.anthropic.com/",
        "description": "Anthropic's official CLI coding agent. Unleash Claude's raw power directly in your terminal.",
        "run_command": "claude --acp",
        "status": "available",
        "installation_command": "npm install -g @anthropic-ai/claude-code",
        "installation_instructions": "Install Claude Code CLI. Requires ANTHROPIC_API_KEY.",
        "requirements": ["node", "npm", "ANTHROPIC_API_KEY"],
    },
    # =========================================================================
    # 3. Codex - OpenAI's Code Generation Agent
    # =========================================================================
    "codex.openai.com": {
        "identity": "codex.openai.com",
        "name": "Codex",
        "short_name": "codex",
        "url": "https://github.com/openai/codex",
        "author_name": "OpenAI",
        "author_url": "https://openai.com",
        "description": "OpenAI's code generation agent with streaming terminal output and ACP adapter.",
        "run_command": "codex --acp",
        "status": "available",
        "installation_command": "npm install -g @openai/codex",
        "installation_instructions": "Install Codex via npm. Requires OPENAI_API_KEY.",
        "requirements": ["node", "npm", "OPENAI_API_KEY"],
    },
    # =========================================================================
    # 4. JetBrains Junie - JetBrains AI Agent
    # =========================================================================
    "junie.jetbrains.com": {
        "identity": "junie.jetbrains.com",
        "name": "JetBrains Junie",
        "short_name": "junie",
        "url": "https://www.jetbrains.com/junie/",
        "author_name": "JetBrains",
        "author_url": "https://www.jetbrains.com/",
        "description": "JetBrains' AI agent with ACP support across their entire IDE ecosystem.",
        "run_command": "junie --acp",
        "status": "available",
        "installation_command": "npm install -g @jetbrains/junie",
        "installation_instructions": "Install Junie via npm. Works with JetBrains account.",
        "requirements": ["node", "npm", "JetBrains account (optional)"],
    },
    # =========================================================================
    # 5. Goose - Square's Open-Source Agent
    # =========================================================================
    "goose.block.xyz": {
        "identity": "goose.block.xyz",
        "name": "Goose",
        "short_name": "goose",
        "url": "https://github.com/block/goose",
        "author_name": "Block",
        "author_url": "https://block.xyz/",
        "description": "Block's developer agent that automates engineering tasks. Extensible with MCP.",
        "run_command": "goose mcp",
        "status": "available",
        "installation_command": "pipx install goose-ai",
        "installation_instructions": "Install Goose via pipx. Configure providers via goose configure.",
        "requirements": ["python3.10+", "pipx"],
    },
    # =========================================================================
    # 6. Kimi CLI - Moonshot AI's Agent
    # =========================================================================
    "kimi.moonshot.cn": {
        "identity": "kimi.moonshot.cn",
        "name": "Kimi CLI",
        "short_name": "kimi",
        "url": "https://github.com/anthropics/kimi-cli",
        "author_name": "Moonshot AI",
        "author_url": "https://moonshot.cn/",
        "description": "CLI AI agent implementing ACP with support for various development workflows.",
        "run_command": "kimi --acp",
        "status": "available",
        "installation_command": "npm install -g kimi-cli",
        "installation_instructions": "Install Kimi CLI via npm. Set MOONSHOT_API_KEY.",
        "requirements": ["node", "npm", "MOONSHOT_API_KEY"],
    },
    # =========================================================================
    # 7. OpenCode - Open-Source Coding Agent
    # =========================================================================
    "opencode.ai": {
        "identity": "opencode.ai",
        "name": "OpenCode",
        "short_name": "opencode",
        "url": "https://opencode.ai/",
        "author_name": "SST",
        "author_url": "https://sst.dev/",
        "description": "Open-source AI coding agent built for the terminal with native ACP support.",
        "run_command": "opencode acp",
        "status": "available",
        "installation_command": "npm install -g opencode-ai",
        "installation_instructions": "Install OpenCode via npm. Supports 75+ LLM providers.",
        "requirements": ["node", "npm"],
    },
    # =========================================================================
    # 8. Stakpak - ACP-Compatible Code Assistance
    # =========================================================================
    "stakpak.dev": {
        "identity": "stakpak.dev",
        "name": "Stakpak",
        "short_name": "stakpak",
        "url": "https://github.com/stakpak/stakpak",
        "author_name": "Stakpak",
        "author_url": "https://stakpak.dev",
        "description": "An ACP-compatible agent focused on comprehensive code assistance and collaboration.",
        "run_command": "stakpak --acp",
        "status": "available",
        "installation_command": "pip install stakpak",
        "installation_instructions": "Install Stakpak via pip.",
        "requirements": ["python3", "pip"],
    },
    # =========================================================================
    # 9. VT Code - Versatile Coding Agent
    # =========================================================================
    "vtcode.dev": {
        "identity": "vtcode.dev",
        "name": "VT Code",
        "short_name": "vtcode",
        "url": "https://github.com/anthropics/vtcode",
        "author_name": "VT Code",
        "author_url": "https://vtcode.dev",
        "description": "A versatile coding agent implementing ACP for seamless development environment integration.",
        "run_command": "vtcode --acp",
        "status": "available",
        "installation_command": "npm install -g vtcode",
        "installation_instructions": "Install VT Code via npm.",
        "requirements": ["node", "npm"],
    },
    # =========================================================================
    # 10. Augment Code (Auggie) - Agentic Code Capabilities
    # =========================================================================
    "augmentcode.com": {
        "identity": "augmentcode.com",
        "name": "Augment Code",
        "short_name": "auggie",
        "url": "https://augmentcode.com/",
        "author_name": "Augment",
        "author_url": "https://augmentcode.com/",
        "description": "AI-powered coding agent with deep codebase understanding and ACP support.",
        "run_command": "auggie --acp",
        "status": "available",
        "installation_command": "npm install -g @anthropic-ai/auggie",
        "installation_instructions": "Install Auggie via npm. Sign up at augmentcode.com.",
        "requirements": ["node", "npm", "Augment account"],
    },
    # =========================================================================
    # 11. Code Assistant - AI Coding Assistant in Rust
    # =========================================================================
    "codeassistant.dev": {
        "identity": "codeassistant.dev",
        "name": "Code Assistant",
        "short_name": "code-assistant",
        "url": "https://github.com/anthropics/code-assistant",
        "author_name": "Code Assistant",
        "author_url": "https://codeassistant.dev",
        "description": "An AI coding assistant built in Rust for autonomous code analysis and modification.",
        "run_command": "code-assistant --acp",
        "status": "available",
        "installation_command": "cargo install code-assistant",
        "installation_instructions": "Install Code Assistant via Cargo.",
        "requirements": ["rust", "cargo"],
    },
    # =========================================================================
    # 12. cagent - Multi-Agent Runtime
    # =========================================================================
    "cagent.dev": {
        "identity": "cagent.dev",
        "name": "cagent",
        "short_name": "cagent",
        "url": "https://github.com/anthropics/cagent",
        "author_name": "cagent",
        "author_url": "https://cagent.dev",
        "description": "A powerful, customizable multi-agent runtime that orchestrates AI agents.",
        "run_command": "cagent --acp",
        "status": "available",
        "installation_command": "pip install cagent",
        "installation_instructions": "Install cagent via pip.",
        "requirements": ["python3", "pip"],
    },
    # =========================================================================
    # 13. fast-agent - Sophisticated Agent Workflows
    # =========================================================================
    "fastagent.ai": {
        "identity": "fastagent.ai",
        "name": "fast-agent",
        "short_name": "fast-agent",
        "url": "https://github.com/evalstate/fast-agent",
        "author_name": "fast-agent",
        "author_url": "https://github.com/evalstate",
        "description": "Create and interact with sophisticated Agents and Workflows in minutes. MCP native.",
        "run_command": "fast-agent-acp -x",
        "status": "available",
        "installation_command": "uv tool install fast-agent-mcp",
        "installation_instructions": "Install fast-agent via uv. Native MCP support.",
        "requirements": ["python3.10+", "uv"],
    },
    # =========================================================================
    # 14. LLMling-Agent - LLM-Powered Agent Framework
    # =========================================================================
    "llmlingagent.dev": {
        "identity": "llmlingagent.dev",
        "name": "LLMling-Agent",
        "short_name": "llmling-agent",
        "url": "https://github.com/phil65/llmling-agent",
        "author_name": "LLMling",
        "author_url": "https://github.com/phil65",
        "description": "A framework for creating and managing LLM-powered agents with structured interactions.",
        "run_command": "llmling-agent --acp",
        "status": "available",
        "installation_command": "pip install llmling-agent",
        "installation_instructions": "Install LLMling-Agent via pip.",
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
