"""Tests for doom-loop detection (consecutive identical tool calls)."""

from superqode.agent.loop_guard import DoomLoopDetector


def test_streak_below_threshold_not_blocked():
    guard = DoomLoopDetector(threshold=3)
    assert guard.observe("grep", {"q": "x"}) is False
    assert guard.observe("grep", {"q": "x"}) is False


def test_third_identical_call_blocked():
    guard = DoomLoopDetector(threshold=3)
    guard.observe("grep", {"q": "x"})
    guard.observe("grep", {"q": "x"})
    assert guard.observe("grep", {"q": "x"}) is True
    assert guard.interventions == 1


def test_different_call_resets_streak():
    guard = DoomLoopDetector(threshold=3)
    guard.observe("grep", {"q": "x"})
    guard.observe("grep", {"q": "x"})
    assert guard.observe("read_file", {"path": "a.py"}) is False
    # Streak restarted: two more identical greps are fine, third blocks.
    assert guard.observe("grep", {"q": "x"}) is False
    assert guard.observe("grep", {"q": "x"}) is False
    assert guard.observe("grep", {"q": "x"}) is True


def test_argument_order_does_not_matter():
    guard = DoomLoopDetector(threshold=3)
    guard.observe("grep", {"a": 1, "b": 2})
    guard.observe("grep", {"b": 2, "a": 1})
    assert guard.observe("grep", {"a": 1, "b": 2}) is True


def test_abort_tripwire_fires_on_repeat_after_block():
    guard = DoomLoopDetector(threshold=3)
    guard.observe("grep", {"q": "x"})
    guard.observe("grep", {"q": "x"})
    assert guard.observe("grep", {"q": "x"}) is True
    # The model repeats the very same call it was just warned about.
    assert guard.should_abort("grep", {"q": "x"}) is True


def test_abort_tripwire_cleared_by_different_call():
    guard = DoomLoopDetector(threshold=3)
    guard.observe("grep", {"q": "x"})
    guard.observe("grep", {"q": "x"})
    assert guard.observe("grep", {"q": "x"}) is True
    assert guard.observe("read_file", {"path": "a.py"}) is False
    assert guard.should_abort("grep", {"q": "x"}) is False


def test_disabled_threshold_never_blocks():
    guard = DoomLoopDetector(threshold=0)
    for _ in range(10):
        assert guard.observe("grep", {"q": "x"}) is False
    assert guard.should_abort("grep", {"q": "x"}) is False


def test_guidance_and_abort_messages_mention_tool():
    guard = DoomLoopDetector(threshold=3)
    assert "grep" in guard.guidance("grep")
    assert "grep" in guard.abort_message("grep")
