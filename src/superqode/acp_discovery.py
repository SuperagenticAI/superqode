"""
SuperQode ACP Agent Discovery - Auto-Discover Available Agents.

Automatically discovers ACP-compatible agents installed on the system
and provides a unified interface for connecting to them.

Supported Agents:
- OpenCode (opencode acp)
- OpenHands (openhands acp)
- Claude Code (claude-code-acp)
- Codex (codex-acp, npx @openai/codex-acp)
- Goose (goose acp)
- Gemini (gemini-cli acp)
- Cursor (cursor acp)

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
    {
        "name": "OpenCode",
        "short_name": "opencode",
        "command": ["opencode", "acp"],
        "icon": "🌿",
        "color": "#22c55e",
        "description": "Open-source AI coding assistant",
        "website": "https://opencode.dev",
        "requires_api_key": False,  # Uses cloud with free tier
        "api_key_env_vars": [],
        "check_command": ["opencode", "--version"],
    },
    {
        "name": "OpenHands",
        "short_name": "openhands",
        "command": ["openhands", "acp"],
        "icon": "🤝",
        "color": "#f97316",
        "description": "AI software development agent",
        "website": "https://github.com/All-Hands-AI/OpenHands",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["openhands", "--version"],
    },
    {
        "name": "Claude Code",
        "short_name": "claude-code",
        "command": ["claude-code-acp"],
        "alt_commands": [
            ["npx", "@zed-industries/claude-code-acp"],
            ["npx", "-y", "@zed-industries/claude-code-acp"],
        ],
        "icon": "🧡",
        "color": "#d97706",
        "description": "Anthropic's Claude for coding",
        "website": "https://claude.ai",
        "requires_api_key": True,
        "api_key_env_vars": ["ANTHROPIC_API_KEY"],
        "check_command": ["claude-code-acp", "--version"],
    },
    {
        "name": "Codex",
        "short_name": "codex",
        "command": ["npx", "@openai/codex-acp"],
        "alt_commands": [
            ["codex-acp"],
            ["npx", "-y", "@openai/codex-acp"],
        ],
        "icon": "📜",
        "color": "#10b981",
        "description": "OpenAI Codex CLI",
        "website": "https://openai.com",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "CODEX_API_KEY"],
        "check_command": ["npx", "@openai/codex-acp", "--version"],
    },
    {
        "name": "Goose",
        "short_name": "goose",
        "command": ["goose", "acp"],
        "icon": "🦆",
        "color": "#8b5cf6",
        "description": "Block's AI coding assistant",
        "website": "https://github.com/block/goose",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["goose", "--version"],
    },
    {
        "name": "Gemini CLI",
        "short_name": "gemini",
        "command": ["gemini-cli", "acp"],
        "alt_commands": [
            ["gemini", "acp"],
        ],
        "icon": "✨",
        "color": "#4285f4",
        "description": "Google's Gemini AI",
        "website": "https://ai.google.dev",
        "requires_api_key": True,
        "api_key_env_vars": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "check_command": ["gemini-cli", "--version"],
    },
    {
        "name": "Cursor",
        "short_name": "cursor",
        "command": ["cursor", "acp"],
        "icon": "▸",
        "color": "#06b6d4",
        "description": "Cursor AI editor agent",
        "website": "https://cursor.sh",
        "requires_api_key": False,  # Uses Cursor's backend
        "api_key_env_vars": [],
        "check_command": ["cursor", "--version"],
    },
    {
        "name": "Aider",
        "short_name": "aider",
        "command": ["aider", "--acp"],
        "icon": "🔧",
        "color": "#f43f5e",
        "description": "AI pair programming in terminal",
        "website": "https://aider.chat",
        "requires_api_key": True,
        "api_key_env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "check_command": ["aider", "--version"],
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
            "opencode": [
                AgentModel(
                    id="auto", name="Auto", is_free=True, description="Automatic model selection"
                ),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet", is_free=True),
                AgentModel(id="gpt-4o", name="GPT-4o", is_free=True),
                AgentModel(id="gemini-1.5-pro", name="Gemini 1.5 Pro", is_free=True),
            ],
            "openhands": [
                AgentModel(id="default", name="Default", description="Default model"),
            ],
            "claude-code": [
                AgentModel(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet"),
                AgentModel(id="claude-3-opus-20240229", name="Claude 3 Opus"),
            ],
            "codex": [
                AgentModel(id="gpt-5.2", name="GPT-5.2 (Latest)"),
                AgentModel(id="gpt-5.2-pro", name="GPT-5.2 Pro"),
                AgentModel(id="gpt-5.2-codex", name="GPT-5.2 Codex"),
                AgentModel(id="gpt-5.1", name="GPT-5.1"),
                AgentModel(id="gpt-5.1-codex", name="GPT-5.1 Codex"),
                AgentModel(id="gpt-5.1-codex-mini", name="GPT-5.1 Codex Mini"),
                AgentModel(id="gpt-4o", name="GPT-4o"),
                AgentModel(id="gpt-4-turbo", name="GPT-4 Turbo"),
            ],
            "goose": [
                AgentModel(id="default", name="Default"),
            ],
            "gemini": [
                AgentModel(id="gemini-1.5-pro", name="Gemini 1.5 Pro"),
                AgentModel(id="gemini-1.5-flash", name="Gemini 1.5 Flash"),
            ],
            "cursor": [
                AgentModel(id="default", name="Default"),
            ],
            "aider": [
                AgentModel(id="gpt-4o", name="GPT-4o"),
                AgentModel(id="claude-3-5-sonnet", name="Claude 3.5 Sonnet"),
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
