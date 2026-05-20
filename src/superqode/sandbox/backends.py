"""Compatibility exports for sandbox backend capabilities."""

from superqode.harness.sandbox import (
    SandboxCapabilities,
    SandboxCapabilityBackend,
    apply_backend_permissions,
    get_sandbox_capabilities,
)

SandboxBackend = SandboxCapabilityBackend

__all__ = [
    "SandboxBackend",
    "SandboxCapabilities",
    "SandboxCapabilityBackend",
    "apply_backend_permissions",
    "get_sandbox_capabilities",
]
