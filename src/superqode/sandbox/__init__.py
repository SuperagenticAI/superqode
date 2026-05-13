"""Sandbox backend abstractions."""

from .backends import (
    SandboxBackend,
    SandboxCapabilities,
    apply_backend_permissions,
    get_sandbox_capabilities,
)
from .execution import (
    SandboxProviderStatus,
    SandboxRunResult,
    run_in_sandbox,
    sandbox_provider_status,
)

__all__ = [
    "SandboxBackend",
    "SandboxCapabilities",
    "SandboxProviderStatus",
    "SandboxRunResult",
    "apply_backend_permissions",
    "get_sandbox_capabilities",
    "run_in_sandbox",
    "sandbox_provider_status",
]
