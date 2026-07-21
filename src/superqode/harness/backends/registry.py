"""Harness backend registry."""

from __future__ import annotations

import importlib.util
from dataclasses import replace

from .base import (
    HarnessBackendCapabilities,
    HarnessBackend,
    HarnessBackendInspection,
    HarnessBackendIssue,
)
from .deepagents import DeepAgentsHarnessBackend
from .managed import ManagedAgentHarnessBackend
from .pydanticai import PydanticAIHarnessBackend
from .rlm_code import RLMCodeHarnessBackend
from .runtime import (
    ADKHarnessBackend,
    ClaudeAgentSDKHarnessBackend,
    CodexSDKHarnessBackend,
    OpenAIAgentsHarnessBackend,
    RuntimeHarnessBackend,
)

_RUNTIME_BACKENDS = {"builtin"}
_OPTIONAL_BACKENDS = {
    "adk",
    "anthropic-managed",
    "openai-agents",
    "codex-sdk",
    "claude-agent-sdk",
    "deepagents",
    "google-agent-engine",
    "pydanticai",
    "rlm-code",
}


def create_harness_backend(name: str | None) -> HarnessBackend:
    """Create a harness backend by name."""
    resolved = (name or "builtin").strip().lower()
    if resolved == "builtin":
        return RuntimeHarnessBackend(resolved)
    if resolved == "adk":
        return ADKHarnessBackend()
    if resolved == "openai-agents":
        return OpenAIAgentsHarnessBackend()
    if resolved == "codex-sdk":
        return CodexSDKHarnessBackend()
    if resolved == "claude-agent-sdk":
        return ClaudeAgentSDKHarnessBackend()
    if resolved == "deepagents":
        return DeepAgentsHarnessBackend()
    if resolved == "pydanticai":
        return PydanticAIHarnessBackend()
    if resolved == "rlm-code":
        return RLMCodeHarnessBackend()
    if resolved in {"google-agent-engine", "anthropic-managed"}:
        return ManagedAgentHarnessBackend(resolved)
    valid = ", ".join(known_harness_backend_names())
    raise ValueError(f"Unknown harness backend {name!r}. Known: {valid}")


def known_harness_backend_names() -> list[str]:
    """Return known harness backend names."""
    return sorted(_RUNTIME_BACKENDS | _OPTIONAL_BACKENDS)


def inspect_harness_backend(
    name: str | None,
    spec,
    *,
    sandbox_backend: str | None = None,
) -> HarnessBackendInspection:
    """Inspect backend compatibility for a HarnessSpec."""
    backend = create_harness_backend(name or spec.runtime.backend)
    capabilities = _with_availability(backend.capabilities)
    issues: list[HarnessBackendIssue] = []

    if spec.is_no_tool and not capabilities.supports_no_tool:
        issues.append(
            HarnessBackendIssue(
                severity="error",
                code="no_tool_unsupported",
                message=f"Backend '{backend.name}' does not support no-tool harnesses.",
            )
        )
    if spec.is_coding and not capabilities.supports_coding:
        issues.append(
            HarnessBackendIssue(
                severity="error",
                code="coding_unsupported",
                message=f"Backend '{backend.name}' does not support tool-capable coding harnesses.",
            )
        )
    if spec.execution_policy.allow_shell and not capabilities.supports_shell:
        issues.append(
            HarnessBackendIssue(
                severity="error",
                code="shell_unsupported",
                message=f"Backend '{backend.name}' cannot honor allow_shell=True.",
            )
        )
    if _uses_mcp(spec) and not capabilities.supports_mcp:
        issues.append(
            HarnessBackendIssue(
                severity="warning",
                code="mcp_unsupported",
                message=f"Backend '{backend.name}' does not currently expose MCP support.",
            )
        )
    if spec.workflow.mode.value != "single" and not capabilities.supports_workflow_children:
        issues.append(
            HarnessBackendIssue(
                severity="error",
                code="workflow_children_unsupported",
                message=f"Backend '{backend.name}' cannot run multi-step workflow children.",
            )
        )
    if _uses_typed_output(spec) and not capabilities.supports_typed_output:
        issues.append(
            HarnessBackendIssue(
                severity="warning",
                code="typed_output_unsupported",
                message=f"Backend '{backend.name}' may not honor structured output schemas.",
            )
        )
    selected_sandbox = sandbox_backend or spec.execution_policy.sandbox
    if selected_sandbox and selected_sandbox != "local" and not capabilities.supports_sandbox:
        issues.append(
            HarnessBackendIssue(
                severity="warning",
                code="sandbox_unsupported",
                message=f"Backend '{backend.name}' may ignore sandbox backend '{selected_sandbox}'.",
            )
        )
    issues.extend(_model_policy_issues(backend.name, spec))

    return HarnessBackendInspection(
        backend=backend.name,
        capabilities=capabilities,
        issues=tuple(issues),
    )


def backend_capabilities(name: str | None):
    """Return capabilities for a known backend name."""
    return _with_availability(create_harness_backend(name).capabilities)


def _with_availability(capabilities: HarnessBackendCapabilities) -> HarnessBackendCapabilities:
    if capabilities.backend in {"google-agent-engine", "anthropic-managed"}:
        return capabilities
    from superqode.providers.env_introspect import install_command

    packages = {
        "builtin": (None, None),
        "adk": ("google.adk", "adk"),
        "openai-agents": ("agents", "openai-agents"),
        "codex-sdk": ("openai_codex", "codex-sdk"),
        "deepagents": ("deepagents", "deepagents"),
        "pydanticai": ("pydantic_ai", "pydanticai"),
        "rlm-code": ("rlm_code", "rlm-code"),
    }
    module_name, extra = packages.get(capabilities.backend, (None, None))
    hint = install_command(extra) if extra else None
    if module_name is None:
        return replace(capabilities, availability="available", install_hint=None)
    available = _optional_module_available(module_name)
    return replace(
        capabilities,
        availability="available" if available else "missing",
        install_hint=None if available else hint,
    )


def _optional_module_available(module_name: str) -> bool:
    """Return whether an optional dependency can be imported without raising.

    ``importlib.util.find_spec("google.adk")`` can raise ModuleNotFoundError
    when the top-level namespace package is absent. Optional backend discovery
    should report that as "missing", not crash CLI/tests.
    """
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def _uses_mcp(spec) -> bool:
    if spec.runtime.config.get("mcp") or spec.runtime.config.get("mcp_servers"):
        return True
    for agent in spec.agents:
        if "mcp" in agent.tools or agent.config.get("mcp") or agent.config.get("mcp_servers"):
            return True
    return False


def _uses_typed_output(spec) -> bool:
    return any(bool(agent.output_schema) for agent in spec.agents)


def _model_policy_issues(backend_name: str, spec) -> list[HarnessBackendIssue]:
    if backend_name not in {"deepagents", "pydanticai"}:
        return []

    issues: list[HarnessBackendIssue] = []
    if spec.model_policy.reasoning:
        issues.append(
            HarnessBackendIssue(
                severity="warning",
                code="reasoning_policy_unverified",
                message=(
                    f"Backend '{backend_name}' may not honor reasoning="
                    f"{spec.model_policy.reasoning!r}."
                ),
            )
        )
    if spec.model_policy.temperature is not None:
        issues.append(
            HarnessBackendIssue(
                severity="warning",
                code="temperature_policy_unverified",
                message=(
                    f"Backend '{backend_name}' may not honor temperature="
                    f"{spec.model_policy.temperature!r}."
                ),
            )
        )
    max_iterations = spec.model_policy.config.get("max_iterations")
    if max_iterations is None:
        max_iterations = next(
            (agent.max_iterations for agent in spec.agents if agent.max_iterations is not None),
            None,
        )
    if max_iterations is not None:
        issues.append(
            HarnessBackendIssue(
                severity="warning",
                code="max_iterations_policy_unverified",
                message=(
                    f"Backend '{backend_name}' may not honor max_iterations={max_iterations!r}."
                ),
            )
        )
    return issues
