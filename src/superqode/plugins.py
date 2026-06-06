"""Plugin manifest loading for SuperQode extensions.

Event hooks
-----------
A manifest's ``event_hooks`` is a list of entries with the shape::

    {
      "point": "before_tool_call",            # one of agent.hooks.ALL_HOOK_POINTS
      "handler": "myplugin.hooks:audit",      # "module:func" or "module.func"
      "name": "audit-tools"                   # optional, defaults to handler basename
    }

Use :func:`register_plugin_hooks` to import each handler and register it
against an :class:`agent.hooks.HookRegistry`. Bad entries (unknown point,
import error, non-callable) are skipped with a recorded error so one
broken plugin doesn't take the others down.
"""

from __future__ import annotations

import importlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from superqode.agent.hooks import HookRegistry


logger = logging.getLogger(__name__)

PLUGIN_STATE_FILE = ".superqode/plugins.json"


@dataclass(frozen=True)
class PluginManifest:
    """A SuperQode plugin manifest."""

    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    tools: List[Dict[str, Any]] = field(default_factory=list)
    commands: List[Dict[str, Any]] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    providers: List[Dict[str, Any]] = field(default_factory=list)
    permission_rules: List[Dict[str, Any]] = field(default_factory=list)
    context_injectors: List[Dict[str, Any]] = field(default_factory=list)
    event_hooks: List[Dict[str, Any]] = field(default_factory=list)
    path: Optional[Path] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], path: Optional[Path] = None) -> "PluginManifest":
        plugin_id = str(data.get("id") or data.get("name") or "").strip()
        name = str(data.get("name") or plugin_id).strip()
        if not plugin_id:
            raise ValueError("plugin manifest requires an id or name")
        return cls(
            id=plugin_id,
            name=name,
            version=str(data.get("version", "0.1.0")),
            description=str(data.get("description", "")),
            tools=list(data.get("tools", [])),
            commands=list(data.get("commands", [])),
            skills=list(data.get("skills", [])),
            providers=list(data.get("providers", [])),
            permission_rules=list(data.get("permission_rules", data.get("permissionRules", []))),
            context_injectors=list(data.get("context_injectors", data.get("contextInjectors", []))),
            event_hooks=list(data.get("event_hooks", data.get("eventHooks", []))),
            path=path,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tools": self.tools,
            "commands": self.commands,
            "skills": self.skills,
            "providers": self.providers,
            "permission_rules": self.permission_rules,
            "context_injectors": self.context_injectors,
            "event_hooks": self.event_hooks,
            "path": str(self.path) if self.path else None,
        }


def discover_plugin_manifests(root: str | Path = ".") -> List[Path]:
    """Discover plugin manifests in project and user plugin directories."""
    base = Path(root).expanduser().resolve()
    candidates = [
        base / ".superqode" / "plugins",
        base / ".agents" / "plugins",
        Path.home() / ".superqode" / "plugins",
    ]

    paths: List[Path] = []
    seen: set[Path] = set()
    for directory in candidates:
        if not directory.exists():
            continue
        for manifest in sorted(directory.glob("*/plugin.json")) + sorted(directory.glob("*.json")):
            resolved = manifest.resolve()
            if resolved not in seen:
                paths.append(resolved)
                seen.add(resolved)
    return paths


def _project_root(root: str | Path = ".") -> Path:
    return Path(root).expanduser().resolve()


def project_plugin_dir(root: str | Path = ".") -> Path:
    """Return the project-local plugin installation directory."""
    return _project_root(root) / ".superqode" / "plugins"


def plugin_state_path(root: str | Path = ".") -> Path:
    """Return the project-local plugin state file."""
    return _project_root(root) / PLUGIN_STATE_FILE


def load_plugin_state(root: str | Path = ".") -> Dict[str, Any]:
    """Load project-local plugin enable/disable state."""
    path = plugin_state_path(root)
    if not path.exists():
        return {"disabled": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"disabled": []}
    disabled = data.get("disabled", [])
    if not isinstance(disabled, list):
        disabled = []
    return {"disabled": [str(item) for item in disabled]}


def save_plugin_state(state: Dict[str, Any], root: str | Path = ".") -> None:
    """Persist project-local plugin enable/disable state."""
    path = plugin_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    disabled = sorted({str(item) for item in state.get("disabled", [])})
    path.write_text(json.dumps({"disabled": disabled}, indent=2) + "\n", encoding="utf-8")


def disabled_plugin_ids(root: str | Path = ".") -> set[str]:
    """Return ids disabled in the project-local plugin state file."""
    return set(load_plugin_state(root).get("disabled", []))


def load_plugin_manifest(path: str | Path) -> PluginManifest:
    """Load a single plugin manifest."""
    manifest_path = Path(path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return PluginManifest.from_dict(data, path=manifest_path)


def load_plugins(root: str | Path = ".", *, include_disabled: bool = False) -> List[PluginManifest]:
    """Load all discoverable plugin manifests."""
    plugins: List[PluginManifest] = []
    disabled = disabled_plugin_ids(root) if not include_disabled else set()
    for path in discover_plugin_manifests(root):
        manifest = load_plugin_manifest(path)
        if manifest.id in disabled:
            continue
        plugins.append(manifest)
    return plugins


def enable_plugin(plugin_id: str, root: str | Path = ".") -> bool:
    """Enable a project plugin id. Returns True if state changed."""
    state = load_plugin_state(root)
    disabled = set(state.get("disabled", []))
    changed = plugin_id in disabled
    disabled.discard(plugin_id)
    state["disabled"] = sorted(disabled)
    save_plugin_state(state, root)
    return changed


def disable_plugin(plugin_id: str, root: str | Path = ".") -> bool:
    """Disable a project plugin id. Returns True if state changed."""
    state = load_plugin_state(root)
    disabled = set(state.get("disabled", []))
    changed = plugin_id not in disabled
    disabled.add(plugin_id)
    state["disabled"] = sorted(disabled)
    save_plugin_state(state, root)
    return changed


def _safe_plugin_dir_name(plugin_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in plugin_id).strip(".-")
    return safe or "plugin"


def install_plugin(source: str | Path, root: str | Path = ".") -> PluginManifest:
    """Install a local plugin manifest or directory into ``.superqode/plugins``."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"plugin source not found: {source}")
    manifest_path = source_path / "plugin.json" if source_path.is_dir() else source_path
    if not manifest_path.exists():
        raise FileNotFoundError(f"plugin manifest not found: {manifest_path}")
    manifest = load_plugin_manifest(manifest_path)
    issues = validate_plugin_manifest(manifest_path)
    if issues:
        raise ValueError("; ".join(issues))

    dest_dir = project_plugin_dir(root) / _safe_plugin_dir_name(manifest.id)
    if dest_dir.exists():
        raise FileExistsError(f"plugin already installed: {manifest.id}")
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(source_path, dest_dir)
    else:
        dest_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source_path, dest_dir / "plugin.json")
    return load_plugin_manifest(dest_dir / "plugin.json")


@dataclass(frozen=True)
class PluginHookRegistration:
    """Outcome of registering one plugin event_hook entry."""

    plugin_id: str
    point: str
    handler: str
    name: str


@dataclass(frozen=True)
class PluginHookError:
    """Failure attaching one plugin event_hook entry. Other entries still run."""

    plugin_id: str
    handler: Optional[str]
    message: str


@dataclass(frozen=True)
class PluginHookRegistrationResult:
    registered: List[PluginHookRegistration] = field(default_factory=list)
    errors: List[PluginHookError] = field(default_factory=list)


def _resolve_handler(spec: str) -> Callable[..., Any]:
    """Resolve an import path to a callable.

    Accepts both ``module:func`` (canonical) and ``module.func`` (Pythonic).
    The colon form is preferred because it disambiguates packages whose
    final dotted segment happens to share a name with an attribute.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("handler must be a non-empty string")
    spec = spec.strip()
    if ":" in spec:
        module_name, _, attr = spec.partition(":")
    else:
        if "." not in spec:
            raise ValueError(f"handler {spec!r} must include a module path")
        module_name, _, attr = spec.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"handler {spec!r} must be 'module:func' or 'module.func'")
    module = importlib.import_module(module_name)
    try:
        target = getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(f"{module_name!r} has no attribute {attr!r}") from exc
    if not callable(target):
        raise ValueError(f"handler {spec!r} resolved to a non-callable")
    return target


def register_plugin_hooks(
    registry: "HookRegistry",
    manifests: List[PluginManifest],
) -> PluginHookRegistrationResult:
    """Resolve each manifest's ``event_hooks`` and register them.

    Per-entry errors are collected, not raised - a single broken plugin
    must not block the others. Inspect the returned ``errors`` list (or
    the logger) to surface failures to the user.
    """
    from superqode.agent.hooks import ALL_HOOK_POINTS

    registered: List[PluginHookRegistration] = []
    errors: List[PluginHookError] = []

    for manifest in manifests:
        for entry in manifest.event_hooks:
            handler_spec = (
                (entry.get("handler") or entry.get("target") or "")
                if isinstance(entry, dict)
                else ""
            )
            point = entry.get("point") if isinstance(entry, dict) else None
            name = entry.get("name") if isinstance(entry, dict) else None

            if not isinstance(entry, dict):
                errors.append(
                    PluginHookError(
                        plugin_id=manifest.id,
                        handler=None,
                        message=f"event_hook entry must be a dict, got {type(entry).__name__}",
                    )
                )
                continue
            if point not in ALL_HOOK_POINTS:
                errors.append(
                    PluginHookError(
                        plugin_id=manifest.id,
                        handler=handler_spec or None,
                        message=(
                            f"unknown hook point {point!r}; valid: {', '.join(ALL_HOOK_POINTS)}"
                        ),
                    )
                )
                continue
            try:
                fn = _resolve_handler(handler_spec)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    PluginHookError(
                        plugin_id=manifest.id,
                        handler=handler_spec or None,
                        message=str(exc),
                    )
                )
                logger.warning(
                    "plugin %s: failed to resolve hook handler %r: %s",
                    manifest.id,
                    handler_spec,
                    exc,
                )
                continue

            resolved_name = name or f"{manifest.id}:{handler_spec}"
            registered_name = registry.register(point, fn, name=resolved_name)
            registered.append(
                PluginHookRegistration(
                    plugin_id=manifest.id,
                    point=point,
                    handler=handler_spec,
                    name=registered_name,
                )
            )

    return PluginHookRegistrationResult(registered=registered, errors=errors)


def validate_plugin_manifest(path: str | Path) -> List[str]:
    """Validate a plugin manifest and return human-readable issues."""
    issues: List[str] = []
    try:
        manifest = load_plugin_manifest(path)
    except Exception as exc:
        return [str(exc)]

    if not manifest.name:
        issues.append("name is required")
    if not manifest.version:
        issues.append("version is required")

    for collection_name in [
        "tools",
        "commands",
        "providers",
        "permission_rules",
        "context_injectors",
        "event_hooks",
    ]:
        collection = getattr(manifest, collection_name)
        if not isinstance(collection, list):
            issues.append(f"{collection_name} must be a list")

    base_dir = Path(path).expanduser().resolve().parent
    for collection_name in ["tools", "commands", "providers", "context_injectors"]:
        collection = getattr(manifest, collection_name)
        if not isinstance(collection, list):
            continue
        for index, entry in enumerate(collection):
            label = f"{collection_name}[{index}]"
            if not isinstance(entry, dict):
                issues.append(f"{label} must be a dict")
                continue
            for key in ["path", "script", "prompt_file", "schema"]:
                value = entry.get(key)
                if not isinstance(value, str) or not value.strip():
                    continue
                ref = Path(value).expanduser()
                if ref.is_absolute():
                    exists = ref.exists()
                else:
                    exists = (base_dir / ref).exists()
                if not exists:
                    issues.append(f"{label}.{key} points to a missing file: {value}")

    # Validate each event_hook entry shape; surface every problem so users
    # can fix them all in one pass rather than re-running validation.
    from superqode.agent.hooks import ALL_HOOK_POINTS

    for index, entry in enumerate(manifest.event_hooks):
        label = f"event_hooks[{index}]"
        if not isinstance(entry, dict):
            issues.append(f"{label} must be a dict")
            continue
        point = entry.get("point")
        if point not in ALL_HOOK_POINTS:
            issues.append(f"{label}.point {point!r} is not one of {', '.join(ALL_HOOK_POINTS)}")
        handler = entry.get("handler") or entry.get("target")
        if not isinstance(handler, str) or not handler.strip():
            issues.append(f"{label}.handler must be a non-empty string")
        elif ":" not in handler and "." not in handler:
            issues.append(f"{label}.handler {handler!r} must be 'module:func' or 'module.func'")

    return issues
