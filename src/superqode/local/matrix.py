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
    source: str = ""
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


# Coarse memory rank per tier, so we can say whether a model "fits" the user's
# hardware: a model fits if the smallest tier it is recommended for needs no
# more memory than the user has.
_TIER_RANK = {
    "cpu": 0,
    "apple_16": 1,
    "nvidia_16": 1,
    "apple_32": 2,
    "nvidia_24": 2,
    "apple_64": 3,
    "nvidia_48": 3,
    "apple_128": 4,
}


_QUANT_BYTES = [
    (r"\b(2bit|q2)\b", 0.34),
    (r"\b(3bit|q3)\b", 0.45),
    (r"\b(4bit|q4|int4|awq|gptq)\b", 0.58),
    (r"\b(5bit|q5)\b", 0.68),
    (r"\b(6bit|q6)\b", 0.78),
    (r"\b(8bit|q8|int8|fp8)\b", 1.05),
    (r"\b(fp16|bf16|f16)\b", 2.0),
    (r"\b(fp32|f32)\b", 4.0),
]


def estimate_model_memory_gb(label: str, *, quantized_default: bool = True) -> Optional[float]:
    """Rough RAM estimate (GB) for a model from its name.

    Parses the largest parameter count (``30B``, ``9B``, ``0.5B``) and the
    quantization (``4bit``, ``Q4``, ``fp8``, ``bf16`` ...). For MoE models the
    TOTAL params drive memory, so we take the largest count. Returns ``None``
    when the name carries no parameter count. This is deliberately approximate.
    """
    import re

    if not label:
        return None
    low = label.lower()
    nums = [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)\s*b(?!it)\b", low)]
    params = max([n for n in nums if 0 < n <= 2000], default=None)
    if not params:
        return None
    bytes_per_param = None
    for pattern, value in _QUANT_BYTES:
        if re.search(pattern, low):
            bytes_per_param = value
            break
    if bytes_per_param is None:
        bytes_per_param = 0.58 if quantized_default else 2.0
    return round(params * bytes_per_param, 1)


def memory_fit_phrase(est_gb: Optional[float], ram_gb: Optional[float]) -> str:
    """A short, honest fit verdict comparing an estimate to available RAM."""
    if est_gb is None:
        return "size unknown"
    size = f"~{est_gb:g} GB"
    if not ram_gb:
        return size
    if est_gb <= 0.6 * ram_gb:
        return f"{size} · likely fits"
    if est_gb <= 0.85 * ram_gb:
        return f"{size} · should fit"
    if est_gb <= ram_gb:
        return f"{size} · tight, may not fit with context"
    return f"{size} · likely too large for {ram_gb:g} GB"


def _engine_from_pull(pull: str) -> str:
    """Human label for which engine a pull command targets."""
    p = (pull or "").lower()
    if p.startswith("ollama "):
        return "ollama"
    if "huggingface-cli" in p or p.startswith("hf ") or "hf download" in p:
        return "mlx / hf"
    if p.startswith("lms ") or "lm studio" in p or "lmstudio" in p:
        return "lmstudio"
    if "llama-server" in p or ".gguf" in p:
        return "llama.cpp"
    return pull.split()[0] if pull else "?"


def _core_key(name: str) -> str:
    """Normalized model key for matching across catalog and Hub names.

    Drops a trailing parenthetical and quant words, then strips separators:
    "Qwen3-Coder 30B-A3B (FP8)" -> "qwen3coder30ba3b".
    """
    import re

    base = re.split(r"[(\[]", name, maxsplit=1)[0]
    base = re.sub(
        r"\b(\d+bit|q\d_?\w*|fp8|fp16|bf16|int4|int8|awq|gptq|mlx|gguf|instruct|it|chat)\b",
        " ",
        base,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[^a-z0-9]", "", base.lower())


def augment_commands_with_hub(hits: List["ModelSearchHit"], hub_models: list) -> None:
    """Attach matching MLX/GGUF get-commands (from the Hub) to curated hits.

    Mutates each hit's ``commands`` so a model lists every engine it can run on
    (Ollama from the catalog, MLX + GGUF from trusted Hub publishers), instead
    of only the one command the catalog stored.
    """
    if not hub_models:
        return
    # Index Hub models by core key, keeping the most-downloaded per format.
    by_key: Dict[str, dict] = {}
    for m in hub_models:
        key = _core_key(m.id.split("/", 1)[-1])
        fmt = (
            "mlx"
            if getattr(m, "is_mlx", False)
            else ("gguf" if getattr(m, "is_gguf", False) else "")
        )
        if not fmt:
            continue
        slot = by_key.setdefault(key, {})
        cur = slot.get(fmt)
        if cur is None or getattr(m, "downloads", 0) > getattr(cur, "downloads", 0):
            slot[fmt] = m

    for hit in hits:
        hk = _core_key(hit.name)
        if not hk:
            continue
        match = None
        for key, slot in by_key.items():
            if hk and (hk in key or key in hk):
                match = slot
                break
        if not match:
            continue
        existing = {e.lower() for e, _ in hit.commands}
        extra = []
        gguf = match.get("gguf")
        mlx = match.get("mlx")
        # Real, native provider commands, with verified syntax:
        #  * llama-server -hf <user>/<repo>   (llama.cpp --hf-repo; quant defaults to Q4_K_M)
        #  * lms get <full HF URL>            (lms get takes a name or the full URL)
        #  * hf download <repo>               (current HF CLI; huggingface-cli is deprecated)
        # The repo ids themselves come from the live Hugging Face API.
        if gguf is not None:
            if "llama.cpp" not in existing:
                extra.append(("llama.cpp", f"llama-server -hf {gguf.id}"))
            if "lm studio" not in existing:
                extra.append(("LM Studio", f"lms get https://huggingface.co/{gguf.id}"))
        if mlx is not None and "mlx" not in existing:
            extra.append(("MLX", f"hf download {mlx.id}"))
        hit.commands = list(hit.commands) + extra
        # Repo for the convenience "superqode models download" alternative.
        hit.hub_repo = (mlx.id if mlx is not None else gguf.id) if (mlx or gguf) else None


@dataclass
class ModelSearchHit:
    """A trusted-catalog model matching a search, with how to get it."""

    name: str
    role: str
    sources: List[str]
    packs: List[str]
    tiers: List[str]
    commands: List[tuple]  # (engine_label, pull_command)
    downloaded_as: Optional[str]
    fits: bool
    est_memory_gb: Optional[float] = None
    hub_repo: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "sources": self.sources,
            "packs": self.packs,
            "tiers": self.tiers,
            "commands": [{"engine": e, "command": c} for e, c in self.commands],
            "downloaded_as": self.downloaded_as,
            "fits": self.fits,
            "est_memory_gb": self.est_memory_gb,
            "hub_repo": self.hub_repo,
            "superqode_download": (
                f"superqode models download {self.hub_repo}" if self.hub_repo else None
            ),
        }


def search_models(
    query: str,
    *,
    tier: Optional[str] = None,
    inventory: Optional[List[LocalModel]] = None,
) -> List[ModelSearchHit]:
    """Search the trusted stack matrix for models matching ``query``.

    Returns one hit per logical model, merged across tiers/engines, annotated
    with the get-commands, whether it is already downloaded, and whether it
    fits the user's hardware ``tier``.
    """
    if inventory is None:
        try:
            from .inventory import inventory_models

            inventory = inventory_models()
        except Exception:
            inventory = []

    q = (query or "").strip().lower()
    matrix = load_matrix()
    user_rank = _TIER_RANK.get(tier or "", 99)

    grouped: Dict[str, dict] = {}
    for tier_def in matrix.get("tiers", []):
        if not isinstance(tier_def, dict):
            continue
        tid = str(tier_def.get("id", ""))
        trank = _TIER_RANK.get(tid, 99)
        for raw in tier_def.get("models", []):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", ""))
            match = [str(m) for m in raw.get("match", [])]
            haystack = (name + " " + " ".join(match)).lower()
            if q and q not in haystack:
                continue
            g = grouped.setdefault(
                name,
                {
                    "role": str(raw.get("role", "main")),
                    "sources": set(),
                    "packs": set(),
                    "tiers": set(),
                    "commands": {},
                    "match": set(),
                    "min_rank": 99,
                },
            )
            if raw.get("source"):
                g["sources"].add(str(raw["source"]))
            if raw.get("pack"):
                g["packs"].add(str(raw["pack"]))
            g["tiers"].add(tid)
            g["min_rank"] = min(g["min_rank"], trank)
            g["match"].update(m.lower() for m in match)
            pull = str(raw.get("pull", ""))
            # huggingface-cli is deprecated and no longer runs; normalize any
            # (shipped or user-override) catalog command to the current `hf` CLI.
            pull = pull.replace("huggingface-cli download", "hf download")
            if pull:
                g["commands"].setdefault(_engine_from_pull(pull), pull)

    results: List[ModelSearchHit] = []
    for name, g in grouped.items():
        downloaded = _find_downloaded(list(g["match"]), inventory)
        results.append(
            ModelSearchHit(
                name=name,
                role=g["role"],
                sources=sorted(g["sources"]),
                packs=sorted(g["packs"]),
                tiers=sorted(g["tiers"], key=lambda t: _TIER_RANK.get(t, 99)),
                commands=sorted(g["commands"].items()),
                downloaded_as=(downloaded.bare_id if downloaded else None),
                fits=(g["min_rank"] <= user_rank) if tier else True,
                est_memory_gb=estimate_model_memory_gb(name, quantized_default=True),
            )
        )

    # Already-downloaded first, then models that fit, then by name.
    results.sort(key=lambda r: (r.downloaded_as is None, not r.fits, r.name.lower()))
    return results


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
            source=str(raw.get("source", "")),
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


__all__ = [
    "ModelCandidate",
    "ModelSearchHit",
    "StackRecommendation",
    "estimate_model_memory_gb",
    "load_matrix",
    "memory_fit_phrase",
    "recommend",
    "search_models",
    "USER_MATRIX",
]
