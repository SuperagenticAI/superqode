"""
Workspace registry — a persisted list of local repository roots.

Lets a local-first user register several repos (``:workspace add ~/code/foo``)
and then search/read across all of them in one pass, without weakening the
default working-directory write sandbox. Stored as JSON in
``~/.superqode/workspace.json``; only existing directories are returned.

This module deliberately depends on nothing else in superqode so it can be
imported from low-level helpers (e.g. tools.validation) without import cycles.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

WORKSPACE_FILE = Path.home() / ".superqode" / "workspace.json"


def _canonical(path: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path).strip())))


def _load_raw() -> List[str]:
    try:
        data = json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    roots = data.get("roots", []) if isinstance(data, dict) else []
    return [str(r) for r in roots if isinstance(r, str) and r.strip()]


def _save_raw(roots: List[str]) -> None:
    WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACE_FILE.write_text(
        json.dumps({"roots": roots}, indent=2) + "\n", encoding="utf-8"
    )


def list_workspace_roots() -> List[Path]:
    """Registered roots that still exist on disk, de-duplicated, order preserved."""
    out: List[Path] = []
    seen: set[str] = set()
    for raw in _load_raw():
        p = _canonical(raw)
        key = str(p)
        if key in seen:
            continue
        if p.is_dir():
            seen.add(key)
            out.append(p)
    return out


def add_workspace_root(path: str) -> Path:
    """Register a repo root. Returns the canonical path. Raises ValueError if missing."""
    p = _canonical(path)
    if not p.is_dir():
        raise ValueError(f"Not a directory: {p}")
    existing = {str(_canonical(r)) for r in _load_raw()}
    if str(p) not in existing:
        _save_raw(_load_raw() + [str(p)])
    return p


def remove_workspace_root(path: str) -> bool:
    """Unregister a root. Returns True if something was removed."""
    target = str(_canonical(path))
    raw = _load_raw()
    kept = [r for r in raw if str(_canonical(r)) != target]
    if len(kept) != len(raw):
        _save_raw(kept)
        return True
    return False
