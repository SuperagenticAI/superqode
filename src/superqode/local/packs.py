"""Model policy packs: tuned defaults per open-model family, shipped as data.

A pack is one YAML file naming a model family, the substrings that identify
it, and the policy knobs that make it behave well in an agent loop (prompt
level, tool-call format, temperature, history budget). Packs ship in
``data/model-packs/`` and users can add or replace them by dropping files in
``~/.superqode/model-packs/`` (same schema; a file with the same ``name``
wins).

Harness specs reference a pack with ``model_policy.pack: gemma4``; without
an explicit reference the pack is auto-detected from the model id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SHIPPED_PACKS_DIR = Path(__file__).parent / "data" / "model-packs"
USER_PACKS_DIR = Path.home() / ".superqode" / "model-packs"


@dataclass(frozen=True)
class ModelPack:
    name: str
    description: str = ""
    match: tuple = ()
    policy: Dict[str, Any] = field(default_factory=dict)
    notes: tuple = ()


def _load_pack_file(path: Path) -> Optional[ModelPack]:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("name"):
        return None
    policy = data.get("policy")
    return ModelPack(
        name=str(data["name"]).strip().lower(),
        description=str(data.get("description", "")),
        match=tuple(str(m).lower() for m in data.get("match", [])),
        policy=dict(policy) if isinstance(policy, dict) else {},
        notes=tuple(str(n) for n in data.get("notes", [])),
    )


def load_packs() -> Dict[str, ModelPack]:
    """All packs by name; user packs override shipped packs with the same name."""
    packs: Dict[str, ModelPack] = {}
    for directory in (SHIPPED_PACKS_DIR, USER_PACKS_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            pack = _load_pack_file(path)
            if pack is not None:
                packs[pack.name] = pack
    return packs


def get_pack(name: str) -> Optional[ModelPack]:
    return load_packs().get(name.strip().lower())


def detect_pack(model_text: str) -> Optional[ModelPack]:
    """The pack whose match substrings appear in a model/provider string.

    Longest match wins so "qwen3-coder" beats "qwen3".
    """
    normalized = model_text.replace("_", "-").lower()
    best: Optional[ModelPack] = None
    best_len = 0
    for pack in load_packs().values():
        for needle in pack.match:
            if needle in normalized and len(needle) > best_len:
                best = pack
                best_len = len(needle)
    return best


def list_packs() -> List[ModelPack]:
    return sorted(load_packs().values(), key=lambda p: p.name)


__all__ = [
    "ModelPack",
    "SHIPPED_PACKS_DIR",
    "USER_PACKS_DIR",
    "detect_pack",
    "get_pack",
    "list_packs",
    "load_packs",
]
