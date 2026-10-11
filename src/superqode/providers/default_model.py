"""Resolve native model defaults from configured credentials and installed models."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import os
from urllib.request import Request, urlopen

from .credentials import provider_api_key
from .dynamic import resolve_base_url, resolve_provider_def
from .models import get_models_for_provider
from .registry import PROVIDERS, ProviderCategory


@dataclass(frozen=True)
class ModelTarget:
    provider: str
    model: str
    source: str

    def to_dict(self):
        return asdict(self)


def installed_models(provider: str, *, timeout: float = 0.4) -> list[str]:
    """Bounded discovery only; never generate text or load a model."""
    definition = resolve_provider_def(provider)
    if definition is None or definition.category != ProviderCategory.LOCAL:
        return []
    base = resolve_base_url(definition) or definition.default_base_url
    if not base:
        from .local.context_probe import candidate_base_urls

        base = next(iter(candidate_base_urls(provider)), "")
    if not base:
        return []
    base = base.rstrip("/")
    url = (
        base.removesuffix("/v1") + "/api/tags"
        if provider == "ollama"
        else base + ("/models" if base.endswith("/v1") else "/v1/models")
    )
    headers = {"Accept": "application/json"}
    key = provider_api_key(definition)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            return []
        data = json.loads(raw)
        entries = data.get("models", []) if provider == "ollama" else data.get("data", [])
        return list(
            dict.fromkeys(
                str(item.get("name") or item.get("model") or item.get("id"))
                for item in entries
                if isinstance(item, dict)
                and (item.get("name") or item.get("model") or item.get("id"))
            )
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def configured_target(provider: str, model: str | None = None) -> ModelTarget | None:
    definition = resolve_provider_def(provider)
    if definition is None:
        return None
    if definition.category == ProviderCategory.LOCAL:
        available = installed_models(provider)
        if not available or (model and model not in available):
            return None
        return ModelTarget(provider, model or available[0], "installed-local-model")
    if not provider_api_key(definition):
        return None
    choices = get_models_for_provider(provider)
    selected = model or next(iter(choices), None) or next(iter(definition.example_models), None)
    return ModelTarget(provider, selected, "configured-credential") if selected else None


def resolve_default_model(
    provider: str | None = None,
    model: str | None = None,
    *,
    saved_provider: str = "",
    saved_model: str = "",
) -> ModelTarget | None:
    """Explicit values win; implicit defaults must have configuration behind them."""
    provider = provider or os.environ.get("SUPERQODE_PROVIDER")
    model = model or os.environ.get("SUPERQODE_MODEL")
    if model and not provider and "/" in model:
        prefix, rest = model.split("/", 1)
        if resolve_provider_def(prefix):
            provider, model = prefix, rest
    if provider and model:
        return ModelTarget(provider, model, "explicit")
    if provider:
        return configured_target(provider)
    if model:
        return None  # An unqualified explicit model needs an explicit provider.
    if saved_provider and saved_model:
        saved = configured_target(saved_provider, saved_model)
        if saved:
            return ModelTarget(saved.provider, saved.model, "saved-connection")
    for provider_id, definition in PROVIDERS.items():
        if definition.category != ProviderCategory.LOCAL:
            target = configured_target(provider_id)
            if target:
                return target
    for provider_id in ("ollama", "lmstudio", "vllm", "sglang", "ds4", "llamacpp", "mlx"):
        target = configured_target(provider_id)
        if target:
            return target
    return None
