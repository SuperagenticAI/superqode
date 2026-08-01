"""Live inventory of what SuperQode can do on this machine, right now.

SuperQode ships roughly eighty integrations across coding agents, providers,
runtimes, memory, tools, sandboxes, observability, evaluation, optimization and
delivery. Until now the only complete map of that surface was the documentation,
which meant the product had to be explained rather than seen.

This module answers three questions per capability: what is it, what is its
state here, and which command acts on it. Everything is probed locally and
cheaply, because the browser renders synchronously; a category that cannot
answer "what is true on this machine" does not belong here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

#: Cap on rows rendered inside one expanded category, so the browser stays
#: navigable when a registry has dozens of entries.
DETAIL_LIMIT = 12


@dataclass(frozen=True)
class CapabilityItem:
    """One concrete integration inside a category."""

    name: str
    state: str  # "on" | "ready" | "available" | "install"
    detail: str = ""

    @property
    def active(self) -> bool:
        return self.state in {"on", "ready"}


@dataclass
class Capability:
    """One row of the capability browser."""

    id: str
    title: str
    command: str
    summary: str = ""
    total: int = 0
    active: int = 0
    status: str = ""
    items: list[CapabilityItem] = field(default_factory=list)

    @property
    def headline(self) -> str:
        parts = []
        if self.total:
            parts.append(f"{self.total} available")
        if self.status:
            parts.append(self.status)
        return "   ".join(parts)


def _safe(fn: Callable[[], Capability], fallback: Capability) -> Capability:
    """Probes must never take the browser down with them."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - one broken probe must not hide the rest
        return fallback


def _coding_agents() -> Capability:
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_VENDORS,
        list_connection_profiles,
    )

    profiles = list_connection_profiles(CONNECT_MENU_VENDORS)
    ready = [profile for profile in profiles if profile.available]
    items = [
        CapabilityItem(
            name=profile.label.replace(" subscription", ""),
            state="ready" if profile.available else "install",
            detail=" · ".join(profile.badges),
        )
        for profile in profiles
    ]
    return Capability(
        id="agents",
        title="Coding agents",
        command=":connect",
        summary="Vendor coding agents that bring their own harness",
        total=len(profiles),
        active=len(ready),
        status=f"{len(ready)} ready",
        items=items,
    )


def _model_providers() -> Capability:
    import os

    from superqode.providers.registry import PROVIDERS

    keyed: list[CapabilityItem] = []
    unkeyed: list[CapabilityItem] = []
    for name, provider in PROVIDERS.items():
        envs = list(getattr(provider, "env_vars", ()) or ())
        has_key = any(os.environ.get(env) for env in envs)
        item = CapabilityItem(
            name=name,
            state="ready" if has_key else "available",
            detail=envs[0] if envs else "no key required",
        )
        (keyed if has_key else unkeyed).append(item)
    return Capability(
        id="providers",
        title="Model providers",
        command=":connect byok",
        summary="Hosted models through your own API key",
        total=len(PROVIDERS),
        active=len(keyed),
        status=f"{len(keyed)} keyed" if keyed else "no keys set",
        items=[*keyed, *unkeyed],
    )


def _local_inference() -> Capability:
    from superqode.local.servers import SPECS, ServerManager

    manager = ServerManager()
    items: list[CapabilityItem] = []
    installed = 0
    for engine in SPECS:
        # Read-only: this must not disturb the interpreter's import state.
        ready = manager.is_installed(engine, refresh_imports=False)
        installed += int(ready)
        items.append(
            CapabilityItem(
                name=engine,
                state="ready" if ready else "install",
                detail="installed" if ready else "not installed",
            )
        )
    return Capability(
        id="local",
        title="Local inference",
        command=":connect local",
        summary="Models on your own machine, no key and no data leaving the box",
        total=len(SPECS),
        active=installed,
        status=f"{installed} installed" if installed else "none installed",
        items=items,
    )


def _harnesses() -> Capability:
    from superqode.harness.catalog import list_harnesses

    entries = list_harnesses(Path.cwd())
    available = [entry for entry in entries if entry.available]
    return Capability(
        id="harnesses",
        title="Harnesses",
        command=":harness",
        summary="Tool loop, policy, memory and model route as one owned artifact",
        total=len(entries),
        active=len(available),
        status=f"{len(available)} available",
        items=[
            CapabilityItem(
                name=entry.id,
                state="ready" if entry.available else "install",
                detail=entry.description[:70],
            )
            for entry in entries
        ],
    )


def _runtimes() -> Capability:
    from superqode.runtime import list_runtimes

    runtimes = list_runtimes()
    ready = [runtime for runtime in runtimes if runtime.ready]
    return Capability(
        id="runtimes",
        title="Execution runtimes",
        command=":runtime",
        summary="Run the same HarnessSpec through another agent framework",
        total=len(runtimes),
        active=len(ready),
        status=f"{len(ready)} ready",
        items=[
            CapabilityItem(
                name=runtime.name,
                state="ready" if runtime.ready else "install",
                detail=runtime.description,
            )
            for runtime in runtimes
        ],
    )


def _memory() -> Capability:
    from superqode.memory import available_memory_providers

    statuses = available_memory_providers(Path.cwd())
    ready = [status for status in statuses if status.available]
    return Capability(
        id="memory",
        title="Memory",
        command=":memory",
        summary="Facts that survive every session, harness and agent switch",
        total=len(statuses),
        active=len(ready),
        status=f"{len(ready)} on" if ready else "none enabled",
        items=[
            CapabilityItem(
                name=status.provider,
                state="on" if status.available else "install",
                detail=status.detail or "",
            )
            for status in statuses
        ],
    )


def _tools_and_mcp() -> Capability:
    from superqode.harness.catalog import list_harnesses
    from superqode.mcp.integration import list_mcp_servers

    entries = {entry.id: entry for entry in list_harnesses(Path.cwd())}
    widest = entries.get("workbench") or entries.get("core")
    tool_count = len(getattr(widest, "tools", ()) or ()) if widest else 0
    items = [
        CapabilityItem(name=name, state="ready", detail="native tool")
        for name in (getattr(widest, "tools", ()) or ())
    ]
    servers = list_mcp_servers()
    items.extend(
        CapabilityItem(
            name=str(server.get("name") or "MCP server"),
            state="on",
            detail="MCP server",
        )
        for server in servers
    )
    total = tool_count + len(servers)
    return Capability(
        id="tools",
        title="Tools and MCP",
        command=":mcp",
        summary="Native tools plus any Model Context Protocol server you attach",
        total=total,
        active=total,
        status=(
            f"{tool_count} native tools · {len(servers)} MCP on"
            if servers
            else f"{tool_count} native tools · no MCP attached"
        ),
        items=items,
    )


def _sandboxes() -> Capability:
    from superqode.sandbox import SUPPORTED_SANDBOX_BACKENDS

    backends = list(SUPPORTED_SANDBOX_BACKENDS)
    return Capability(
        id="sandboxes",
        title="Sandboxes",
        command=":sandbox",
        summary="Run shell work isolated, locally or in a cloud devbox",
        total=len(backends),
        active=1 if "local-os" in backends else 0,
        status="local-os ready" if "local-os" in backends else "none active",
        items=[
            CapabilityItem(
                name=str(backend),
                state="ready" if backend == "local-os" else "available",
            )
            for backend in backends
        ],
    )


def _observability() -> Capability:
    sinks = ("OpenTelemetry", "MLflow", "LangSmith", "Logfire", "Arize Phoenix")
    items = [CapabilityItem(name="Local run events", state="ready")]
    items.extend(CapabilityItem(name=sink, state="available") for sink in sinks)
    return Capability(
        id="observability",
        title="Observability",
        command=":harness observability status",
        summary="Export normalized runs, spans and evidence to your own stack",
        total=len(items),
        active=1,
        status="local events always on",
        items=items,
    )


def _evaluation() -> Capability:
    items = [
        CapabilityItem(name="eval packs", state="ready"),
        CapabilityItem(name="scorecards", state="ready"),
        CapabilityItem(name="benchmarks", state="ready", detail="HarnessBench"),
        CapabilityItem(name="regression gates", state="ready", detail="for CI"),
    ]
    return Capability(
        id="evaluation",
        title="Evaluation",
        command=":eval",
        summary="Score a harness on your repository: tasks, rubrics, regression gates",
        total=len(items),
        active=len(items),
        status="ready",
        items=items,
    )


def _optimization() -> Capability:
    items = [
        CapabilityItem(name="GEPA", state="available", detail="reflective search"),
        CapabilityItem(name="GEPA meta-harness", state="available", detail="candidate frontier"),
        CapabilityItem(name="MetaHarness", state="available", detail="Superagentic export"),
        CapabilityItem(name="SkillOpt", state="available", detail="markdown skill review"),
        CapabilityItem(name="AutoResearch", state="available"),
    ]
    return Capability(
        id="optimization",
        title="Optimization",
        command=":harness optimize",
        summary="Generate harness candidates from recorded failure evidence",
        total=len(items),
        active=0,
        status="needs an eval first",
        items=items,
    )


def _remote() -> Capability:
    import shutil

    items = [
        CapabilityItem(name="Telegram", state="available", detail="bot token and allowlist"),
        CapabilityItem(name="Slack", state="available", detail="Socket Mode app"),
        CapabilityItem(name="Discord", state="available", detail="bot token and allowlist"),
        CapabilityItem(name="Browser TUI", state="available", detail="superqode serve web"),
        CapabilityItem(
            name="SuperQode as an ACP agent",
            state="ready" if shutil.which("superqode") else "available",
            detail="serve acp, so editors like Zed can drive it",
        ),
    ]
    return Capability(
        id="remote",
        title="Remote control",
        command=":daemon",
        summary="Drive a session from chat, a browser, or another editor",
        total=len(items),
        active=sum(item.active for item in items),
        status="not running",
        items=items,
    )


def _delivery() -> Capability:
    items = [
        CapabilityItem(name="WorkOrders", state="ready", detail="tasks, leases, recovery"),
        CapabilityItem(name="Code factory", state="ready", detail="cross-repository runs"),
        CapabilityItem(name="Session sharing", state="ready", detail=":share create"),
        CapabilityItem(name="Session tree", state="ready", detail=":tree"),
    ]
    return Capability(
        id="delivery",
        title="Delivery",
        command=":work",
        summary="Durable multi-repository work with checks, reviews and evidence",
        total=len(items),
        active=len(items),
        status="ready",
        items=items,
    )


#: Probe order is the order the browser renders. It follows the ownership
#: ladder (agents, then models, then your own harness) and then the platform
#: capabilities that apply to all three.
_PROBES: tuple[tuple[str, Callable[[], Capability]], ...] = (
    ("agents", _coding_agents),
    ("providers", _model_providers),
    ("local", _local_inference),
    ("harnesses", _harnesses),
    ("runtimes", _runtimes),
    ("memory", _memory),
    ("tools", _tools_and_mcp),
    ("sandboxes", _sandboxes),
    ("observability", _observability),
    ("evaluation", _evaluation),
    ("optimization", _optimization),
    ("remote", _remote),
    ("delivery", _delivery),
)


#: Last probe result, keyed by the directory it described. Probing reaches into
#: registries, local server state and the filesystem, so it is something a
#: caller opts into rather than something a render triggers.
_LAST_INVENTORY: dict[str, list["Capability"]] = {}


def capability_inventory() -> list[Capability]:
    """Probe every capability category. Individual failures degrade to a stub."""
    inventory = [
        _safe(
            probe,
            Capability(id=key, title=key.title(), command="", status="unavailable"),
        )
        for key, probe in _PROBES
    ]
    _LAST_INVENTORY.clear()
    _LAST_INVENTORY[str(Path.cwd())] = inventory
    return inventory


def cached_inventory() -> list[Capability]:
    """Return the last inventory probed for this directory, or an empty list.

    Rendering must not probe. A screen that reaches into thirteen registries
    every time it is drawn is doing real work as a side effect of display,
    which makes the display both slow and order-dependent. Callers that want
    fresh numbers ask for them with :func:`capability_inventory`.
    """
    try:
        return _LAST_INVENTORY.get(str(Path.cwd()), [])
    except OSError:  # the working directory can vanish under us
        return []


def inventory_totals(capabilities: list[Capability]) -> tuple[int, int]:
    """Return (active, total) across every category with countable items."""
    total = sum(capability.total for capability in capabilities)
    active = sum(capability.active for capability in capabilities)
    return active, total


__all__ = [
    "DETAIL_LIMIT",
    "Capability",
    "CapabilityItem",
    "cached_inventory",
    "capability_inventory",
    "inventory_totals",
]
