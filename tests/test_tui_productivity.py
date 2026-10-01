"""Actual keyboard workflows, continuous context edits and performance gates."""

import importlib.util
from pathlib import Path

import pytest
from textual.containers import ScrollableContainer
from textual.widgets import Button, Input, OptionList, TextArea
from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.app.outcomes import Outcome, OutcomeAction, OutcomeSeverity
from superqode.widgets.context_preview import ContextPreviewScreen
from superqode.widgets.connection_browser import ConnectionBrowserScreen
from superqode.providers.connection_profiles import ConnectionProfile
from superqode.widgets.outcome_screen import OutcomeScreen
from superqode.widgets.panel_shortcuts import PanelShortcuts


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
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
async def test_context_keyboard_removes_multiple_references_and_keeps_cursor(size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "@first.py @second.py explain\nthis carefully"
        prompt.cursor_position = len("@first.py @second.py explain\nthis")
        app._attached_refs = ["@first.py", "@second.py"]
        app._attachment_prefill = "@first.py @second.py "
        app._preview_next_context(app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        options = screen.query_one("#context-preview-list", OptionList)
        assert options.has_focus
        hints = screen.query_one(PanelShortcuts)
        assert "Delete" not in str(hints.render())
        await pilot.press("down", "delete")
        await pilot.pause()
        assert app.screen is screen
        assert app._attached_refs == ["@second.py"]
        assert "Delete" in str(hints.render())
        assert hints.region.bottom <= app.size.height
        assert prompt.value == "@second.py explain\nthis carefully"
        await pilot.press("delete")
        await pilot.pause()
        assert app.screen is screen
        assert app._attached_refs == []
        assert prompt.value == "explain\nthis carefully"
        assert prompt.cursor_position == len("explain\nthis")
        options.highlighted = 0
        await pilot.press("enter")
        assert screen.query_one("#context-preview-detail", TextArea).has_focus
        assert "Scroll" in str(hints.render())
        assert (
            "explain\nthis carefully" in screen.query_one("#context-preview-detail", TextArea).text
        )
        await pilot.press("tab")
        assert screen.query_one("#context-preview-back", Button).has_focus
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is app.default_screen
        assert prompt.has_focus
        assert prompt.cursor_position == len("explain\nthis")


async def test_context_mcp_removal_preserves_multiline_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "keep\n mcp://fixture/source \nmy exact layout"
        original = prompt.value
        prompt.cursor_position = len(original)
        app._attached_refs = ["mcp://fixture/source"]
        app._preview_next_context(app.query_one("#log", ConversationLog))
        await pilot.pause()
        await pilot.press("down", "delete", "escape")
        await pilot.pause()
        assert prompt.value == "keep\n  \nmy exact layout"
        assert prompt.cursor_position == len(prompt.value)
        assert app._attached_refs == []


async def test_context_image_removal_keeps_other_payloads_and_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "@source.py explain these images"
        prompt.cursor_position = len("@source.py explain")
        app._attached_refs = ["@one.png", "@two.png", "@source.py"]
        remaining_image = object()
        app._staged_images = {"@one.png": object(), "@two.png": remaining_image}
        app._attachment_prefill = "@source.py "
        app._preview_next_context(app.query_one("#log", ConversationLog))
        await pilot.pause()
        await pilot.press("down", "delete", "escape")
        await pilot.pause()
        assert app._attached_refs == ["@two.png", "@source.py"]
        assert app._staged_images == {"@two.png": remaining_image}
        assert prompt.value == "@source.py explain these images"
        assert prompt.cursor_position == len("@source.py explain")
        assert prompt.has_focus


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_connection_search_arrows_and_detail_scroll_are_independent(size):
    app = SuperQodeApp()
    profiles = [
        ConnectionProfile(
            id=f"fixture-{i}",
            label=f"Fixture {i}",
            description="Long setup guidance. " * 100,
            connector="acp",
        )
        for i in range(2)
    ]
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "unfinished draft"
        prompt.cursor_position = 4
        screen = ConnectionBrowserScreen(loader=lambda: profiles)
        app.push_screen(screen, callback=lambda _: app._ensure_input_focus())
        await pilot.pause()
        assert screen.query_one("#connection-search", Input).has_focus
        await pilot.press("down")
        assert screen.query_one("#connection-results", OptionList).highlighted == 1
        await pilot.press("up")
        assert screen.query_one("#connection-results", OptionList).highlighted == 0
        detail = screen.query_one("#connection-detail-scroll")
        detail.focus()
        await pilot.press("down")
        await pilot.pause(0.3)
        assert detail.scroll_y > 0
        assert screen.query_one("#connection-results", OptionList).highlighted == 0
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.has_focus and prompt.value == "unfinished draft"
        assert prompt.cursor_position == 4


async def test_activity_enter_activates_selected_action_and_restores_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft retained"
        prompt.cursor_position = 5
        calls = []
        app._handle_command = lambda command, log: calls.append(command)
        app._outcome_store().add(
            Outcome(
                title="Connection failed",
                summary="Fixture",
                severity=OutcomeSeverity.ERROR,
                actions=(OutcomeAction("retry", "Retry", ":connect retry"),),
            )
        )
        app._activity_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        app.screen.query_one("#activity-list", OptionList).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert calls == [":connect retry"]
        assert prompt.has_focus and prompt.value == "draft retained"
        assert prompt.cursor_position == 5


async def test_activity_without_action_enters_details_and_escape_returns_to_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft"
        app._outcome_store().add(
            Outcome(title="Done", summary="Fixture", details=("Long evidence\n" * 100,))
        )
        app._activity_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        app.screen.query_one("#activity-list", OptionList).focus()
        await pilot.press("enter")
        assert app.screen.query_one("#activity-detail-scroll", ScrollableContainer).has_focus
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.has_focus and prompt.value == "draft"


async def test_outcome_tab_enter_runs_recovery_and_escape_does_not_run_it():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft"
        calls = []
        app._handle_command = lambda command, log: calls.append(command)
        outcome = Outcome(
            title="Connection failed",
            summary="Fixture",
            severity=OutcomeSeverity.ERROR,
            actions=(OutcomeAction("retry", "Retry", ":connect retry"),),
        )
        log = app.query_one("#log", ConversationLog)
        app._present_outcome(outcome, log=log)
        await pilot.pause()
        app.screen.query_one("#outcome-content", ScrollableContainer).focus()
        await pilot.press("tab", "enter")
        await pilot.pause()
        assert calls == [":connect retry"]
        assert prompt.has_focus and prompt.value == "draft"
        app._present_outcome(outcome, log=log)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert calls == [":connect retry"]
        assert prompt.has_focus


async def test_diff_file_shortcuts_work_inside_readonly_text():
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft"
        patches = [
            (
                "Working tree",
                f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-before\n+after",
            )
            for name in ("one.py", "two.py")
        ]
        app._open_diff_review_overlay(patches)
        await pilot.pause()
        screen = app.screen
        screen.query_one("#text-area", TextArea).focus()
        await pilot.press("n")
        assert screen._index == 1
        await pilot.press("p")
        assert screen._index == 0
        await pilot.press("down")
        assert screen._index == 0
        await pilot.press("tab")
        assert screen.query_one("#prev-file", Button).has_focus
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.has_focus and prompt.value == "draft"


async def test_routine_success_is_quiet_and_failure_keeps_one_recovery_action():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        notifications = []
        app.notify = lambda *a, **kw: notifications.append((a, kw))
        log = app.query_one("#log", ConversationLog)
        app._announce_transition(
            title="Model ready", primary="Fixture", severity="success", log=log
        )
        await pilot.pause()
        assert not notifications and app.screen is app.default_screen
        assert app._outcome_store().list()[0].title == "Model ready"
        app._announce_transition(
            title="Connection failed",
            primary="Fixture",
            severity="error",
            log=log,
            guidance=":connect retry",
        )
        await pilot.pause()
        assert isinstance(app.screen, OutcomeScreen)
        assert len(app.screen.outcome.actions) == 1
        assert app.screen.outcome.actions[0].command == ":connect retry"
        await pilot.press("escape")


def test_responsiveness_gate_fails_on_stalls_and_missing_measurements():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_tui_responsiveness.py"
    spec = importlib.util.spec_from_file_location("tui_performance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = [
        {
            "size": list(size),
            "rendered_lines": 2500,
            **dict.fromkeys(module.PERFORMANCE_BUDGETS_MS, 1),
        }
        for size in ((80, 24), (120, 40))
    ]
    assert module.budget_failures({"results": results}) == []
    assert module.budget_failures({"results": [results[0], results[0]]})
    results[0]["typing_two_keys_ms"] = 2000
    assert any(
        "typing_two_keys_ms" in failure for failure in module.budget_failures({"results": results})
    )
    del results[1]["event_loop_max_delay_ms"]
    assert any(
        "event_loop_max_delay_ms" in failure
        for failure in module.budget_failures({"results": results})
    )
    results[0]["rendered_lines"] = 100000
    assert any("4,000-line" in failure for failure in module.budget_failures({"results": results}))


@pytest.mark.parametrize(
    "text",
    ["a" * 140, "界" * 140, "e\u0301" * 140, "abcdefghij " * 30],
    ids=["ascii", "wide", "combining", "word-wrap"],
)
async def test_composer_height_matches_rendered_wrapping_through_resize(text):
    """Prompt height follows terminal cells and actual word wrapping."""
    app = SuperQodeApp()
    async with app.run_test(size=(50, 30)) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = text
        prompt.cursor_position = len(text)
        await pilot.pause()
        for size in [(50, 30), (80, 30), (45, 30)]:
            await pilot.resize_terminal(*size)
            await pilot.pause()
            expected = max(
                prompt.MIN_PROMPT_HEIGHT,
                min(prompt.MAX_PROMPT_HEIGHT, prompt.wrapped_document.height),
            )
            assert prompt.size.height == expected
            assert prompt.value == text
            assert prompt.cursor_position == len(text)
