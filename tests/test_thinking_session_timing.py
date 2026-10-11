"""Thinking sessions must not require an implicitly created asyncio loop."""

from unittest.mock import Mock

import pytest

from superqode.widgets.thinking_display import ThinkingSource, UnifiedThinkingManager


def test_thinking_session_can_start_without_an_event_loop(monkeypatch):
    clock = iter((0.0, 0.25))
    monkeypatch.setattr("superqode.widgets.thinking_display.time.monotonic", lambda: next(clock))
    panel = Mock()
    manager = UnifiedThinkingManager(panel)

    manager.start_session(ThinkingSource.BYOK)
    stats = manager.end_session()

    assert stats.source == ThinkingSource.BYOK
    assert stats.duration_ms == pytest.approx(250.0)
    panel.clear.assert_called_once()


@pytest.mark.asyncio
async def test_thinking_session_records_duration_inside_an_event_loop():
    manager = UnifiedThinkingManager(Mock())
    manager.start_session(ThinkingSource.ACP)
    stats = manager.end_session()

    assert stats.duration_ms >= 0
    assert stats.source == ThinkingSource.ACP
