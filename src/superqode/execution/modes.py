"""
Execution Modes for SuperQode.

Defines the primary execution modes:
- BYOK: Direct LLM API calls (user provides API keys)
- ACP: Agent Client Protocol (full coding agent capabilities)
- LOCAL: Local/self-hosted models (no API keys required)

QE Modes (Perception & Usability):
- Quick Scan: Time-boxed, shallow exploration, pre-commit/fast CI
- Deep QE: Full sandbox, destructive testing, pre-release/nightly CI

SECURITY PRINCIPLE:
- BYOK: Keys read from user's environment, never stored by SuperQode
- ACP: Agent manages its own auth, SuperQode just connects
- LOCAL: No API keys needed, runs on local machine
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ExecutionMode(Enum):
    """Execution mode for a role."""

    BYOK = "byok"  # Bring Your Own Key - Direct LLM API
    ACP = "acp"  # Agent Client Protocol - Full agent
    LOCAL = "local"  # Local/self-hosted models - No API key required


class QEMode(Enum):
    """QE execution mode."""

    QUICK_SCAN = "quick_scan"  # Fast, shallow, time-boxed
    DEEP_QE = "deep_qe"  # Full exploration, destructive allowed


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


# =============================================================================
# QE Mode Configurations
# =============================================================================


@dataclass
class QuickScanConfig:
    """
    Quick Scan Mode Configuration.

    Use cases:
    - Pre-commit hooks
    - Developer laptop testing
    - Fast CI feedback

    Characteristics:
    - Time-boxed (seconds, not minutes)
    - Shallow exploration
    - High-risk paths only
    - Minimal QIRs
    """

    timeout_seconds: int = 60
    depth: str = "shallow"

    # Execution constraints
    fail_fast: bool = True
    max_tests: int = 50  # Limit number of tests to run

    # Test selection
    run_smoke: bool = True
    run_sanity: bool = True
    run_regression: bool = False  # Skip full regression

    # Generation constraints
    generate_tests: bool = False
    generate_patches: bool = False

    # Destructive testing
    destructive_allowed: bool = False

    # QIR settings
    minimal_qir: bool = True  # Short summary only

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": "quick_scan",
            "timeout_seconds": self.timeout_seconds,
            "depth": self.depth,
            "fail_fast": self.fail_fast,
            "max_tests": self.max_tests,
            "run_smoke": self.run_smoke,
            "run_sanity": self.run_sanity,
            "run_regression": self.run_regression,
            "generate_tests": self.generate_tests,
            "generate_patches": self.generate_patches,
            "destructive_allowed": self.destructive_allowed,
            "minimal_qir": self.minimal_qir,
        }


@dataclass
class DeepQEConfig:
    """
    Deep QE Mode Configuration.

    Use cases:
    - Pre-release validation
    - Nightly CI runs
    - Compliance evidence gathering

    Characteristics:
    - Full sandbox environment
    - Destructive testing allowed
    - Failure simulation hooks
    - Full Investigation Reports
    """

    timeout_seconds: int = 1800  # 30 minutes
    depth: str = "full"

    # Execution constraints
    fail_fast: bool = False
    max_tests: int = 0  # No limit

    # Test selection
    run_smoke: bool = True
    run_sanity: bool = True
    run_regression: bool = True

    # Generation enabled
    generate_tests: bool = True
    generate_patches: bool = True

    # Test generation types
    generate_unit_tests: bool = True
    generate_integration_tests: bool = True
    generate_api_tests: bool = True
    generate_fuzz_tests: bool = True
    generate_security_tests: bool = True

    # Destructive testing
    destructive_allowed: bool = True
    simulate_failures: bool = True
    stress_testing: bool = True
    chaos_testing: bool = False  # Advanced - disabled by default

    # QIR settings
    minimal_qir: bool = False  # Full detailed report
    include_evidence: bool = True
    include_metrics: bool = True

    # Flake detection
    detect_flakes: bool = True
    retry_count: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": "deep_qe",
            "timeout_seconds": self.timeout_seconds,
            "depth": self.depth,
            "fail_fast": self.fail_fast,
            "max_tests": self.max_tests,
            "run_smoke": self.run_smoke,
            "run_sanity": self.run_sanity,
            "run_regression": self.run_regression,
            "generate_tests": self.generate_tests,
            "generate_patches": self.generate_patches,
            "test_generation": {
                "unit": self.generate_unit_tests,
                "integration": self.generate_integration_tests,
                "api": self.generate_api_tests,
                "fuzz": self.generate_fuzz_tests,
                "security": self.generate_security_tests,
            },
            "destructive_testing": {
                "allowed": self.destructive_allowed,
                "simulate_failures": self.simulate_failures,
                "stress_testing": self.stress_testing,
                "chaos_testing": self.chaos_testing,
            },
            "qr": {
                "minimal": self.minimal_qir,
                "include_evidence": self.include_evidence,
                "include_metrics": self.include_metrics,
            },
            "flake_detection": {
                "enabled": self.detect_flakes,
                "retry_count": self.retry_count,
            },
        }


def get_qe_mode_config(mode: QEMode) -> QuickScanConfig | DeepQEConfig:
    """Get the configuration for a QE mode."""
    if mode == QEMode.QUICK_SCAN:
        return QuickScanConfig()
    elif mode == QEMode.DEEP_QE:
        return DeepQEConfig()
    else:
        raise ValueError(f"Unknown QE mode: {mode}")
