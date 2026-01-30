"""
SuperQode ACP Agent Discovery - Auto-Discover Available Agents.

Automatically discovers ACP-compatible agents installed on the system
and provides a unified interface for connecting to them.

Supported Agents (14 Official ACP Agents):
- Gemini CLI (gemini) - Google's reference ACP implementation
- Claude Code (claude-code-acp) - Anthropic's Claude via Zed SDK adapter
- Codex (codex-acp) - OpenAI's code generation agent
- JetBrains Junie (junie) - JetBrains' AI agent for IDE ecosystem
- Goose (goose acp) - Square's open-source agent
- Kimi CLI (kimi) - CLI AI agent with ACP support
- OpenCode (opencode acp) - Open-source coding agent
- Stakpak (stakpak) - ACP-compatible code assistance agent
- VT Code (vtcode) - Versatile coding agent
- Augment Code (auggie) - Agentic capabilities for code analysis
- Code Assistant (code-assistant) - AI coding assistant in Rust
- cagent (cagent) - Multi-agent runtime orchestration
- fast-agent (fast-agent) - Sophisticated agent workflows
- LLMling-Agent (llmling-agent) - LLM-powered agent framework

Features:
- Auto-detection of installed agents
- Version checking
- Capability discovery
- Model listing
- Health checking

Usage:
    from superqode.acp_discovery import ACPDiscovery

    discovery = ACPDiscovery()
    agents = await discovery.discover_all()

    for agent in agents:
        print(f"{agent.name}: {agent.status}")
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================================
# ENUMS
# ============================================================================


class AgentStatus(Enum):
    """Agent availability status."""

    AVAILABLE = auto()  # Installed and ready
    NOT_INSTALLED = auto()  # Not found on system
    NOT_CONFIGURED = auto()  # Installed but needs setup (API key, etc)
    ERROR = auto()  # Error checking status


class ConnectionType(Enum):
    """Agent connection type."""

    ACP = "acp"  # Agent Client Protocol
    BYOK = "byok"  # Bring Your Own Key (direct API)
    LOCAL = "local"  # Local model


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class AgentCapability:
    """An agent capability."""

    name: str
    supported: bool = True
    version: str = ""
    notes: str = ""


@dataclass
class AgentModel:
    """An available model for an agent."""

    id: str
    name: str
    provider: str = ""
    is_free: bool = False
    description: str = ""
    context_window: int = 0


@dataclass
class DiscoveredAgent:
    """Information about a discovered agent."""

    # Identity
    name: str  # Display name
    short_name: str  # Short identifier
    command: List[str]  # Command to run ACP

    # Status
    status: AgentStatus = AgentStatus.NOT_INSTALLED
    version: str = ""
    error_message: str = ""

    # Connection
    connection_type: ConnectionType = ConnectionType.ACP
    requires_api_key: bool = False
    api_key_env_vars: List[str] = field(default_factory=list)
    has_api_key: bool = False

    # Capabilities
    capabilities: List[AgentCapability] = field(default_factory=list)
    models: List[AgentModel] = field(default_factory=list)

    # Metadata
    icon: str = "🤖"
    color: str = "#a855f7"
    website: str = ""
    description: str = ""


# ============================================================================
# AGENT DEFINITIONS
# ============================================================================

KNOWN_AGENTS: List[Dict[str, Any]] = [
    # =========================================================================
    # 1. Gemini CLI - Google's Reference ACP Implementation
    # =========================================================================
    {
        "name": "Gemini CLI",
        "short_name": "gemini",
        "command": ["gemini", "--experimental-acp"],
        "alt_commands": [
            ["npx", "-y", "@google/gemini-cli", "--experimental-acp"],
            ["gemini-cli", "--experimental-acp"],
        ],
        "icon": "✨",
        "color": "#4285f4",
        "description": "Google's reference ACP implementation showing full potential of agent integration",
        "website": "https://github.com/google-gemini/gemini-cli",
        "requires_api_key": True,
        "api_key_env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "check_command": ["gemini", "--version"],
    },
    # =========================================================================
    # 2. Claude Code - Anthropic's Claude via Zed SDK Adapter
    # =========================================================================
    {
        "name": "Claude Code",
        "short_name": "claude-code",
        "command": ["claude", "--acp"],
        "alt_commands": [
            ["npx", "-y", "@anthropic-ai/claude-code", "--acp"],
            ["claude-code-acp"],
            ["npx", "@anthropic-ai/claude-code-acp"],
        ],
        "icon": "🧡",
        "color": "#d97706",
        "description": "Anthropic's Claude integrated through Zed's SDK adapter",
        "website": "https://claude.ai/code",
        "requires_api_key": True,
        "api_key_env_vars": ["ANTHROPIC_API_KEY"],
        "check_command": ["claude", "--version"],
    },
    # =========================================================================
    # 3. Codex - OpenAI's Code Generation Agent
    # =========================================================================
    {
        "name": "Codex",
        "short_name": "codex",
        "command": ["codex", "--acp"],
        "alt_commands": [
            ["npx", "-y", "@openai/codex", "--acp"],
            ["npx", "@openai/codex-acp"],
        ],
        "icon": "📜",
        "color": "#10b981",
        "description": "OpenAI's code generation agent with streaming terminal output",
        "website": "https://github.com/openai/codex",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "CODEX_API_KEY"],
        "check_command": ["codex", "--version"],
    },
    # =========================================================================
    # 4. JetBrains Junie - JetBrains AI Agent
    # =========================================================================
    {
        "name": "JetBrains Junie",
        "short_name": "junie",
        "command": ["junie", "--acp"],
        "alt_commands": [
            ["npx", "-y", "@jetbrains/junie", "--acp"],
        ],
        "icon": "🧠",
        "color": "#fe315d",
        "description": "JetBrains' AI agent with ACP support across their entire IDE ecosystem",
        "website": "https://www.jetbrains.com/junie/",
        "requires_api_key": False,  # Uses JetBrains account
        "api_key_env_vars": ["JETBRAINS_API_KEY"],
        "check_command": ["junie", "--version"],
    },
    # =========================================================================
    # 5. Goose - Square's Open-Source Agent
    # =========================================================================
    {
        "name": "Goose",
        "short_name": "goose",
        "command": ["goose", "mcp"],
        "alt_commands": [
            ["goose", "acp"],
            ["goose", "--acp"],
        ],
        "icon": "🦆",
        "color": "#8b5cf6",
        "description": "Square's open-source agent with native ACP implementation",
        "website": "https://github.com/block/goose",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"],
        "check_command": ["goose", "--version"],
    },
    # =========================================================================
    # 6. Kimi CLI - CLI AI Agent with ACP
    # =========================================================================
    {
        "name": "Kimi CLI",
        "short_name": "kimi",
        "command": ["kimi", "--acp"],
        "alt_commands": [
            ["npx", "-y", "@anthropic-ai/kimi-cli", "--acp"],
            ["kimi-cli", "--acp"],
        ],
        "icon": "🌙",
        "color": "#5b21b6",
        "description": "CLI AI agent implementing ACP with support for various development workflows",
        "website": "https://github.com/anthropics/kimi-cli",
        "requires_api_key": True,
        "api_key_env_vars": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "check_command": ["kimi", "--version"],
    },
    # =========================================================================
    # 7. OpenCode - Open-Source Coding Agent
    # =========================================================================
    {
        "name": "OpenCode",
        "short_name": "opencode",
        "command": ["opencode", "acp"],
        "alt_commands": [
            ["opencode", "--acp"],
        ],
        "icon": "🌿",
        "color": "#22c55e",
        "description": "Open-source coding agent with ACP implementation for flexible integration",
        "website": "https://github.com/opencode-ai/opencode",
        "requires_api_key": False,  # Uses cloud with free tier
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["opencode", "--version"],
    },
    # =========================================================================
    # 8. Stakpak - ACP-Compatible Code Assistance
    # =========================================================================
    {
        "name": "Stakpak",
        "short_name": "stakpak",
        "command": ["stakpak", "--acp"],
        "alt_commands": [
            ["npx", "-y", "stakpak", "--acp"],
        ],
        "icon": "📦",
        "color": "#0ea5e9",
        "description": "ACP-compatible agent for comprehensive code assistance and collaboration",
        "website": "https://stakpak.dev",
        "requires_api_key": True,
        "api_key_env_vars": ["STAKPAK_API_KEY", "OPENAI_API_KEY"],
        "check_command": ["stakpak", "--version"],
    },
    # =========================================================================
    # 9. VT Code - Versatile Coding Agent
    # =========================================================================
    {
        "name": "VT Code",
        "short_name": "vtcode",
        "command": ["vtcode", "--acp"],
        "alt_commands": [
            ["vt-code", "--acp"],
            ["npx", "-y", "vtcode", "--acp"],
        ],
        "icon": "⚡",
        "color": "#f59e0b",
        "description": "Versatile coding agent implementing ACP for seamless integration",
        "website": "https://vtcode.dev",
        "requires_api_key": True,
        "api_key_env_vars": ["VTCODE_API_KEY", "OPENAI_API_KEY"],
        "check_command": ["vtcode", "--version"],
    },
    # =========================================================================
    # 10. Augment Code (Auggie) - Agentic Code Capabilities
    # =========================================================================
    {
        "name": "Augment Code",
        "short_name": "auggie",
        "command": ["auggie", "--acp"],
        "alt_commands": [
            ["augment", "--acp"],
            ["npx", "-y", "@anthropic-ai/auggie", "--acp"],
        ],
        "icon": "🔮",
        "color": "#ec4899",
        "description": "Powerful agentic capabilities to analyze code, make changes, and execute tools",
        "website": "https://www.augmentcode.com",
        "requires_api_key": True,
        "api_key_env_vars": ["AUGMENT_API_KEY"],
        "check_command": ["auggie", "--version"],
    },
    # =========================================================================
    # 11. Code Assistant - AI Coding Assistant in Rust
    # =========================================================================
    {
        "name": "Code Assistant",
        "short_name": "code-assistant",
        "command": ["code-assistant", "--acp"],
        "alt_commands": [
            ["ca", "--acp"],
        ],
        "icon": "🦀",
        "color": "#f97316",
        "description": "AI coding assistant built in Rust for autonomous code analysis and modification",
        "website": "https://github.com/anthropics/code-assistant",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["code-assistant", "--version"],
    },
    # =========================================================================
    # 12. cagent - Multi-Agent Runtime
    # =========================================================================
    {
        "name": "cagent",
        "short_name": "cagent",
        "command": ["cagent", "--acp"],
        "alt_commands": [
            ["npx", "-y", "cagent", "--acp"],
        ],
        "icon": "🤖",
        "color": "#6366f1",
        "description": "Powerful, easy-to-use, customizable multi-agent runtime that orchestrates AI agents",
        "website": "https://github.com/anthropics/cagent",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["cagent", "--version"],
    },
    # =========================================================================
    # 13. fast-agent - Sophisticated Agent Workflows
    # =========================================================================
    {
        "name": "fast-agent",
        "short_name": "fast-agent",
        "command": ["fast-agent-acp", "-x"],
        "alt_commands": [
            ["fast-agent-acp"],
            ["fast-agent", "serve", "--transport", "acp"],
        ],
        "icon": "🚀",
        "color": "#14b8a6",
        "description": "Create and interact with sophisticated Agents and Workflows in minutes",
        "website": "https://github.com/anthropics/fast-agent",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["fast-agent", "--version"],
    },
    # =========================================================================
    # 14. LLMling-Agent - LLM-Powered Agent Framework
    # =========================================================================
    {
        "name": "LLMling-Agent",
        "short_name": "llmling-agent",
        "command": ["llmling-agent", "--acp"],
        "alt_commands": [
            ["llmling", "--acp"],
            ["pip", "run", "llmling-agent", "--acp"],
        ],
        "icon": "🔗",
        "color": "#a855f7",
        "description": "Framework for creating and managing LLM-powered agents with structured interactions",
        "website": "https://github.com/anthropics/llmling-agent",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["llmling-agent", "--version"],
    },
]


# ============================================================================
# ACP DISCOVERY
# ============================================================================


class ACPDiscovery:
    """
    Discovers ACP-compatible agents on the system.
    """

    def __init__(self):
        self._agents: Dict[str, DiscoveredAgent] = {}
        self._discovered = False

    # ========================================================================
    # DISCOVERY
    # ========================================================================

    async def discover_all(self, force: bool = False) -> List[DiscoveredAgent]:
        """
        Discover all available ACP agents.

        Returns list of discovered agents.
        """
        if self._discovered and not force:
            return list(self._agents.values())

        # Run checks in parallel
        tasks = [self._check_agent(agent_def) for agent_def in KNOWN_AGENTS]
        agents = await asyncio.gather(*tasks)

        # Store results
        self._agents.clear()
        for agent in agents:
            self._agents[agent.short_name] = agent

        self._discovered = True
        return agents

    async def _check_agent(self, agent_def: Dict[str, Any]) -> DiscoveredAgent:
        """Check if an agent is available."""
        agent = DiscoveredAgent(
            name=agent_def["name"],
            short_name=agent_def["short_name"],
            command=agent_def["command"],
            icon=agent_def.get("icon", "🤖"),
            color=agent_def.get("color", "#a855f7"),
            description=agent_def.get("description", ""),
            website=agent_def.get("website", ""),
            requires_api_key=agent_def.get("requires_api_key", False),
            api_key_env_vars=agent_def.get("api_key_env_vars", []),
        )

        try:
            # Check if command exists
            cmd = agent_def.get("check_command", agent_def["command"])

            # Try main command first
            is_available, version = await self._check_command(cmd)

            # Try alternative commands if main fails
            if not is_available and "alt_commands" in agent_def:
                for alt_cmd in agent_def["alt_commands"]:
                    is_available, version = await self._check_command(alt_cmd)
                    if is_available:
                        agent.command = alt_cmd
                        break

            if is_available:
                agent.status = AgentStatus.AVAILABLE
                agent.version = version

                # Check for API key
                if agent.requires_api_key:
                    agent.has_api_key = any(os.environ.get(var) for var in agent.api_key_env_vars)
                    if not agent.has_api_key:
                        agent.status = AgentStatus.NOT_CONFIGURED
                        agent.error_message = (
                            f"Missing API key. Set one of: {', '.join(agent.api_key_env_vars)}"
                        )

                # Get capabilities and models
                agent.capabilities = await self._get_capabilities(agent)
                agent.models = await self._get_models(agent)

            else:
                agent.status = AgentStatus.NOT_INSTALLED

        except Exception as e:
            agent.status = AgentStatus.ERROR
            agent.error_message = str(e)

        return agent

    async def _check_command(self, cmd: List[str]) -> Tuple[bool, str]:
        """
        Check if a command exists and get its version.

        Returns (is_available, version).
        """
        try:
            # First check if the base command exists
            base_cmd = cmd[0]
            if not shutil.which(base_cmd) and base_cmd != "npx":
                return (False, "")

            # Try to get version
            loop = asyncio.get_event_loop()

            def run_check():
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result

            result = await loop.run_in_executor(None, run_check)

            if result.returncode == 0:
                # Try to extract version from output
                version = ""
                for line in (result.stdout + result.stderr).split("\n"):
                    line = line.strip()
                    if line and ("version" in line.lower() or line[0].isdigit()):
                        version = line
                        break

                return (True, version or "installed")

            # Command exists but returned error - might still be usable
            return (shutil.which(base_cmd) is not None or base_cmd == "npx", "")

        except subprocess.TimeoutExpired:
            return (True, "timeout")
        except Exception:
            return (False, "")

    async def _get_capabilities(self, agent: DiscoveredAgent) -> List[AgentCapability]:
        """Get agent capabilities via ACP handshake."""
        # Standard ACP capabilities
        capabilities = [
            AgentCapability(name="file_read", supported=True),
            AgentCapability(name="file_write", supported=True),
            AgentCapability(name="shell", supported=True),
            AgentCapability(name="search", supported=True),
        ]

        # TODO: Actually query agent for capabilities
        # This would involve starting the ACP process and doing handshake

        return capabilities

    async def _get_models(self, agent: DiscoveredAgent) -> List[AgentModel]:
        """Get available models for an agent."""
        # Predefined models based on agent type
        models_map = {
            # Gemini CLI - Google's models
            "gemini": [
                AgentModel(
                    id="gemini-2.5-pro",
                    name="Gemini 2.5 Pro",
                    provider="google",
                    description="Latest Gemini Pro with 2M context",
                    context_window=2000000,
                ),
                AgentModel(
                    id="gemini-2.5-flash",
                    name="Gemini 2.5 Flash",
                    provider="google",
                    description="Fast Gemini with 1M context",
                    context_window=1000000,
                ),
                AgentModel(
                    id="gemini-2.0-flash",
                    name="Gemini 2.0 Flash",
                    provider="google",
                    description="Previous generation flash model",
                    context_window=1000000,
                ),
                AgentModel(
                    id="gemini-2.0-flash-thinking",
                    name="Gemini 2.0 Flash Thinking",
                    provider="google",
                    description="Flash model with extended thinking",
                    context_window=1000000,
                ),
                AgentModel(
                    id="gemini-exp-1206",
                    name="Gemini Experimental",
                    provider="google",
                    description="Experimental Gemini model",
                    context_window=2000000,
                ),
            ],
            # Claude Code - Anthropic's models
            "claude-code": [
                AgentModel(
                    id="claude-sonnet-4-20250514",
                    name="Claude Sonnet 4",
                    provider="anthropic",
                    description="Latest Claude Sonnet",
                ),
                AgentModel(
                    id="claude-opus-4-20250514",
                    name="Claude Opus 4",
                    provider="anthropic",
                    description="Most capable Claude model",
                ),
                AgentModel(
                    id="claude-3-5-sonnet-20241022",
                    name="Claude 3.5 Sonnet",
                    provider="anthropic",
                    description="Previous generation Sonnet",
                ),
            ],
            # Codex - OpenAI's models
            "codex": [
                AgentModel(
                    id="o3", name="O3", provider="openai", description="Latest reasoning model"
                ),
                AgentModel(
                    id="o3-mini", name="O3 Mini", provider="openai", description="Fast reasoning"
                ),
                AgentModel(id="o1", name="O1", provider="openai", description="Advanced reasoning"),
                AgentModel(id="o1-mini", name="O1 Mini", provider="openai", description="Fast O1"),
                AgentModel(
                    id="gpt-4.1", name="GPT-4.1", provider="openai", description="Latest GPT"
                ),
                AgentModel(
                    id="gpt-4o", name="GPT-4o", provider="openai", description="Multimodal GPT"
                ),
            ],
            # JetBrains Junie
            "junie": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(id="junie-pro", name="Junie Pro", description="JetBrains Pro model"),
            ],
            # Goose - Square's agent
            "goose": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet", provider="anthropic"),
                AgentModel(id="gpt-4o", name="GPT-4o", provider="openai"),
                AgentModel(id="gemini-2.5-pro", name="Gemini 2.5 Pro", provider="google"),
            ],
            # Kimi CLI
            "kimi": [
                AgentModel(
                    id="moonshot-v1-128k",
                    name="Moonshot V1 128K",
                    provider="moonshot",
                    context_window=128000,
                ),
                AgentModel(
                    id="moonshot-v1-32k",
                    name="Moonshot V1 32K",
                    provider="moonshot",
                    context_window=32000,
                ),
                AgentModel(
                    id="moonshot-v1-8k",
                    name="Moonshot V1 8K",
                    provider="moonshot",
                    context_window=8000,
                ),
            ],
            # OpenCode
            "opencode": [
                AgentModel(
                    id="auto", name="Auto", is_free=True, description="Automatic model selection"
                ),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet", is_free=True),
                AgentModel(id="gpt-4o", name="GPT-4o", is_free=True),
                AgentModel(id="gemini-2.5-pro", name="Gemini 2.5 Pro", is_free=True),
                AgentModel(id="kimi-k2.5-free", name="Kimi K2.5 (Free)", is_free=True),
            ],
            # Stakpak
            "stakpak": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(
                    id="stakpak-pro", name="Stakpak Pro", description="Enhanced capabilities"
                ),
            ],
            # VT Code
            "vtcode": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(
                    id="vtcode-pro", name="VT Code Pro", description="Enhanced capabilities"
                ),
            ],
            # Augment Code (Auggie)
            "auggie": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(id="auggie-pro", name="Auggie Pro", description="Enhanced capabilities"),
            ],
            # Code Assistant
            "code-assistant": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet", provider="anthropic"),
                AgentModel(id="gpt-4o", name="GPT-4o", provider="openai"),
            ],
            # cagent
            "cagent": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet", provider="anthropic"),
                AgentModel(id="gpt-4o", name="GPT-4o", provider="openai"),
            ],
            # fast-agent
            "fast-agent": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet", provider="anthropic"),
                AgentModel(id="gpt-4o", name="GPT-4o", provider="openai"),
            ],
            # LLMling-Agent
            "llmling-agent": [
                AgentModel(id="auto", name="Auto", description="Automatic model selection"),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet", provider="anthropic"),
                AgentModel(id="gpt-4o", name="GPT-4o", provider="openai"),
            ],
        }

        return models_map.get(agent.short_name, [])

    # ========================================================================
    # QUERIES
    # ========================================================================

    def get_agent(self, short_name: str) -> Optional[DiscoveredAgent]:
        """Get a specific agent by short name."""
        return self._agents.get(short_name)

    def get_available_agents(self) -> List[DiscoveredAgent]:
        """Get list of available (ready to use) agents."""
        return [a for a in self._agents.values() if a.status == AgentStatus.AVAILABLE]

    def get_all_agents(self) -> List[DiscoveredAgent]:
        """Get all known agents."""
        return list(self._agents.values())

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    async def health_check(self, short_name: str) -> Tuple[bool, str]:
        """
        Perform a health check on an agent.

        Returns (is_healthy, message).
        """
        agent = self._agents.get(short_name)
        if not agent:
            return (False, "Agent not found")

        if agent.status == AgentStatus.NOT_INSTALLED:
            return (False, "Agent not installed")

        if agent.status == AgentStatus.NOT_CONFIGURED:
            return (False, agent.error_message or "Agent not configured")

        try:
            # Try to start ACP and do minimal handshake
            loop = asyncio.get_event_loop()

            def test_acp():
                process = subprocess.Popen(
                    agent.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                # Send minimal hello request
                request = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "hello",
                        "id": 1,
                        "params": {},
                    }
                )

                try:
                    stdout, stderr = process.communicate(request + "\n", timeout=5)
                    process.terminate()
                    return "success" in stdout.lower() or "result" in stdout.lower()
                except subprocess.TimeoutExpired:
                    process.kill()
                    return False

            is_healthy = await loop.run_in_executor(None, test_acp)

            if is_healthy:
                return (True, "Agent is healthy")
            else:
                return (False, "Agent did not respond to handshake")

        except Exception as e:
            return (False, str(e))


# ============================================================================
# QUICK ACCESS FUNCTIONS
# ============================================================================

_discovery: Optional[ACPDiscovery] = None


async def discover_agents() -> List[DiscoveredAgent]:
    """Quick function to discover all agents."""
    global _discovery
    if _discovery is None:
        _discovery = ACPDiscovery()
    return await _discovery.discover_all()


async def get_available_agents() -> List[DiscoveredAgent]:
    """Quick function to get available agents."""
    global _discovery
    if _discovery is None:
        _discovery = ACPDiscovery()
        await _discovery.discover_all()
    return _discovery.get_available_agents()


def get_discovery() -> ACPDiscovery:
    """Get the global discovery instance."""
    global _discovery
    if _discovery is None:
        _discovery = ACPDiscovery()
    return _discovery


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Enums
    "AgentStatus",
    "ConnectionType",
    # Data classes
    "AgentCapability",
    "AgentModel",
    "DiscoveredAgent",
    # Classes
    "ACPDiscovery",
    # Functions
    "discover_agents",
    "get_available_agents",
    "get_discovery",
    # Constants
    "KNOWN_AGENTS",
]
