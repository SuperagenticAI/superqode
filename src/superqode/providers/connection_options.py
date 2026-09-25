"""Per-provider connection options from superqode.yaml.

Supports optional fields used by local / openai-compatible routes:

- ``tool_choice_mode``: ``omit`` | ``send`` (default preserves current send-when-set)
- ``reviewer_model``: optional model id on the same endpoint for auto permission
  reviews / reviewer-role preference
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

ToolChoiceMode = Literal["omit", "send"]


@dataclass(frozen=True)
class ConnectionOptions:
    tool_choice_mode: Optional[ToolChoiceMode] = None
    reviewer_model: str = ""


def _normalize_tool_choice_mode(value: object) -> Optional[ToolChoiceMode]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"omit", "send"}:
        return text  # type: ignore[return-value]
    raise ValueError(f"tool_choice_mode must be 'omit' or 'send', got {value!r}")


def connection_options_for(provider_id: str) -> ConnectionOptions:
    """Load connection options for a provider from the active config."""
    pid = str(provider_id or "").strip().lower()
    if not pid:
        return ConnectionOptions()
    try:
        from superqode.config.loader import load_config

        config = load_config()
    except Exception:
        return ConnectionOptions()
    providers = getattr(config, "providers", None) or {}
    provider_config = providers.get(pid) or providers.get(provider_id)
    if provider_config is None:
        return ConnectionOptions()
    try:
        mode = _normalize_tool_choice_mode(getattr(provider_config, "tool_choice_mode", None))
    except ValueError:
        mode = None
    reviewer = str(getattr(provider_config, "reviewer_model", "") or "").strip()
    return ConnectionOptions(tool_choice_mode=mode, reviewer_model=reviewer)


def resolve_reviewer_model(provider_id: str, selected_model: str = "") -> str:
    """Return configured reviewer_model, else the selected model id."""
    options = connection_options_for(provider_id)
    if options.reviewer_model:
        return options.reviewer_model
    return str(selected_model or "").strip()


def apply_tool_choice_mode(
    provider_id: str,
    request: dict,
    *,
    tool_choice: Optional[str] = None,
) -> None:
    """Mutate ``request`` so tool_choice respects the provider's mode.

    Default (unset / ``send``): keep current behavior (include tool_choice when
    provided). ``omit``: never send tool_choice for partial OpenAI compatibility.
    """
    options = connection_options_for(provider_id)
    mode = options.tool_choice_mode or "send"
    if mode == "omit":
        request.pop("tool_choice", None)
        return
    if tool_choice:
        request["tool_choice"] = tool_choice
    # If tool_choice was already placed on the request and mode is send, leave it.


__all__ = [
    "ConnectionOptions",
    "ToolChoiceMode",
    "apply_tool_choice_mode",
    "connection_options_for",
    "resolve_reviewer_model",
]
