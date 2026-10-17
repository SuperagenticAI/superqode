"""CodeGem cost estimates from Google's published Gemini API prices.

Source: https://ai.google.dev/gemini-api/docs/pricing (Standard paid tier).
"""

import pytest

from superqode.codegem.provider import gemini_cost
from superqode.pipy.messages import Usage
from superqode.providers.models import MODELS, price_schedule

M = 1_000_000


def _usage(input=0, output=0, cache_read=0, reasoning=None):
    return Usage(input=input, output=output, cache_read=cache_read, reasoning=reasoning)


@pytest.mark.parametrize(
    "model_id, on, expected",
    [
        ("gemini-4-argon", "2026-11-30", (2.0, 10.0, 0.10)),
        ("gemini-4-argon", "2026-12-01", (4.0, 20.0, 0.20)),
        ("gemini-3.8-flash", "2026-12-31", (0.75, 3.75, 0.075)),
        ("gemini-3.8-flash", "2027-01-01", (1.50, 7.50, 0.15)),
        ("gemini-3.6-flash", "2026-10-17", (0.75, 3.75, 0.075)),
        ("gemini-3.6-flash", "2027-01-01", (1.50, 7.50, 0.15)),
        ("gemini-3.5-flash-lite", "2026-10-17", (0.30, 2.50, 0.03)),
        ("gemini-3.1-flash-lite", "2026-10-17", (0.25, 1.50, 0.025)),
        ("gemini-3.1-pro-preview", "2026-10-17", (2.0, 12.0, 0.20)),
        ("gemini-3.1-pro-preview-customtools", "2026-10-17", (2.0, 12.0, 0.20)),
    ],
)
def test_published_prices_and_schedules(model_id, on, expected):
    assert price_schedule(MODELS["google"][model_id], 1000, on) == expected


@pytest.mark.parametrize(
    "model_id", ["gemini-3.1-pro-preview", "gemini-3.1-pro-preview-customtools"]
)
def test_pro_long_context_tier_above_200k(model_id):
    info = MODELS["google"][model_id]
    assert price_schedule(info, 200_000, "2026-10-17") == (2.0, 12.0, 0.20)
    assert price_schedule(info, 200_001, "2026-10-17") == (4.0, 18.0, 0.40)


def test_cached_tokens_charge_cache_rate_and_thinking_bills_as_output():
    cost = gemini_cost(
        "gemini-3.8-flash",
        _usage(input=1 * M, output=M // 2, cache_read=M // 2, reasoning=M // 2),
        on="2026-10-17",
    )
    assert cost.input == pytest.approx(0.375)
    assert cost.cache_read == pytest.approx(0.0375)
    assert cost.output == pytest.approx(3.75)
    assert cost.total == pytest.approx(0.375 + 0.0375 + 3.75)


def test_argon_cache_rate_and_december_change():
    usage = _usage(input=2 * M, output=0, cache_read=M)
    assert gemini_cost("gemini-4-argon", usage, on="2026-11-01").cache_read == pytest.approx(0.10)
    later = gemini_cost("gemini-4-argon", usage, on="2026-12-01")
    assert later.cache_read == pytest.approx(0.20)
    assert later.input == pytest.approx(4.0)


def test_long_context_cost_uses_prompt_size():
    usage = _usage(input=300_000, output=1000, cache_read=100_000)
    cost = gemini_cost("gemini-3.1-pro-preview", usage, 300_000, on="2026-10-17")
    assert cost.input == pytest.approx(200_000 * 4.0 / M)
    assert cost.cache_read == pytest.approx(100_000 * 0.40 / M)
    assert cost.output == pytest.approx(1000 * 18.0 / M)


def test_gemma_on_gemini_api_is_free_tier_only():
    cost = gemini_cost("gemma-4-31b-it", _usage(input=M, output=M))
    assert cost.total == 0.0


def test_unknown_model_has_zero_cost():
    assert gemini_cost("gemini-unknown", _usage(input=M)).total == 0.0
