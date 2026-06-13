"""The hardware-model-engine recommendation matrix.

Loads the shipped ``data/stack_matrix.yaml``, merges a user override from
``~/.superqode/stack_matrix.yaml`` (tiers replace by id), and produces a
ranked recommendation for a detected hardware profile, preferring engines
that are installed and models that are already downloaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .engines import EngineStatus
from .hardware import HardwareProfile
from .inventory import LocalModel

SHIPPED_MATRIX = Path(__file__).parent / "data" / "stack_matrix.yaml"
USER_MATRIX = Path.home() / ".superqode" / "stack_matrix.yaml"


@dataclass
class ModelCandidate:
    name: str
    match: List[str]
    pull: str
    role: str = "main"
    pack: str = ""
    downloaded: Optional[LocalModel] = None


@dataclass
class StackRecommendation:
    tier_id: str
    description: str
    engine: Optional[str] = None  # best installed engine
    engine_ranked: List[str] = field(default_factory=list)
    engines_missing: List[str] = field(default_factory=list)
    models: List[ModelCandidate] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def best_model(self) -> Optional[ModelCandidate]:
        downloaded_main = [m for m in self.models if m.role == "main" and m.downloaded]
        if downloaded_main:
            return downloaded_main[0]
        mains = [m for m in self.models if m.role == "main"]
        return mains[0] if mains else None

    @property
    def utility_model(self) -> Optional[ModelCandidate]:
        utilities = [m for m in self.models if m.role == "utility"]
        downloaded = [m for m in utilities if m.downloaded]
        return (downloaded or utilities or [None])[0]


def _load_yaml(path: Path) -> Dict[str, Any]:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_matrix() -> Dict[str, Any]:
    """Shipped matrix merged with the user's overrides (tiers replace by id)."""
    matrix = _load_yaml(SHIPPED_MATRIX)
    tiers = {t.get("id"): t for t in matrix.get("tiers", []) if isinstance(t, dict)}
    if USER_MATRIX.is_file():
        user = _load_yaml(USER_MATRIX)
        for tier in user.get("tiers", []):
            if isinstance(tier, dict) and tier.get("id"):
                tiers[tier["id"]] = tier
        if user.get("version"):
            matrix["version"] = f"{matrix.get('version', '')} + user overrides"
    matrix["tiers"] = list(tiers.values())
    return matrix


def _find_downloaded(
    candidate_matches: List[str], inventory: List[LocalModel]
) -> Optional[LocalModel]:
    for needle in candidate_matches:
        normalized = needle.lower()
        for model in inventory:
            if normalized in model.model_id.lower():
                return model
    return None


def recommend(
    profile: HardwareProfile,
    engines: Dict[str, EngineStatus],
    inventory: List[LocalModel],
    matrix: Optional[Dict[str, Any]] = None,
) -> StackRecommendation:
    matrix = matrix or load_matrix()
    tier_id = profile.tier
    tier = next((t for t in matrix.get("tiers", []) if t.get("id") == tier_id), None)
    if tier is None:
        tier = {
            "id": tier_id,
            "description": "no matrix entry",
            "engines": [],
            "models": [],
            "notes": [],
        }

    ranked = [str(e) for e in tier.get("engines", [])]
    installed = [e for e in ranked if engines.get(e) and engines[e].installed]
    missing = [e for e in ranked if e not in installed]

    candidates: List[ModelCandidate] = []
    for raw in tier.get("models", []):
        if not isinstance(raw, dict):
            continue
        candidate = ModelCandidate(
            name=str(raw.get("name", "")),
            match=[str(m) for m in raw.get("match", [])],
            pull=str(raw.get("pull", "")),
            role=str(raw.get("role", "main")),
            pack=str(raw.get("pack", "")),
        )
        candidate.downloaded = _find_downloaded(candidate.match, inventory)
        candidates.append(candidate)

    notes = [str(n) for n in tier.get("notes", [])]
    if profile.neural_accelerators:
        notes.insert(
            0,
            "M5 Neural Accelerators active (macOS 26.2+): the MLX path gets ~4x faster prompt processing.",
        )

    return StackRecommendation(
        tier_id=tier_id,
        description=str(tier.get("description", "")),
        engine=installed[0] if installed else None,
        engine_ranked=ranked,
        engines_missing=missing,
        models=candidates,
        notes=notes,
    )


__all__ = ["ModelCandidate", "StackRecommendation", "load_matrix", "recommend", "USER_MATRIX"]
