"""Phase 7 — OpenAI Agents SandboxAgent integration.

When the OpenAI Agents runtime is asked for a sandbox backend (via the
``sandbox_backend`` kwarg or by setting ``SUPERQODE_SANDBOX``), we upgrade the
constructed Agent to a ``SandboxAgent`` and pass a ``SandboxRunConfig`` to the
Runner.

Two clients ship in the local SDK source tree: ``unix_local`` and ``docker``.
The other clients announced in the v0.14 release (E2B / Daytona / Modal /
Vercel / Runloop / Blaxel / Cloudflare) ship as third-party adapters — they're
recognized by name here and a clear install hint is surfaced when missing.

This module imports the SDK lazily so importing ``superqode.runtime`` is free
of the optional ``openai-agents`` dependency.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..agent.loop import AgentConfig
from .errors import RuntimeNotInstalledError

logger = logging.getLogger(__name__)


# Mapping: superqode --sandbox name -> (module path, class name).
# `local` and `docker` ship with openai-agents 0.14+; the rest are third-party.
_SANDBOX_CLIENTS: Dict[str, tuple[str, str, Optional[str]]] = {
    # name              module to import                         class               extra hint
    "local": ("agents.sandbox.sandboxes.unix_local", "UnixLocalSandboxClient", None),
    "docker": ("agents.sandbox.sandboxes.docker", "DockerSandboxClient", None),
    "e2b": ("agents_e2b", "E2BSandboxClient", "agents-e2b"),
    "daytona": ("agents_daytona", "DaytonaSandboxClient", "agents-daytona"),
    "modal": ("agents_modal", "ModalSandboxClient", "agents-modal"),
    "vercel": ("agents_vercel", "VercelSandboxClient", "agents-vercel"),
    "runloop": ("agents_runloop", "RunloopSandboxClient", "agents-runloop"),
    "blaxel": ("agents_blaxel", "BlaxelSandboxClient", "agents-blaxel"),
    "cloudflare": ("agents_cloudflare", "CloudflareSandboxClient", "agents-cloudflare"),
}


def supported_sandbox_backends() -> list[str]:
    """Return the sandbox backend names this module understands.

    Note that being *recognized* doesn't mean the adapter is installed —
    use :func:`is_sandbox_backend_available` for that check.
    """
    return list(_SANDBOX_CLIENTS.keys())


def is_sandbox_backend_available(name: str) -> bool:
    """Return True when the backend's client module imports successfully."""
    entry = _SANDBOX_CLIENTS.get(name.lower())
    if entry is None:
        return False
    module_path, _class_name, _extra = entry
    try:
        importlib.import_module(module_path)
        return True
    except ImportError:
        return False


def build_sandbox_client(name: str) -> Any:
    """Build a sandbox client instance for the given backend name.

    Raises:
        ValueError: when ``name`` is not a recognized backend.
        RuntimeNotInstalledError: when the recognized backend's package is missing.
    """
    key = name.lower().strip()
    if key not in _SANDBOX_CLIENTS:
        raise ValueError(
            f"Unknown sandbox backend '{name}'. Known: {', '.join(sorted(_SANDBOX_CLIENTS))}"
        )
    module_path, class_name, extra = _SANDBOX_CLIENTS[key]
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = f"pip install {extra}" if extra else "pip install superqode[openai-agents]"
        raise RuntimeNotInstalledError(
            f"Sandbox backend '{name}' requires '{module_path}'. Install with: {hint}"
        ) from exc

    cls = getattr(module, class_name, None)
    if cls is None:
        raise RuntimeNotInstalledError(
            f"Module '{module_path}' has no class '{class_name}' for backend '{name}'"
        )
    return cls()


def build_manifest(config: AgentConfig) -> Any:
    """Translate SuperQode's AgentConfig into an OpenAI Agents ``Manifest``.

    v1 wiring: mount the agent's working directory under ``repo``. Environment
    variables and other entries are left empty — users who need them can
    declare a Manifest directly via the lower-level SDK and pass it through
    ``SandboxRunConfig(manifest=...)``.
    """
    try:
        from agents.sandbox import Manifest
        from agents.sandbox.entries import LocalDir
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents 0.14+ is required for sandbox manifests. "
            "Install with: pip install 'superqode[openai-agents]'"
        ) from exc

    working_directory = Path(config.working_directory)
    return Manifest(entries={"repo": LocalDir(src=working_directory)})


def build_sandbox_agent(
    *,
    name: str,
    instructions: str,
    tools: list,
    model: Any,
    manifest: Any,
) -> Any:
    """Construct a ``SandboxAgent`` with the bridged tools and default Manifest.

    The capabilities list (Filesystem / Shell / Compaction) is the SDK default,
    which is what we want until SuperQode wires per-role capability overrides.
    """
    try:
        from agents.sandbox import SandboxAgent
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents 0.14+ is required for SandboxAgent. "
            "Install with: pip install 'superqode[openai-agents]'"
        ) from exc

    return SandboxAgent(
        name=name,
        instructions=instructions,
        tools=tools,
        model=model,
        default_manifest=manifest,
    )


def build_sandbox_run_config(client: Any, base_run_config: Any) -> Any:
    """Return a RunConfig with the sandbox set; copy fields from ``base_run_config``.

    SDK's ``RunConfig`` is a dataclass; ``replace`` would be ideal but the
    sandbox slot is on ``SandboxRunConfig``. We construct a new RunConfig
    preserving ``tracing_disabled`` from the base.
    """
    try:
        from agents.run import RunConfig
        from agents.sandbox import SandboxRunConfig
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents 0.14+ is required for SandboxRunConfig. "
            "Install with: pip install 'superqode[openai-agents]'"
        ) from exc

    return RunConfig(
        tracing_disabled=getattr(base_run_config, "tracing_disabled", True),
        sandbox=SandboxRunConfig(client=client),
    )
