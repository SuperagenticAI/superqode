"""Tests for the hosted agent's request limits."""

from __future__ import annotations

from superqode.a2a.limits import (
    MAX_TRACKED_CALLERS,
    RateLimiter,
    RateLimitPolicy,
    caller_identity,
)


def test_a_caller_is_held_to_its_tier_ceiling():
    limiter = RateLimiter(RateLimitPolicy(anonymous_per_minute=3, global_per_day=0))
    outcomes = [limiter.check("ip:1.2.3.4", "anonymous", now=100.0).allowed for _ in range(5)]
    assert outcomes == [True, True, True, False, False]

    refusal = limiter.check("ip:1.2.3.4", "anonymous", now=100.0)
    assert refusal.retry_after_seconds > 0
    assert "per-minute limit" in refusal.reason


def test_the_window_reopens():
    limiter = RateLimiter(RateLimitPolicy(anonymous_per_minute=2, global_per_day=0))
    assert limiter.check("ip:a", "anonymous", now=100.0).allowed
    assert limiter.check("ip:a", "anonymous", now=100.0).allowed
    assert not limiter.check("ip:a", "anonymous", now=100.0).allowed
    assert limiter.check("ip:a", "anonymous", now=161.0).allowed


def test_callers_do_not_share_a_budget():
    limiter = RateLimiter(RateLimitPolicy(anonymous_per_minute=1, global_per_day=0))
    assert limiter.check("ip:a", "anonymous", now=100.0).allowed
    assert not limiter.check("ip:a", "anonymous", now=100.0).allowed
    assert limiter.check("ip:b", "anonymous", now=100.0).allowed


def test_a_keyed_caller_gets_the_larger_ceiling():
    limiter = RateLimiter(
        RateLimitPolicy(anonymous_per_minute=1, keyed_per_minute=5, global_per_day=0)
    )
    assert sum(limiter.check("key:abc", "one-off", now=100.0).allowed for _ in range(6)) == 5


def test_the_global_ceiling_binds_every_tier_including_exempt_ones():
    """The backstop exists because per-caller accounting will be wrong one day.

    An exempt tier skips its per-caller window, but a ceiling that anyone can
    step over is not a ceiling, so the daily total still applies to it.
    """
    limiter = RateLimiter(RateLimitPolicy(global_per_day=4))
    outcomes = [limiter.check("key:op", "operator", now=100.0) for _ in range(6)]
    assert [item.allowed for item in outcomes] == [True] * 4 + [False] * 2
    assert outcomes[-1].scope == "global"
    assert "daily limit" in outcomes[-1].reason


def test_an_exempt_tier_skips_its_per_caller_window():
    limiter = RateLimiter(RateLimitPolicy(anonymous_per_minute=1, global_per_day=0))
    assert all(limiter.check("key:op", "operator", now=100.0).allowed for _ in range(50))


def test_the_caller_table_does_not_grow_without_bound():
    """A flood of distinct addresses must not become a memory leak."""
    limiter = RateLimiter(RateLimitPolicy(anonymous_per_minute=1, global_per_day=0))
    for index in range(1500):
        limiter.check(f"ip:10.0.{index // 256}.{index % 256}", "anonymous", now=100.0)
    tracked = limiter.snapshot()["tracked_callers"]
    assert tracked <= MAX_TRACKED_CALLERS

    # Windows that have reset are pruned rather than accumulated.
    limiter.check("ip:fresh", "anonymous", now=100_000.0)
    assert limiter.snapshot()["tracked_callers"] < tracked


def test_identity_prefers_the_key_then_the_proxy_header():
    """Behind a proxy the socket address is the proxy, not the caller."""
    assert caller_identity("abc", "10.0.0.1", "203.0.113.7") == "key:abc"
    assert caller_identity("", "10.0.0.1", "203.0.113.7, 10.0.0.1") == "ip:203.0.113.7"
    assert caller_identity("", "10.0.0.1", None) == "ip:10.0.0.1"
    assert caller_identity("", None, None) == "ip:unknown"
    assert caller_identity("", "10.0.0.1", "  ") == "ip:10.0.0.1"
