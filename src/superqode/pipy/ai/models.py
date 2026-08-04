"""Resolving a model descriptor for a run.

pi carries a large generated model catalog. PiPy does not duplicate it: the
provider and model come from whatever SuperQode already resolved, and only the
few fields the loop actually uses are filled in here.
"""

from __future__ import annotations

from ..stream import Model

#: Provider ids whose models accept a reasoning or thinking level. Used only to
#: decide whether to send the parameter, never to decide what to send.
_REASONING_PROVIDERS = frozenset({"anthropic", "openai", "google", "xai", "deepseek"})

#: Which wire API a provider speaks, for the ``api`` field pi records on every
#: assistant message.
_PROVIDER_APIS: dict[str, str] = {
    "anthropic": "anthropic-messages",
    "openai": "openai-completions",
    "google": "google-generative-ai",
    "ollama": "openai-completions",
    "openrouter": "openai-completions",
}


def lookup_context_window(provider: str, model_id: str) -> int:
    """Ask SuperQode's model catalog how much context a model accepts.

    Returns zero when the model is unknown, which leaves automatic compaction
    off rather than compacting against a guessed limit.
    """
    try:
        from superqode.providers.models import get_model_info
    except Exception:  # noqa: BLE001 - the catalog is optional here
        return 0
    try:
        info = get_model_info(provider, model_id)
    except Exception:  # noqa: BLE001 - unknown model is not an error
        return 0
    return int(getattr(info, "context_window", 0) or 0)


def resolve_model(
    model_id: str,
    provider: str = "",
    *,
    api: str | None = None,
    supports_reasoning: bool | None = None,
    context_window: int | None = None,
) -> Model:
    """Build the descriptor a run is sent with.

    ``model_id`` may carry a ``provider/model`` prefix, which SuperQode uses
    throughout; the prefix wins when no explicit provider is given.
    """
    resolved_provider = provider
    resolved_id = model_id
    if "/" in model_id and not provider:
        resolved_provider, resolved_id = model_id.split("/", 1)

    normalized = resolved_provider.strip().lower()
    return Model(
        id=resolved_id,
        provider=normalized,
        api=api or _PROVIDER_APIS.get(normalized, "openai-completions"),
        supports_reasoning=(
            normalized in _REASONING_PROVIDERS if supports_reasoning is None else supports_reasoning
        ),
        context_window=(
            lookup_context_window(normalized, resolved_id)
            if context_window is None
            else context_window
        ),
    )


__all__ = ["lookup_context_window", "resolve_model"]
