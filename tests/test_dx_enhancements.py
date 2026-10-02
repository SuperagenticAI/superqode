"""Tests for developer experience (DX) enhancements:

- Prompt history fuzzy search modal (HistorySearchModal)
- One-key code snippet yank/copy (action_copy_code, :yank, leader 'y', ctrl+y)
- History search action (action_search_history, :history search, leader 'r', ctrl+shift+r)
- Context gauge in status bar
"""

import json
from unittest.mock import MagicMock

from superqode.app.inputs import SelectionAwareInput
from superqode.app.mixins.actions_misc import MiscActionsMixin
from superqode.app.widgets import ColorfulStatusBar, ConversationLog
from superqode.history import HistoryEntry, HistoryManager
from superqode.widgets.history_search import HistorySearchModal
from superqode.widgets.leader_key import LEADER_KEYS, LeaderKeyMixin


def test_history_search_modal_initialization():
    entries = [
        HistoryEntry(input="first prompt", timestamp=100.0, mode="build"),
        HistoryEntry(input="second prompt", timestamp=200.0, mode="chat"),
        HistoryEntry(input="first prompt", timestamp=300.0, mode="build"),  # Duplicate
    ]
    modal = HistorySearchModal(entries=entries)
    # Check deduplication and reverse ordering (most recent first)
    assert len(modal._all_entries) == 2
    assert modal._all_entries[0][0] == "first prompt"
    assert modal._all_entries[1][0] == "second prompt"


def test_history_search_modal_filtering():
    entries = [
        HistoryEntry(input=":connect byok openai", timestamp=100.0),
        HistoryEntry(input="write a quicksort in rust", timestamp=200.0),
        HistoryEntry(input=":diff", timestamp=300.0),
        HistoryEntry(input="write tests for quicksort", timestamp=400.0),
    ]
    modal = HistorySearchModal(entries=entries)

    # Filter by "quick"
    opts = modal._build_options("quick")
    assert len(opts) == 2
    assert len(modal._filtered_entries) == 2
    assert "quicksort" in modal._filtered_entries[0][0]

    # Filter with no match
    opts_empty = modal._build_options("nonexistent_command_xyz")
    assert len(opts_empty) == 1  # 1 disabled "No matching history" option
    assert len(modal._filtered_entries) == 0


def test_leader_key_has_yank_and_history():
    assert "y" in LEADER_KEYS
    assert LEADER_KEYS["y"]["action"] == "copy_code"
    assert "r" in LEADER_KEYS
    assert LEADER_KEYS["r"]["action"] == "search_history"


def test_leader_key_dispatches_yank_and_history():
    class DummyApp(LeaderKeyMixin):
        def __init__(self):
            self.calls = []

        def action_copy_code(self):
            self.calls.append("copy_code")

        def action_search_history(self):
            self.calls.append("search_history")

    app = DummyApp()
    app._handle_leader_action("copy_code")
    assert "copy_code" in app.calls

    app._handle_leader_action("search_history")
    assert "search_history" in app.calls


def test_status_bar_context_gauge_display():
    bar = ColorfulStatusBar()
    bar.update_byok_status("anthropic", "claude-sonnet-4-6", tokens=14200, context_window=200000)

    plain = bar._render_for_width(120).plain
    assert "ctx 7%" in plain
    assert "14.2K/200K" in plain


def test_app_actions_wired():
    assert hasattr(MiscActionsMixin, "action_return_to_agent")
    assert hasattr(MiscActionsMixin, "action_copy_code")
    assert hasattr(MiscActionsMixin, "action_search_history")


def test_search_history_action_uses_entries_property():
    class HistoryStub:
        def __init__(self):
            self.loaded = False
            self.entries = [HistoryEntry(input="previous prompt", timestamp=100.0)]

        def ensure_loaded(self):
            self.loaded = True

    class AppStub(MiscActionsMixin):
        def __init__(self):
            self._history_manager = HistoryStub()
            self.pushed = None

        def push_screen(self, screen, callback):
            self.pushed = (screen, callback)

    app = AppStub()
    app.action_search_history()

    assert app._history_manager.loaded is True
    assert isinstance(app.pushed[0], HistorySearchModal)
    assert app.pushed[0]._all_entries[0][0] == "previous prompt"


def test_return_to_agent_restores_transcript_and_focus():
    class LogStub:
        def __init__(self):
            self.redraws = 0

        def redraw_conversation(self):
            self.redraws += 1

    class AppStub(MiscActionsMixin):
        def __init__(self):
            self.log = LogStub()
            self._awaiting_harness_selection = True
            self._welcome_active = True
            self.reset_connect = False
            self.timer_callback = None

        def _reset_connect_selection_states(self):
            self.reset_connect = True

        def _end_connection_view(self, _log):
            return False

        def query_one(self, *_args, **_kwargs):
            return self.log

        def set_timer(self, _delay, callback):
            self.timer_callback = callback

        def _ensure_input_focus(self):
            pass

    app = AppStub()
    app.action_return_to_agent()

    assert app.reset_connect is True
    assert app._awaiting_harness_selection is False
    assert app._welcome_active is False
    assert app.log.redraws == 1
    assert app.timer_callback == app._ensure_input_focus


def test_ctrl_g_remains_available_for_stash_draft():
    class AppStub:
        def __init__(self):
            self.return_calls = 0

        def action_return_to_agent(self):
            self.return_calls += 1

    app = AppStub()
    prompt = SelectionAwareInput()
    prompt._app = app
    event = MagicMock()
    event.key = "ctrl+g"
    event.aliases = {"ctrl+g"}
    event.character = None

    prompt.on_key(event)

    assert app.return_calls == 0
    event.stop.assert_not_called()
    event.prevent_default.assert_not_called()


def test_ensure_loaded_reads_only_requested_tail(tmp_path):
    history_file = tmp_path / "history.jsonl"
    records = [
        json.dumps({"input": f"prompt {index}", "timestamp": float(index)}) for index in range(700)
    ]
    history_file.write_text("\n".join(records) + "\n", encoding="utf-8")

    history = HistoryManager(history_file=history_file)
    history.ensure_loaded(max_entries=5)

    assert [entry.input for entry in history.entries] == [
        "prompt 695",
        "prompt 696",
        "prompt 697",
        "prompt 698",
        "prompt 699",
    ]


def test_get_last_code_block_returns_final_fence():
    log = ConversationLog()
    log._last_response = (
        """First:\n```python\nprint('first')\n```\nLast:\n```c++\nreturn 42;\n```"""
    )

    assert log.get_last_code_block() == "return 42;"


def test_redraw_empty_conversation_clears_command_screen():
    log = ConversationLog()
    log.write("temporary command screen")

    log.redraw_conversation()

    assert not log.lines
