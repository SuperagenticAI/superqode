"""Project trust state for local SuperQode workspaces.

Trust is stored outside the project by default so a repository cannot mark
itself trusted by committing a file. Tests and portable setups can override
the store with ``SUPERQODE_TRUST_STORE``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

TRUST_STORE_ENV = "SUPERQODE_TRUST_STORE"


@dataclass(frozen=True)
class ProjectTrust:
    """Trust record for one project path."""

    path: str
    trusted: bool
    trusted_at: str = ""
    note: str = ""


def canonical_project_path(path: str | Path = ".") -> str:
    """Return a stable absolute project path."""
    return str(Path(path).expanduser().resolve())


def trust_store_path() -> Path:
    """Return the per-user trust store path."""
    override = os.environ.get(TRUST_STORE_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".superqode" / "trust.json"


def project_key(path: str | Path = ".") -> str:
    """Hash a canonical path for compact trust-store keys."""
    canonical = canonical_project_path(path)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _load_store() -> dict[str, Any]:
    path = trust_store_path()
    if not path.exists():
        return {"version": 1, "projects": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "projects": {}}
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    return {"version": 1, "projects": projects}


def _save_store(data: dict[str, Any]) -> None:
    path = trust_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_project_trust(path: str | Path = ".") -> ProjectTrust:
    """Return current trust state for a project path."""
    canonical = canonical_project_path(path)
    record = _load_store().get("projects", {}).get(project_key(canonical), {})
    if not isinstance(record, dict):
        record = {}
    return ProjectTrust(
        path=canonical,
        trusted=bool(record.get("trusted")),
        trusted_at=str(record.get("trusted_at") or ""),
        note=str(record.get("note") or ""),
    )


def set_project_trust(path: str | Path = ".", trusted: bool = True, note: str = "") -> ProjectTrust:
    """Persist trust state for a project path."""
    canonical = canonical_project_path(path)
    data = _load_store()
    projects = data.setdefault("projects", {})
    projects[project_key(canonical)] = {
        "path": canonical,
        "trusted": bool(trusted),
        "trusted_at": datetime.now().isoformat(timespec="seconds") if trusted else "",
        "note": note,
    }
    _save_store(data)
    return get_project_trust(canonical)


def project_risk_signals(path: str | Path = ".") -> list[str]:
    """Return project-local features that can execute code or connect tools."""
    root = Path(path).expanduser().resolve()
    signals: list[str] = []
    if (root / ".superqode" / "plugins").exists():
        signals.append(".superqode/plugins")
    if (root / ".agents" / "plugins").exists():
        signals.append(".agents/plugins")
    if (root / ".superqode" / "mcp.json").exists():
        signals.append(".superqode/mcp.json")
    if (root / ".mcp.json").exists():
        signals.append(".mcp.json")
    if (root / ".superqode" / "hooks.json").exists():
        signals.append(".superqode/hooks.json")
    return signals


def is_project_trusted(path: str | Path = ".") -> bool:
    """Return True when the project is trusted by the local user."""
    return get_project_trust(path).trusted
