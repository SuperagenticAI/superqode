"""Inventory of models already downloaded on this machine.

Sources: the Ollama API (tags and loaded models), the Hugging Face hub
cache (including mlx-community artifacts), and the LM Studio models
directory. Recommendations prefer models the user already has, because the
best model is often the one that needs no 20GB download.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROBE_TIMEOUT = 1.5


@dataclass
class LocalModel:
    model_id: str  # e.g. "ollama:gemma4:12b-mlx" or "hf:mlx-community/gemma-4-12B-it-4bit"
    source: str  # ollama | hf | lmstudio
    size_gb: Optional[float] = None
    loaded: bool = False  # currently resident in an engine

    @property
    def bare_id(self) -> str:
        return self.model_id.split(":", 1)[1] if ":" in self.model_id else self.model_id


def _ollama_base() -> str:
    base = os.environ.get("OLLAMA_HOST", "").strip() or "http://localhost:11434"
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


def _ollama_models(path: str) -> List[dict]:
    try:
        request = Request(
            f"{_ollama_base()}{path}", headers={"User-Agent": "SuperQode"}, method="GET"
        )
        with urlopen(request, timeout=PROBE_TIMEOUT) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return []
    models = payload.get("models", []) if isinstance(payload, dict) else []
    return [m for m in models if isinstance(m, dict)]


def list_ollama_models() -> List[LocalModel]:
    loaded_names = set()
    for item in _ollama_models("/api/ps"):
        name = str(item.get("model") or item.get("name") or "").strip()
        if name:
            loaded_names.add(name)
    out: List[LocalModel] = []
    for item in _ollama_models("/api/tags"):
        name = str(item.get("model") or item.get("name") or "").strip()
        if not name:
            continue
        size = item.get("size")
        out.append(
            LocalModel(
                model_id=f"ollama:{name}",
                source="ollama",
                size_gb=round(size / (1024**3), 1) if isinstance(size, (int, float)) else None,
                loaded=name in loaded_names,
            )
        )
    return out


def _hf_cache_root() -> Path:
    from .storage import cache_directory

    return cache_directory()


def _cache_dir_model_id(entry: Path) -> str:
    # models--org--name -> org/name
    raw = entry.name[len("models--") :]
    return raw.replace("--", "/", 1)


def _cache_has_weights(entry: Path) -> bool:
    snapshots = entry / "snapshots"
    if snapshots.is_symlink() or not snapshots.is_dir():
        return False
    for snap in snapshots.iterdir():
        if snap.is_symlink() or not snap.is_dir():
            continue
        for pattern in ("*.safetensors", "*.gguf", "*.npz"):
            if any(snap.glob(pattern)):
                return True
    return False


def _dir_size_gb(entry: Path) -> Optional[float]:
    # Cache entries can contain user-created links to protected folders. Never
    # recurse into those directories or stat external file targets for inventory.
    try:
        if entry.is_symlink():
            return None
        total = 0
        seen = set()
        pending = [entry]
        while pending:
            directory = pending.pop()
            for path in directory.iterdir():
                # Check the link itself before asking for any target metadata.
                if path.is_symlink():
                    continue
                if path.is_dir():
                    pending.append(path)
                elif path.is_file():
                    info = path.stat()
                    identity = (info.st_dev, info.st_ino)
                    if identity not in seen:
                        total += info.st_size
                        seen.add(identity)
        return round(total / (1024**3), 1)
    except OSError:
        return None


def list_hf_models(limit: int = 200) -> List[LocalModel]:
    root = _hf_cache_root()
    if not root.is_dir():
        return []
    out: List[LocalModel] = []
    for entry in sorted(root.glob("models--*")):
        if entry.is_symlink() or not entry.is_dir() or not _cache_has_weights(entry):
            continue
        model_id = _cache_dir_model_id(entry)
        out.append(
            LocalModel(
                model_id=f"hf:{model_id}",
                source="hf",
                size_gb=_dir_size_gb(entry),
            )
        )
        if len(out) >= limit:
            break
    return out


def _lmstudio_models_root() -> Optional[Path]:
    for candidate in (
        Path.home() / ".lmstudio" / "models",
        Path.home() / ".cache" / "lm-studio" / "models",
    ):
        if not candidate.is_symlink() and candidate.is_dir():
            return candidate
    return None


def list_lmstudio_models(limit: int = 200) -> List[LocalModel]:
    root = _lmstudio_models_root()
    if root is None:
        return []
    out: List[LocalModel] = []
    # LM Studio lays out models as <publisher>/<model>/<files>
    for publisher in sorted(p for p in root.iterdir() if not p.is_symlink() and p.is_dir()):
        for model_dir in sorted(
            m for m in publisher.iterdir() if not m.is_symlink() and m.is_dir()
        ):
            out.append(
                LocalModel(
                    model_id=f"lmstudio:{publisher.name}/{model_dir.name}",
                    source="lmstudio",
                    size_gb=_dir_size_gb(model_dir),
                )
            )
            if len(out) >= limit:
                return out
    return out


def inventory_models() -> List[LocalModel]:
    """All locally available models, deduplicated, Ollama first."""
    seen = set()
    out: List[LocalModel] = []
    for model in list_ollama_models() + list_hf_models() + list_lmstudio_models():
        if model.model_id in seen:
            continue
        seen.add(model.model_id)
        out.append(model)
    return out


__all__ = [
    "LocalModel",
    "inventory_models",
    "list_hf_models",
    "list_lmstudio_models",
    "list_ollama_models",
]
