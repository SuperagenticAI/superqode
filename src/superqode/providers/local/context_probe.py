"""
Detect the *real loaded* context window of a local model server.

The number that matters for a local model is not its model-card maximum but the
window the server actually loaded it with (Ollama `num_ctx`, llama.cpp `--ctx`,
vLLM `--max-model-len`, LM Studio's loaded context). Overflowing that window is
catastrophic on local models, so we probe the live server and feed the result
into adaptive compaction.

Each backend reports the loaded window on a different endpoint:
  - Ollama      GET /api/ps             -> models[].context_length
  - llama.cpp   GET /props              -> default_generation_settings.n_ctx
  - LM Studio   GET /api/v1/models      -> data[].loaded_context_length
  - vLLM/DS4/…  GET /v1/models          -> data[].max_model_len | context_length

This module is dependency-light (urllib in a thread) and best-effort: any
failure returns None so the caller can fall back conservatively.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import List, Optional, Tuple

PROBE_TIMEOUT = 2.0
# Sane floor/ceiling so a bogus reading can't wreck compaction.
MIN_SANE_WINDOW = 512
MAX_SANE_WINDOW = 2_000_000


def candidate_base_urls(provider: str) -> List[str]:
    """Likely base URLs for a local provider, honoring its env override."""
    provider = (provider or "").lower()
    urls: List[str] = []

    def add(*vals: Optional[str]) -> None:
        for v in vals:
            if v:
                u = v.rstrip("/")
                # Strip a trailing /v1 so we can try sibling endpoints too.
                if u.endswith("/v1"):
                    u = u[:-3]
                if u not in urls:
                    urls.append(u)

    if "ollama" in provider:
        add(os.environ.get("OLLAMA_HOST"), "http://localhost:11434")
    elif "lmstudio" in provider or "lm-studio" in provider or "lm_studio" in provider:
        add(os.environ.get("LMSTUDIO_HOST"), "http://localhost:1234")
    elif "ds4" in provider or "dwarfstar" in provider:
        add(os.environ.get("DS4_HOST"), "http://127.0.0.1:8000")
    elif "vllm" in provider:
        add(os.environ.get("VLLM_HOST"), "http://localhost:8000")
    elif "sglang" in provider:
        add(os.environ.get("SGLANG_HOST"), "http://localhost:30000")
    elif "mlx" in provider:
        add(os.environ.get("MLX_HOST"), "http://localhost:8080", "http://localhost:8081")
    elif "tgi" in provider:
        add(os.environ.get("TGI_HOST"), "http://localhost:8080")
    else:  # llamacpp / openai_compatible / unknown local
        add(
            os.environ.get("OPENAI_BASE_URL"),
            os.environ.get("LOCAL_LLM_HOST"),
            "http://localhost:8080",
            "http://localhost:8000",
        )
    return urls


def _sane(value) -> Optional[int]:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if MIN_SANE_WINDOW <= n <= MAX_SANE_WINDOW:
        return n
    return None


def _http_get_json(url: str, timeout: float) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (local only)
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _model_matches(entry_id: str, model_id: Optional[str]) -> bool:
    if not model_id:
        return True
    a, b = str(entry_id or "").lower(), str(model_id).lower()
    return a == b or a in b or b in a


def _parse_ollama_ps(data: dict, model_id: Optional[str]) -> Optional[int]:
    for m in data.get("models", []) or []:
        if _model_matches(m.get("name") or m.get("model", ""), model_id):
            win = _sane(m.get("context_length") or m.get("context"))
            if win:
                return win
    return None


def _parse_llamacpp_props(data: dict, _model_id: Optional[str]) -> Optional[int]:
    gen = data.get("default_generation_settings") or {}
    return _sane(gen.get("n_ctx") or data.get("n_ctx"))


def _parse_models_list(data: dict, model_id: Optional[str]) -> Optional[int]:
    """OpenAI-style /v1/models or LM Studio /api/v1/models entries."""
    entries = data.get("data", data if isinstance(data, list) else [])
    if isinstance(entries, dict):
        entries = entries.get("data", [])
    best = None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        win = _sane(
            entry.get("loaded_context_length")
            or entry.get("max_context_length")
            or entry.get("max_model_len")
            or entry.get("context_length")
            or entry.get("context_window")
            or ((entry.get("top_provider") or {}).get("context_length"))
        )
        if win and _model_matches(entry.get("id", ""), model_id):
            return win
        if win and best is None:
            best = win
    return best


# Endpoint -> parser, ordered so loaded-window sources win over model maxima.
_PROBE_SEQUENCE = (
    ("/api/ps", _parse_ollama_ps),
    ("/props", _parse_llamacpp_props),
    ("/api/v1/models", _parse_models_list),
    ("/v1/models", _parse_models_list),
)


async def probe_base_url(
    base_url: str, model_id: Optional[str] = None, timeout: float = PROBE_TIMEOUT
) -> Optional[Tuple[int, str]]:
    """Return (loaded_window, endpoint) for one base URL, or None."""
    for path, parser in _PROBE_SEQUENCE:
        data = await asyncio.to_thread(_http_get_json, base_url + path, timeout)
        if not data:
            continue
        try:
            win = parser(data, model_id)
        except Exception:
            win = None
        if win:
            return win, path
    return None


async def resolve_local_context_window(
    provider: str, model: str, timeout: float = PROBE_TIMEOUT
) -> Optional[Tuple[int, str]]:
    """Probe a local provider's candidate URLs for the real loaded window.

    Returns ``(window, endpoint)`` or ``None`` if nothing answered.
    """
    for base in candidate_base_urls(provider):
        result = await probe_base_url(base, model, timeout)
        if result:
            return result
    return None
