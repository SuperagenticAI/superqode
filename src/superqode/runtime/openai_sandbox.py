"""Compatibility exports for OpenAI Agents sandbox helpers.

The sandbox contract now lives in ``superqode.harness.sandbox`` so harness
specs, runtimes, and tests use one source of sandbox capability truth.
"""

from superqode.harness.sandbox import (
    build_manifest,
    build_sandbox_agent,
    build_sandbox_client,
    build_sandbox_run_config,
    is_sandbox_backend_available,
    supported_sandbox_backends,
)

__all__ = [
    "build_manifest",
    "build_sandbox_agent",
    "build_sandbox_client",
    "build_sandbox_run_config",
    "is_sandbox_backend_available",
    "supported_sandbox_backends",
]
