"""Resume and editing regressions that would lose a developer's working context."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import TextArea

from superqode.agent.session_manager import SessionManager
from superqode.pure_mode import PureMode
from superqode.session.harness_bridge import SessionResumeError, upsert_harness_session_meta
from superqode.sidebar import FilePreview
from superqode.widgets.file_editor import FileEditorScreen, read_editable_file, save_edited_file


def test_custom_harness_survives_a_new_process_instance(tmp_path, monkeypatch):
    from superqode.harness.loader import save_harness_spec
    from superqode.harness.templates import pipy_template

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    from dataclasses import replace

    spec = replace(pipy_template(), name="my-custom-harness")
    path = save_harness_spec(spec, tmp_path / "custom.yaml")
    original = PureMode()
    original.select_harness(path)
    original.connect("ollama", "qwen", session_id="custom-session")
    stored = SessionManager().get_session_info("custom-session")
    assert stored.harness_path == str(path.resolve())

    restored = PureMode()
    assert restored.resume_session("custom-session") == []
    assert restored._harness_path == str(path.resolve())
    assert restored._harness_session_id == "custom-session"
    assert restored._harness_spec.name == "my-custom-harness"


@pytest.mark.parametrize("failure", ["credential", "directory", "transcript", "harness"])
def test_resume_preflight_preserves_the_active_runtime(tmp_path, monkeypatch, failure):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    pure = PureMode()
    pure.connect("ollama", "qwen", session_id="active-session")
    active_runtime = pure._runtime
    active_agent = pure._agent
    upsert_harness_session_meta(
        "broken-session",
        provider="openai" if failure == "credential" else "ollama",
        model="qwen",
        harness_id="nonexistent-harness" if failure == "harness" else "pipy",
        working_directory=tmp_path / "missing" if failure == "directory" else tmp_path,
        backend_session_path=str(tmp_path / "missing.jsonl") if failure == "transcript" else "",
    )
    with pytest.raises(SessionResumeError):
        pure.resume_session("broken-session")
    assert pure._runtime is active_runtime
    assert pure._agent is active_agent
    assert pure.get_current_session_id() == "active-session"
    assert pure._harness_definition.id == "core"


def test_failed_switch_does_not_mark_target_active():
    from superqode.app.mixins.switchboard import SwitchboardMixin

    board = Mock()
    board.info.return_value = {"session_id": "target"}
    host = SimpleNamespace(
        _switchboard=lambda: board, _handle_resume_session=Mock(return_value=False)
    )
    SwitchboardMixin._switchboard_switch(host, ["target"], Mock())
    board.switch.assert_not_called()
    host._handle_resume_session.return_value = True
    SwitchboardMixin._switchboard_switch(host, ["target"], Mock())
    board.switch.assert_called_once_with("target")


def test_busy_resume_does_not_touch_the_runtime():
    from superqode.app.mixins.slash_commands import SlashCommandMixin

    host = SimpleNamespace(is_busy=True)
    log = Mock()
    assert SlashCommandMixin._handle_resume_session(host, "target", log) is False
    assert "active turn" in log.add_error.call_args.args[0]


def test_preview_is_bounded_and_reads_external_edits(tmp_path):
    path = tmp_path / "huge.py"
    path.write_text("x = 1\n" * 100000)
    preview = FilePreview()
    rendered = preview._render_file_content(path)
    assert len(rendered.code) < 66000
    assert "Preview limited" in rendered.code
    path.write_text("fresh = True\n")
    assert "fresh = True" in preview._render_file_content(path).code


def test_save_preserves_crlf_and_executable_mode(tmp_path):
    path = tmp_path / "script.sh"
    path.write_bytes(b"echo old\r\n")
    path.chmod(0o755)
    original = read_editable_file(path)
    save_edited_file(path, original, "echo new\n")
    assert path.read_bytes() == b"echo new\r\n"
    assert path.stat().st_mode & 0o777 == 0o755
    assert sorted(p.name for p in tmp_path.iterdir()) == ["script.sh"]


def test_save_rejects_concurrent_changes(tmp_path):
    path = tmp_path / "file.py"
    path.write_text("original")
    original = read_editable_file(path)
    path.write_text("agent's edit")
    with pytest.raises(ValueError, match="changed on disk"):
        save_edited_file(path, original, "my draft")
    assert path.read_text() == "agent's edit"


@pytest.mark.parametrize("data", [b"\0binary", b"\xff", b"x" * (1024 * 1024 + 1)])
def test_editor_rejects_unsafe_input(tmp_path, data):
    path = tmp_path / "file"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        read_editable_file(path)


async def test_editor_keyboard_save_and_dirty_close(tmp_path):
    path = tmp_path / "file.py"
    path.write_text("old\n")
    app = App()
    async with app.run_test() as pilot:
        screen = FileEditorScreen(path)
        app.push_screen(screen)
        await pilot.pause()
        editor = screen.query_one(TextArea)
        editor.load_text("saved\n")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert path.read_text() == "saved\n"
        editor.load_text("discarded\n")
        await pilot.pause()
        await pilot.press("escape")
        assert app.screen is screen
        await pilot.press("escape")
        assert app.screen is not screen
        assert path.read_text() == "saved\n"


async def test_preview_reload_same_file(tmp_path):
    path = tmp_path / "file.py"
    path.write_text("before\n")

    class PreviewApp(App):
        def compose(self) -> ComposeResult:
            yield FilePreview()

    app = PreviewApp()
    async with app.run_test() as pilot:
        preview = app.query_one(FilePreview)
        preview.set_file(path)
        await app.workers.wait_for_complete()
        await pilot.pause()
        path.write_text("after\n")
        preview.set_file(path)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert preview.query_one("#preview-syntax").content.code == "after\n"
        preview._show_preview(preview._preview_generation - 1, "stale result")
        assert preview.query_one("#preview-syntax").content.code == "after\n"


async def test_sidebar_opens_editor_and_refreshes_after_save(tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp
    from superqode.sidebar import CollapsibleSidebar
    from superqode.app.widgets import ConversationLog

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)
    path = tmp_path / "edit.py"
    path.write_text("old\n")
    app = SuperQodeApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        sidebar = app.query_one(CollapsibleSidebar)
        if not app.sidebar_visible:
            app.action_toggle_sidebar()
        preview = sidebar.query_one(FilePreview)
        preview.set_file(path)
        sidebar.current_view = "code"
        workers = [w for w in app.workers if w.group == "file-preview"]
        if workers:
            await app.workers.wait_for_complete(workers)
        await pilot.pause()
        log = app.query_one(ConversationLog)
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, FileEditorScreen)
        app.screen.query_one(TextArea).load_text("new\n")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("escape")
        workers = [w for w in app.workers if w.group == "file-preview"]
        if workers:
            await app.workers.wait_for_complete(workers)
        await pilot.pause()
        assert app.query_one(ConversationLog) is log
        assert path.read_text() == "new\n"
        assert preview.query_one("#preview-syntax").content.code == "new\n"
        await pilot.resize_terminal(80, 30)
        await pilot.pause()
        assert app.query_one("#content").size.width >= 40
        app.action_expand_sidebar()
        await pilot.pause()
        assert sidebar._width <= 39
        assert app.query_one("#content").size.width >= 40


def test_interrupted_metadata_replace_preserves_previous_record(tmp_path, monkeypatch):
    from superqode.agent import session_manager

    manager = SessionManager(str(tmp_path / "sessions"))
    manager.start_session("durable", provider="ollama", model="old")
    metadata = manager.get_session_info("durable")
    metadata.model = "new"

    def fail_replace(*args):
        raise OSError("interrupted")

    monkeypatch.setattr(session_manager.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted"):
        manager.store._save_metadata(metadata)
    assert manager.get_session_info("durable").model == "old"
    assert not list((tmp_path / "sessions").glob("*.tmp"))


async def test_fresh_tui_resume_restores_controls_and_isolates_transcript(tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp
    from superqode.app.widgets import ConversationLog, ModeBadge

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)
    manager = SessionManager()
    manager.start_session("saved-session", provider="ollama", model="qwen", harness_id="core")
    manager.add_user_message("remember this request")
    manager.add_assistant_message("saved response")
    app = SuperQodeApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        log = app.query_one(ConversationLog)
        log.add_user("other session private text")
        log._session_tool_calls.append({"name": "old-tool"})
        app._awaiting_byok_provider = True
        assert app._handle_resume_session("saved-session", log) is True
        await pilot.pause()
        assert app.current_mode == "local"
        assert app._awaiting_byok_provider is False
        assert app.query_one(ModeBadge).model == "qwen"
        pure = app._pure_mode
        assert callable(pure.on_tool_call)
        assert callable(pure.on_tool_result)
        assert callable(pure.on_permission_request)
        assert pure.get_current_session_id() == "saved-session"
        assert "remember this request" in str(log._messages)
        assert "other session private text" not in str(log._messages)
        assert log._session_tool_calls == []
        assert [m.content for m in pure._agent._session_manager.get_messages()] == [
            "remember this request",
            "saved response",
        ]


def test_stream_boundary_scan_matches_reference():
    from superqode.app.widgets import ConversationLog

    samples = [
        "first\n\nsecond",
        "```python\na\n\nb\n\n```\n\nlast",
        "a\n\n```\nx\n\n",
        "``````\n\n",
        "\n\n" * 4000,
    ]
    for text in samples:
        safe = start = 0
        while (index := text.find("\n\n", start)) >= 0:
            start = index + 2
            if text.count("```", 0, start) % 2 == 0:
                safe = start
        assert ConversationLog._stable_markdown_split(text) == safe
