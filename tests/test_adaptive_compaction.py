"""Tests for adaptive context compaction (auto-scales to the model's window)."""

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop, AgentMessage


class _FakeContextManager:
    def count_tokens(self, messages):
        return sum(max(1, len(str(m.get("content", ""))) // 4) for m in messages)


def _make_loop(window=0, **cfg_kwargs):
    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(provider="x", model="y", context_window=window, **cfg_kwargs)
    loop.context_manager = _FakeContextManager()
    loop._cached_context_window = window or 8192
    return loop


def test_budgets_scale_with_window():
    small = _make_loop(4096)._compaction_budgets()
    large = _make_loop(200000)._compaction_budgets()
    # (threshold, keep_recent, window)
    assert small[2] == 4096 and large[2] == 200000
    # Threshold leaves a reserve and is below the window.
    assert small[0] < 4096 and large[0] < 200000
    # Larger window => larger absolute keep-recent budget.
    assert large[1] > small[1]
    # Reserve is capped (~16k) on huge windows, not 15% of 200k.
    assert (large[2] - large[0]) <= 16384


def test_threshold_below_window_with_reserve():
    threshold, keep_recent, window = _make_loop(32000)._compaction_budgets()
    reserve = window - threshold
    assert reserve >= 512
    assert keep_recent + reserve < window  # tail + reserve never swallow the window


def test_explicit_overrides_respected():
    loop = _make_loop(32000, compaction_reserve_tokens=2000, keep_recent_tokens=5000)
    threshold, keep_recent, window = loop._compaction_budgets()
    assert window - threshold == 2000
    assert keep_recent == 5000


def test_compaction_active_default_on_and_env_opt_out(monkeypatch):
    loop = _make_loop(8192)
    monkeypatch.delenv("SUPERQODE_AUTO_COMPACT", raising=False)
    assert loop._compaction_active() is True
    monkeypatch.setenv("SUPERQODE_AUTO_COMPACT", "0")
    assert loop._compaction_active() is False
    monkeypatch.setenv("SUPERQODE_AUTO_COMPACT", "on")
    assert loop._compaction_active() is True


def test_effective_window_prefers_config():
    assert _make_loop(64000)._effective_context_window() == 64000


def test_token_budgeted_split_keeps_recent_tail():
    loop = _make_loop(8192)
    # 10 messages, ~400 tokens each (1600 chars). keep_recent=1000 => ~3 kept.
    msgs = [AgentMessage(role="user", content="x" * 1600) for _ in range(10)]
    dicts = [{"role": m.role, "content": m.content} for m in msgs]
    split = loop._token_budgeted_split(msgs, dicts, 1000)
    tail = len(msgs) - split
    assert 2 <= tail <= 4  # keeps a token-budgeted tail, not a fixed count


@pytest.mark.asyncio
async def test_no_compaction_when_under_threshold():
    loop = _make_loop(32000)
    msgs = [AgentMessage(role="user", content="short message")]
    out = await loop._maybe_summarize(msgs)
    assert out is msgs  # returns the same list untouched


@pytest.mark.asyncio
async def test_disabled_via_env_is_noop(monkeypatch):
    monkeypatch.setenv("SUPERQODE_AUTO_COMPACT", "0")
    loop = _make_loop(2048)
    msgs = [AgentMessage(role="user", content="x" * 100000)]  # way over any window
    out = await loop._maybe_summarize(msgs)
    assert out is msgs  # opted out -> no compaction even when huge
