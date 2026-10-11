"""First-session recovery and interrupt behavior in the mounted terminal UI."""

import asyncio
import concurrent.futures
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from textual.document._document import Selection
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static, TextArea

from superqode.app_main import SelectionAwareInput, SuperQodeApp
from superqode.app.widgets import ConversationLog
from superqode.widgets.connection_browser import ConnectionBrowserScreen
from superqode.widgets.developer_trial import DeveloperTrialScreen


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("superqode.app.theme_bridge._CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path / "progress"))
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


class PendingModelScreen(ModalScreen):
    def compose(self):
        yield Static("Model selection is still finishing")


async def wait_for_guide(app, pilot):
    async with asyncio.timeout(5):
        while not isinstance(app.screen, DeveloperTrialScreen):
            await pilot.pause(0.1)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_help_palette_and_completion_have_actionable_shared_descriptions(size, monkeypatch):
    from superqode.command_registry import COMMAND_ROUTES, command_metadata

    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        rendered = []
        monkeypatch.setattr(
            app, "_show_command_output", lambda log, value: rendered.append(value.plain)
        )
        app._handle_command(":help", log)
        text = rendered[-1]
        assert "SuperQode TUI command" not in text
        assert "Export the conversation to a file" in text
        assert "Browse product capabilities" in text
        for root in COMMAND_ROUTES:
            assert f"    :{root}  " in text
        metadata = command_metadata()
        palette = {item.command: item.description for item in app._build_palette_commands()}
        for name in (":work", ":export", ":explore", ":rlm", ":connect status"):
            assert palette[name] == metadata[name].description
            candidates = app._static_command_candidates(name[:-1])
            candidate = next((item for item in candidates if item.value == name), None)
            assert candidate is not None, (name, [item.value for item in candidates])
            assert candidate.description == metadata[name].description
        app._handle_command(":help work", log)
        assert "    :work  " in rendered[-1]
        assert ":workspace" not in rendered[-1] and ":workflow" not in rendered[-1]
        app._handle_command(":help  MODEL  ", log)
        assert ":model reasoning" in rendered[-1]
        await pilot.pause()


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_guide_returns_after_connection_picker_finishes_and_requires_explicit_run(
    size, tmp_path, monkeypatch
):
    (tmp_path / "README.md").write_text("Project documentation")
    app = SuperQodeApp()
    runs = []
    route = ["disconnected"]
    monkeypatch.setattr(app, "_connection_target", lambda: ("runtime", "codex", "model"))
    monkeypatch.setattr(app, "_connection_fingerprint", lambda: tuple(route))
    monkeypatch.setattr(app, "_has_live_connection", lambda: route[0] != "disconnected")
    monkeypatch.setattr(app, "_handle_message", lambda text, log: runs.append(text))

    def connected(profile, log):
        assert profile.id == "codex"
        route[0] = "connected"
        app._awaiting_codex_model = True
        app.push_screen(PendingModelScreen())
        app._mark_onboarding_complete()

    monkeypatch.setattr(app, "_dispatch_connection_profile", connected)
    async with app.run_test(size=size) as pilot:
        draft = app.query_one("#prompt-input", SelectionAwareInput)
        draft.value = "Keep my existing task"
        app._handle_command(":trial", app.query_one("#log", ConversationLog))
        await pilot.pause()
        custom_task = "Read the attached README and explain the test command."
        app.screen.query_one("#trial-task", TextArea).load_text(custom_task)
        app.screen.query_one("#trial-connect", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ConnectionBrowserScreen)
        browser = app.screen
        async with asyncio.timeout(10):
            while not browser.catalog_loaded:
                await pilot.pause(0.1)
        browser.query_one("#connection-search", Input).value = "Codex CLI"
        await pilot.pause()
        options = browser.query_one("#connection-results", OptionList)
        options.highlighted = next(
            i for i, profile in enumerate(browser.matching_profiles) if profile.id == "codex"
        )
        options.focus()
        await pilot.press("enter")
        await pilot.pause(0.4)  # Longer than the original one-shot handoff timer.
        assert isinstance(app.screen, PendingModelScreen)
        assert app._trial_state().awaiting_connection
        assert not runs
        route[0] = "model-selected"  # Selecting the final model is part of setup.
        app._awaiting_codex_model = False
        app.screen.dismiss(None)
        await wait_for_guide(app, pilot)
        guide = app.screen
        assert guide.query_one("#trial-task", TextArea).text == custom_task
        assert guide.query_one("#trial-run", Button).disabled
        assert not app._trial_state().awaiting_connection
        assert draft.value == "Keep my existing task"
        assert not runs
        await guide.validate_setup().wait()
        guide.attach_context()
        await pilot.pause()
        assert not guide.query_one("#trial-run", Button).disabled
        assert not runs
        guide.action_run()
        await pilot.pause()
        assert len(runs) == 1 and custom_task in runs[0]
        assert "@README.md" in runs[0]
        assert "Keep my existing task" in app._draft_stash[-1]


async def test_cancelling_guide_connection_does_not_reopen_it_on_an_unrelated_connection(
    monkeypatch,
):
    app = SuperQodeApp()
    monkeypatch.setattr(app, "_has_live_connection", lambda: True)
    async with app.run_test() as pilot:
        app._handle_command(":trial", app.query_one("#log", ConversationLog))
        await pilot.pause()
        app.screen.query_one("#trial-connect", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ConnectionBrowserScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not app._trial_state().awaiting_connection
        app._mark_onboarding_complete()
        await pilot.pause(0.3)
        assert app.screen is app.default_screen


async def test_guide_waits_for_approval_and_busy_state_without_consuming_the_return(monkeypatch):
    app = SuperQodeApp()
    monkeypatch.setattr(app, "_has_live_connection", lambda: True)
    async with app.run_test() as pilot:
        state = app._trial_state()
        state.awaiting_connection = True
        app.is_busy = True
        app._permission_pending = True
        app._mark_onboarding_complete()
        await pilot.pause(0.3)
        assert app.screen is app.default_screen and state.awaiting_connection
        app.is_busy = False
        await pilot.pause(0.2)
        assert app.screen is app.default_screen and state.awaiting_connection
        app._permission_pending = False
        await wait_for_guide(app, pilot)
        await pilot.pause(0.3)
        assert len(app.screen_stack) == 2


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
