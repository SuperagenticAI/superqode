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


def _chat_model(model: str) -> bool:
    """Coding and chat models. Embedding, rerank and cloud routes stay out of the picker."""
    from superqode.providers.local.base import is_embedding_model

    if not model or len(model) > 4096 or any(ord(char) < 32 for char in model):
        return False
    if is_embedding_model(model, model):
        return False
    return "cloud" not in model.lower()


def _get_json(url: str, timeout: float = 2):
    request = Request(url, headers={"User-Agent": "SuperQode"}, method="GET")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read(2_000_000))


def _ollama_manifest_root() -> Path:
    override = os.environ.get("OLLAMA_MODELS", "").strip()
    if override:
        return Path(override).expanduser() / "manifests"
    return Path.home() / ".ollama" / "models" / "manifests"


def _lmstudio_model_roots() -> List[Path]:
    return [
        Path.home() / ".lmstudio" / "models",
        Path.home() / ".cache" / "lm-studio" / "models",
    ]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def ollama_advertised_models() -> List[dict]:
    """Models the local Ollama server will run by name.

    Uses the same ``/api/tags`` library as the terminal picker. Loopback only.
    An empty list means the server did not answer, not that the disk is empty.
    """
    for base in ("http://127.0.0.1:11434", "http://localhost:11434"):
        try:
            payload = _get_json(base + "/api/tags")
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            continue
        loaded = set()
        try:
            running = _get_json(base + "/api/ps")
            for item in running.get("models", []) if isinstance(running, dict) else []:
                name = str(item.get("model") or item.get("name") or "").strip()
                if name:
                    loaded.add(name)
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            pass
        rows = []
        for item in payload.get("models", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("model") or item.get("name") or "").strip()
            if not _chat_model(name):
                continue
            size = item.get("size")
            rows.append(
                {
                    "engine": "ollama",
                    "model": name,
                    "name": name,
                    "loaded": name in loaded,
                    "advertised": True,
                    "on_disk": True,
                    "size_gb": round(size / (1024**3), 1)
                    if isinstance(size, (int, float))
                    else None,
                }
            )
        return rows
    return []


def _ollama_name(parts: tuple) -> str:
    # manifests/<registry>/<namespace>/<repository>/<tag>
    if len(parts) < 4:
        return ""
    namespace, tag = parts[1:-1], parts[-1]
    if not tag or any(not piece or piece in {".", ".."} for piece in (*namespace, tag)):
        return ""
    if namespace[:1] == ("library",) and len(namespace) == 2:
        return f"{namespace[1]}:{tag}"
    return "/".join(namespace) + ":" + tag


def ollama_disk_models(limit: int = 200) -> List[dict]:
    """Installed Ollama models from the on-disk manifest library."""
    root = _ollama_manifest_root()
    if root.is_symlink() or not root.is_dir():
        return []
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or not _inside(path, root):
            continue
        try:
            name = _ollama_name(path.relative_to(root).parts)
        except ValueError:
            continue
        if not _chat_model(name):
            continue
        rows.append(
            {
                "engine": "ollama",
                "model": name,
                "name": name,
                "loaded": False,
                "advertised": False,
                "on_disk": True,
                "size_gb": None,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def lmstudio_advertised_models() -> List[dict]:
    """Downloaded LM Studio models reported by its local API, including unloaded ones."""
    from urllib.error import HTTPError as _HTTPError

    from superqode.local.servers import SPECS

    port = SPECS["lmstudio"].default_port
    answered = False
    for path in ("/api/v1/models", "/v1/models"):
        try:
            _get_json(f"http://127.0.0.1:{port}{path}")
            answered = True
            break
        except _HTTPError:
            answered = True
            break
        except (URLError, OSError, ValueError, json.JSONDecodeError):
            continue
    if not answered:
        return []
    try:
        from superqode.local.lmstudio_api import models as lm_models

        listed = lm_models()
    except (OSError, ValueError, URLError):
        return []
    rows = []
    for row in listed:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        if not isinstance(key, str) or not _chat_model(key):
            continue
        size = row.get("size_bytes") or row.get("size")
        rows.append(
            {
                "engine": "lmstudio",
                "model": key,
                "name": key.split("/")[-1] or key,
                "loaded": bool(row.get("loaded_instances")),
                "advertised": True,
                "on_disk": True,
                "size_gb": round(size / (1024**3), 1) if isinstance(size, (int, float)) else None,
                "metadata": row,
            }
        )
    return rows


def _weight_files(directory: Path, root: Path):
    for pattern in ("*.gguf", "*.safetensors"):
        for path in directory.rglob(pattern):
            if path.is_symlink() or not path.is_file() or not _inside(path, root):
                continue
            yield path


def lmstudio_disk_models(limit: int = 200) -> List[dict]:
    """Weights already stored in LM Studio's model directory."""
    rows = []
    seen = set()
    for root in _lmstudio_model_roots():
        if root.is_symlink() or not root.is_dir():
            continue
        publishers = sorted(p for p in root.iterdir() if not p.is_symlink() and p.is_dir())
        for publisher in publishers:
            model_dirs = sorted(m for m in publisher.iterdir() if not m.is_symlink() and m.is_dir())
            for model_dir in model_dirs:
                files = list(_weight_files(model_dir, root))
                gguf = [path for path in files if path.suffix.lower() == ".gguf"]
                keys = (
                    [path.relative_to(root).as_posix() for path in gguf]
                    if gguf
                    else [f"{publisher.name}/{model_dir.name}"]
                    if files
                    else []
                )
                for key in keys:
                    if key in seen or not _chat_model(key):
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "engine": "lmstudio",
                            "model": key,
                            "name": Path(key).name,
                            "loaded": False,
                            "advertised": False,
                            "on_disk": True,
                            "size_gb": None,
                        }
                    )
                    if len(rows) >= limit:
                        return rows
    return rows


def installed_chat_models() -> List[dict]:
    """Ollama and LM Studio chat models already on this Mac.

    A running server is listed first, with the same names the terminal picker
    uses. Models that are only on disk stay selectable so a stopped server does
    not turn into a download prompt.
    """
    import hashlib

    rows = []
    seen = set()
    for row in (
        ollama_advertised_models()
        + ollama_disk_models()
        + lmstudio_advertised_models()
        + lmstudio_disk_models()
    ):
        identity = (row["engine"], row["model"])
        if identity in seen:
            continue
        seen.add(identity)
        digest = hashlib.sha256((row["engine"] + "\n" + row["model"]).encode()).hexdigest()[:24]
        rows.append({**row, "id": digest})
    return rows


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
    "installed_chat_models",
    "inventory_models",
    "list_hf_models",
    "list_lmstudio_models",
    "list_ollama_models",
    "lmstudio_advertised_models",
    "lmstudio_disk_models",
    "ollama_advertised_models",
    "ollama_disk_models",
]
