"""Model profiles — per-provider / per-model tuning for the agent loop.

A `ModelProfile` is a small declarative bundle that says "when running against
this provider or model, do these things":

- Append `system_prompt_suffix` to the assembled system prompt.
- Hide `excluded_tools` from the tool set the model sees.
- Layer `init_kwargs` (and optionally `init_kwargs_factory()`) into the
  gateway request kwargs.
- Run `pre_init(spec)` once before the first model call (e.g. version
  validation, env-var sanity checks).

Profiles are registered under either a bare provider key (``"anthropic"``,
applies to every model from that provider) or a full ``provider:model`` key
(``"anthropic:claude-sonnet-4-6"``, applies to that one model). On lookup,
the exact-model entry is layered on top of the provider entry — both
contribute, and the exact-model fields win on conflicts.

Provider and exact-model profiles are collapsed into a single struct because
SuperQode does not split model-construction from runtime behavior.

Example:
    >>> from superqode.providers.profiles import ModelProfile, register_model_profile
    >>> register_model_profile(
    ...     "anthropic:claude-sonnet-4-6",
    ...     ModelProfile(system_prompt_suffix="Think step by step."),
    ... )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelProfile:
    """Per-provider or per-model tuning for the agent loop.

    All fields are optional. An empty profile is a valid "no-op".
    """

    system_prompt_suffix: Optional[str] = None
    """Text appended to the assembled system prompt with a blank-line separator."""

    excluded_tools: frozenset[str] = field(default_factory=frozenset)
    """Tool names to hide from this model. Useful when a model handles a
    particular tool poorly (e.g. nested-JSON-arg confusion on smaller models)."""

    init_kwargs: Mapping[str, Any] = field(default_factory=dict)
    """Static kwargs merged into every gateway request for this profile.
    Caller-supplied kwargs on the request always win."""

    init_kwargs_factory: Optional[Callable[[], dict[str, Any]]] = None
    """Optional zero-arg callable producing dynamic kwargs at request time.
    Use when a value depends on runtime state (env vars, time of day, etc.).
    Factory output overrides ``init_kwargs`` on key collision; caller kwargs
    still override both."""

    pre_init: Optional[Callable[[str], None]] = None
    """Optional callable invoked once with the resolved spec before the first
    request. Raise to abort. Use for version pins or env-var preflight."""

    def __post_init__(self) -> None:
        # Freeze mutable containers so callers can't mutate a registered profile.
        if not isinstance(self.init_kwargs, MappingProxyType):
            object.__setattr__(
                self,
                "init_kwargs",
                MappingProxyType(dict(self.init_kwargs)),
            )
        if not isinstance(self.excluded_tools, frozenset):
            object.__setattr__(self, "excluded_tools", frozenset(self.excluded_tools))

    def resolve_kwargs(self, caller_kwargs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Compose the final request kwargs.

        Merge order (later wins): ``init_kwargs`` → ``init_kwargs_factory()`` →
        ``caller_kwargs``. Returns a fresh dict.
        """
        merged: dict[str, Any] = dict(self.init_kwargs)
        if self.init_kwargs_factory is not None:
            try:
                merged.update(self.init_kwargs_factory())
            except Exception:
                logger.exception("init_kwargs_factory raised; ignoring its contribution.")
        if caller_kwargs:
            merged.update(caller_kwargs)
        return merged


_EMPTY_PROFILE = ModelProfile()
_REGISTRY: dict[str, ModelProfile] = {}
_PRE_INIT_DONE: set[str] = set()
_BUILTINS_LOADED = False


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not key or key.isspace():
        raise ValueError(f"Profile key must be a non-empty string, got {key!r}")
    if key.count(":") > 1:
        raise ValueError(f"Profile key must be 'provider' or 'provider:model', got {key!r}")
    if ":" in key:
        provider, _, model = key.partition(":")
        if not provider or not model:
            raise ValueError(
                f"Profile key with ':' must have non-empty provider and model, got {key!r}"
            )


def _merge(base: ModelProfile, override: ModelProfile) -> ModelProfile:
    """Layer ``override`` on top of ``base``.

    - Scalar fields: override wins when set; otherwise base.
    - ``excluded_tools``: union of both sets.
    - ``init_kwargs``: dict merge with override winning per key.
    - ``init_kwargs_factory``: chained — base first, then override; override
      keys win on collision.
    - ``pre_init``: chained — base first, then override.
    """
    suffix = (
        override.system_prompt_suffix
        if override.system_prompt_suffix is not None
        else base.system_prompt_suffix
    )
    excluded = base.excluded_tools | override.excluded_tools
    kwargs = {**base.init_kwargs, **override.init_kwargs}

    if base.init_kwargs_factory and override.init_kwargs_factory:
        base_factory = base.init_kwargs_factory
        over_factory = override.init_kwargs_factory

        def chained_factory() -> dict[str, Any]:
            out = dict(base_factory())
            out.update(over_factory())
            return out

        factory: Optional[Callable[[], dict[str, Any]]] = chained_factory
    else:
        factory = override.init_kwargs_factory or base.init_kwargs_factory

    if base.pre_init and override.pre_init:
        base_pre = base.pre_init
        over_pre = override.pre_init

        def chained_pre_init(spec: str) -> None:
            base_pre(spec)
            over_pre(spec)

        pre: Optional[Callable[[str], None]] = chained_pre_init
    else:
        pre = override.pre_init or base.pre_init

    return ModelProfile(
        system_prompt_suffix=suffix,
        excluded_tools=excluded,
        init_kwargs=kwargs,
        init_kwargs_factory=factory,
        pre_init=pre,
    )


def register_model_profile(key: str, profile: ModelProfile) -> None:
    """Register a profile under a provider key or full ``provider:model`` key.

    Registrations are **additive**: if a profile already exists under ``key``
    (including a built-in), the new profile is merged on top with the
    incoming fields winning on conflicts.

    Raises:
        ValueError: if ``key`` is malformed.
    """
    _ensure_builtins_loaded()
    _validate_key(key)
    existing = _REGISTRY.get(key)
    _REGISTRY[key] = _merge(existing, profile) if existing else profile


def resolve_model_profile(provider: str | None, model: str | None) -> ModelProfile:
    """Return the merged profile for ``provider`` / ``model``.

    Lookup order:
      1. ``provider:model`` exact match.
      2. ``provider`` prefix match.

    When both exist, the exact-model profile is layered on top of the
    provider profile. When neither exists, an empty default profile is
    returned.
    """
    _ensure_builtins_loaded()
    if not provider:
        return _EMPTY_PROFILE
    base = _REGISTRY.get(provider)
    exact = _REGISTRY.get(f"{provider}:{model}") if model else None
    if base and exact:
        return _merge(base, exact)
    return exact or base or _EMPTY_PROFILE


def run_pre_init_once(provider: str | None, model: str | None) -> None:
    """Run the profile's ``pre_init`` hook the first time we see this spec.

    Safe to call before every request; the spec is recorded in a module-level
    set so the hook only fires once per (provider, model) pair.
    """
    if not provider:
        return
    spec = f"{provider}:{model}" if model else provider
    if spec in _PRE_INIT_DONE:
        return
    _PRE_INIT_DONE.add(spec)
    profile = resolve_model_profile(provider, model)
    if profile.pre_init is None:
        return
    try:
        profile.pre_init(spec)
    except Exception:
        logger.exception("pre_init for %r raised; downstream request may fail.", spec)
        raise


def clear_registry() -> None:
    """Test helper — drop every registration and reset the builtins-loaded flag."""
    global _BUILTINS_LOADED
    _REGISTRY.clear()
    _PRE_INIT_DONE.clear()
    _BUILTINS_LOADED = False


def _ensure_builtins_loaded() -> None:
    """Lazy-load built-in profiles on first registry access."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    try:
        from ._builtin_profiles import register_all

        register_all()
    except Exception:
        logger.exception("Failed to load built-in model profiles; continuing without them.")


# Re-export for convenience — callers usually only import from this module.
__all__ = [
    "ModelProfile",
    "register_model_profile",
    "resolve_model_profile",
    "run_pre_init_once",
    "clear_registry",
]
