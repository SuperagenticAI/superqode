"""Free and starter-credit inference catalog for developer onboarding.

The goal is not to promise that an offer is permanent. Provider free tiers and
trial credits change often, so each entry carries a verification date, source
URL, and confidence level. The CLI can then be useful offline while still being
honest about freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from .registry import PROVIDERS

AccessMode = Literal["api-key", "account", "acp", "local", "routed"]
OfferKind = Literal["free-tier", "monthly-credits", "free-models", "trial-credits", "local"]
Confidence = Literal["high", "medium", "low"]
LiveSource = Literal["openrouter", "models-dev", "litellm"]


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
LITELLM_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)


@dataclass(frozen=True)
class FreeInferenceOffer:
    """One free or starter-credit inference path SuperQode can surface."""

    provider: str
    name: str
    offer_kind: OfferKind
    access_mode: AccessMode
    summary: str
    setup: str
    env_vars: tuple[str, ...] = ()
    models_hint: tuple[str, ...] = ()
    source_url: str = ""
    last_verified: str = ""
    confidence: Confidence = "medium"
    notes: str = ""
    superqode_command: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "name": self.name,
            "offer_kind": self.offer_kind,
            "access_mode": self.access_mode,
            "summary": self.summary,
            "setup": self.setup,
            "env_vars": list(self.env_vars),
            "models_hint": list(self.models_hint),
            "source_url": self.source_url,
            "last_verified": self.last_verified,
            "confidence": self.confidence,
            "notes": self.notes,
            "superqode_command": self.superqode_command,
        }


@dataclass(frozen=True)
class LiveFreeInferenceCandidate:
    """A free model or zero-price route discovered from a live catalog."""

    source: str
    provider: str
    model: str
    name: str = ""
    context_window: int = 0
    input_price: float = 0.0
    output_price: float = 0.0
    access_mode: AccessMode = "api-key"
    source_url: str = ""
    supports_tools: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "provider": self.provider,
            "model": self.model,
            "name": self.name,
            "context_window": self.context_window,
            "input_price": self.input_price,
            "output_price": self.output_price,
            "access_mode": self.access_mode,
            "source_url": self.source_url,
            "supports_tools": self.supports_tools,
            "notes": self.notes,
        }


OFFERS: tuple[FreeInferenceOffer, ...] = (
    FreeInferenceOffer(
        provider="google",
        name="Google AI Studio / Gemini API",
        offer_kind="free-tier",
        access_mode="api-key",
        summary="Free input/output tokens on selected Gemini API models with AI Studio access.",
        setup="Create an AI Studio API key and export GOOGLE_API_KEY or GEMINI_API_KEY.",
        env_vars=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        models_hint=("gemini-flash-latest", "gemini-3.1-flash-lite"),
        source_url="https://ai.google.dev/gemini-api/docs/pricing",
        last_verified="2026-06-14",
        confidence="high",
        notes="Free-tier data may be used to improve Google products; paid billing changes data-use terms.",
        superqode_command="superqode connect byok google",
    ),
    FreeInferenceOffer(
        provider="huggingface",
        name="Hugging Face Inference Providers",
        offer_kind="monthly-credits",
        access_mode="routed",
        summary="Monthly inference credits route through Hugging Face across many providers.",
        setup="Create a Hugging Face token and export HUGGINGFACE_API_KEY or HF_TOKEN.",
        env_vars=("HUGGINGFACE_API_KEY", "HF_TOKEN"),
        models_hint=("openai/gpt-oss-20b", "Qwen/Qwen3-Coder-30B-A3B-Instruct"),
        source_url="https://huggingface.co/docs/inference-providers/pricing",
        last_verified="2026-06-14",
        confidence="high",
        notes="Credits apply to routed Hugging Face requests, not custom provider keys.",
        superqode_command="superqode models hub qwen3 --gguf",
    ),
    FreeInferenceOffer(
        provider="groq",
        name="GroqCloud",
        offer_kind="free-tier",
        access_mode="api-key",
        summary="Developer API access with published free-tier rate limits for supported fast models.",
        setup="Create a GroqCloud API key and export GROQ_API_KEY.",
        env_vars=("GROQ_API_KEY",),
        models_hint=("llama-3.3-70b-versatile", "openai/gpt-oss-20b"),
        source_url="https://console.groq.com/docs/rate-limits",
        last_verified="2026-06-14",
        confidence="medium",
        notes="Rate limits are account/model dependent and can change without a fixed dollar-credit promise.",
        superqode_command="superqode connect byok groq",
    ),
    FreeInferenceOffer(
        provider="openrouter",
        name="OpenRouter",
        offer_kind="free-models",
        access_mode="api-key",
        summary="Marketplace exposes zero-price/free model routes and a free-models router.",
        setup="Create an OpenRouter API key and export OPENROUTER_API_KEY.",
        env_vars=("OPENROUTER_API_KEY",),
        models_hint=(":free models", "openrouter/auto"),
        source_url="https://openrouter.ai/docs",
        last_verified="2026-06-14",
        confidence="medium",
        notes="Free model availability is dynamic; refresh the model catalog before relying on it.",
        superqode_command="superqode models --provider openrouter --free --refresh",
    ),
    FreeInferenceOffer(
        provider="opencode",
        name="OpenCode ACP free catalog",
        offer_kind="free-models",
        access_mode="acp",
        summary="ACP agents can expose their own free model catalog for SuperQode to discover.",
        setup="Install/configure the ACP agent, then run the free-model discovery command.",
        env_vars=(),
        models_hint=("agent-declared free models",),
        source_url="https://agentclientprotocol.com/",
        last_verified="2026-06-14",
        confidence="medium",
        notes="SuperQode already supports agent-declared [free_models] discovery with fallbacks.",
        superqode_command="superqode agents free-models --refresh",
    ),
    FreeInferenceOffer(
        provider="ollama",
        name="Ollama local models",
        offer_kind="local",
        access_mode="local",
        summary="No hosted inference bill; run downloaded open models on local hardware.",
        setup="Install Ollama, pull a model, then run local doctor to generate a tuned harness.",
        env_vars=(),
        models_hint=("qwen3-coder", "deepseek-coder", "gpt-oss"),
        source_url="https://ollama.com/",
        last_verified="2026-06-14",
        confidence="high",
        notes="Hardware, model license, and quantization determine practical coding performance.",
        superqode_command="superqode local doctor --generate harness.yaml",
    ),
    FreeInferenceOffer(
        provider="mlx",
        name="MLX local server",
        offer_kind="local",
        access_mode="local",
        summary="Apple Silicon local inference via MLX with Hugging Face models.",
        setup="Install the MLX extra, download/pick an MLX model, and start mlx_lm.server.",
        env_vars=(),
        models_hint=("mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",),
        source_url="https://github.com/ml-explore/mlx-lm",
        last_verified="2026-06-14",
        confidence="high",
        notes="Best path for local Apple Silicon coding experiments.",
        superqode_command="superqode providers mlx setup",
    ),
)


def list_free_inference_offers(
    *,
    provider: str | None = None,
    access_mode: AccessMode | None = None,
    offer_kind: OfferKind | None = None,
    configured_only: bool = False,
) -> list[FreeInferenceOffer]:
    """Return matching free/starter-credit inference offers."""
    selected: Iterable[FreeInferenceOffer] = OFFERS
    if provider:
        needle = provider.strip().lower()
        selected = [o for o in selected if o.provider == needle or needle in o.name.lower()]
    if access_mode:
        selected = [o for o in selected if o.access_mode == access_mode]
    if offer_kind:
        selected = [o for o in selected if o.offer_kind == offer_kind]
    if configured_only:
        selected = [o for o in selected if _offer_configured(o)]
    return sorted(selected, key=lambda o: (o.access_mode != "local", o.provider))


def _offer_configured(offer: FreeInferenceOffer) -> bool:
    """Whether the offer is usable without adding an API key."""
    if offer.access_mode in {"local", "acp"} and not offer.env_vars:
        return True
    if not offer.env_vars:
        return False
    import os

    return any(os.environ.get(name) for name in offer.env_vars)


def offer_status(offer: FreeInferenceOffer) -> str:
    """Human-readable setup state for one offer."""
    if _offer_configured(offer):
        return "ready"
    if offer.env_vars:
        return f"set one of: {', '.join(offer.env_vars)}"
    if offer.access_mode == "acp":
        return "install/configure ACP agent"
    return "setup required"


def known_offer_provider_ids() -> set[str]:
    """Provider ids represented by the offer catalog and known registry."""
    return {offer.provider for offer in OFFERS if offer.provider in PROVIDERS or offer.access_mode}


def scan_live_free_candidates(
    *,
    sources: Iterable[LiveSource] | None = None,
    timeout: float = 8.0,
    limit: int = 100,
) -> tuple[list[LiveFreeInferenceCandidate], list[dict[str, str]]]:
    """Query live model/pricing catalogs for zero-price model routes.

    This intentionally discovers *model routes*, not account signup credits.
    Signup-credit balances and trial entitlements are provider-account state and
    generally require authenticated billing APIs, if they exist at all.
    """
    selected = list(sources or ("openrouter", "models-dev", "litellm"))
    candidates: list[LiveFreeInferenceCandidate] = []
    errors: list[dict[str, str]] = []

    for source in selected:
        try:
            if source == "openrouter":
                candidates.extend(_scan_openrouter(timeout=timeout))
            elif source == "models-dev":
                candidates.extend(_scan_models_dev(limit=limit))
            elif source == "litellm":
                candidates.extend(_scan_litellm(timeout=timeout))
        except Exception as exc:
            errors.append({"source": source, "error": str(exc)})

    seen: set[tuple[str, str, str]] = set()
    deduped: list[LiveFreeInferenceCandidate] = []
    for item in candidates:
        key = (item.source, item.provider, item.model)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(key=lambda item: (item.source, item.provider, item.model))
    if limit > 0:
        deduped = deduped[:limit]
    return deduped, errors


def _http_json(url: str, *, timeout: float) -> object:
    import httpx

    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _as_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_zero_price(input_price: object, output_price: object) -> bool:
    return _as_float(input_price) == 0 and _as_float(output_price) == 0


def _scan_openrouter(*, timeout: float) -> list[LiveFreeInferenceCandidate]:
    data = _http_json(OPENROUTER_MODELS_URL, timeout=timeout)
    items = data.get("data", []) if isinstance(data, dict) else []
    out: list[LiveFreeInferenceCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        prompt = pricing.get("prompt")
        completion = pricing.get("completion")
        if not (_is_zero_price(prompt, completion) or model_id.endswith(":free")):
            continue
        provider = model_id.split("/", 1)[0] if "/" in model_id else "openrouter"
        supported = item.get("supported_parameters") or []
        out.append(
            LiveFreeInferenceCandidate(
                source="openrouter",
                provider=provider,
                model=model_id,
                name=str(item.get("name") or model_id),
                context_window=int(item.get("context_length") or 0),
                input_price=_as_float(prompt),
                output_price=_as_float(completion),
                access_mode="api-key",
                source_url=OPENROUTER_MODELS_URL,
                supports_tools="tools" in supported,
                notes="OpenRouter zero-price route; availability and rate limits can change.",
            )
        )
    return out


def _scan_models_dev(*, limit: int) -> list[LiveFreeInferenceCandidate]:
    from .catalog import filter_models, load_models_catalog_cached

    models = filter_models(load_models_catalog_cached(), free=True, limit=limit, sort="provider")
    out: list[LiveFreeInferenceCandidate] = []
    for model in models:
        out.append(
            LiveFreeInferenceCandidate(
                source="models-dev",
                provider=model.provider,
                model=model.id,
                name=model.name,
                context_window=model.context_window,
                input_price=model.input_price,
                output_price=model.output_price,
                access_mode="api-key",
                source_url="https://models.dev/api.json",
                supports_tools=model.supports_tools,
                notes="models.dev cached catalog; run `superqode models --refresh` to update cache.",
            )
        )
    return out


def _scan_litellm(*, timeout: float) -> list[LiveFreeInferenceCandidate]:
    data = _http_json(LITELLM_PRICES_URL, timeout=timeout)
    if not isinstance(data, dict):
        return []
    out: list[LiveFreeInferenceCandidate] = []
    for model_id, item in data.items():
        if not isinstance(item, dict) or not isinstance(model_id, str):
            continue
        input_cost = item.get("input_cost_per_token", item.get("input_cost_per_character"))
        output_cost = item.get("output_cost_per_token", item.get("output_cost_per_character"))
        if not _is_zero_price(input_cost, output_cost):
            continue
        provider = str(item.get("litellm_provider") or model_id.split("/", 1)[0])
        out.append(
            LiveFreeInferenceCandidate(
                source="litellm",
                provider=provider,
                model=model_id,
                name=str(item.get("mode") or model_id),
                context_window=int(item.get("max_input_tokens") or item.get("max_tokens") or 0),
                input_price=0.0,
                output_price=0.0,
                access_mode="api-key",
                source_url=LITELLM_PRICES_URL,
                supports_tools=bool(item.get("supports_function_calling")),
                notes="LiteLLM pricing/context registry entry with zero input/output cost.",
            )
        )
    return out


__all__ = [
    "FreeInferenceOffer",
    "LiveFreeInferenceCandidate",
    "OFFERS",
    "list_free_inference_offers",
    "scan_live_free_candidates",
    "offer_status",
    "known_offer_provider_ids",
]
