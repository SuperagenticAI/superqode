"""Read-only inspection of ``~/.fx/settings.json`` custom providers.

SuperQode never writes or rewrites Fx settings. Doctor and status helpers may
detect configured custom connection names so users know path B is available.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_FX_SETTINGS = Path.home() / ".fx" / "settings.json"


def read_fx_custom_providers(
    settings_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a structured, read-only summary of Fx custom providers.

    Never raises for missing/malformed files; returns ``ok=False`` instead.
    """
    path = Path(settings_path) if settings_path else DEFAULT_FX_SETTINGS
    result: dict[str, Any] = {
        "ok": False,
        "path": str(path),
        "exists": path.exists(),
        "provider_names": [],
        "selected_provider": "",
        "error": "",
    }
    if not path.exists():
        result["error"] = "settings file not found"
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["error"] = f"unreadable settings: {exc}"
        return result
    if not isinstance(data, dict):
        result["error"] = "settings root must be a JSON object"
        return result

    providers = data.get("providers")
    names: list[str] = []
    if isinstance(providers, dict):
        for name, entry in providers.items():
            if not isinstance(name, str) or not name.strip():
                continue
            # Built-in reserved names are still "providers" entries when the
            # user defines openai-chat-completions connections; report all keys.
            if isinstance(entry, dict) and entry.get("protocol") == "openai-chat-completions":
                names.append(name.strip())
            elif isinstance(entry, dict) and entry.get("base_url"):
                names.append(name.strip())
    selected = str(data.get("provider") or "").strip()
    result.update(
        {
            "ok": True,
            "provider_names": sorted(names),
            "selected_provider": selected,
            "error": "",
        }
    )
    return result


def describe_fx_custom_providers(
    settings_path: Path | str | None = None,
) -> str:
    """One-line human hint for CLI/TUI doctor output."""
    info = read_fx_custom_providers(settings_path)
    if not info.get("exists"):
        return ""
    if not info.get("ok"):
        return f"fx settings unreadable ({info.get('error') or 'unknown error'})"
    names = list(info.get("provider_names") or [])
    if not names:
        return "fx settings present; no custom openai-chat-completions providers"
    selected = str(info.get("selected_provider") or "").strip()
    listed = ", ".join(names)
    if selected and selected in names:
        return f"fx custom providers: {listed} (selected: {selected})"
    return f"fx custom providers: {listed}"


__all__ = [
    "DEFAULT_FX_SETTINGS",
    "describe_fx_custom_providers",
    "read_fx_custom_providers",
]
