"""Sandbox backend abstractions."""

from .backends import (
    SandboxBackend,
    SandboxCapabilities,
    apply_backend_permissions,
    get_sandbox_capabilities,
)
from .execution import (
    LOCAL_SANDBOX_BACKENDS,
    POPULAR_CLOUD_SANDBOX_BACKENDS,
    SANDBOX_PROFILES,
    SANDBOX_PROVIDERS,
    SUPPORTED_SANDBOX_BACKENDS,
    SandboxProviderDefinition,
    SandboxProviderStatus,
    SandboxRunResult,
    sandbox_profile_backends,
    run_in_sandbox,
    sandbox_provider_status,
    supported_sandbox_backends,
)

__all__ = [
    "SandboxBackend",
    "SandboxCapabilities",
    "SandboxProviderDefinition",
    "SandboxProviderStatus",
    "SandboxRunResult",
    "LOCAL_SANDBOX_BACKENDS",
    "POPULAR_CLOUD_SANDBOX_BACKENDS",
    "SANDBOX_PROFILES",
    "SANDBOX_PROVIDERS",
    "SUPPORTED_SANDBOX_BACKENDS",
    "apply_backend_permissions",
    "get_sandbox_capabilities",
    "run_in_sandbox",
    "sandbox_profile_backends",
    "sandbox_provider_status",
    "supported_sandbox_backends",
]
