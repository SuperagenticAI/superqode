"""Unified picker entries for native, vendor, and ACP coding-agent integrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


VENDOR_HARNESS_IDS = (
    "codex",
    "claude",
    "kimi-code",
    "qwen-code",
    "antigravity",
    "grok",
    "copilot",
    "cursor",
    "amp",
    "muse",
    "prime-agent",
    "devin",
    "droid",
    "kiro",
    "glm-cli",
)
VENDOR_ACP_AGENT_NAMES = frozenset({"kimi", "qwen"})
ACP_BROWSER_ID = "acp:all"


@dataclass(frozen=True)
class HarnessPickerItem:
    """One consistently rendered item in the interactive harness picker."""

    id: str
    display_name: str
    description: str
    runtime: str
    source: str
    group: str
    available: bool
    issue: str
    continuity: str
    provider: str = ""
    model: str = ""
    path: Path | None = None
    kind: str = "harness"
    target: Any = None
    install_extra: str = ""
    #: Shown in the detail panel when this entry is highlighted. Empty for
    #: every entry that does not declare one, so nothing changes for them.
    warning: str = ""


def _native_group(entry) -> str:
    if entry.source in {"file", "registry"}:
        return "Project harnesses"
    if entry.source.startswith("optional:"):
        return "Optional integrations"
    if entry.source == "built-in" and entry.category == "workflow":
        return "SuperQode harnesses"
    return "Model and task presets"


def _native_item(entry) -> HarnessPickerItem:
    return HarnessPickerItem(
        id=entry.id,
        display_name=entry.display_name,
        description=entry.description,
        runtime=entry.runtime,
        source=entry.source,
        group=_native_group(entry),
        available=entry.available,
        issue=entry.issue,
        continuity=entry.continuity,
        provider=entry.provider,
        model=entry.model,
        path=entry.path,
        kind="harness",
        target=entry,
        install_extra="tau" if entry.source == "optional:tau" and not entry.available else "",
        warning=str(entry.spec.metadata.get("selection_warning") or ""),
    )


def _vendor_item(profile) -> HarnessPickerItem:
    python_extras = {
        "codex-sdk": "codex-sdk",
        "claude-agent-sdk": "claude-agent-sdk",
        "copilot-sdk": "copilot-sdk",
    }
    install_extra = ""
    extra = python_extras.get(str(profile.runtime or ""))
    if extra:
        try:
            # Ask about this one package only. The full list_runtimes() probe
            # shells out to every vendor CLI, which cost the picker seconds.
            from superqode.runtime import optional_package_installed

            if not optional_package_installed(profile.runtime):
                install_extra = extra
        except Exception:
            install_extra = extra
    target = profile.runtime or profile.acp_agent or profile.connector
    return HarnessPickerItem(
        id=profile.id,
        display_name=profile.label,
        description=profile.description,
        runtime=target,
        source=f"connection:{profile.connector}",
        group="Coding agents",
        available=profile.available,
        issue=profile.unavailable_hint,
        continuity="fresh-session",
        kind="connection",
        target=profile,
        install_extra=install_extra,
    )


def _acp_agent_mapping(metadata: dict[str, Any]) -> dict[str, Any]:
    """Convert legacy synchronous registry metadata to the live Agent shape."""
    run_command = str(metadata.get("run_command") or "")
    install_command = str(metadata.get("installation_command") or "")
    name = str(metadata.get("name") or metadata.get("short_name") or "ACP agent")
    instructions = str(metadata.get("installation_instructions") or "")
    return {
        **metadata,
        "protocol": "acp",
        "type": "coding",
        "run_command": {"*": run_command},
        "actions": {
            "*": {
                "install": {
                    "command": install_command,
                    "description": f"Install {name}",
                }
            }
        },
        "help": f"# {name}\n\n## Installation\n\n{instructions}",
    }


def _acp_item(
    agent: dict[str, Any],
    *,
    installed: bool | None = None,
    recent: bool = False,
) -> HarnessPickerItem:
    from superqode.commands.acp import check_agent_installed
    from superqode.providers.acp_registry import registry_catalog_tier

    short_name = str(agent.get("short_name") or "").strip()
    installed = check_agent_installed(agent) if installed is None else installed
    install = (
        agent.get("actions", {}).get("*", {}).get("install", {}).get("command", "")
        if isinstance(agent.get("actions"), dict)
        else ""
    )
    tier = registry_catalog_tier(str(agent.get("registry_id") or ""), short_name)
    labels = []
    if installed:
        labels.append("installed")
    if recent:
        labels.append("recent")
    if tier == "featured":
        labels.append("featured")
    source = f"acp:{'+'.join(labels) or tier}"
    return HarnessPickerItem(
        id=f"acp:{short_name}",
        display_name=f"{agent.get('name') or short_name} (ACP)",
        description=str(agent.get("description") or "ACP-compatible coding agent."),
        runtime="ACP",
        source=source,
        group="ACP agents",
        available=bool(installed),
        issue=str(install or agent.get("installation_instructions") or ""),
        continuity="context-replay",
        kind="acp",
        target=agent,
    )


def acp_picker_items(*, include_registry: bool = False) -> list[HarnessPickerItem]:
    """Return installed, recent, and featured ACP agents for the unified picker.

    ``include_registry`` expands to the complete bundled registry for command
    completion and explicit catalog searches. The visual picker remains
    intentionally curated and ends with a visible Browse All row.
    """
    from superqode.acp.session_store import recent_agent_identities
    from superqode.agents.acp_registry import get_all_registry_agents
    from superqode.commands.acp import check_agent_installed
    from superqode.providers.acp_registry import registry_catalog_tier

    agents = [_acp_agent_mapping(dict(agent)) for agent in get_all_registry_agents().values()]
    recent_order = {
        identity.casefold(): index for index, identity in enumerate(recent_agent_identities())
    }
    candidates: list[tuple[dict[str, Any], bool, bool, str]] = []
    for agent in agents:
        short_name = str(agent.get("short_name") or "")
        identity = str(agent.get("identity") or "")
        installed = check_agent_installed(agent)
        recent = identity.casefold() in recent_order
        tier = registry_catalog_tier(str(agent.get("registry_id") or ""), short_name)
        if include_registry or installed or recent or tier == "featured":
            candidates.append((agent, installed, recent, tier))

    # The named vendor integrations already provide these routes on the first
    # screen. Keep their ACP variants searchable without showing duplicates.
    visible_vendor_names = set(VENDOR_HARNESS_IDS) | set(VENDOR_ACP_AGENT_NAMES)
    if not include_registry:
        candidates = [
            candidate
            for candidate in candidates
            if str(candidate[0].get("short_name") or "").casefold() not in visible_vendor_names
        ]

    def sort_key(candidate: tuple[dict[str, Any], bool, bool, str]):
        agent, installed, recent, tier = candidate
        recent_rank = recent_order.get(str(agent.get("identity") or "").casefold(), 999)
        return (
            0 if installed else 1,
            0 if recent else 1,
            recent_rank,
            0 if tier == "featured" else 1,
            str(agent.get("name") or "").casefold(),
        )

    return [
        _acp_item(agent, installed=installed, recent=recent)
        for agent, installed, recent, _tier in sorted(candidates, key=sort_key)
    ]


def harness_acp_item(reference: str) -> HarnessPickerItem | None:
    """Resolve an explicit ``acp:<name>`` or a bare ACP short name."""
    wanted = reference.strip()
    if wanted.casefold() == ACP_BROWSER_ID:
        return HarnessPickerItem(
            id=ACP_BROWSER_ID,
            display_name="Browse all ACP agents",
            description="Open the complete official ACP agent catalog.",
            runtime="ACP registry",
            source="acp:registry",
            group="ACP agents",
            available=True,
            issue="",
            continuity="catalog",
            kind="acp-browser",
        )
    if wanted.casefold().startswith("acp:"):
        wanted = wanted[4:]
    wanted = wanted.strip().casefold()
    if not wanted:
        return None
    for item in acp_picker_items(include_registry=True):
        if str(item.target.get("short_name") or "").casefold() == wanted:
            return item
    return None


def _acp_browser_item(total: int) -> HarnessPickerItem:
    return HarnessPickerItem(
        id=ACP_BROWSER_ID,
        display_name=f"Browse all ACP agents ({total})",
        description="Open the complete official ACP registry with setup guidance.",
        runtime="ACP registry",
        source="acp:registry",
        group="ACP agents",
        available=True,
        issue="",
        continuity="catalog",
        kind="acp-browser",
    )


def harness_connection_profile(reference: str):
    """Return a vendor profile exposed through the harness picker."""
    from dataclasses import replace

    from superqode.providers.connection_profiles import get_connection_profile

    requested = (reference or "").strip().casefold()
    # ``claude`` remains the concise harness-switch name, but it resolves only
    # to the Anthropic API-key runtime. It is not a subscription connection
    # profile and therefore never appears in :connect or --connect choices.
    if requested == "claude":
        profile = get_connection_profile("claude-api")
        return replace(profile, id="claude") if profile is not None else None
    profile = get_connection_profile(requested)
    return profile if profile is not None and profile.id in VENDOR_HARNESS_IDS else None


def harness_picker_items(
    root: str | Path = ".",
    *,
    include_all: bool = True,
    expand_protocol_catalog: bool = False,
    native_entries=None,
) -> list[HarnessPickerItem]:
    """Build the complete, section-ordered interactive picker inventory."""
    from superqode.harness import list_harnesses, recommended_harnesses

    if native_entries is not None:
        supplied = list(native_entries)
        if supplied and all(isinstance(entry, HarnessPickerItem) for entry in supplied):
            return supplied
        native_entries = supplied

    entries = (
        native_entries
        if native_entries is not None
        else (list_harnesses(Path(root)) if include_all else recommended_harnesses(Path(root)))
    )
    native_items = [_native_item(entry) for entry in entries]
    group_order = {
        "SuperQode harnesses": 0,
        "Optional integrations": 1,
        "Model and task presets": 2,
        "Project harnesses": 3,
    }
    native_items.sort(key=lambda item: group_order.get(item.group, 99))
    managed = [item for item in native_items if item.group == "SuperQode harnesses"]
    optional = [item for item in native_items if item.group == "Optional integrations"]
    presets = [item for item in native_items if item.group == "Model and task presets"]
    projects = [item for item in native_items if item.group == "Project harnesses"]

    if not include_all or native_entries is not None:
        return [*managed, *optional, *presets, *projects]

    vendors: list[HarnessPickerItem] = []
    for profile_id in VENDOR_HARNESS_IDS:
        profile = harness_connection_profile(profile_id)
        if profile is not None:
            vendors.append(_vendor_item(profile))
    all_acp_items = acp_picker_items(include_registry=True)
    acp_items = (
        all_acp_items
        if expand_protocol_catalog
        else [*acp_picker_items(), _acp_browser_item(len(all_acp_items))]
    )
    return [*managed, *vendors, *acp_items, *optional, *presets, *projects]


__all__ = [
    "ACP_BROWSER_ID",
    "HarnessPickerItem",
    "VENDOR_ACP_AGENT_NAMES",
    "VENDOR_HARNESS_IDS",
    "acp_picker_items",
    "harness_acp_item",
    "harness_connection_profile",
    "harness_picker_items",
]
