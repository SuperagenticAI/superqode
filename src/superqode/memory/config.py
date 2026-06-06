"""Configuration helpers for SuperQode memory providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MemoryProviderConfig:
    """Configuration for one memory provider."""

    name: str
    enabled: bool = False
    settings: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


@dataclass(frozen=True)
class MemoryConfig:
    """Project memory configuration."""

    default_provider: str = "local"
    providers: dict[str, MemoryProviderConfig] = field(default_factory=dict)

    def provider(self, name: str) -> MemoryProviderConfig:
        provider_name = (name or "local").strip().lower()
        if provider_name in self.providers:
            return self.providers[provider_name]
        return MemoryProviderConfig(
            name=provider_name,
            enabled=provider_name == "local",
            settings={},
        )


def load_memory_config(project_root: str | Path = ".") -> MemoryConfig:
    """Load the `memory:` section from `superqode.yaml` if present."""
    root = Path(project_root).expanduser().resolve()
    config_path = root / "superqode.yaml"
    raw: dict[str, Any] = {}
    if config_path.exists():
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                raw = loaded.get("memory") or {}
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    default_provider = str(raw.get("default_provider") or "local").strip().lower() or "local"
    providers_raw = raw.get("providers") or {}
    providers: dict[str, MemoryProviderConfig] = {
        "local": MemoryProviderConfig(name="local", enabled=True, settings={}),
        "specmem": MemoryProviderConfig(name="specmem", enabled=bool(raw.get("specmem_enabled", False)), settings={}),
    }

    if isinstance(providers_raw, dict):
        for name, value in providers_raw.items():
            provider_name = str(name).strip().lower()
            if not provider_name:
                continue
            if isinstance(value, dict):
                settings = dict(value)
                enabled = bool(settings.pop("enabled", provider_name == "local"))
            else:
                enabled = bool(value)
                settings = {}
            if provider_name == "local":
                enabled = True
            providers[provider_name] = MemoryProviderConfig(
                name=provider_name,
                enabled=enabled,
                settings=settings,
            )

    return MemoryConfig(default_provider=default_provider, providers=providers)
