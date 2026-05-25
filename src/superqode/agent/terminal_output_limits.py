"""Compute per-model byte caps for tool output (shell, web, etc.).

A single ``bash`` invocation can easily produce 20k lines of output. Splatting
that into the conversation eats the model's context window before the agent
has a chance to reason about it. We pick a byte cap that's a fraction of the
model's ``max_output_tokens`` so the tool reply fits comfortably inside one
assistant turn.

Constants follow fast-agent's ``llm/terminal_output_limits.py`` so prompts /
fixtures tuned against fast-agent give comparable cap sizes here.

Floors and ceilings keep the cap reasonable for both tiny models (still get
at least 8 KB so simple commands work) and huge-context models (capped at
100 KB so a single bash call doesn't drown the conversation).
"""

from __future__ import annotations

from typing import Optional

from ..providers.models import get_model_info

# --- Tunables (mirrored from fast-agent) ----------------------------------

#: Default byte budget when we have no model info to work from.
DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT = 8192

#: Hard ceiling regardless of model size - one bash call shouldn't drown the chat.
MAX_TERMINAL_OUTPUT_BYTE_LIMIT = 100_000

#: Fraction of ``max_output_tokens`` we're willing to spend on terminal output.
TERMINAL_OUTPUT_TOKEN_RATIO = 0.83

#: Headroom kept free for the actual assistant response after tool output.
TERMINAL_OUTPUT_TOKEN_HEADROOM_RATIO = 0.2

#: Empirical bytes-per-token (English/code). Closer to 4 for prose, lower for
#: code; 3.3 is a conservative middle.
TERMINAL_BYTES_PER_TOKEN = 3.3


def calculate_terminal_output_limit_for_max_tokens(max_tokens: Optional[int]) -> int:
    """Convert a model's ``max_output_tokens`` to a byte cap for tool output.

    The cap is clamped to ``[DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT,
    MAX_TERMINAL_OUTPUT_BYTE_LIMIT]`` so even unknown / unreasonable model
    values give a sensible result.
    """
    if not max_tokens or max_tokens <= 0:
        return DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT

    terminal_token_budget = max(int(max_tokens * TERMINAL_OUTPUT_TOKEN_RATIO), 1)
    terminal_token_budget = max(
        int(terminal_token_budget * (1 - TERMINAL_OUTPUT_TOKEN_HEADROOM_RATIO)), 1
    )
    terminal_byte_budget = int(terminal_token_budget * TERMINAL_BYTES_PER_TOKEN)

    terminal_byte_budget = min(terminal_byte_budget, MAX_TERMINAL_OUTPUT_BYTE_LIMIT)
    return max(DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT, terminal_byte_budget)


def calculate_terminal_output_limit_for_model(
    provider: Optional[str], model: Optional[str]
) -> int:
    """Look up a model's max-output-tokens and return the byte cap.

    Unknown providers/models fall back to ``DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT``
    rather than raising - tools should still run; they just can't size up.
    """
    if not provider or not model:
        return DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT

    info = get_model_info(provider, model)
    if info is None:
        return DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT

    return calculate_terminal_output_limit_for_max_tokens(info.max_output)


__all__ = [
    "DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT",
    "MAX_TERMINAL_OUTPUT_BYTE_LIMIT",
    "TERMINAL_BYTES_PER_TOKEN",
    "TERMINAL_OUTPUT_TOKEN_HEADROOM_RATIO",
    "TERMINAL_OUTPUT_TOKEN_RATIO",
    "calculate_terminal_output_limit_for_max_tokens",
    "calculate_terminal_output_limit_for_model",
]
