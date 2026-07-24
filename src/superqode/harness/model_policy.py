"""Harness-level model policy resolution.

The provider gateway still owns request-level shaping, but the harness layer
needs one explicit place to decide which prompt level, tool surface, and
iteration budgets fit a model family.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..agent.system_prompts import SystemPromptLevel
from .spec import HarnessFlavor, HarnessSpec


@dataclass(frozen=True)
class EffectiveModelPolicy:
    """Resolved model behavior knobs for one harness run."""

    profile: str
    family: str
    temperature: float | None = None
    system_level: SystemPromptLevel = SystemPromptLevel.FULL
    tool_profile: str | None = None
    tool_call_format: str | None = None
    reasoning: str | None = None
    parallel_tools: bool = True
    # 0 or negative => unlimited (loop until the model stops calling tools).
    # Positive => safety cap.
    max_iterations: int = 0
    session_history_limit: int = 20


def resolve_harness_model_policy(
    spec: HarnessSpec,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> EffectiveModelPolicy:
    """Resolve the effective model policy for a harness run.

    Explicit ``spec.model_policy.profile`` wins. If it is absent, provider,
    model, and route labels are used to select local-optimized defaults.
    Model policy packs (``model_policy.pack``, or auto-detected from the
    model id) layer family-tuned defaults on top of the base profile, and
    ``model_policy.config`` overrides everything else.
    """
    profile = _select_profile(spec, provider=provider, model=model)
    policy = _base_policy(spec, profile)
    policy = _apply_pack(policy, spec, provider=provider, model=model)
    return _apply_config_overrides(policy, spec.model_policy.config)


def _select_profile(spec: HarnessSpec, *, provider: str | None, model: str | None) -> str:
    explicit = (spec.model_policy.profile or "").strip().lower()
    if explicit:
        return explicit

    haystack = " ".join(
        item
        for item in (
            provider,
            model,
            spec.model_policy.primary,
            *spec.model_policy.fallbacks,
            spec.model_policy.local_hardware,
            spec.model_policy.tool_call_format,
        )
        if item
    ).lower()

    if spec.flavor == HarnessFlavor.NO_TOOL:
        if _mentions_modern_gemma(haystack):
            return "gemma4-no-tool"
        return "no-tool"
    if _mentions_laguna(haystack):
        return "laguna-coding"
    if _mentions_ds4(haystack):
        return "ds4-coding"
    if _mentions_modern_gemma(haystack):
        return "gemma4-coding"
    return "coding"


def _base_policy(spec: HarnessSpec, profile: str) -> EffectiveModelPolicy:
    temperature = spec.model_policy.temperature
    tool_call_format = spec.model_policy.tool_call_format

    if spec.flavor == HarnessFlavor.NO_TOOL:
        family = "gemma4" if "gemma4" in profile or "gemma-4" in profile else "model-only"
        return EffectiveModelPolicy(
            profile=profile,
            family=family,
            temperature=temperature if temperature is not None else 0.2,
            system_level=SystemPromptLevel.NO_TOOL,
            tool_profile="none",
            tool_call_format=tool_call_format,
            reasoning=spec.model_policy.reasoning or "off",
            parallel_tools=False,
            max_iterations=0,
            session_history_limit=8,
        )

    if profile in {"laguna-coding", "laguna"}:
        return EffectiveModelPolicy(
            profile=profile,
            family="laguna",
            # Poolside's native sampled default is part of Laguna's reasoning
            # recipe. Leave it unset unless the harness explicitly chooses one.
            temperature=temperature,
            system_level=SystemPromptLevel.MINIMAL,
            tool_profile="ds4",
            tool_call_format=tool_call_format or "compact-json",
            reasoning=spec.model_policy.reasoning,
            parallel_tools=False,
            max_iterations=0,
            session_history_limit=20,
        )

    if profile in {"ds4-coding", "ds4-fast-local", "ds4"}:
        return EffectiveModelPolicy(
            profile=profile,
            family="ds4",
            temperature=temperature if temperature is not None else 0.2,
            system_level=SystemPromptLevel.MINIMAL,
            tool_profile="ds4",
            tool_call_format=tool_call_format or "compact-json",
            reasoning=spec.model_policy.reasoning or "low",
            parallel_tools=False,
            max_iterations=0,
            session_history_limit=10 if profile == "ds4-fast-local" else 12,
        )

    if profile in {"gemma4-coding", "gemma4", "gemma-4"}:
        return EffectiveModelPolicy(
            profile=profile,
            family="gemma4",
            temperature=temperature if temperature is not None else 0.2,
            system_level=SystemPromptLevel.MINIMAL,
            tool_profile="ds4",
            tool_call_format=tool_call_format or "strict-json",
            reasoning=spec.model_policy.reasoning,
            parallel_tools=False,
            max_iterations=0,
            session_history_limit=12,
        )

    return EffectiveModelPolicy(
        profile=profile or "coding",
        family="general",
        temperature=temperature,
        system_level=SystemPromptLevel.FULL,
        tool_profile=None,
        tool_call_format=tool_call_format,
        reasoning=spec.model_policy.reasoning,
        parallel_tools=True,
        max_iterations=0,
        session_history_limit=20,
    )


def _apply_pack(
    policy: EffectiveModelPolicy,
    spec: HarnessSpec,
    *,
    provider: str | None,
    model: str | None,
) -> EffectiveModelPolicy:
    """Layer a model policy pack's tuned defaults onto the base policy.

    An explicit ``model_policy.pack`` always applies; otherwise the pack is
    auto-detected from the model id. Scalar fields the spec sets explicitly
    (temperature, tool_call_format, reasoning) are not overridden by a pack.
    """
    from ..local.packs import detect_pack, get_pack

    pack = None
    explicit = (spec.model_policy.pack or "").strip().lower()
    if explicit:
        pack = get_pack(explicit)
    else:
        haystack = " ".join(
            item
            for item in (provider, model, spec.model_policy.primary, *spec.model_policy.fallbacks)
            if item
        )
        if haystack:
            pack = detect_pack(haystack)
    if pack is None or not pack.policy:
        return policy

    overrides = dict(pack.policy)
    if spec.model_policy.temperature is not None:
        overrides.pop("temperature", None)
    if spec.model_policy.tool_call_format:
        overrides.pop("tool_call_format", None)
    if spec.model_policy.reasoning:
        overrides.pop("reasoning", None)
    if spec.flavor == HarnessFlavor.NO_TOOL:
        # The no-tool contract (NO_TOOL prompt, no tool surface, reasoning
        # off) is part of the flavor, not something a model-family pack may
        # re-enable.
        for key in (
            "system_level",
            "system_prompt_level",
            "tool_profile",
            "tool_call_format",
            "parallel_tools",
            "reasoning",
            "reasoning_effort",
        ):
            overrides.pop(key, None)
    return _apply_config_overrides(policy, overrides)


def _apply_config_overrides(
    policy: EffectiveModelPolicy,
    config: dict[str, Any],
) -> EffectiveModelPolicy:
    if not config:
        return policy

    values: dict[str, Any] = {}
    if "temperature" in config:
        values["temperature"] = _optional_float(config["temperature"])
    if "system_level" in config:
        values["system_level"] = SystemPromptLevel(str(config["system_level"]).strip().lower())
    if "system_prompt_level" in config:
        values["system_level"] = SystemPromptLevel(
            str(config["system_prompt_level"]).strip().lower()
        )
    if "tool_profile" in config:
        values["tool_profile"] = str(config["tool_profile"]).strip().lower() or None
    if "tool_call_format" in config:
        values["tool_call_format"] = str(config["tool_call_format"]).strip().lower() or None
    if "reasoning" in config:
        values["reasoning"] = str(config["reasoning"]).strip().lower() or None
    if "reasoning_effort" in config:
        values["reasoning"] = str(config["reasoning_effort"]).strip().lower() or None
    if "parallel_tools" in config:
        values["parallel_tools"] = bool(config["parallel_tools"])
    if "max_iterations" in config:
        values["max_iterations"] = int(config["max_iterations"])
    if "session_history_limit" in config:
        values["session_history_limit"] = int(config["session_history_limit"])

    return EffectiveModelPolicy(**{**policy.__dict__, **values})


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _mentions_ds4(text: str) -> bool:
    return "ds4" in text or "dwarfstar" in text or "deepseek-v4" in text


def _mentions_laguna(text: str) -> bool:
    normalized = text.replace("_", "-")
    return "laguna-s-2.1" in normalized or "laguna-s2.1" in normalized


def _mentions_modern_gemma(text: str) -> bool:
    """Match the tool-capable Gemma family (Gemma 3 / Gemma 4).

    Both route to the Gemma-optimized profile (MINIMAL system prompt, strict-JSON
    tool calls). Gemma 1/2 are excluded — they don't reliably tool-call.
    """
    normalized = text.replace("_", "-").replace(" ", "-")
    return any(v in normalized for v in ("gemma4", "gemma-4", "gemma3", "gemma-3"))
