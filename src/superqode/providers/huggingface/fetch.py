"""Modern Hugging Face Hub search + download for local models.

Built on ``huggingface_hub`` (>=1.x): ``HfApi.list_models`` for search,
``snapshot_download(dry_run=True)`` for an exact size preview before committing,
and ``snapshot_download``/``hf_hub_download`` for the actual transfer (resumable,
and accelerated by ``hf_xet`` when installed). This is the user-facing engine
behind ``superqode models hub`` / ``superqode models download``.

Targets:
  * ``ollama``       — download a GGUF file, register it with Ollama (ready to run).
  * ``mlx``          — snapshot an MLX repo (e.g. ``mlx-community/...``) to disk.
  * ``transformers`` — snapshot a full repo for transformers/local inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


class HFNotInstalled(RuntimeError):
    """Raised when huggingface_hub is unavailable."""


def _require_hub():
    try:
        import huggingface_hub  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise HFNotInstalled(
            "huggingface_hub is required. Install with: pip install 'huggingface_hub[hf_xet]'"
        ) from exc


@dataclass
class HubModel:
    """A searchable Hugging Face Hub model entry."""

    id: str
    downloads: int = 0
    likes: int = 0
    library: str = ""
    gated: bool = False
    tags: List[str] = field(default_factory=list)
    pipeline_tag: str = ""

    @property
    def is_gguf(self) -> bool:
        return self.library == "gguf" or any("gguf" in t.lower() for t in self.tags)

    @property
    def is_mlx(self) -> bool:
        return self.id.startswith("mlx-community/") or any("mlx" in t.lower() for t in self.tags)


@dataclass
class SizeEstimate:
    """Result of a dry-run download size check."""

    total_bytes: int
    file_count: int
    cached_bytes: int = 0

    @property
    def to_download_bytes(self) -> int:
        return max(0, self.total_bytes - self.cached_bytes)


def search_hub(
    query: str,
    *,
    kind: Optional[str] = None,
    sort: str = "downloads",
    limit: int = 25,
) -> List[HubModel]:
    """Search the Hub for downloadable models.

    ``kind`` filters the result set: ``gguf`` (Ollama/llama.cpp), ``mlx``
    (Apple Silicon), or ``None`` (text-generation models generally).
    """
    _require_hub()
    from huggingface_hub import HfApi

    api = HfApi()
    kwargs: dict[str, Any] = {"sort": sort, "limit": limit, "full": False}
    if query:
        kwargs["search"] = query
    if kind == "gguf":
        kwargs["filter"] = "gguf"
    elif kind == "mlx":
        # mlx-community hosts the bulk of ready-to-run MLX models.
        kwargs["author"] = "mlx-community"
    else:
        kwargs["pipeline_tag"] = "text-generation"

    out: List[HubModel] = []
    for m in api.list_models(**kwargs):
        tags = list(getattr(m, "tags", []) or [])
        out.append(
            HubModel(
                id=m.id,
                downloads=int(getattr(m, "downloads", 0) or 0),
                likes=int(getattr(m, "likes", 0) or 0),
                library=str(getattr(m, "library_name", "") or ""),
                gated=bool(getattr(m, "gated", False)),
                tags=tags,
                pipeline_tag=str(getattr(m, "pipeline_tag", "") or ""),
            )
        )
    return out


def estimate_size(
    repo_id: str,
    *,
    allow_patterns: Optional[List[str]] = None,
    token: Optional[str] = None,
) -> Optional[SizeEstimate]:
    """Return the download size via a dry run, or ``None`` if unavailable."""
    _require_hub()
    from huggingface_hub import snapshot_download

    try:
        infos = snapshot_download(
            repo_id,
            allow_patterns=allow_patterns,
            token=token,
            dry_run=True,
        )
    except TypeError:
        # Older hub without dry_run — size preview not available.
        return None
    except Exception:
        return None

    total = 0
    cached = 0
    count = 0
    for info in infos or []:
        # huggingface_hub DryRunFileInfo: file_size / is_cached / will_download.
        size = int(getattr(info, "file_size", None) or getattr(info, "size", 0) or 0)
        total += size
        count += 1
        will_download = getattr(info, "will_download", getattr(info, "would_download", True))
        if getattr(info, "is_cached", False) or not will_download:
            cached += size
    return SizeEstimate(total_bytes=total, file_count=count, cached_bytes=cached)


def list_gguf_files(repo_id: str, *, token: Optional[str] = None) -> List[str]:
    """List GGUF filenames in a repo."""
    _require_hub()
    from huggingface_hub import HfApi

    files = HfApi().list_repo_files(repo_id, token=token)
    return [f for f in files if f.lower().endswith(".gguf")]


def pick_gguf_file(repo_id: str, quant: str, *, token: Optional[str] = None) -> Optional[str]:
    """Choose the GGUF file matching ``quant`` (case-insensitive), else the first."""
    files = list_gguf_files(repo_id, token=token)
    if not files:
        return None
    q = (quant or "").lower()
    for f in files:
        if q and q in f.lower():
            return f
    return files[0]


def download_file(
    repo_id: str,
    filename: str,
    *,
    target_dir: Optional[Path] = None,
    token: Optional[str] = None,
) -> Path:
    """Download a single file (e.g. a GGUF). Progress shown by huggingface_hub."""
    _require_hub()
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        repo_id,
        filename,
        local_dir=str(target_dir) if target_dir else None,
        token=token,
    )
    return Path(path)


def download_repo(
    repo_id: str,
    *,
    target_dir: Optional[Path] = None,
    allow_patterns: Optional[List[str]] = None,
    token: Optional[str] = None,
) -> Path:
    """Snapshot an entire repo to disk (resumable, hf_xet-accelerated)."""
    _require_hub()
    from huggingface_hub import snapshot_download

    path = snapshot_download(
        repo_id,
        allow_patterns=allow_patterns,
        local_dir=str(target_dir) if target_dir else None,
        token=token,
    )
    return Path(path)


def detect_target(model: Optional[HubModel], repo_id: str, *, token: Optional[str] = None) -> str:
    """Best-guess download target: 'ollama' (GGUF), 'mlx', or 'transformers'."""
    if model is not None:
        if model.is_gguf:
            return "ollama"
        if model.is_mlx:
            return "mlx"
    if repo_id.startswith("mlx-community/"):
        return "mlx"
    try:
        if list_gguf_files(repo_id, token=token):
            return "ollama"
    except Exception:
        pass
    return "transformers"


def hf_xet_available() -> bool:
    try:
        import hf_xet  # noqa: F401

        return True
    except ImportError:
        return False


# Files an MLX model actually needs — skip GGUF and other formats so an
# MLX download stays small.
MLX_ALLOW_PATTERNS = [
    "*.json",
    "model*.safetensors",
    "*.safetensors",
    "tokenizer*",
    "*.model",
    "*.tiktoken",
    "*.txt",
    "*.jinja",
    "*.py",
]


@dataclass
class CachedRepo:
    """A repo in the local Hugging Face cache."""

    repo_id: str
    size_bytes: int
    nb_files: int
    last_accessed: float
    path: str

    @property
    def size_display(self) -> str:
        n = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
            n /= 1024
        return f"{n:.1f}TB"


def scan_cache() -> List[CachedRepo]:
    """List models in the local HF cache (largest first)."""
    _require_hub()
    from huggingface_hub import scan_cache_dir

    try:
        info = scan_cache_dir()
    except Exception:
        return []
    repos = [
        CachedRepo(
            repo_id=r.repo_id,
            size_bytes=r.size_on_disk,
            nb_files=r.nb_files,
            last_accessed=float(getattr(r, "last_accessed", 0) or 0),
            path=str(r.repo_path),
        )
        for r in info.repos
    ]
    repos.sort(key=lambda r: r.size_bytes, reverse=True)
    return repos


def delete_cached(pattern: str) -> Tuple[int, int]:
    """Delete cached repos whose id contains ``pattern`` (case-insensitive).

    Returns ``(repos_deleted, bytes_freed)``. Uses HF's revision deletion so
    only the matching repos' blobs are removed.
    """
    _require_hub()
    from huggingface_hub import scan_cache_dir

    info = scan_cache_dir()
    needle = pattern.lower()
    revisions = []
    freed = 0
    count = 0
    for repo in info.repos:
        if needle in repo.repo_id.lower():
            for rev in repo.revisions:
                revisions.append(rev.commit_hash)
            freed += repo.size_on_disk
            count += 1
    if revisions:
        info.delete_revisions(*revisions).execute()
    return count, freed


__all__ = [
    "HFNotInstalled",
    "HubModel",
    "SizeEstimate",
    "CachedRepo",
    "MLX_ALLOW_PATTERNS",
    "search_hub",
    "estimate_size",
    "list_gguf_files",
    "pick_gguf_file",
    "download_file",
    "download_repo",
    "detect_target",
    "scan_cache",
    "delete_cached",
    "hf_xet_available",
]
