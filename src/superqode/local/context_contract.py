"""Shared approximate context and working-set contract for local inference."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

# Verified Ollama artifacts, November 2026. Largest published size per tag.
# MoE memory uses total weights, never the active parameter count.
STARTERS = {
    "qwen3.5:4b": (4, 4.0),
    "qwen3.5:9b": (9, 7.6),
    "devstral-small-2:24b": (24, 15.0),
    "qwen3.6:27b": (27, 19.0),
    "qwen3.6:35b": (35, 23.0),
    "qwen3-coder-next:q4_K_M": (80, 52.0),
}

LM_STARTERS = {
    "qwen/qwen3.5-4b": "qwen3.5:4b",
    "qwen/qwen3.5-9b": "qwen3.5:9b",
    "qwen/qwen3.6-27b": "qwen3.6:27b",
    "qwen/qwen3.6-35b-a3b": "qwen3.6:35b",
}


def memory_fit(
    model, ram_gb, context=8192, *, weights_gb=None, metadata=None, kv_cache="q8_0", apple=True
):
    """Include weights, KV cache, buffers and headroom, all in approximate GiB.

    The Metal working-set budget is estimated at 70 percent of unified memory.
    Unknown architectures get a conservative dense-attention estimate rather
    than assumed hybrid savings. Ratings are guidance, not measured tests.
    """
    from .matrix import estimate_model_memory_gb

    metadata = metadata or {}
    known = STARTERS.get(LM_STARTERS.get(model, model))
    weights = (
        weights_gb
        if weights_gb is not None
        else (known[1] if known else estimate_model_memory_gb(model))
    )
    budget = float(ram_gb or 0) * (0.70 if apple else 0.85)
    if weights is None or not budget:
        return {
            "rating": "Unknown",
            "verdict": "Unknown size or memory budget",
            "likely_fits": False,
            "budget_gb": round(budget, 2),
            "estimate_gb": None,
        }
    element = {"q8_0": 1.125, "q4_0": 0.625}.get(kv_cache, 2.0)
    layers = metadata.get("num_hidden_layers") or metadata.get("block_count")
    heads = metadata.get("num_key_value_heads") or metadata.get("head_count_kv")
    dim = metadata.get("head_dim") or metadata.get("key_length")
    if not dim and metadata.get("hidden_size") and metadata.get("num_attention_heads"):
        dim = metadata["hidden_size"] / metadata["num_attention_heads"]
    if all(isinstance(v, (int, float)) and v > 0 for v in (layers, heads, dim)):
        kv = 2 * layers * heads * dim * context * element / 1024**3
        source = "architecture metadata"
    else:
        scale = max(1.0, math.sqrt(float(known[0] if known else weights / 0.58) / 9))
        kv = context * 128 * 1024 * scale * element / 2 / 1024**3
        source = "conservative estimate (architecture unknown)"
    buffers = max(0.75, weights * 0.06)
    headroom = max(1.0, float(ram_gb) * 0.03)
    total = weights + kv + buffers + headroom
    rating = "Fits" if total <= budget * 0.90 else "Tight" if total <= budget else "Too large"
    return {
        "rating": rating,
        "verdict": f"{rating} · about {total:.1f} GB including context",
        "likely_fits": rating == "Fits",
        "estimate_gb": round(total, 2),
        "weights_gb": round(weights, 2),
        "kv_gb": round(kv, 2),
        "buffers_gb": round(buffers, 2),
        "headroom_gb": round(headroom, 2),
        "budget_gb": round(budget, 2),
        "memory_gb": ram_gb,
        "kv_source": source,
        "note": "Approximate working-set budget; other apps and runtime behavior can change fit.",
    }


@dataclass(frozen=True)
class ContextContract:
    context: int
    max_tokens: int
    kv_cache: str
    fit: dict
    source: str = "hardware suggestion"


def choose_contract(
    model,
    hardware=None,
    *,
    context=None,
    provider="ollama",
    metadata=None,
    weights_gb=None,
    kv_cache=None,
):
    from .hardware import detect_hardware
    from .guardrails import build_guardrails

    hw = hardware or detect_hardware()
    ram = hw.available_memory_gb
    cap = build_guardrails(hw).recommended_context_cap
    target = min(int(context or (8192 if not ram or ram < 32 else 16384)), cap)
    model_cap = (metadata or {}).get("max_context_length")
    if type(model_cap) is int and model_cap >= 512:
        target = min(target, model_cap)
    target = max(512, min(target, 262144))
    cache = (
        kv_cache
        if kv_cache and kv_cache != "auto"
        else ("q8_0" if provider == "ollama" else "auto")
    )
    kwargs = {
        "kv_cache": cache,
        "apple": hw.is_apple_silicon,
        "metadata": metadata,
        "weights_gb": weights_gb,
    }
    fit = memory_fit(model, ram, target, **kwargs)
    while target > 4096 and fit["rating"] != "Fits":
        target //= 2
        fit = memory_fit(model, ram, target, **kwargs)
    return ContextContract(target, min(4096, max(128, target // 4)), cache, fit)


def _contract_path(provider, model):
    key = hashlib.sha256((provider + "\n" + model).encode()).hexdigest()
    return Path.home() / ".superqode" / "local-context" / (key + ".json")


def save_contract(provider, model, contract):
    """Per-model atomic files work across the desktop's worker processes."""
    path = _contract_path(provider, model)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(asdict(contract), stream)
        temporary = stream.name
    os.replace(temporary, path)


def requested_context(provider, model):
    try:
        value = json.loads(_contract_path(provider, model).read_text())["context"]
        if type(value) is int and 512 <= value <= 262144:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return choose_contract(model, provider=provider).context


def output_limit(provider, model):
    try:
        value = json.loads(_contract_path(provider, model).read_text())["max_tokens"]
        if type(value) is int and 128 <= value <= 65536:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return choose_contract(model, provider=provider).max_tokens


def effective_context(provider, model, actual=None):
    requested = requested_context(provider, model)
    return min(requested, actual) if actual else requested


def estimate_tokens(messages, tools=None):
    """Conservative UTF-8 heuristic, including structured content and schemas.

    Not a tokenizer. UTF-8 bytes avoid the non-Latin undercount of chars/4.
    guard_request reserves an additional 256-token margin for framing.
    """
    size = len(json.dumps(messages, ensure_ascii=False, default=str).encode("utf-8"))
    if tools:
        size += len(json.dumps(tools, ensure_ascii=False, default=str).encode("utf-8"))
    return math.ceil(size / 3) + 8 * len(messages) + (16 if tools else 0)


def guard_request(messages, tools, context, max_tokens=None):
    """Return kept indices and clamped output; remove only complete old turns.

    Preserve systems and the newest user/tool turn. Never mutate history or
    orphan tool results. Oversized newest turns get clear advice before send.
    """
    if type(max_tokens) is not int or max_tokens <= 0:
        max_tokens = 2048
    kept = list(range(len(messages)))
    reserve = min(max_tokens or 2048, max(128, context // 4))
    while estimate_tokens([messages[i] for i in kept], tools) + reserve + 256 > context:
        users = [n for n, i in enumerate(kept) if messages[i].get("role") == "user"]
        if len(users) < 2:
            break
        start, end = users[0], users[1]
        kept = [
            i
            for n, i in enumerate(kept)
            if not start <= n < end or messages[i].get("role") in {"system", "developer"}
        ]
    prompt = estimate_tokens([messages[i] for i in kept], tools)
    remaining = context - prompt - 256
    if remaining < 128:
        raise ValueError(
            "Local model context is full, including tool schemas. Start a new thread, "
            "shorten the prompt or use fewer tools. Nothing was sent."
        )
    return kept, min(max_tokens or 2048, remaining)
