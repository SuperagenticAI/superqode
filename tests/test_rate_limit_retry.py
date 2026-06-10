"""Tests for transient-overload retry (429/529/503 with Retry-After) in the gateway."""

import types

import pytest

from superqode.providers.gateway import litellm_gateway as gw_module
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


def _patch_litellm(monkeypatch, acompletion):
    """Install a fake litellm module into the gateway's lazy-load cache."""
    fake = types.SimpleNamespace(acompletion=acompletion)
    monkeypatch.setattr(gw_module, "_litellm_module", fake)


class _FakeRateLimitError(Exception):
    pass


class _FakeHeaders(dict):
    pass


class _FakeResponse:
    def __init__(self, headers):
        self.headers = _FakeHeaders(headers)


def _gateway() -> LiteLLMGateway:
    # __new__ is enough: the retry helpers only use class attrs and env.
    return LiteLLMGateway.__new__(LiteLLMGateway)


def test_detects_rate_limit_by_class_name():
    class RateLimitError(Exception):
        pass

    assert LiteLLMGateway._is_transient_overload_error(RateLimitError("nope")) is True


def test_detects_overload_by_message():
    for msg in (
        "Error code: 429 - too many requests",
        "anthropic overloaded_error",
        "503 Service Unavailable",
        "HTTP 529",
    ):
        assert LiteLLMGateway._is_transient_overload_error(Exception(msg)) is True


def test_ignores_other_errors():
    assert LiteLLMGateway._is_transient_overload_error(Exception("model not found")) is False
    assert LiteLLMGateway._is_transient_overload_error(Exception("invalid api key")) is False


def test_retry_after_seconds_header():
    err = Exception("429")
    err.response = _FakeResponse({"retry-after": "7"})
    assert LiteLLMGateway._retry_after_seconds(err) == 7.0


def test_retry_after_ms_header_preferred():
    err = Exception("429")
    err.response = _FakeResponse({"retry-after-ms": "1500", "retry-after": "99"})
    assert LiteLLMGateway._retry_after_seconds(err) == 1.5


def test_retry_after_absent():
    assert LiteLLMGateway._retry_after_seconds(Exception("429")) is None


def test_delay_honors_retry_after_and_gives_up_on_huge_values():
    err = Exception("429")
    err.response = _FakeResponse({"retry-after": "10"})
    assert LiteLLMGateway._rate_limit_delay(0, err) == 10.0
    err2 = Exception("429")
    err2.response = _FakeResponse({"retry-after": "3600"})
    assert LiteLLMGateway._rate_limit_delay(0, err2) is None  # don't hang sessions


def test_delay_backs_off_exponentially_without_headers():
    err = Exception("429")
    d0 = LiteLLMGateway._rate_limit_delay(0, err)
    d3 = LiteLLMGateway._rate_limit_delay(3, err)
    assert d0 is not None and d3 is not None
    assert d3 > d0
    assert d3 <= LiteLLMGateway._RATE_LIMIT_MAX_DELAY + 0.5


def test_retries_env_override(monkeypatch):
    monkeypatch.setenv(LiteLLMGateway.RATE_LIMIT_RETRIES_ENV, "0")
    assert LiteLLMGateway._rate_limit_retries() == 0
    monkeypatch.setenv(LiteLLMGateway.RATE_LIMIT_RETRIES_ENV, "5")
    assert LiteLLMGateway._rate_limit_retries() == 5
    monkeypatch.delenv(LiteLLMGateway.RATE_LIMIT_RETRIES_ENV)
    assert LiteLLMGateway._rate_limit_retries() == LiteLLMGateway._RATE_LIMIT_DEFAULT_RETRIES


@pytest.mark.asyncio
async def test_acompletion_retries_then_succeeds(monkeypatch):
    gateway = _gateway()
    attempts = {"n": 0}
    sleeps = []

    async def fake_acompletion(**kwargs):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise _FakeRateLimitError("429 too many requests")
        return {"ok": True}

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    _patch_litellm(monkeypatch, fake_acompletion)
    monkeypatch.setattr(gw_module.asyncio, "sleep", fake_sleep)

    result = await gateway._acompletion_with_retry({"model": "m"})
    assert result == {"ok": True}
    assert attempts["n"] == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]  # backoff grew


@pytest.mark.asyncio
async def test_acompletion_gives_up_after_max_retries(monkeypatch):
    gateway = _gateway()

    async def always_429(**kwargs):
        raise _FakeRateLimitError("429 too many requests")

    async def fake_sleep(seconds):
        pass

    _patch_litellm(monkeypatch, always_429)
    monkeypatch.setattr(gw_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setenv(LiteLLMGateway.RATE_LIMIT_RETRIES_ENV, "2")

    with pytest.raises(_FakeRateLimitError):
        await gateway._acompletion_with_retry({"model": "m"})


@pytest.mark.asyncio
async def test_acompletion_non_transient_fails_fast(monkeypatch):
    gateway = _gateway()
    attempts = {"n": 0}

    async def auth_error(**kwargs):
        attempts["n"] += 1
        raise Exception("invalid api key")

    _patch_litellm(monkeypatch, auth_error)

    with pytest.raises(Exception, match="invalid api key"):
        await gateway._acompletion_with_retry({"model": "m"})
    assert attempts["n"] == 1  # no retry on non-transient errors
