"""Provider/model reference parsing helpers.

Most SuperQode surfaces accept ``provider/model``. Hugging Face Inference
Provider routes add one wrinkle: the model itself is a Hub repo id containing
``/`` plus an optional ``:provider`` suffix, and fast-agent commonly writes the
provider as ``hf.<repo>``.
"""

from __future__ import annotations

from dataclasses import dataclass


HUGGINGFACE_PROVIDER = "huggingface"
HF_PROVIDER_ALIASES = {"hf", "huggingface"}


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str


def normalize_provider_id(provider: str | None) -> str:
    value = (provider or "").strip()
    if value.lower() in HF_PROVIDER_ALIASES:
        return HUGGINGFACE_PROVIDER
    return value


def normalize_model_for_provider(provider: str | None, model: str | None) -> str:
    value = (model or "").strip()
    if normalize_provider_id(provider) != HUGGINGFACE_PROVIDER:
        return value
    return normalize_huggingface_model(value)


def normalize_huggingface_model(model: str | None) -> str:
    value = (model or "").strip()
    lower = value.lower()
    for prefix in ("hf.", "hf/", "huggingface/"):
        if lower.startswith(prefix):
            return value[len(prefix) :]
    return value


def split_provider_model_ref(raw: str | None, default_provider: str = "") -> ModelSpec:
    """Split a route string into provider/model, honoring HF shorthand.

    Examples:
      - ``hf.zai-org/GLM-5.2:fireworks-ai`` -> ``huggingface``, ``zai-org/...``
      - ``hf/zai-org/GLM-5.2:fireworks-ai`` -> ``huggingface``, ``zai-org/...``
      - ``huggingface/zai-org/GLM-5.2:fireworks-ai`` -> ``huggingface``, ``zai-org/...``
      - ``openai/gpt-5`` -> ``openai``, ``gpt-5``
      - ``gpt-5`` with default ``openai`` -> ``openai``, ``gpt-5``
    """
    value = (raw or "").strip()
    default = normalize_provider_id(default_provider)
    if not value:
        return ModelSpec(default, "")

    if value.lower().startswith("hf."):
        return ModelSpec(HUGGINGFACE_PROVIDER, normalize_huggingface_model(value))

    if "/" in value:
        provider, model = value.split("/", 1)
        provider = normalize_provider_id(provider)
        return ModelSpec(provider, normalize_model_for_provider(provider, model))

    return ModelSpec(default, normalize_model_for_provider(default, value))


def split_hf_provider_suffix(model: str | None) -> tuple[str, str | None]:
    normalized = normalize_huggingface_model(model)
    if ":" not in normalized:
        return normalized, None
    base, suffix = normalized.rsplit(":", 1)
    if not base:
        return normalized, None
    return base, suffix or None
