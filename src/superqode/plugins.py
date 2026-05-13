"""Plugin manifest loading for SuperQode extensions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def load_plugin_manifest(path: str | Path) -> PluginManifest:
    """Load a single plugin manifest."""
    manifest_path = Path(path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return PluginManifest.from_dict(data, path=manifest_path)


def load_plugins(root: str | Path = ".") -> List[PluginManifest]:
    """Load all discoverable plugin manifests."""
    plugins: List[PluginManifest] = []
    for path in discover_plugin_manifests(root):
        plugins.append(load_plugin_manifest(path))
    return plugins


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

    return issues
