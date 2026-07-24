"""Shared Laguna S 2.1 model metadata and local GGUF resolution.

Laguna's official Q4_K_M GGUF can be loaded by both DwarfStar and llama.cpp.
Keep the artifact location independent from either engine so users download the
~68 GB file once and switch runtimes without copying it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

LAGUNA_MODEL_ID = "laguna-s-2.1"
LAGUNA_CHAT_MODEL_ID = "laguna-s-2.1-chat"
LAGUNA_HF_REPO = "poolside/Laguna-S-2.1-GGUF"
LAGUNA_GGUF_FILENAME = "laguna-s-2.1-Q4_K_M.gguf"
LAGUNA_CONTEXT_WINDOW = 262_144
LAGUNA_SAFE_CONTEXT = 32_768
LAGUNA_DS4_REF = "laguna-s2.1"

_LAGUNA_ALIASES = {
    "laguna",
    LAGUNA_MODEL_ID,
    LAGUNA_CHAT_MODEL_ID,
    LAGUNA_GGUF_FILENAME.lower(),
    f"{LAGUNA_HF_REPO}:q4_k_m".lower(),
    f"hf.co/{LAGUNA_HF_REPO}:q4_k_m".lower(),
}


def default_laguna_gguf() -> Path:
    """Return the preferred existing GGUF, with the legacy path as fallback."""
    configured = os.environ.get("SUPERQODE_LAGUNA_GGUF", "").strip()
    if configured:
        return Path(configured).expanduser()
    cached = huggingface_cached_laguna_gguf()
    if cached is not None:
        return cached
    # Backward compatibility for downloads made with the original documented
    # ``--local-dir`` command. New downloads use Hugging Face's normal cache.
    return Path.home() / "models" / LAGUNA_MODEL_ID / LAGUNA_GGUF_FILENAME


def huggingface_cached_laguna_gguf() -> Optional[Path]:
    """Return Poolside's GGUF from the standard Hugging Face cache, offline."""
    try:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(
            repo_id=LAGUNA_HF_REPO,
            filename=LAGUNA_GGUF_FILENAME,
        )
    except (ImportError, OSError, ValueError):
        return None
    if not isinstance(cached, str):
        return None
    path = Path(cached)
    return path if path.is_file() else None


def is_laguna_model(value: str | Path | None) -> bool:
    """Whether an id, repo reference, or filesystem path denotes Laguna."""
    if value is None:
        return False
    normalized = str(value).strip().replace("_", "-").lower()
    if normalized in _LAGUNA_ALIASES:
        return True
    return "laguna-s-2.1" in normalized or normalized.endswith("/laguna-s-2.1")


def resolve_laguna_gguf(value: str | Path | None) -> Optional[Path]:
    """Resolve a Laguna alias/path to the single shared GGUF.

    Existing explicit paths always win. Known aliases resolve through an
    explicit ``SUPERQODE_LAGUNA_GGUF``, Hugging Face's standard cache, then the
    legacy ``~/models`` location. Returns ``None`` when the value is not Laguna
    or the shared file is absent.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    explicit = Path(raw).expanduser()
    if explicit.is_file():
        return explicit
    if not is_laguna_model(raw):
        return None
    candidate = default_laguna_gguf()
    return candidate if candidate.is_file() else None


def laguna_download_command() -> str:
    """Return the standard-cache Hugging Face CLI command shown in errors/docs."""
    return f"hf download {LAGUNA_HF_REPO} {LAGUNA_GGUF_FILENAME}"


__all__ = [
    "LAGUNA_CHAT_MODEL_ID",
    "LAGUNA_CONTEXT_WINDOW",
    "LAGUNA_DS4_REF",
    "LAGUNA_GGUF_FILENAME",
    "LAGUNA_HF_REPO",
    "LAGUNA_MODEL_ID",
    "LAGUNA_SAFE_CONTEXT",
    "default_laguna_gguf",
    "huggingface_cached_laguna_gguf",
    "is_laguna_model",
    "laguna_download_command",
    "resolve_laguna_gguf",
]
