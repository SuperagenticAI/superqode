"""Local HarnessSpec registry for sharing validated specs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .loader import harness_spec_to_dict, load_harness_spec

DEFAULT_REGISTRY_DIR = Path.home() / ".superqode" / "harness-registry"


def registry_root(root: str | Path | None = None) -> Path:
    return Path(root).expanduser() if root else DEFAULT_REGISTRY_DIR


def publish_harness_spec(
    spec_path: str | Path,
    *,
    root: str | Path | None = None,
    name: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    spec_path = Path(spec_path).expanduser()
    spec = load_harness_spec(spec_path)
    item_name = _safe_name(name or spec.name)
    target_dir = registry_root(root) / item_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "harness.yaml"
    if target.exists() and not force:
        raise FileExistsError(f"Registry entry already exists: {item_name}")
    shutil.copyfile(spec_path, target)
    manifest = {
        "name": item_name,
        "harness": spec.name,
        "source": str(spec_path),
        "spec": str(target),
        "inherits": spec.inherits or "",
        "flavor": spec.flavor.value,
        "runtime": spec.runtime.backend,
        "model": spec.model_policy.primary or "",
        "metadata": spec.metadata,
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def list_registry_specs(*, root: str | Path | None = None) -> list[dict[str, Any]]:
    base = registry_root(root)
    if not base.is_dir():
        return []
    entries = []
    for manifest_path in sorted(base.glob("*/manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["manifest"] = str(manifest_path)
            entries.append(data)
        except Exception:
            continue
    return entries


def install_registry_spec(
    name: str,
    output: str | Path,
    *,
    root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    item_name = _safe_name(name)
    manifest_path = registry_root(root) / item_name / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Unknown harness registry entry: {name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = Path(manifest["spec"])
    target = Path(output).expanduser()
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {**manifest, "installed_to": str(target)}


def registry_manifest_for_spec(spec_path: str | Path) -> dict[str, Any]:
    spec = load_harness_spec(spec_path)
    return {
        "name": spec.name,
        "resolved_spec": harness_spec_to_dict(spec),
    }


def _safe_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in name.strip())
    safe = safe.strip("-._")
    if not safe:
        raise ValueError("Registry name cannot be empty")
    return safe
