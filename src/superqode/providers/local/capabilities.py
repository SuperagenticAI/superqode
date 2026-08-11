"""Runtime-reported capabilities for local models.

Model names are not a capability API. Any allowlist of families or versions is
stale the day a new model ships, and the failure is silent: the model is served
a request with no tools and answers by *describing* the command it would have
run. This module asks the running provider what a model can do and treats a
name-based guess as a last resort that may inform a decision but never veto it.

Providers that cannot answer return ``None`` rather than ``False``, so callers
can distinguish "this model has no tools" from "nobody knows".
"""

import os
from typing import Dict, Optional, Tuple


# Providers whose runtime passes tool definitions straight through to the
# model. These are OpenAI-compatible servers: tool support is a property of the
# server contract, not of any particular model name, so the whole provider is
# recorded here rather than the models it happens to serve today.
TOOL_PASSTHROUGH_PROVIDERS = frozenset(
    {
        "ds4",
        "vllm",
        "sglang",
        "tgi",
        "lmstudio",
        "llamacpp",
        "llama.cpp",
        "mlx",
    }
)

# (provider, model) -> tool support, or None when the runtime could not say.
_CACHE: Dict[Tuple[str, str], Optional[bool]] = {}


def _ollama_declares_tools(model_id: str) -> Optional[bool]:
    """Read tool support out of Ollama's ``/api/show`` capability list."""
    try:
        from superqode.providers.local.ollama import OllamaClient

        show = OllamaClient()._request(
            "POST", "/api/show", data={"name": model_id}, timeout=_timeout()
        )
    except Exception:
        return None
    capabilities = show.get("capabilities") or []
    if not capabilities:
        return None
    return "tools" in capabilities


def _timeout() -> float:
    """Capability probes sit in the request path, so keep them short."""
    raw = os.environ.get("SUPERQODE_CAPABILITY_TIMEOUT", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return 2.0
    return value if value > 0 else 2.0


def declared_tool_support(provider: str, model_id: str) -> Optional[bool]:
    """Return what the runtime says about ``model_id``'s tool support.

    ``True``/``False`` when the provider states it, ``None`` when it cannot.
    Results are cached per process: this runs on the turn path and the answer
    does not change while a model is loaded.
    """
    key = (provider, model_id)
    if key in _CACHE:
        return _CACHE[key]

    result: Optional[bool] = None
    if provider == "ollama":
        result = _ollama_declares_tools(model_id)
    elif provider in TOOL_PASSTHROUGH_PROVIDERS:
        result = True

    _CACHE[key] = result
    return result


def clear_cache() -> None:
    """Forget cached probes (used by tests and after a model is swapped)."""
    _CACHE.clear()
