"""Mounted developer workflows: drafts, setup continuity, review and history."""

from types import SimpleNamespace

import pytest
from textual.widgets import Button, Input, Static

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog, ColorfulStatusBar
from superqode.app.task_review import task_review
from superqode.providers.connection_profiles import ConnectionProfile
from superqode.widgets.connection_browser import ConnectionBrowserScreen


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
async def test_typing_and_pasting_during_work_queues_once(size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        app.is_busy = True
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.focus()
        await pilot.press("h", "i")
        assert prompt.value == "hi"
        await pilot.press("enter")
        await pilot.pause()
        assert app._typeahead_queue == ["hi"]
        assert prompt.value == ""
        from textual.events import Paste

        app.post_message(Paste("second\nmessage"))
        await pilot.pause()
        assert prompt.value == "second\nmessage"
        await pilot.press("enter")
        await pilot.pause()
        assert app._typeahead_queue == ["hi", "second\nmessage"]
        app._drain_message_queue = lambda: None
        app.is_busy = False


async def test_approval_preserves_draft_and_cannot_queue_an_invalid_answer():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        log = app.query_one("#log", ConversationLog)
        app.is_busy = True
        prompt.value = "my next task"
        app._show_permission_prompt("bash", {"command": "pytest -q"}, log)
        assert prompt.value == ""
        prompt.value = "maybe"
        app.on_input_submitted(Input.Submitted(prompt, "maybe"))
        assert app._permission_pending
        assert not getattr(app, "_typeahead_queue", [])
        assert app._handle_permission_input("n")
        assert prompt.value == "my next task"
        app.is_busy = False
        await pilot.pause()


async def test_queue_delivery_preserves_unsent_draft_and_cancel_pauses_delivery():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        log = app.query_one("#log", ConversationLog)
        sent = []
        app._handle_message = lambda text, target: sent.append(text)
        app._typeahead_queue = ["queued task"]
        prompt.value = "unfinished draft"
        app._queue_paused = True
        app._cancel_requested = False
        app._drain_message_queue()
        await pilot.pause()
        assert not sent
        assert app._typeahead_queue == ["queued task"]
        app._handle_queue("send", log)
        await pilot.pause()
        assert sent == ["queued task"]
        assert prompt.value == "unfinished draft"


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_connection_back_restores_transcript_position_draft_and_runtime(size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        app._welcome_active = False
        log = app.query_one("#log", ConversationLog)
        log.clear()
        log.add_user("original task")
        # Markdown soft line breaks collapse into one paragraph. Use actual
        # paragraphs so the saved reading position stays within the viewport's
        # scroll range after the composer/setup layout settles.
        log.add_assistant("answer\n\n" * 60)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft before setup"
        await pilot.pause()
        log.scroll_to(y=5, animate=False, force=True)
        await pilot.pause()
        old_scroll = log.scroll_y
        assert old_scroll == 5
        before = [line.text for line in log.lines]
        messages = list(log._messages)
        runtime = object()
        app._pure_mode = SimpleNamespace(_runtime=runtime)
        app._show_connect_type_picker(log)
        await pilot.pause()
        assert "original task" not in "\n".join(line.text for line in log.lines)
        app.action_smart_cancel()
        await pilot.pause()
        assert [line.text for line in log.lines] == before
        assert log._messages == messages
        assert log.scroll_y == old_scroll
        assert prompt.value == "draft before setup"
        assert app._pure_mode._runtime is runtime
        assert not app.default_screen.has_class("connection-setup")


async def test_successful_setup_keeps_prior_turn_when_next_prompt_starts():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        log.reset_conversation()
        log.add_user("previous task")
        app._show_connect_type_picker(log)
        app._clear_for_workspace(log, "LOCAL")
        app._begin_conversation_transcript(log)
        assert "previous task" in "\n".join(line.text for line in log.lines)
        await pilot.pause()


async def test_small_connect_menu_exposes_all_root_options(monkeypatch):
    app = SuperQodeApp()
    monkeypatch.setattr("superqode.providers.connection_profiles.detected_chips", lambda: [])
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_type_picker(log)
        await pilot.pause()
        visible = "\n".join(line.text for line in log.lines[: log.scrollable_content_region.height])
        for index in range(1, 6):
            assert f"[{index}]" in visible
        assert "click a row" in visible


async def test_small_search_details_are_scrollable_and_actions_visible():
    profile = ConnectionProfile(
        id="demo",
        label="Demo",
        description="Details\n" * 12,
        connector="runtime",
        unavailable_hint="Recovery command",
        detect=lambda: False,
    )
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = ConnectionBrowserScreen(loader=lambda: [profile])
        app.push_screen(screen)
        for _ in range(8):
            await pilot.pause()
        scroll = screen.query_one("#connection-detail-scroll")
        assert scroll.max_scroll_y > 0
        scroll.scroll_end(animate=False)
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y
        assert "Recovery command" in str(screen.query_one("#connection-detail", Static).render())
        button = screen.query_one("#connection-select", Button)
        assert button.region.bottom <= 24
        assert not button.disabled


@pytest.mark.parametrize("route", ["codex-sdk", "acp", "builtin"])
def test_authentication_identity_is_visible_on_each_status_branch(route):
    status = ColorfulStatusBar()
    status.connection_auth = "subscription"
    if route == "builtin":
        status.byok_provider = "provider"
    else:
        status.active_runtime = route
    status.active_model = "model"
    assert "SUBSCRIPTION" in status._render_for_width(120).plain


@pytest.mark.parametrize("width", [60, 76, 80, 120])
def test_subscription_status_fits_short_terminals(width):
    from rich.cells import cell_len

    status = ColorfulStatusBar()
    status.connection_auth = "subscription"
    status.active_runtime = "codex-sdk"
    status.active_model = "example-model"
    status.active_harness = "codex"
    text = status._render_for_width(width).plain
    assert all(cell_len(line) <= width for line in text.splitlines())
    assert "BUILD" in text


def test_task_review_uses_recorded_failures_and_only_this_turns_diffs():
    outcome = task_review(
        {
            "files_modified": ["a.py"],
            "file_diffs": {
                "a.py": {"diff_text": "-old\n+new"},
                "unrelated.py": {"diff_text": "unrelated"},
            },
        },
        [
            {
                "name": "bash",
                "command": "uv run pytest -q",
                "status": "success",
                "metadata": {"exit_code": 1},
                "output": "FAILED",
            }
        ],
    )
    assert "Command failed" in outcome.summary
    assert "unrelated" not in "\n".join(outcome.details)
    assert "+new" in "\n".join(outcome.details)
    assert "Not recorded" in task_review({}, []).summary
    assert (
        "Not recorded"
        in task_review(
            {}, [{"name": "bash", "command": "echo pytest", "status": "success"}]
        ).summary
    )
    masked = task_review(
        {},
        [
            {
                "name": "bash",
                "command": "pytest || true",
                "status": "success",
                "metadata": {"exit_code": 0},
            }
        ],
    )
    assert "Passed" not in masked.summary


async def test_large_restored_history_is_bounded_and_copy_history_stays_complete():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        turns = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"history {i}"}
            for i in range(10000)
        ]
        app._replay_resumed_transcript(log, turns)
        assert len(log._messages) == 10000
        assert len(log.lines) < 1000
        assert log._history_start == 9960
        log.add_user("new task after resume")
        await pilot.pause()
        app._run_clicked_command("history-earlier")
        await pilot.pause()
        assert log._history_start == 9920
        assert log._messages[-1][1] == "new task after resume"
        assert len(log._messages) == 10001
        assert "history 9920" in "\n".join(line.text for line in log.lines)
        app._vim_search(log, "history 12")
        await pilot.pause()
        assert "history 12" in "\n".join(line.text for line in log.lines)
        assert len(log.lines) < 1000
        assert "history 0" in log.get_all_text()
        assert "history 9999" in log.get_all_text()
        app._run_clicked_command("history-later")
        await pilot.pause()
        assert log._history_end == 80
        assert len(log._messages) == 10001
        log.reset_conversation()
        assert log._history_start == 0
        assert not log._restored_history
