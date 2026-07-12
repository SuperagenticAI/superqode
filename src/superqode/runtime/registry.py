"""Runtime registry and factory.

Public entry points:
    create_runtime(name, **kwargs) -> AgentRuntime
    list_runtimes() -> list[RuntimeInfo]
    resolve_runtime_name(cli, yaml, env) -> str

Optional backends (adk, openai-agents, pydanticai) are imported lazily so importing
``superqode.runtime`` is cheap and works without optional extras.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any, Callable

from .base import AgentRuntime
from .builtin import BuiltinRuntime
from .errors import RuntimeNotInstalledError, UnknownRuntimeError

_DEFAULT = "builtin"


@dataclass(frozen=True)
class RuntimeInfo:
    """Metadata about a known runtime, for `superqode runtime list` and the TUI dialog."""

    name: str
    description: str
    installed: bool
    install_hint: str | None  # None when no extra is needed
    implemented: bool  # False for stubs (openai-agents in v1)
    ready: bool = True
    status_detail: str | None = None

    @property
    def usable(self) -> bool:
        return self.installed and self.implemented and self.ready


def _builtin_factory(**kwargs) -> AgentRuntime:
    return BuiltinRuntime(**kwargs)


def _extra_install(extra: str) -> str:
    """uv install command for ``superqode[extra]`` targeting SuperQode's env."""
    from superqode.providers.env_introspect import install_command

    return install_command(extra)


def _adk_factory(**kwargs) -> AgentRuntime:
    try:
        module = importlib.import_module("superqode.runtime.adk")
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            f"ADK runtime requires the 'adk' extra. Install with: {_extra_install('adk')}"
        ) from exc
    return module.ADKRuntime(**kwargs)


def _openai_agents_factory(**kwargs) -> AgentRuntime:
    try:
        module = importlib.import_module("superqode.runtime.openai_agents")
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "OpenAI Agents runtime requires the 'openai-agents' extra. "
            f"Install with: {_extra_install('openai-agents')}"
        ) from exc
    return module.OpenAIAgentsRuntime(**kwargs)


def _pydanticai_factory(**kwargs) -> AgentRuntime:
    try:
        module = importlib.import_module("superqode.runtime.pydanticai")
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "PydanticAI runtime requires the 'pydanticai' extra. "
            f"Install with: {_extra_install('pydanticai')}"
        ) from exc
    return module.PydanticAIRuntime(**kwargs)


def _codex_sdk_factory(**kwargs) -> AgentRuntime:
    try:
        module = importlib.import_module("superqode.runtime.codex_sdk")
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "Codex SDK runtime requires the 'codex-sdk' extra. "
            f"Install with: {_extra_install('codex-sdk')}"
        ) from exc
    return module.CodexSDKRuntime(**kwargs)


def _claude_agent_sdk_factory(**kwargs) -> AgentRuntime:
    try:
        module = importlib.import_module("superqode.runtime.claude_agent_sdk")
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "Claude Agent SDK runtime requires the 'claude-agent-sdk' extra. "
            f"Install with: {_extra_install('claude-agent-sdk')}"
        ) from exc
    return module.ClaudeAgentSDKRuntime(**kwargs)


def _antigravity_sdk_factory(**kwargs) -> AgentRuntime:
    try:
        module = importlib.import_module("superqode.runtime.antigravity_sdk")
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "Antigravity SDK runtime requires the 'antigravity-sdk' extra. "
            f"Install with: {_extra_install('antigravity-sdk')}"
        ) from exc
    return module.AntigravitySDKRuntime(**kwargs)


def _antigravity_cli_factory(**kwargs) -> AgentRuntime:
    module = importlib.import_module("superqode.runtime.antigravity_cli")
    return module.AntigravityCLIRuntime(**kwargs)


_FACTORIES: dict[str, Callable[..., AgentRuntime]] = {
    "builtin": _builtin_factory,
    "adk": _adk_factory,
    "openai-agents": _openai_agents_factory,
    "pydanticai": _pydanticai_factory,
    "codex-sdk": _codex_sdk_factory,
    "claude-agent-sdk": _claude_agent_sdk_factory,
    "antigravity-sdk": _antigravity_sdk_factory,
    "antigravity-cli": _antigravity_cli_factory,
}

_DESCRIPTIONS: dict[str, str] = {
    "builtin": "SuperQode native agent loop (default)",
    "adk": "Google Agent Development Kit",
    "openai-agents": "OpenAI Agents SDK",
    "pydanticai": "PydanticAI agent framework",
    "codex-sdk": "OpenAI Codex Python SDK / local app-server",
    "claude-agent-sdk": "Anthropic Claude Agent SDK (API key)",
    "antigravity-sdk": "Google Antigravity SDK (Gemini API key)",
    "antigravity-cli": "Google Antigravity CLI (Google Sign-In)",
}

_OPTIONAL_PACKAGES: dict[str, tuple[str, str]] = {
    # runtime name -> (importable package, pip extra)
    "adk": ("google.adk", "superqode[adk]"),
    "openai-agents": ("agents", "superqode[openai-agents]"),
    "pydanticai": ("pydantic_ai", "superqode[pydanticai]"),
    "codex-sdk": ("openai_codex", "superqode[codex-sdk]"),
    "claude-agent-sdk": ("claude_agent_sdk", "superqode[claude-agent-sdk]"),
    "antigravity-sdk": ("google.antigravity", "superqode[antigravity-sdk]"),
}


def create_runtime(name: str | None, **kwargs: Any) -> AgentRuntime:
    """Construct a runtime by name.

    ``name=None`` or an empty string returns the default (builtin). Unknown
    names raise UnknownRuntimeError. Missing optional deps raise
    RuntimeNotInstalledError with the exact install hint.
    """
    resolved = (name or _DEFAULT).strip().lower()
    if resolved not in _FACTORIES:
        raise UnknownRuntimeError(
            f"Unknown runtime '{name}'. Known: {', '.join(sorted(_FACTORIES))}"
        )
    return _FACTORIES[resolved](**kwargs)


def list_runtimes() -> list[RuntimeInfo]:
    """Describe every known runtime and whether its dependencies are installed."""
    out: list[RuntimeInfo] = []
    for name in _FACTORIES:
        if name == "builtin":
            installed = True
            install_hint = None
            implemented = True
            ready = True
            status_detail = None
        elif name == "antigravity-cli":
            from .antigravity_status import probe_antigravity_cli

            status = probe_antigravity_cli()
            installed = status.installed
            ready = status.compatible
            status_detail = status.issue or (
                f"compatible CLI {status.version_text}; Google Sign-In is verified on first use"
                if status.version_text
                else None
            )
            install_hint = None if installed else status.issue
            implemented = True
        else:
            pkg, extra = _OPTIONAL_PACKAGES[name]
            try:
                importlib.import_module(pkg)
                installed = True
            except ImportError:
                installed = False
            install_hint = None if installed else _extra_install(name)
            implemented = True
            ready = installed
            status_detail = None
        out.append(
            RuntimeInfo(
                name=name,
                description=_DESCRIPTIONS[name],
                installed=installed,
                install_hint=install_hint,
                implemented=implemented,
                ready=ready,
                status_detail=status_detail,
            )
        )
    return out


def known_runtime_names() -> list[str]:
    """Return all registered runtime names — useful for click choice arguments."""
    return list(_FACTORIES.keys())


def resolve_runtime_name(
    cli: str | None = None,
    yaml: str | None = None,
    env_var: str = "SUPERQODE_RUNTIME",
) -> str:
    """Resolve the active runtime name with precedence: CLI > YAML > env > default."""
    for candidate in (cli, yaml, os.environ.get(env_var)):
        if candidate:
            return candidate.strip().lower()
    return _DEFAULT
