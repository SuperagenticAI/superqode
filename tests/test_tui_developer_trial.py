"""First-session recovery and interrupt behavior in the mounted terminal UI."""

import concurrent.futures
import threading
from types import SimpleNamespace

import pytest
from textual.document._document import Selection

from superqode.app_main import SelectionAwareInput, SuperQodeApp
from superqode.app.widgets import ConversationLog


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_ctrl_c_interrupts_work_and_preserves_the_next_draft(size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "next task\nkeep this draft"
        prompt.cursor_position = 4
        cancelled, exits = [], []
        app._pure_mode = SimpleNamespace(cancel=lambda: cancelled.append(True))
        app.action_quit = lambda: exits.append(True)
        app.is_busy = True
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert cancelled == [True]
        assert exits == []
        assert not app.is_busy
        assert app._queue_paused
        assert prompt.value == "next task\nkeep this draft"
        assert prompt.cursor_position == 4


async def test_idle_ctrl_c_requires_a_second_press_and_keeps_the_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "unfinished prompt"
        exits = []
        app.action_quit = lambda: exits.append(True)
        await pilot.press("ctrl+c")
        assert exits == []
        assert prompt.value == "unfinished prompt"
        await pilot.press("ctrl+c")
        assert exits == [True]


async def test_ctrl_c_copies_selected_prompt_text_without_arming_exit():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "copy this draft"
        prompt.selection = Selection((0, 0), (0, 4))
        exits = []
        app.action_quit = lambda: exits.append(True)
        await pilot.press("ctrl+c", "ctrl+c")
        assert app.clipboard == "copy"
        assert not exits
        assert prompt.value == "copy this draft"


@pytest.mark.parametrize("key", ["escape", "ctrl+c"])
@pytest.mark.parametrize("busy", [True, False])
async def test_interrupt_rejects_pending_approval_and_restores_draft(key, busy):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft before approval"
        prompt.cursor_position = 5
        cancelled = []
        app._pure_mode = SimpleNamespace(_agent=object(), cancel=lambda: cancelled.append(True))
        app.is_busy = True
        decision = threading.Event()
        app._permission_response_event = decision
        app._show_permission_prompt(
            "bash", {"command": "pytest -q"}, app.query_one("#log", ConversationLog)
        )
        assert prompt.value == ""
        app.is_busy = busy
        prompt.value = "approval answer"
        prompt.selection = Selection((0, 0), (0, 8))
        await pilot.press(key)
        await pilot.pause()
        assert decision.is_set()
        assert app._permission_response == "deny"
        assert not app._permission_pending
        assert cancelled == [True]
        assert prompt.value == "draft before approval"
        assert prompt.cursor_position == 5
        assert not app._handle_permission_input("y")


async def test_escape_releases_an_agent_question_and_restores_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft before question"
        app._pure_mode = SimpleNamespace(_agent=object(), cancel=lambda: None)
        app.is_busy = True
        future = concurrent.futures.Future()
        app._pending_agent_question_future = future
        app._pending_agent_question = object()
        app._awaiting_agent_question = True
        app._permission_pending = True
        app._set_composer_working_state(True, interactive=True)
        await pilot.press("escape")
        await pilot.pause()
        assert future.cancelled()
        assert not app._awaiting_agent_question
        assert not app._permission_pending
        assert prompt.value == "draft before question"


async def test_unconnected_first_prompt_is_restored_for_sending_after_setup():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        original = "Summarize this repository\n  preserve my formatting"
        prompt.value = original
        prompt.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert not app.is_busy
        assert prompt.value == original
        assert prompt.has_focus
        assert "Not connected" in app.query_one("#log", ConversationLog).get_all_text()
        await pilot.press("ctrl+k", *"connect")
        await pilot.pause()
        from superqode.widgets.command_palette import CommandPalette

        palette = app.query_one("#command-palette", CommandPalette)
        assert palette.filtered_commands[palette.selected_index].id == "connect", [
            command.id for command in palette.filtered_commands
        ]
        await pilot.press("enter")
        await pilot.pause()
        assert app.default_screen.has_class("connection-setup")
        assert app._connection_draft == original
        await pilot.press("escape")
        await pilot.pause()
        assert not app.default_screen.has_class("connection-setup")
        assert prompt.value == original
        assert prompt.has_focus


@pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 24)])
async def test_full_hub_keeps_results_actions_and_filter_keyboard_reachable(size):
    from textual.widgets import Button, OptionList, Select

    from superqode.app.harness_picker import harness_picker_items
    from superqode.widgets.harness_hub import HarnessHubScreen

    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        screen = HarnessHubScreen(harness_picker_items(include_all=True))
        app.push_screen(screen)
        await pilot.pause()
        results = screen.query_one("#hub-list", OptionList)
        assert results.region.height >= 6
        for target in ("#hub-use", "#hub-close", "#hub-inspect"):
            button = screen.query_one(target, Button)
            assert button.region.bottom <= size[1] - 1
            assert button.region.right <= size[0]
        selected = results.highlighted
        screen.action_inspect()
        await pilot.pause()
        detail = screen.query_one("#hub-detail-scroll")
        assert detail.has_focus and detail.max_scroll_y > 0
        await pilot.press("down")
        await pilot.pause(0.3)
        assert detail.scroll_y > 0
        assert results.highlighted == selected
        readiness = screen.query_one("#hub-readiness-select", Select)
        readiness.focus()
        await pilot.press("enter", "down", "enter")
        await pilot.pause()
        assert app.screen is screen
        assert screen.filter_name == "ready"
        assert readiness.value == "ready"
        language = screen.query_one("#hub-language-select", Select)
        language.focus()
        await pilot.press("enter", "down", "enter")
        await pilot.pause()
        assert app.screen is screen
        assert screen.language_filter
        assert language.value == screen.language_filter
        screen.action_filter_all()
        await pilot.pause()
        assert readiness.value == "all"
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert not screen.has_class("compact")
        assert language.value == screen.language_filter
