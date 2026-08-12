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


def _copilot_sdk_factory(**kwargs) -> AgentRuntime:
    try:
        module = importlib.import_module("superqode.runtime.copilot_sdk")
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "GitHub Copilot SDK runtime requires the 'copilot-sdk' extra. "
            f"Install with: {_extra_install('copilot-sdk')}"
        ) from exc
    return module.CopilotSDKRuntime(**kwargs)


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


def _antigravity_managed_factory(**kwargs) -> AgentRuntime:
    module = importlib.import_module("superqode.runtime.antigravity_managed")
    return module.AntigravityManagedRuntime(**kwargs)


def _devin_cli_factory(**kwargs) -> AgentRuntime:
    module = importlib.import_module("superqode.runtime.devin_cli")
    return module.DevinCLIRuntime(**kwargs)


def _vendor_cli_spec(runtime_name: str):
    """Vendor CLI descriptor for a runtime name, or None if it is not one."""
    try:
        module = importlib.import_module("superqode.runtime.vendor_cli")
    except ImportError:  # pragma: no cover - module ships with the package
        return None
    spec = module.spec_for(runtime_name)
    return spec if spec is not None and spec.name == runtime_name else None


def is_vendor_cli_runtime(name: str | None) -> bool:
    """True when ``name`` is a subscription runtime that drives a vendor CLI.

    Callers use this to decide whether SuperQode's permission policy can be
    projected onto the child process. Only these runtimes accept
    ``permission_manager`` / ``approval_mode``: ``builtin`` forwards unknown
    kwargs to AgentLoop, and the SDK runtimes read ``permission_manager is
    None`` as "prompt the user per tool".
    """
    resolved = (name or "").strip().lower()
    return bool(resolved) and _vendor_cli_spec(resolved) is not None


def _vendor_cli_factory(vendor: str) -> Callable[..., AgentRuntime]:
    """Build a subscription runtime that drives one vendor's own CLI."""

    def factory(**kwargs) -> AgentRuntime:
        module = importlib.import_module("superqode.runtime.vendor_cli")
        spec = module.spec_for(vendor)
        if spec is None:  # pragma: no cover - guarded by the spec table test
            raise RuntimeNotInstalledError(f"No vendor CLI descriptor for {vendor!r}")
        return module.VendorCLIRuntime(spec=spec, **kwargs)

    return factory


_FACTORIES: dict[str, Callable[..., AgentRuntime]] = {
    "builtin": _builtin_factory,
    "adk": _adk_factory,
    "openai-agents": _openai_agents_factory,
    "pydanticai": _pydanticai_factory,
    "codex-sdk": _codex_sdk_factory,
    "copilot-sdk": _copilot_sdk_factory,
    "claude-agent-sdk": _claude_agent_sdk_factory,
    "antigravity-sdk": _antigravity_sdk_factory,
    "antigravity-cli": _antigravity_cli_factory,
    "antigravity-managed": _antigravity_managed_factory,
    "devin-cli": _devin_cli_factory,
    # Subscription runtimes that drive the vendor CLI directly (no ACP).
    "copilot-cli": _vendor_cli_factory("copilot"),
    "grok-cli": _vendor_cli_factory("grok"),
}

_DESCRIPTIONS: dict[str, str] = {
    "builtin": "SuperQode native agent loop (default)",
    "adk": "Google Agent Development Kit",
    "openai-agents": "OpenAI Agents SDK",
    "pydanticai": "PydanticAI agent framework",
    "codex-sdk": "OpenAI Codex Python SDK / local app-server",
    "copilot-sdk": "GitHub Copilot SDK / bundled Copilot runtime",
    "claude-agent-sdk": "Anthropic Claude Agent SDK (API key)",
    "antigravity-sdk": "Google Antigravity SDK (Gemini API key)",
    "antigravity-cli": "Google Antigravity CLI (Google Sign-In)",
    "antigravity-managed": "Google-hosted Antigravity agent (Gemini API key)",
    "devin-cli": "Cognition Devin CLI (devin auth login)",
    "copilot-cli": "GitHub Copilot CLI on your subscription (copilot login)",
    "grok-cli": "Grok CLI on your subscription (grok login)",
}

_OPTIONAL_PACKAGES: dict[str, tuple[str, str]] = {
    # runtime name -> (importable package, pip extra)
    "adk": ("google.adk", "superqode[adk]"),
    "openai-agents": ("agents", "superqode[openai-agents]"),
    "pydanticai": ("pydantic_ai", "superqode[pydanticai]"),
    "codex-sdk": ("openai_codex", "superqode[codex-sdk]"),
    "copilot-sdk": ("copilot", "superqode[copilot-sdk]"),
    "claude-agent-sdk": ("claude_agent_sdk", "superqode[claude-agent-sdk]"),
    "antigravity-sdk": ("google.antigravity", "superqode[antigravity-sdk]"),
}


_DOCUMENTATION_URLS: dict[str, str] = {
    # Vendor documentation for runtimes a user may install by hand. Only
    # entries that were checked to resolve belong here: a stale or guessed link
    # is worse than sending someone to their own search engine.
    "adk": "https://google.github.io/adk-docs/",
    "openai-agents": "https://openai.github.io/openai-agents-python/",
    "pydanticai": "https://ai.pydantic.dev/",
    "codex-sdk": "https://developers.openai.com/codex/sdk/",
    "copilot-sdk": "https://github.com/github/copilot-sdk",
    "claude-agent-sdk": "https://docs.claude.com/en/api/agent-sdk/overview",
    "antigravity-sdk": "https://antigravity.google/docs/cli-install",
    "antigravity-cli": "https://antigravity.google/docs/cli-install",
    "devin-cli": "https://docs.devin.ai/cli",
}


def runtime_documentation_url(name: str | None) -> str | None:
    """Return the vendor's documentation for ``name``, if one is known.

    Returns None rather than a guess so callers can simply omit the link.
    """
    return _DOCUMENTATION_URLS.get((name or "").strip().lower())


def runtime_extra(name: str | None) -> str | None:
    """Return the SuperQode extra providing ``name``, or None if it needs none.

    Lets the TUI offer an in-place install for a missing runtime instead of
    printing a command the user has to leave the app to run.
    """
    entry = _OPTIONAL_PACKAGES.get((name or "").strip().lower())
    if entry is None:
        return None
    spec = entry[1]
    if "[" not in spec:
        return None
    return spec.split("[", 1)[1].rstrip("]").strip() or None


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
        elif name == "devin-cli":
            from .devin_status import probe_devin_cli

            status = probe_devin_cli()
            installed = status.installed
            ready = status.compatible
            status_detail = status.detail
            install_hint = None if installed else status.issue
            implemented = True
        elif name == "antigravity-managed":
            installed = True
            ready = True
            install_hint = None
            implemented = True
            status_detail = "Gemini API key is verified on first use"
        elif _vendor_cli_spec(name) is not None:
            # Subscription CLI runtimes need the vendor binary on PATH rather
            # than an optional Python package.
            import shutil

            spec = _vendor_cli_spec(name)
            installed = shutil.which(spec.binary) is not None
            ready = installed
            install_hint = None if installed else spec.install_hint
            implemented = True
            status_detail = (
                f"{spec.label} CLI on PATH; the subscription login is verified on first use"
                if installed
                else spec.install_hint
            )
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
