"""
Execution Modes for SuperQode.

Defines the primary execution modes:
- BYOK: Direct LLM API calls (user provides API keys)
- ACP: Agent Client Protocol (full coding agent capabilities)
- LOCAL: Local/self-hosted models (no API keys required)

SECURITY PRINCIPLE:
- BYOK: Keys read from user's environment, never stored by SuperQode
- ACP: Agent manages its own auth, SuperQode just connects
- LOCAL: No API keys needed, runs on local machine
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ExecutionMode(Enum):
    """Execution mode for a role."""

    BYOK = "byok"  # Bring Your Own Key - Direct LLM API
    ACP = "acp"  # Agent Client Protocol - Full agent
    LOCAL = "local"  # Local/self-hosted models - No API key required


class GatewayType(Enum):
    """Gateway type for BYOK mode."""

    LITELLM = "litellm"  # Default: LiteLLM unified API
    DIRECT = "direct"  # Future: Direct API calls


@dataclass
class BYOKConfig:
    """Configuration for BYOK (Bring Your Own Key) mode.

    In BYOK mode:
    - SuperQode makes direct LLM API calls via a gateway (LiteLLM)
    - User provides API keys via environment variables
    - Capabilities: Chat completion, streaming, tool calling (if supported)
    - No agent features (no file editing, no shell commands)
    """

    provider: str
    model: str
    gateway: GatewayType = GatewayType.LITELLM

    # Optional overrides
    base_url: Optional[str] = None
    extra_headers: Dict[str, str] = field(default_factory=dict)

    # Cost tracking
    track_costs: bool = True

    def get_litellm_model(self) -> str:
        """Get the model string for LiteLLM."""
        from ..providers.registry import PROVIDERS

        provider_def = PROVIDERS.get(self.provider)
        if provider_def and provider_def.litellm_prefix:
            # Don't double-prefix
            if self.model.startswith(provider_def.litellm_prefix):
                return self.model
            return f"{provider_def.litellm_prefix}{self.model}"
        return self.model


@dataclass
class ACPConfig:
    """Configuration for ACP (Agent Client Protocol) mode.

    In ACP mode:
    - SuperQode connects to an ACP-compatible coding agent
    - Agent manages its own LLM authentication
    - Capabilities: Full agent (files, shell, MCP, reasoning)
    - Agent handles all LLM interactions internally
    """

    agent: str  # Agent ID (e.g., "opencode")

    # Agent's internal LLM config (passed to agent)
    agent_provider: Optional[str] = None
    agent_model: Optional[str] = None

    # Connection settings
    connection_type: str = "stdio"  # "stdio" | "http"
    command: Optional[str] = None  # Override agent command
    host: Optional[str] = None  # For HTTP connections
    port: Optional[int] = None


@dataclass
class ExecutionConfig:
    """Complete execution configuration for a role."""

    mode: ExecutionMode

    # Mode-specific config (one will be set based on mode)
    byok: Optional[BYOKConfig] = None
    acp: Optional[ACPConfig] = None

    # Common settings
    job_description: str = ""
    enabled: bool = True

    @classmethod
    def from_byok(
        cls, provider: str, model: str, job_description: str = "", **kwargs
    ) -> "ExecutionConfig":
        """Create a BYOK execution config."""
        return cls(
            mode=ExecutionMode.BYOK,
            byok=BYOKConfig(provider=provider, model=model, **kwargs),
            job_description=job_description,
        )

    @classmethod
    def from_acp(
        cls,
        agent: str,
        agent_provider: Optional[str] = None,
        agent_model: Optional[str] = None,
        job_description: str = "",
        **kwargs,
    ) -> "ExecutionConfig":
        """Create an ACP execution config."""
        return cls(
            mode=ExecutionMode.ACP,
            acp=ACPConfig(
                agent=agent, agent_provider=agent_provider, agent_model=agent_model, **kwargs
            ),
            job_description=job_description,
        )

    def get_mode_info(self) -> Dict[str, Any]:
        """Get human-readable info about the execution mode."""
        if self.mode == ExecutionMode.BYOK:
            return {
                "mode": "BYOK (Bring Your Own Key)",
                "description": "Direct LLM API calls via gateway",
                "provider": self.byok.provider if self.byok else None,
                "model": self.byok.model if self.byok else None,
                "gateway": self.byok.gateway.value if self.byok else None,
                "capabilities": [
                    "Chat completion",
                    "Streaming responses",
                    "Tool calling (if model supports)",
                ],
                "limitations": [
                    "No file editing",
                    "No shell commands",
                    "No MCP tools",
                ],
                "auth_info": "API key from your environment variables",
            }
        else:  # ACP
            return {
                "mode": "ACP (Agent Client Protocol)",
                "description": "Full coding agent capabilities",
                "agent": self.acp.agent if self.acp else None,
                "agent_provider": self.acp.agent_provider if self.acp else None,
                "agent_model": self.acp.agent_model if self.acp else None,
                "capabilities": [
                    "File reading/writing",
                    "Shell command execution",
                    "MCP tool integration",
                    "Multi-step reasoning",
                    "Context management",
                ],
                "auth_info": "Managed by the agent (not SuperQode)",
            }
