"""Optional PydanticAI harness backend."""

from __future__ import annotations

from .base import HarnessBackendCapabilities
from .runtime import RuntimeHarnessBackend


class PydanticAIHarnessBackend(RuntimeHarnessBackend):
    """Harness adapter name for PydanticAI.

    The heavy lifting lives in ``superqode.runtime.pydanticai`` and the shared
    PydanticAI tool bridge. Keeping this as a first-class harness backend lets
    spec-driven runs advertise PydanticAI-specific capabilities without
    duplicating runtime construction code.
    """

    def __init__(self) -> None:
        super().__init__("pydanticai")
        self.capabilities = HarnessBackendCapabilities(
            backend=self.name,
            supports_coding=True,
            supports_no_tool=True,
            supports_streaming=True,
            supports_approvals=True,
            supports_sandbox=False,
            supports_shell=True,
            supports_mcp=True,
            supports_typed_output=True,
            notes=(
                "PydanticAI uses SuperQode JSON-schema tool bridging.",
                "Native MCP loads from runtime.config.pydanticai.mcp_config_path.",
                "Logfire tracing and fallback chains are available through HarnessSpec policy.",
                "Prefect and DBOS durable wrappers are available through runtime.config.pydanticai.durable.",
            ),
        )
