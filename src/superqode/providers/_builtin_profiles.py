"""Built-in model profiles loaded lazily on first registry access.

`register_all()` is invoked from `_ensure_builtins_loaded` in `profiles.py`.
Add new entries by appending to the body of `register_all()`. Keep each
block self-contained so it can be deleted without ripple effects.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .profiles import ModelProfile, _REGISTRY, _merge, _validate_key

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anthropic — Claude family prompt-engineering guidance from Anthropic's
# published best-practices doc. Applied as a system-prompt suffix so it
# lands closest to the conversation history.
# Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
# ---------------------------------------------------------------------------

_CLAUDE_BASE_SUFFIX = """\
<use_parallel_tool_calls>
If you intend to call multiple tools and there are no dependencies between the tool calls, make all of the independent tool calls in parallel. Prioritize calling tools simultaneously whenever the actions can be done in parallel rather than sequentially. Never use placeholders or guess missing parameters in tool calls.
</use_parallel_tool_calls>

<investigate_before_answering>
Never speculate about code you have not opened. If the user references a specific file, you MUST read the file before answering. Investigate and read relevant files BEFORE answering questions about the codebase. Give grounded, hallucination-free answers.
</investigate_before_answering>

<tool_result_reflection>
After receiving tool results, reflect on their quality and determine optimal next steps before proceeding. Use your thinking to plan and iterate based on this new information, and then take the best next action.
</tool_result_reflection>"""


# ---------------------------------------------------------------------------
# OpenRouter — inject app-attribution headers when the user hasn't set them
# via env vars. Mirrors the pattern documented at
# https://openrouter.ai/docs/app-attribution.
# ---------------------------------------------------------------------------

_OPENROUTER_APP_URL_DEFAULT = "https://github.com/Shashikant86/superqode"
_OPENROUTER_APP_TITLE_DEFAULT = "SuperQode"


def _openrouter_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if os.environ.get("OPENROUTER_APP_URL") is None:
        kwargs["app_url"] = _OPENROUTER_APP_URL_DEFAULT
    if os.environ.get("OPENROUTER_APP_TITLE") is None:
        kwargs["app_title"] = _OPENROUTER_APP_TITLE_DEFAULT
    return kwargs


def _register(key: str, profile: ModelProfile) -> None:
    """Register without re-triggering the lazy bootstrap (we're inside it)."""
    _validate_key(key)
    existing = _REGISTRY.get(key)
    _REGISTRY[key] = _merge(existing, profile) if existing else profile


def register_all() -> None:
    """Register every built-in profile. Idempotent — re-registration merges."""
    _register(
        "anthropic:claude-sonnet-4-6",
        ModelProfile(system_prompt_suffix=_CLAUDE_BASE_SUFFIX),
    )
    _register(
        "anthropic:claude-opus-4-7",
        ModelProfile(system_prompt_suffix=_CLAUDE_BASE_SUFFIX),
    )
    _register(
        "anthropic:claude-haiku-4-5",
        ModelProfile(system_prompt_suffix=_CLAUDE_BASE_SUFFIX),
    )
    _register(
        "openrouter",
        ModelProfile(init_kwargs_factory=_openrouter_kwargs),
    )
