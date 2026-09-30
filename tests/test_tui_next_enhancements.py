"""Task ownership, recovery, context controls and incremental stream regressions."""

from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
from textual.widgets import Button, OptionList, TextArea, Static
from superqode.app.task_changes import TaskChanges
from superqode.app.widgets import ConversationLog, StreamingThinkingIndicator
from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.widgets.context_preview import ContextPreviewScreen
from superqode.widgets.connection_browser import ConnectionBrowserScreen


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True
        ).stdout

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "file.txt").write_text("original\n")
    git("add", ".")
    git("commit", "-m", "initial")
    return tmp_path, git


def test_task_diff_and_undo_preserve_staged_and_unstaged_prior_edits(repo):
    root, git = repo
    path = root / "file.txt"
    path.write_text("staged\n")
    git("add", "file.txt")
    path.write_text("my unfinished edit\n")
    (root / "unrelated.txt").write_text("my notes\n")
    index = git("ls-files", "--stage")
    task = TaskChanges(root).capture()
    path.write_text("agent result\n")
    task.finish(["file.txt"])
    assert set(task.diffs) == {"file.txt"}
    patch = task.diffs["file.txt"]["diff_text"]
    assert "-my unfinished edit" in patch
    assert "-original" not in patch and "-staged" not in patch
    assert task.diffs["file.txt"]["preexisting"]
    task.undo("file.txt")
    assert path.read_text() == "my unfinished edit\n"
    assert (root / "unrelated.txt").read_text() == "my notes\n"
    assert git("ls-files", "--stage") == index


def test_task_detects_shell_edits_and_refuses_to_overwrite_later_changes(repo):
    root, _ = repo
    task = TaskChanges(root).capture()
    (root / "file.txt").write_text("same number of lines\n")
    (root / "new.txt").write_text("created by shell\n")
    task.finish([])
    assert set(task.diffs) == {"file.txt", "new.txt"}
    (root / "file.txt").write_text("later user edit\n")
    with pytest.raises(ValueError, match="changed since"):
        task.undo("file.txt")
    assert (root / "file.txt").read_text() == "later user edit\n"
    task.undo("new.txt")
    assert not (root / "new.txt").exists()


def test_task_undo_restores_deleted_file_and_rejects_symlink_substitution(repo):
    root, _ = repo
    task = TaskChanges(root).capture()
    path = root / "file.txt"
    path.unlink()
    task.finish([])
    task.undo("file.txt")
    assert path.read_text() == "original\n"
    task = TaskChanges(root).capture()
    path.write_text("agent change\n")
    task.finish([])
    outside = root.parent / "outside.txt"
    outside.write_text("leave alone")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        task.undo("file.txt")
    assert outside.read_text() == "leave alone"


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 1000])
def test_incremental_markdown_handles_split_fences_without_duplicate_output(chunk_size):
    text = "First paragraph.\n\n```python\n" + "print(1)\n\n" * 100 + "```\n\nFinal paragraph.\n\n"
    log = ConversationLog()
    log.reset_response_stream()
    for start in range(0, len(text), chunk_size):
        log._streaming_response += text[start : start + chunk_size]
        assert log._incremental_markdown_split() == log._stable_markdown_split(
            log._streaming_response
        )


@pytest.fixture
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
async def test_context_preview_removes_reference_without_losing_draft(quiet, size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "@file.txt explain this carefully"
        app._attached_refs = ["@file.txt"]
        app._attachment_prefill = "@file.txt "
        app._preview_next_context(app.query_one("#log", ConversationLog))
        await pilot.pause()
        assert isinstance(app.screen, ContextPreviewScreen)
        options = app.screen.query_one("#context-preview-list", OptionList)
        options.highlighted = 1
        await pilot.pause()
        remove = app.screen.query_one("#context-preview-remove", Button)
        assert not remove.disabled
        assert remove.region.bottom <= size[1]
        app.screen.remove_selected()
        await pilot.pause()
        assert prompt.value.strip() == "explain this carefully"
        assert app._attached_refs == []


async def test_failed_connection_restores_transcript_draft_and_retry_target(quiet, monkeypatch):
    from superqode.agents import discovery

    async def unavailable(_):
        raise RuntimeError("fixture startup failure")

    monkeypatch.setattr(discovery, "get_agent_by_short_name_async", unavailable)
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        log.add_user("existing conversation")
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "unfinished draft"
        app._begin_connection_view(log)
        await app._connect_agent.__wrapped__(app, "fixture-agent")
        await pilot.pause()
        assert prompt.value == "unfinished draft"
        assert any(m[1] == "existing conversation" for m in log._messages)
        assert app._connection_retry_target == ("acp", ("fixture-agent", None))
        assert app._connection_attempt_state == "Failed"
        assert app.screen.outcome.actions[0].command == ":connect retry"
        app.screen.action_close()
        await pilot.pause()


async def test_catalog_retry_preserves_search(quiet):
    attempts = []

    def loader():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("fixture")
        return []

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = ConnectionBrowserScreen(query="retained filter", loader=loader)
        app.push_screen(screen)
        await pilot.pause()
        assert screen.load_failed
        screen.retry_load()
        await pilot.pause()
        assert screen.catalog_loaded and not screen.load_failed
        from textual.widgets import Input

        assert screen.query_one("#connection-search", Input).value == "retained filter"
        screen.action_close()


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_diff_task_undo_controls_fit_and_restore_baseline(quiet, repo, monkeypatch, size):
    root, _ = repo
    monkeypatch.chdir(root)
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        app._begin_task_changes()
        (root / "file.txt").write_text("agent result\n")
        files = ["file.txt"]
        app._compute_file_diffs(files)
        app._handle_command(":diff task", app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        undo = screen.query_one("#undo-task-file", Button)
        close = screen.query_one("#close-btn", Button)
        assert undo.region.bottom <= size[1] and close.region.right <= size[0]
        assert "-original" in screen.query_one("#text-area", TextArea).text
        screen.action_undo_current()
        assert (root / "file.txt").read_text() == "agent result\n"
        screen.action_undo_current()
        assert (root / "file.txt").read_text() == "original\n"
        screen.dismiss()


async def test_running_status_uses_observed_tools_and_approval_state(quiet):
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        indicator = app.query_one("#streaming-thinking", StreamingThinkingIndicator)
        log = app.query_one("#log", ConversationLog)
        indicator.begin()
        log.add_tool_call("bash", "running", command="pytest -q")
        await pilot.pause()
        assert "Executing" in indicator.render().plain
        assert "pytest -q" in indicator.render().plain
        app._permission_pending = True
        assert "Awaiting approval" in indicator.render().plain
        app._permission_pending = False
        log.clear_running_tools()
        indicator.status = "Receiving response"
        assert "Receiving response" in indicator.render().plain
        indicator.end()


def test_task_baseline_preserves_clean_crlf_working_files(repo):
    root, git = repo
    git("config", "core.autocrlf", "true")
    path = root / "file.txt"
    path.write_bytes(b"original\r\n")
    assert not git("diff", "--name-only")
    task = TaskChanges(root).capture()
    path.write_bytes(b"agent result\r\n")
    task.finish(["file.txt"])
    task.undo("file.txt")
    assert path.read_bytes() == b"original\r\n"


def test_large_dirty_file_has_no_undo_and_budget_is_bounded(repo, monkeypatch):
    root, _ = repo
    monkeypatch.setattr(TaskChanges, "FILE_LIMIT", 10)
    (root / "file.txt").write_text("my very large unfinished edit\n")
    task = TaskChanges(root).capture()
    (root / "file.txt").write_text("agent\n")
    task.finish(["file.txt"])
    with pytest.raises(ValueError, match="No restorable"):
        task.undo("file.txt")
    assert (root / "file.txt").read_text() == "agent\n"
    assert task.used <= task.MEMORY_LIMIT


async def test_failed_model_initialization_retains_previous_session(quiet, monkeypatch):
    app = SuperQodeApp()
    from types import SimpleNamespace

    prior = SimpleNamespace(
        session=SimpleNamespace(provider="old", model="old-model", connected=True),
        _agent="old-agent",
    )
    app._pure_mode = prior

    def fail(*args, **kwargs):
        prior.session.provider = "broken"
        prior._agent = None
        raise ValueError("fixture model setup failed")

    monkeypatch.setattr(app, "_connect_byok_mode_impl", fail)
    async with app.run_test() as pilot:
        app._connect_byok_mode("fixture", "new-model", app.query_one("#log", ConversationLog))
        await pilot.pause()
        assert prior.session.provider == "old"
        assert prior.session.model == "old-model"
        assert prior._agent == "old-agent"
        assert app._connection_retry_target == ("model", ("fixture", "new-model"))
        app.screen.action_close()


def test_task_review_preserves_paths_with_spaces(repo):
    from superqode.app.mixins.helper_diff_review import HelperDiffReviewMixin

    root, git = repo
    path = root / "my file.txt"
    path.write_text("before\n")
    git("add", ".")
    git("commit", "-m", "space path")
    task = TaskChanges(root).capture()
    path.write_text("after\n")
    task.finish(["my file.txt"])
    entry = HelperDiffReviewMixin()._diff_review_entries(
        [("Task changes", task.diffs["my file.txt"]["diff_text"])]
    )[0]
    assert entry["path"] == "my file.txt"
    task.undo(entry["path"])
    assert path.read_text() == "before\n"


async def test_failed_acp_model_setup_restores_selected_agent_and_chrome(quiet, monkeypatch):
    from superqode.agents import discovery
    from superqode.app.session_state import get_session
    from superqode.app.widgets import ColorfulStatusBar, ModeBadge

    async def found(_):
        return {"short_name": "codex", "name": "Fixture Codex"}

    monkeypatch.setattr(discovery, "get_agent_by_short_name_async", found)
    app = SuperQodeApp()
    previous_session = dict(vars(get_session()))
    try:
        async with app.run_test() as pilot:
            old_agent = {"short_name": "old-agent", "name": "Old agent"}
            get_session().connect_to_agent(old_agent)
            app.current_agent = "old-agent"
            app.current_model = "old-model"
            badge = app.query_one("#mode-badge", ModeBadge)
            badge.agent = "old-agent"
            status = app.query_one("#status-bar", ColorfulStatusBar)
            status.active_model = "old-model"

            def fail(*args):
                badge.agent = "codex"
                status.active_model = "new-model"
                raise RuntimeError("fixture model picker failed")

            monkeypatch.setattr(app, "_show_codex_models_selection", fail)
            await app._connect_agent.__wrapped__(app, "codex")
            await pilot.pause()
            assert get_session().connected_agent == old_agent
            assert app.current_agent == badge.agent == "old-agent"
            assert app.current_model == status.active_model == "old-model"
            app.screen.action_close()
    finally:
        vars(get_session()).clear()
        vars(get_session()).update(previous_session)


def test_task_never_deletes_preexisting_ignored_files(repo):
    root, _ = repo
    (root / ".gitignore").write_text("private.txt\n")
    path = root / "private.txt"
    path.write_text("preexisting private content\n")
    task = TaskChanges(root).capture()
    path.write_text("agent modified private content\n")
    task.finish(["private.txt"])
    assert "baseline or preview unavailable" in task.diffs["private.txt"]["diff_text"]
    with pytest.raises(ValueError, match="No restorable"):
        task.undo("private.txt")
    assert path.read_text() == "agent modified private content\n"
