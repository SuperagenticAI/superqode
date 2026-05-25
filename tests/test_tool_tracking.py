"""Tests for ToolCallTracker - dual-keyed (id + index) tool call state."""

from __future__ import annotations

import pytest

from superqode.agent.tool_tracking import ToolCallState, ToolCallTracker


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_new_call_returns_state():
    tracker = ToolCallTracker()
    state = tracker.register(tool_use_id="toolu_1", name="read_file")
    assert isinstance(state, ToolCallState)
    assert state.tool_use_id == "toolu_1"
    assert state.name == "read_file"
    assert state.kind == "tool"
    assert state.index is None


def test_register_same_id_twice_returns_same_state():
    tracker = ToolCallTracker()
    a = tracker.register(tool_use_id="toolu_1", name="read_file")
    b = tracker.register(tool_use_id="toolu_1", name="read_file")
    assert a is b


def test_register_with_index_indexes_by_both():
    tracker = ToolCallTracker()
    state = tracker.register(tool_use_id="call_xyz", name="read_file", index=0)
    assert tracker.resolve_open(tool_use_id="call_xyz") is state
    assert tracker.resolve_open(index=0) is state


# ---------------------------------------------------------------------------
# Provider-specific stream patterns
# ---------------------------------------------------------------------------


def test_openai_index_only_then_id_converges_to_one_state():
    """OpenAI: deltas arrive index-only, then a delta brings the real id."""
    tracker = ToolCallTracker()
    # First delta: no real id yet (provider uses index as placeholder).
    first = tracker.register(tool_use_id="placeholder_0", name="tool", index=0)
    assert first.name == "tool"  # generic placeholder
    # Second delta: real id arrives, named the same tool.
    second = tracker.register(tool_use_id="call_abc123", name="read_file", index=0)
    # Should be the same state, re-keyed to the real id.
    assert second.tool_use_id == "call_abc123"
    assert second.name == "read_file"
    assert tracker.resolve_open(index=0) is second
    assert tracker.resolve_open(tool_use_id="call_abc123") is second
    # The placeholder id is gone.
    assert tracker.resolve_open(tool_use_id="placeholder_0") is None
    # Only one open call total.
    assert len(tracker.incomplete()) == 1


def test_anthropic_id_only_pattern():
    """Anthropic: tool_use_id present from the start, no index involved."""
    tracker = ToolCallTracker()
    state = tracker.register(tool_use_id="toolu_01ABC", name="bash")
    assert state.index is None
    assert tracker.resolve_open(tool_use_id="toolu_01ABC") is state
    assert tracker.resolve_open(index=0) is None


def test_generic_name_does_not_overwrite_real_name():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="id1", name="grep")
    state = tracker.register(tool_use_id="id1", name="tool")  # generic delta
    assert state.name == "grep"  # real name preserved


def test_real_name_overwrites_generic():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="id1", name="tool")
    state = tracker.register(tool_use_id="id1", name="bash")
    assert state.name == "bash"


def test_kind_upgrades_from_tool_to_specialized():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="id1", name="search")
    state = tracker.register(tool_use_id="id1", name="search", kind="web_search")
    assert state.kind == "web_search"


def test_kind_does_not_downgrade():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="id1", name="search", kind="web_search")
    state = tracker.register(tool_use_id="id1", name="search", kind="tool")
    assert state.kind == "web_search"


# ---------------------------------------------------------------------------
# resolve, close, completed
# ---------------------------------------------------------------------------


def test_resolve_returns_completed_after_close():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="id1", name="read")
    tracker.close(tool_use_id="id1")
    assert tracker.resolve_open(tool_use_id="id1") is None
    state = tracker.resolve(tool_use_id="id1")
    assert state is not None
    assert state.name == "read"


def test_close_by_index():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="call_1", name="read", index=0)
    closed = tracker.close(index=0)
    assert closed is not None
    assert closed.tool_use_id == "call_1"
    assert tracker.resolve_open(index=0) is None
    assert tracker.is_completed(index=0) is True


def test_close_unknown_returns_none():
    tracker = ToolCallTracker()
    assert tracker.close(tool_use_id="ghost") is None
    assert tracker.close(index=999) is None


def test_is_completed_false_for_open_call():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="id1", name="read")
    assert tracker.is_completed(tool_use_id="id1") is False


def test_incomplete_and_completed_lists():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="a", name="read")
    tracker.register(tool_use_id="b", name="write")
    tracker.register(tool_use_id="c", name="bash")
    tracker.close(tool_use_id="b")
    incomplete_ids = {s.tool_use_id for s in tracker.incomplete()}
    completed_ids = {s.tool_use_id for s in tracker.completed()}
    assert incomplete_ids == {"a", "c"}
    assert completed_ids == {"b"}


# ---------------------------------------------------------------------------
# rekey_open
# ---------------------------------------------------------------------------


def test_rekey_open_renames_id():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="temp_id", name="read", index=0)
    state = tracker.rekey_open(tool_use_id="temp_id", new_tool_use_id="call_final")
    assert state is not None
    assert state.tool_use_id == "call_final"
    assert tracker.resolve_open(tool_use_id="temp_id") is None
    assert tracker.resolve_open(tool_use_id="call_final") is state
    # Index lookup still works.
    assert tracker.resolve_open(index=0) is state


def test_rekey_open_unknown_returns_none():
    tracker = ToolCallTracker()
    assert tracker.rekey_open(tool_use_id="ghost", new_tool_use_id="anything") is None


def test_rekey_open_to_same_id_is_noop():
    tracker = ToolCallTracker()
    tracker.register(tool_use_id="a", name="read")
    state = tracker.rekey_open(tool_use_id="a", new_tool_use_id="a")
    assert state is not None
    assert state.tool_use_id == "a"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_index_reassignment_moves_lookup():
    tracker = ToolCallTracker()
    state = tracker.register(tool_use_id="a", name="read", index=0)
    # Same call, new index (rare but possible).
    tracker.register(tool_use_id="a", name="read", index=2)
    assert state.index == 2
    assert tracker.resolve_open(index=0) is None
    assert tracker.resolve_open(index=2) is state


def test_independent_calls_with_different_indices():
    tracker = ToolCallTracker()
    a = tracker.register(tool_use_id="a", name="read", index=0)
    b = tracker.register(tool_use_id="b", name="write", index=1)
    assert a is not b
    assert len(tracker.incomplete()) == 2
    assert tracker.resolve_open(index=0) is a
    assert tracker.resolve_open(index=1) is b


def test_resolve_with_no_keys_returns_none():
    tracker = ToolCallTracker()
    assert tracker.resolve_open() is None
    assert tracker.resolve() is None


def test_start_notified_flag_persists():
    tracker = ToolCallTracker()
    state = tracker.register(tool_use_id="a", name="read")
    state.start_notified = True
    again = tracker.register(tool_use_id="a", name="read")
    assert again.start_notified is True
