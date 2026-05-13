"""Provider and model recommendation helpers for CLI and TUI."""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .models import ModelCapability, ModelInfo, get_all_models, get_model_info
from .registry import PROVIDERS, ProviderCategory, ProviderDef, ProviderTier


TASK_ALIASES = {
    "build": "coding",
    "code": "coding",
    "coding": "coding",
    "debug": "debugging",
    "debugging": "debugging",
    "implement": "coding",
    "review": "review",
    "qe": "testing",
    "test": "testing",
    "testing": "testing",
    "cheap": "budget",
    "budget": "budget",
    "fast": "speed",
    "speed": "speed",
    "local": "local",
    "offline": "local",
    "large": "large-context",
    "large-context": "large-context",
    "reasoning": "reasoning",
    "hard": "reasoning",
}


TASK_REQUIREMENTS = {
    "coding": {"code": True, "tools": True},
    "debugging": {"code": True, "tools": True, "reasoning": True},
    "review": {"code": True, "long_context": True},
    "testing": {"code": True, "tools": True},
    "budget": {"low_cost": True, "tools": True},
    "speed": {"low_cost": True},
    "local": {"local": True, "tools": True, "code": True},
    "large-context": {"long_context": True},
    "reasoning": {"reasoning": True, "code": True},
}


@dataclass(frozen=True)
class ProviderSetupHint:
    """Provider setup state and useful hints."""

    provider: str
    name: str
    configured: bool
    required_env_vars: List[str]
    configured_env_vars: List[str]
    docs_url: str
    setup_hint: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "name": self.name,
            "configured": self.configured,
            "required_env_vars": self.required_env_vars,
            "configured_env_vars": self.configured_env_vars,
            "docs_url": self.docs_url,
            "setup_hint": self.setup_hint,
        }


@dataclass(frozen=True)
class ModelRecommendation:
    """Recommended model with quality labels."""

    provider: str
    provider_name: str
    model: str
    name: str
    task: str
    score: int
    price: str
    context: str
    tool_support: str
    labels: List[str]
    setup: ProviderSetupHint
    reason: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "provider_name": self.provider_name,
            "model": self.model,
            "name": self.name,
            "task": self.task,
            "score": self.score,
            "price": self.price,
            "context": self.context,
            "tool_support": self.tool_support,
            "labels": self.labels,
            "setup": self.setup.to_dict(),
            "reason": self.reason,
        }


def normalize_task(task: str | None) -> str:
    """Normalize user-facing task names."""
    if not task:
        return "coding"
    return TASK_ALIASES.get(task.strip().lower(), task.strip().lower())


def provider_setup_hint(provider_id: str) -> ProviderSetupHint:
    """Return setup status and env hints for a provider."""
    provider = PROVIDERS[provider_id]
    configured = provider.category == ProviderCategory.LOCAL or not provider.env_vars
    configured_vars = []
    for env_var in provider.env_vars:
        if os.environ.get(env_var):
            configured_vars.append(env_var)
            configured = True

    setup_hint = "Ready"
    if provider_id == "ds4":
        base_url = os.environ.get(provider.base_url_env or "", provider.default_base_url or "")
        try:
            with urllib.request.urlopen(f"{base_url.rstrip('/')}/models", timeout=1) as response:
                configured = 200 <= response.status < 300
                setup_hint = (
                    f"Ready at {base_url}" if configured else f"Start ds4-server at {base_url}"
                )
        except Exception:
            configured = False
            setup_hint = f"Start ds4-server at {base_url}"
        return ProviderSetupHint(
            provider=provider_id,
            name=provider.name,
            configured=configured,
            required_env_vars=[],
            configured_env_vars=[],
            docs_url=provider.docs_url,
            setup_hint=setup_hint,
        )

    if not configured and provider.env_vars:
        setup_hint = f"Set {' or '.join(provider.env_vars)}"
    elif provider.base_url_env and not os.environ.get(provider.base_url_env):
        setup_hint = f"Optional: set {provider.base_url_env} for a custom endpoint"

    return ProviderSetupHint(
        provider=provider_id,
        name=provider.name,
        configured=configured,
        required_env_vars=list(provider.env_vars),
        configured_env_vars=configured_vars,
        docs_url=provider.docs_url,
        setup_hint=setup_hint,
    )


def provider_quality_labels(provider: ProviderDef) -> List[str]:
    """Return compact labels for a provider."""
    labels = []
    if provider.tier == ProviderTier.TIER1:
        labels.append("first-class")
    elif provider.tier == ProviderTier.TIER2:
        labels.append("supported")
    elif provider.tier == ProviderTier.LOCAL or provider.category == ProviderCategory.LOCAL:
        labels.append("local")
    if provider.free_models:
        labels.append("free-tier")
    if provider.deployment_mode and provider.deployment_mode not in labels:
        labels.append(provider.deployment_mode)
    return labels


def model_quality_labels(model: ModelInfo) -> List[str]:
    """Return compact labels for a model."""
    labels = []
    if model.supports_tools:
        labels.append("tools")
    if model.is_code_optimized:
        labels.append("code")
    if model.supports_reasoning:
        labels.append("reasoning")
    if model.context_window >= 200_000:
        labels.append("long-context")
    if model.input_price == 0 and model.output_price == 0:
        labels.append("free")
    elif model.input_price <= 1.0 and model.output_price <= 5.0:
        labels.append("low-cost")
    return labels


def _score_model(model: ModelInfo, task: str) -> int:
    requirements = TASK_REQUIREMENTS.get(task, TASK_REQUIREMENTS["coding"])
    score = 0
    if requirements.get("tools") and model.supports_tools:
        score += 25
    if requirements.get("code") and model.is_code_optimized:
        score += 25
    if requirements.get("reasoning") and model.supports_reasoning:
        score += 25
    if requirements.get("long_context") and model.context_window >= 200_000:
        score += 25
    if requirements.get("low_cost"):
        if model.input_price == 0 and model.output_price == 0:
            score += 30
        elif model.input_price <= 1.0 and model.output_price <= 5.0:
            score += 20
    if requirements.get("local") and model.input_price == 0 and model.output_price == 0:
        score += 30
        if model.provider == "ds4":
            score += 20
    if task == "debugging" and "coding" in model.recommended_for:
        score += 15
    if task in model.recommended_for:
        score += 20
    if "coding" in model.recommended_for and task in ("coding", "testing", "review"):
        score += 10
    if model.provider in ("openai", "anthropic", "google"):
        score += 5
    return score


def _reason_for(model: ModelInfo, task: str) -> str:
    labels = model_quality_labels(model)
    if task == "budget":
        return "Low cost with usable coding/tool features."
    if task == "large-context":
        return f"{model.context_display} context for large repositories or long traces."
    if task == "local":
        return "Local/offline coding model with no API billing."
    if task == "debugging":
        return "Tool-capable coding model with stronger reasoning labels for debugging."
    if task == "reasoning":
        return "Strong reasoning and coding labels for harder implementation work."
    if "code" in labels and "tools" in labels:
        return "Code-optimized with tool calling support."
    if "tools" in labels:
        return "Tool calling support with broad provider compatibility."
    return model.description or "Useful fallback model for this task."


def recommend_models(task: str | None = None, limit: int = 8) -> List[ModelRecommendation]:
    """Return ranked model recommendations for a task."""
    normalized = normalize_task(task)
    ranked = sorted(
        get_all_models(), key=lambda model: _score_model(model, normalized), reverse=True
    )
    recommendations = []
    for model in ranked:
        if _score_model(model, normalized) <= 0:
            continue
        provider_def = PROVIDERS.get(model.provider)
        if not provider_def:
            continue
        if normalized == "local" and provider_def.category != ProviderCategory.LOCAL:
            continue
        setup = provider_setup_hint(model.provider)
        labels = provider_quality_labels(provider_def) + model_quality_labels(model)
        recommendations.append(
            ModelRecommendation(
                provider=model.provider,
                provider_name=provider_def.name,
                model=model.id,
                name=model.name,
                task=normalized,
                score=_score_model(model, normalized),
                price=model.price_display,
                context=model.context_display,
                tool_support="yes" if model.supports_tools else "no",
                labels=labels,
                setup=setup,
                reason=_reason_for(model, normalized),
            )
        )
        if len(recommendations) >= limit:
            break
    return recommendations


def provider_model_cards(provider_id: str) -> List[Dict[str, object]]:
    """Return model cards with labels for one provider."""
    provider = PROVIDERS[provider_id]
    cards = []
    for model_id in provider.example_models:
        model = get_model_info(provider_id, model_id)
        if model:
            cards.append(
                {
                    "model": model.id,
                    "name": model.name,
                    "price": model.price_display,
                    "context": model.context_display,
                    "tool_support": model.supports_tools,
                    "labels": model_quality_labels(model),
                    "recommended_for": model.recommended_for,
                }
            )
        else:
            cards.append(
                {
                    "model": model_id,
                    "name": model_id,
                    "price": "unknown",
                    "context": "unknown",
                    "tool_support": "unknown",
                    "labels": [],
                    "recommended_for": [],
                }
            )
    return cards


def provider_doctor_cards(provider_ids: Optional[Iterable[str]] = None) -> List[Dict[str, object]]:
    """Return provider setup and model quality cards."""
    selected = provider_ids or PROVIDERS.keys()
    cards = []
    for provider_id in selected:
        provider = PROVIDERS[provider_id]
        setup = provider_setup_hint(provider_id)
        cards.append(
            {
                "provider": provider_id,
                "name": provider.name,
                "configured": setup.configured,
                "setup_hint": setup.setup_hint,
                "docs_url": provider.docs_url,
                "labels": provider_quality_labels(provider),
                "models": provider_model_cards(provider_id)[:6],
            }
        )
    return cards
