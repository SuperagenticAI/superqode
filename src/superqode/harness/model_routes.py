"""Stable model-family routes used by built-in harnesses.

Routes are deliberately curated.  A newly announced model is never promoted
merely because it appears in a remote model catalogue; maintainers update the
stable target after validation while existing versioned templates remain
reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

from .spec import ModelPolicySpec


@dataclass(frozen=True)
class ModelFamilyRoute:
    """A maintained provider/model family with explicit release channels."""

    id: str
    provider: str
    stable: str
    description: str
    fallbacks: tuple[str, ...] = ()
    preview: str | None = None
    fast: str | None = None
    pack: str | None = None
    context_window: int | None = None
    reasoning: str | None = None
    config: dict[str, object] | None = None

    def target(self, channel: str = "stable") -> str:
        """Return the explicitly curated target for a channel."""
        normalized = channel.strip().lower() or "stable"
        if normalized not in {"stable", "preview", "fast"}:
            raise ValueError(f"Unknown channel {channel!r}; expected stable, preview, or fast")
        model = getattr(self, normalized)
        if not model:
            raise ValueError(f"Model family {self.id!r} has no {normalized!r} channel")
        return f"{self.provider}/{model}"


MODEL_FAMILY_ROUTES: dict[str, ModelFamilyRoute] = {
    "kimi": ModelFamilyRoute(
        id="kimi",
        provider="moonshot",
        stable="kimi-k3",
        fast="kimi-k2.7-code-highspeed",
        description="Moonshot Kimi long-context coding family.",
        fallbacks=("moonshot/kimi-k2.7-code-highspeed", "moonshot/kimi-k2.7-code"),
        pack="kimi",
        context_window=1_048_576,
        reasoning="max",
        config={"parallel_tools": True, "session_history_limit": 40},
    ),
}


def get_model_family_route(route_id: str) -> ModelFamilyRoute:
    """Return a curated family route by id."""
    normalized = route_id.strip().lower()
    try:
        return MODEL_FAMILY_ROUTES[normalized]
    except KeyError as exc:
        valid = ", ".join(sorted(MODEL_FAMILY_ROUTES))
        raise ValueError(f"Unknown model family {route_id!r}. Available families: {valid}") from exc


def list_model_family_routes() -> tuple[ModelFamilyRoute, ...]:
    """Return maintained family routes in deterministic order."""
    return tuple(MODEL_FAMILY_ROUTES[key] for key in sorted(MODEL_FAMILY_ROUTES))


def model_policy_for_route(
    route_id: str,
    *,
    channel: str = "stable",
    profile: str | None = None,
) -> ModelPolicySpec:
    """Materialize a family route into an exact, runnable model policy."""
    route = get_model_family_route(route_id)
    return ModelPolicySpec(
        primary=route.target(channel),
        fallbacks=route.fallbacks,
        profile=profile or f"{route.id}-coding",
        pack=route.pack,
        context_window=route.context_window,
        reasoning=route.reasoning,
        config=dict(route.config or {}),
    )


__all__ = [
    "MODEL_FAMILY_ROUTES",
    "ModelFamilyRoute",
    "get_model_family_route",
    "list_model_family_routes",
    "model_policy_for_route",
]
