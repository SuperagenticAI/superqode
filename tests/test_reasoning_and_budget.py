"""Tests for B5 (reasoning_effort + structured_output_mode) and B8
(per-task token budget) from the fast-agent gap audit.

These cover the *mapping* layer (provider-neutral → provider-specific
kwargs) and the *enforcement* layer (pre-check + credit), all at unit
level — no live API calls.
"""

from __future__ import annotations

import pytest

from superqode.providers.gateway.base import (
    GatewayResponse,
    Message,
    TaskBudgetExceeded,
    TaskTokenBudget,
    Usage,
)
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


# ---------------------------------------------------------------------------
# B5 — reasoning_effort
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider,model,level,expected",
    [
        # Anthropic-shape (Claude, DS4) → thinking.budget_tokens
        (
            "anthropic",
            "claude-sonnet-4",
            "low",
            {"thinking": {"type": "enabled", "budget_tokens": 1024}},
        ),
        (
            "anthropic",
            "claude-sonnet-4",
            "medium",
            {"thinking": {"type": "enabled", "budget_tokens": 4096}},
        ),
        (
            "anthropic",
            "claude-sonnet-4",
            "high",
            {"thinking": {"type": "enabled", "budget_tokens": 16000}},
        ),
        (
            "anthropic",
            "claude-sonnet-4",
            "max",
            {"thinking": {"type": "enabled", "budget_tokens": 31999}},
        ),
        (
            "ds4",
            "deepseek-v4-flash",
            "high",
            {"thinking": {"type": "enabled", "budget_tokens": 16000}},
        ),
        # Model-name-based detection: provider isn't "ds4" but the model is
        (
            "openai-compatible",
            "deepseek-v4-flash",
            "low",
            {"thinking": {"type": "enabled", "budget_tokens": 1024}},
        ),
        # OpenAI o-series → reasoning_effort
        ("openai", "gpt-5", "low", {"reasoning_effort": "low"}),
        ("openai", "gpt-5", "medium", {"reasoning_effort": "medium"}),
        ("openai", "gpt-5", "high", {"reasoning_effort": "high"}),
        # ``max`` collapses to ``high`` on OpenAI (no deeper tier exists).
        ("openai", "gpt-5", "max", {"reasoning_effort": "high"}),
        # OpenRouter passes through.
        ("openrouter", "anthropic/claude-sonnet-4", "medium", {"reasoning_effort": "medium"}),
        # Pi-style model-only runs can explicitly disable Anthropic-shape thinking.
        ("anthropic", "claude-sonnet-4", "off", {"thinking": {"type": "disabled"}}),
        ("ds4", "deepseek-v4-flash", "off", {"thinking": {"type": "disabled"}}),
        ("openai", "gpt-5", "off", {}),
        # Providers with no native reasoning concept → empty mapping.
        ("ollama", "qwen2.5-coder", "high", {}),
        ("google", "gemini-pro", "high", {}),
        ("mlx", "Qwen2.5-Coder-7B-mlx", "max", {}),
    ],
)
def test_reasoning_effort_mapping(provider, model, level, expected):
    gw = LiteLLMGateway()
    assert gw._resolve_reasoning_effort(provider, model, level) == expected


def test_reasoning_effort_unknown_level_returns_empty():
    """Unknown values must not raise — silently drop so a typo in a
    config file doesn't break an entire session."""
    gw = LiteLLMGateway()
    assert gw._resolve_reasoning_effort("anthropic", "claude-sonnet-4", "ultra") == {}
    assert gw._resolve_reasoning_effort("anthropic", "claude-sonnet-4", "") == {}
    assert gw._resolve_reasoning_effort("anthropic", "claude-sonnet-4", None) == {}


def test_reasoning_effort_is_case_insensitive():
    gw = LiteLLMGateway()
    assert gw._resolve_reasoning_effort("openai", "gpt-5", "HIGH") == {"reasoning_effort": "high"}
    assert gw._resolve_reasoning_effort("anthropic", "claude", "  Medium  ") == {
        "thinking": {"type": "enabled", "budget_tokens": 4096}
    }


# ---------------------------------------------------------------------------
# B5 — structured_output_mode
# ---------------------------------------------------------------------------


def test_structured_output_json_maps_to_response_format_for_openai():
    gw = LiteLLMGateway()
    out = gw._resolve_structured_output_mode("openai", "json", has_response_schema=False)
    assert out == {"response_format": {"type": "json_object"}}


def test_structured_output_json_passes_through_for_groq_and_openrouter():
    """OpenAI-compatible providers honor the same field name."""
    gw = LiteLLMGateway()
    assert gw._resolve_structured_output_mode("groq", "json", False) == {
        "response_format": {"type": "json_object"}
    }
    assert gw._resolve_structured_output_mode("openrouter", "json", False) == {
        "response_format": {"type": "json_object"}
    }


def test_structured_output_json_returns_empty_for_anthropic():
    """Anthropic has no ``response_format`` field. Empty mapping is
    correct — the agent loop handles "respond in JSON" via prompt
    instruction in that case."""
    gw = LiteLLMGateway()
    assert gw._resolve_structured_output_mode("anthropic", "json", False) == {}


def test_structured_output_tool_use_emits_marker():
    """The ``tool_use`` mode is a *request shape* concern — the caller
    binds a single tool. The gateway only surfaces an internal marker
    so higher layers can detect the intent."""
    gw = LiteLLMGateway()
    out = gw._resolve_structured_output_mode("anthropic", "tool_use", False)
    assert out == {"_structured_output_mode": "tool_use"}


def test_structured_output_auto_is_noop():
    """``auto`` means "let the gateway decide" — currently a no-op so
    nothing changes in the request shape without an explicit choice."""
    gw = LiteLLMGateway()
    assert gw._resolve_structured_output_mode("openai", "auto", False) == {}
    assert gw._resolve_structured_output_mode("openai", "auto", True) == {}


def test_structured_output_unknown_mode_returns_empty():
    gw = LiteLLMGateway()
    assert gw._resolve_structured_output_mode("openai", "bogus", False) == {}
    assert gw._resolve_structured_output_mode("openai", None, False) == {}


# ---------------------------------------------------------------------------
# B5 — end-to-end through chat_completion (mocked LiteLLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_translates_reasoning_effort(monkeypatch):
    """End-to-end: ``reasoning_effort="high"`` for Anthropic must
    surface as a ``thinking`` kwarg in the actual LiteLLM call."""
    gw = LiteLLMGateway()
    captured: dict = {}

    class _Choice:
        finish_reason = "stop"

        class message:
            role = "assistant"
            content = "ok"
            tool_calls = None

    class _FakeResponse:
        choices = [_Choice()]
        model = "claude"
        usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()
        _hidden_params = {}

    class _FakeLiteLLM:
        async def acompletion(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

        AuthenticationError = type("AuthenticationError", (Exception,), {})
        RateLimitError = type("RateLimitError", (Exception,), {})
        NotFoundError = type("NotFoundError", (Exception,), {})
        BadRequestError = type("BadRequestError", (Exception,), {})

    monkeypatch.setattr(gw, "_get_litellm", lambda: _FakeLiteLLM())

    await gw.chat_completion(
        messages=[Message(role="user", content="hi")],
        model="claude-sonnet-4",
        provider="anthropic",
        reasoning_effort="high",
    )
    assert captured.get("thinking") == {
        "type": "enabled",
        "budget_tokens": 16000,
    }


@pytest.mark.asyncio
async def test_chat_completion_translates_structured_output_for_openai(monkeypatch):
    gw = LiteLLMGateway()
    captured: dict = {}

    class _Choice:
        finish_reason = "stop"

        class message:
            role = "assistant"
            content = '{"x": 1}'
            tool_calls = None

    class _FakeResponse:
        choices = [_Choice()]
        model = "gpt-5"
        usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()
        _hidden_params = {}

    class _FakeLiteLLM:
        async def acompletion(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

        AuthenticationError = type("AE", (Exception,), {})
        RateLimitError = type("RE", (Exception,), {})
        NotFoundError = type("NE", (Exception,), {})
        BadRequestError = type("BE", (Exception,), {})

    monkeypatch.setattr(gw, "_get_litellm", lambda: _FakeLiteLLM())

    await gw.chat_completion(
        messages=[Message(role="user", content="give me JSON")],
        model="gpt-5",
        provider="openai",
        structured_output_mode="json",
    )
    assert captured.get("response_format") == {"type": "json_object"}
    # The internal-only marker must not leak.
    assert "_structured_output_mode" not in captured


# ---------------------------------------------------------------------------
# B8 — TaskTokenBudget unit tests
# ---------------------------------------------------------------------------


def test_budget_construction_rejects_non_positive():
    """A zero or negative budget is almost certainly a config error —
    raise loudly rather than silently never running anything."""
    with pytest.raises(ValueError):
        TaskTokenBudget(0)
    with pytest.raises(ValueError):
        TaskTokenBudget(-1)


def test_budget_check_passes_below_limit():
    b = TaskTokenBudget(1000)
    b.credit(500)
    b.check()  # not exhausted yet — must not raise
    assert b.remaining == 500


def test_budget_check_raises_when_exhausted():
    b = TaskTokenBudget(100)
    b.credit(100)
    assert b.exhausted is True
    with pytest.raises(TaskBudgetExceeded) as exc_info:
        b.check()
    # Error includes the numbers so the user can see what hit them.
    assert "100/100" in str(exc_info.value)


def test_budget_credit_ignores_non_positive():
    """LiteLLM occasionally reports zero tokens on a degenerate response.
    That must not advance the counter — and a negative would be a bug
    we don't want to amplify."""
    b = TaskTokenBudget(100)
    b.credit(0)
    b.credit(-50)
    assert b.used == 0


def test_budget_reset_zeros_used_but_preserves_cap():
    b = TaskTokenBudget(1000)
    b.credit(500)
    b.reset()
    assert b.used == 0
    assert b.max_tokens == 1000


def test_budget_remaining_never_negative():
    """If a single response goes over (rare, but possible with very
    long completions), ``remaining`` clamps at zero rather than going
    negative — UI math is simpler."""
    b = TaskTokenBudget(100)
    b.credit(250)
    assert b.remaining == 0
    assert b.exhausted is True


# ---------------------------------------------------------------------------
# B8 — gateway integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_pre_check_blocks_call_when_exhausted(monkeypatch):
    """The whole point of pre-checking: an exhausted budget must stop
    the request *before* it hits LiteLLM."""
    gw = LiteLLMGateway()
    b = TaskTokenBudget(100)
    b.credit(100)

    called = False

    class _FakeLiteLLM:
        async def acompletion(self, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("must not reach LiteLLM when budget is exhausted")

    monkeypatch.setattr(gw, "_get_litellm", lambda: _FakeLiteLLM())

    with pytest.raises(TaskBudgetExceeded):
        await gw.chat_completion(
            messages=[Message(role="user", content="hi")],
            model="gpt-5",
            provider="openai",
            task_budget=b,
        )
    assert called is False


@pytest.mark.asyncio
async def test_budget_credited_from_response_usage(monkeypatch):
    """After a successful call, the budget's ``used`` must reflect the
    response's reported total — otherwise running multiple turns until
    the budget hits zero is impossible."""
    gw = LiteLLMGateway()
    b = TaskTokenBudget(10_000)

    class _Choice:
        finish_reason = "stop"

        class message:
            role = "assistant"
            content = "hello"
            tool_calls = None

    class _FakeResponse:
        choices = [_Choice()]
        model = "gpt-5"
        usage = type(
            "U", (), {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        )()
        _hidden_params = {}

    class _FakeLiteLLM:
        async def acompletion(self, **kwargs):
            return _FakeResponse()

        AuthenticationError = type("AE", (Exception,), {})
        RateLimitError = type("RE", (Exception,), {})
        NotFoundError = type("NE", (Exception,), {})
        BadRequestError = type("BE", (Exception,), {})

    monkeypatch.setattr(gw, "_get_litellm", lambda: _FakeLiteLLM())

    await gw.chat_completion(
        messages=[Message(role="user", content="hi")],
        model="gpt-5",
        provider="openai",
        task_budget=b,
    )
    assert b.used == 150
    assert b.remaining == 9850


@pytest.mark.asyncio
async def test_budget_kwarg_not_leaked_to_litellm(monkeypatch):
    """``task_budget`` is a SuperQode-internal concept — LiteLLM would
    explode if we passed it through as a kwarg."""
    gw = LiteLLMGateway()
    b = TaskTokenBudget(10_000)
    captured: dict = {}

    class _Choice:
        finish_reason = "stop"

        class message:
            role = "assistant"
            content = "ok"
            tool_calls = None

    class _FakeResponse:
        choices = [_Choice()]
        model = "gpt-5"
        usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()
        _hidden_params = {}

    class _FakeLiteLLM:
        async def acompletion(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

        AuthenticationError = type("AE", (Exception,), {})
        RateLimitError = type("RE", (Exception,), {})
        NotFoundError = type("NE", (Exception,), {})
        BadRequestError = type("BE", (Exception,), {})

    monkeypatch.setattr(gw, "_get_litellm", lambda: _FakeLiteLLM())

    await gw.chat_completion(
        messages=[Message(role="user", content="hi")],
        model="gpt-5",
        provider="openai",
        task_budget=b,
    )
    assert "task_budget" not in captured
    assert "reasoning_effort" not in captured  # not set, but double-check
