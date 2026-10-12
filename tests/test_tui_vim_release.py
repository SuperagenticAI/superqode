"""Vim preferences and panel navigation preserve developer data and decisions."""

import asyncio
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Input, OptionList, Select, TextArea
from textual.widgets.text_area import Selection

from superqode import design_system as ds
from superqode.app import theme_bridge
from superqode.app.mixins.helper_vim import HelperVimMixin
from superqode.app.widgets import ConversationLog
from superqode.app_main import SelectionAwareInput, SuperQodeApp
from superqode.widgets.connection_browser import ConnectionBrowserScreen
from superqode.widgets.context_preview import ContextItem, ContextPreviewScreen
from superqode.widgets.hotkeys import HotkeysScreen


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    registry = dict(ds.THEMES)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(theme_bridge, "_CONFIG_PATH", tmp_path / ".superqode/config.json")
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1")
    monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path / "progress"))
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)
    yield
    ds.THEMES.clear()
    ds.THEMES.update(registry)
    theme_bridge.apply_theme("superqode")


def config_file(content):
    path = theme_bridge._CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.parametrize(
    "value,enabled",
    [(True, True), (False, False), ("false", False), ("true", False), (1, False), ([], False)],
)
def test_vim_load_accepts_json_booleans_only(value, enabled, monkeypatch):
    monkeypatch.delenv("SUPERQODE_VIM_MODE")
    config_file(json.dumps({"vim_mode": value}).encode())
    assert HelperVimMixin()._load_vim_preference() is enabled


@pytest.mark.parametrize(
    "content",
    [
        b'{"theme":"nord","appearance":',
        b"[]",
        b"null",
        b"\xff",
        b" " * (theme_bridge.MAX_CONFIG_BYTES + 1),
    ],
    ids=["incomplete-object", "array", "null", "invalid-utf8", "oversized"],
)
def test_vim_save_retains_invalid_configuration(content):
    path = config_file(content)
    error = HelperVimMixin()._save_vim_preference(True)
    assert error and "this session" in error
    assert path.read_bytes() == content


def test_vim_save_preserves_unrelated_settings_and_failed_replace(monkeypatch):
    original = {"theme": "nord", "appearance": {"motion": "reduced"}, "custom": {"keep": True}}
    path = config_file(json.dumps(original).encode())
    helper = HelperVimMixin()
    assert helper._save_vim_preference(True) is None
    assert json.loads(path.read_text()) == {**original, "vim_mode": True}
    saved = path.read_bytes()

    def refuse_replace(*args):
        raise PermissionError("Configuration is read-only")

    monkeypatch.setattr("superqode.theming.os.replace", refuse_replace)
    assert "could not be saved" in helper._save_vim_preference(False)
    assert path.read_bytes() == saved
    assert list(path.parent.iterdir()) == [path]


async def test_vim_toggle_reports_session_only_change_without_losing_config():
    original = b'{"theme":"nord","appearance":'
    path = config_file(original)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        assert app._vim_config_path() == path
        assert path.read_bytes() == original
        log = app.query_one("#log", ConversationLog)
        app._vim_cmd("on", log)
        assert app._vim_enabled()
        assert any(
            role == "warning" and "this session" in text for role, text, _agent in log._messages
        )
        app._vim_cmd("off", log)
        await pilot.pause()
        assert not app.query_one("#prompt-input", SelectionAwareInput).read_only
        assert path.read_bytes() == original


def panel_for(kind):
    if kind == "connections":
        profiles = [
            SimpleNamespace(
                id=f"profile-{i:02}", label=f"Profile {i:02}", description="Test profile", badges=()
            )
            for i in range(30)
        ]
        return ConnectionBrowserScreen(loader=lambda: profiles)
    if kind == "hotkeys":
        return HotkeysScreen([("app", f"f{i}", f"action_{i}", f"Action {i}") for i in range(30)])
    return ContextPreviewScreen(
        [
            ContextItem(f"Context {i}", "\n".join(f"Line {line}" for line in range(100)))
            for i in range(30)
        ]
    )


@pytest.mark.parametrize("kind", ["connections", "hotkeys", "context"])
@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_panel_vim_navigation_preserves_draft_and_original_mode(kind, size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        draft = app.query_one("#prompt-input", SelectionAwareInput)
        draft.value = "Keep my next task\nand its formatting"
        await app.push_screen(panel_for(kind))
        if kind == "connections":
            async with asyncio.timeout(10):
                while not app.screen.catalog_loaded:
                    await pilot.pause(0.1)
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        if kind == "hotkeys":
            assert options.highlighted == 0
        options.focus()
        options.highlighted = 0
        await pilot.press("j")
        assert options.highlighted == 1
        await pilot.press("k")
        assert options.highlighted == 0
        await pilot.press("G")
        assert options.highlighted == 29
        await pilot.press("g")
        assert options.highlighted == 29
        await pilot.press("g")
        assert options.highlighted == 0
        await pilot.press("ctrl+d")
        assert options.highlighted > 0
        await pilot.press("ctrl+u")
        assert options.highlighted == 0
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert draft.value == "Keep my next task\nand its formatting"
        assert app._vim_input_mode == "normal"


async def test_vim_panel_search_is_text_and_hidden_decisions_remain_pending():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._permission_pending = True
        app._pending_plan_status = "pending"
        app._pending_plan_content = "A plan awaiting approval"
        app.push_screen(panel_for("hotkeys"))
        await pilot.pause()
        search = app.screen.query_one(Input)
        await pilot.press(*"jkgyn")
        assert search.value == "jkgyn"
        assert app._permission_pending
        assert app._pending_plan_status == "pending"
        search.value = ""
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        options.focus()
        options.highlighted = 0
        await pilot.press("j", "k")
        assert options.highlighted == 0
        assert app._permission_pending
        await pilot.press("escape")
        assert app._permission_pending, "Closing help must not reject a hidden approval"


async def test_vim_read_only_detail_scrolls_without_changing_content():
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(panel_for("context"))
        await pilot.pause()
        detail = app.screen.query_one(TextArea)
        content = detail.text
        detail.focus()
        await pilot.press("j", "ctrl+d")
        await pilot.pause()
        assert detail.scroll_y > 1
        await pilot.press("G")
        await pilot.pause()
        assert detail.scroll_y == detail.max_scroll_y
        await pilot.press("g", "g")
        await pilot.pause()
        assert detail.scroll_y == 0
        assert detail.text == content


async def test_vim_theme_navigation_previews_and_escape_restores_workspace():
    from superqode.app.constants import THEME

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        draft = app.query_one("#prompt-input", SelectionAwareInput)
        draft.value = "Keep my theme draft"
        original = dict(THEME)
        app._handle_theme("", app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        options = screen.query_one("#theme-list", OptionList)
        options.focus()
        await pilot.press("G")
        assert options.highlighted == options.option_count - 1
        await pilot.press("g", "g", "j")
        await pilot.pause()
        assert options.highlighted == 1
        assert screen._preview_name == screen._names[1]
        await pilot.press("escape")
        await pilot.pause()
        assert dict(THEME) == original
        assert draft.value == "Keep my theme draft"


async def test_vim_editable_task_and_expanded_settings_select_keep_their_own_keys():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._trial_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        task = app.screen.query_one("#trial-task", TextArea)
        task.load_text("")
        task.focus()
        await pilot.press(*"jkg")
        assert task.text == "jkg"
        await pilot.press("escape")
        app._appearance_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        select = app.screen.query_one("#appearance-density", Select)
        select.focus()
        await pilot.press("enter")
        await pilot.pause()
        options = select.query_one(OptionList)
        before = options.highlighted
        await pilot.press("j")
        assert options.highlighted != before
        await pilot.press("enter")
        await pilot.pause()
        assert select.value == "compact"


async def test_panel_vim_binding_is_optional_and_rebindable(monkeypatch):
    keymap = theme_bridge._CONFIG_PATH.parent / "keybindings.json"
    keymap.parent.mkdir(parents=True)
    keymap.write_text(json.dumps({"app": {"panel_vim_down": "n"}}))
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app.push_screen(panel_for("hotkeys"))
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        options.focus()
        options.highlighted = 0
        await pilot.press("j")
        assert options.highlighted == 0
        await pilot.press("n")
        assert options.highlighted == 1
        app._vim_experience_enabled = False
        await pilot.press("n")
        assert options.highlighted == 1
        await pilot.press("down")
        assert options.highlighted == 2


async def test_first_task_welcome_link_opens_guide_without_starting_a_connection(monkeypatch):
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        draft = app.query_one("#prompt-input", SelectionAwareInput)
        draft.value = "My existing draft"
        connections = []
        monkeypatch.setattr(
            app, "_dispatch_connection_profile", lambda *args: connections.append(args)
        )
        app._run_clicked_command("trial")
        await pilot.pause()
        assert app.screen.query_one("#trial-connect").label.plain == "Choose connection"
        assert not connections
        assert draft.value == "My existing draft"
        await pilot.press("escape")
        assert draft.value == "My existing draft"


@pytest.mark.parametrize("prefix", [":", "/", "?"])
@pytest.mark.parametrize("cancel", ["escape", "ctrl+["])
async def test_vim_line_cancel_restores_multiline_draft_and_selection(prefix, cancel):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        original = "Keep this task\nand its selected context"
        selection = Selection((0, 5), (1, 7))
        prompt.value = original
        prompt.selection = selection
        await pilot.press(prefix)
        await pilot.press(*"help")
        app._draft_revision = 0
        state, _ = app._draft_snapshot()
        assert state["text"] == original, "Recovery must save the task, not the command line"
        app._decision_draft = (prompt.value, prompt.cursor_location)
        state, _ = app._draft_snapshot()
        assert state["text"] == original, "An approval must not persist the scratch line either"
        app._decision_draft = None
        await pilot.press(cancel)
        assert prompt.value == original
        assert prompt.selection == selection
        assert prompt.read_only
        assert app._vim_input_mode == "normal"
        assert not app._prompt_completion_visible
        await pilot.press("i")
        assert not prompt.read_only
        assert prompt.selection == selection


@pytest.mark.parametrize("line", [":vim status", "/help", "?help"])
async def test_vim_line_submit_restores_task_and_search_does_not_run_slash_commands(line):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        log = app.query_one("#log", ConversationLog)
        log.add_info("Some help reviewing the code")
        original = "Next task\nwith a draft"
        selection = Selection.cursor((1, 3))
        prompt.value = original
        prompt.selection = selection
        await pilot.press(line[0])
        await pilot.press(*line[1:])
        await pilot.press("enter")
        await pilot.pause()
        assert prompt.value == original
        assert prompt.selection == selection
        assert app._vim_input_mode == "normal"
        if line[0] != ":":
            assert app._vim_search_query == "help"
            assert app._vim_search_matches


async def test_vim_connection_picker_keeps_draft_out_of_selection_then_restores_on_back():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        original = "Do this after connecting"
        selection = Selection.cursor((0, 4))
        prompt.value = original
        prompt.selection = selection
        await pilot.press(":", *"connect", "enter")
        await pilot.pause()
        assert app._awaiting_connect_type
        assert prompt.value == ""
        await pilot.press("j")
        assert app._byok_highlighted_connect_type_index == 1
        await pilot.press("escape")
        await pilot.pause()
        assert not app._awaiting_connect_type
        assert prompt.value == original
        assert prompt.selection == selection


@pytest.mark.parametrize("keys", [("l",), ("ctrl+w", "l")])
async def test_vim_pane_return_is_explicit_and_background_focus_keeps_sidebar(keys):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my task"
        await pilot.press("h")
        await pilot.pause()
        sidebar = app.query_one("#sidebar")
        assert app.focused.id == "file-tree"
        app._ensure_input_focus()
        assert app.focused.id == "file-tree"
        await pilot.press("h")
        assert sidebar.current_view == "files", "Vim h must not select the History tab"
        await pilot.press(*keys)
        assert app.focused is prompt
        assert app.sidebar_visible
        assert prompt.value == "Keep my task"


async def test_vim_sidebar_search_preserves_ordinary_typing_and_escape():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.press("h")
        await pilot.pause()
        app.query_one("#sidebar").action_toggle_search()
        await pilot.pause()
        search = app.query_one("#search-input", Input)
        search.focus()
        await pilot.press(*"hjklg")
        assert search.value == "hjklg"
        assert app.focused is search


async def test_vim_off_retains_typing_and_sidebar_shortcuts(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        await pilot.press(*"hjkl:q@/?")
        assert prompt.value == "hjkl:q@/?"
        assert not prompt.read_only
        app.action_sidebar_files()
        await pilot.pause()
        await pilot.press("h")
        assert app.query_one("#sidebar").current_view == "history"
        assert not app._vim_workspace_navigation_active("l")


@pytest.mark.parametrize("entry", ["ctrl+e", ":edit external"])
async def test_vim_external_editor_round_trip_preserves_markdown_without_sending(
    entry, monkeypatch
):
    monkeypatch.setenv("EDITOR", '"my-editor" --foreground')
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        original = "# Task\n\nKeep my café draft\n"
        edited = "# Revised task\n\nReview before sending\n"
        prompt.value = original
        sent, files, commands = [], [], []
        monkeypatch.setattr(app, "_handle_message", lambda message, log: sent.append(message))
        monkeypatch.setattr(app, "suspend", nullcontext)

        def editor(cmd, **kwargs):
            path = Path(cmd[-1])
            assert path.read_text(encoding="utf-8") == original
            files.append(path)
            commands.append(cmd)
            path.write_text(edited, encoding="utf-8")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("subprocess.run", editor)
        if entry == "ctrl+e":
            await pilot.press(entry)
        else:
            await pilot.press(":", *"edit external", "enter")
        assert commands, app.query_one("#log", ConversationLog)._messages
        assert commands[0][:-1] == ["my-editor", "--foreground"]
        assert prompt.value == edited
        assert app._vim_input_mode == "insert"
        assert not prompt.read_only
        assert not sent
        assert all(not path.exists() for path in files)


@pytest.mark.parametrize("failure", ["exit", "missing", "invalid-utf8"])
async def test_vim_editor_failure_keeps_task_and_cleans_temporary_file(failure, monkeypatch):
    monkeypatch.setenv("EDITOR", "my-editor")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep the original task"
        selection = Selection.cursor((0, 5))
        prompt.selection = selection
        files = []
        monkeypatch.setattr(app, "suspend", nullcontext)

        def editor(cmd, **kwargs):
            path = Path(cmd[-1])
            files.append(path)
            if failure == "missing":
                raise FileNotFoundError("Editor not found")
            if failure == "invalid-utf8":
                path.write_bytes(b"\xff")
                return SimpleNamespace(returncode=0)
            path.write_text("Partial changes")
            return SimpleNamespace(returncode=1)

        monkeypatch.setattr("subprocess.run", editor)
        await pilot.press(":", *"edit external", "enter")
        assert prompt.value == "Keep the original task"
        assert prompt.selection == selection
        assert all(not path.exists() for path in files)


async def test_vim_off_keeps_existing_external_editor_submission(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.setenv("EDITOR", "my-editor")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        sent = []
        monkeypatch.setattr(app, "suspend", nullcontext)
        monkeypatch.setattr(app, "_handle_message", lambda message, log: sent.append(message))

        def editor(cmd, **kwargs):
            Path(cmd[-1]).write_text("The edited task")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("subprocess.run", editor)
        app.action_open_editor()
        assert sent == ["The edited task"]
        assert app.query_one("#prompt-input", SelectionAwareInput).value == ""


async def test_disabling_vim_from_command_line_restores_unsent_task():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep this when Vim is disabled"
        await pilot.press(":", *"vim off", "enter")
        assert not app._vim_enabled()
        assert prompt.value == "Keep this when Vim is disabled"
        assert not prompt.read_only
        await pilot.press("end", "!")
        assert prompt.value.endswith("!")


async def test_disabling_vim_while_search_is_open_does_not_leave_a_search_handler(monkeypatch):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "An ordinary task"
        await pilot.press("/", *"help")
        app._vim_cmd("off", app.query_one("#log", ConversationLog))
        assert prompt.value == "An ordinary task"
        assert not prompt.read_only
        sent = []
        monkeypatch.setattr(app, "_handle_message", lambda message, log: sent.append(message))
        await pilot.press("enter")
        assert sent == ["An ordinary task"]


@pytest.mark.parametrize("vim", [False, True])
async def test_plain_edit_keeps_its_existing_previous_task_action(vim, monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1" if vim else "0")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        called = []
        monkeypatch.setattr(app, "_edit_last_message", lambda log: called.append(True))
        if vim:
            await pilot.press(":", *"edit", "enter")
        else:
            await pilot.press(*":edit", "enter")
        assert called == [True]


@pytest.mark.parametrize("vim", [False, True])
async def test_approval_and_operation_cancel_keep_priority_over_vim(vim, monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1" if vim else "0")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        decisions, cancellations = [], []
        monkeypatch.setattr(
            app, "_handle_permission_input", lambda answer: decisions.append(answer)
        )
        monkeypatch.setattr(app, "action_cancel_agent", lambda: cancellations.append(True))
        app._permission_pending = True
        await pilot.press("y")
        assert decisions == ["y"]
        await pilot.press("escape")
        assert cancellations == [True]
        app._permission_pending = False
        app.is_busy = True
        await pilot.press("escape")
        assert cancellations == [True, True]
        app.is_busy = False


@pytest.mark.parametrize("vim", [False, True])
async def test_ctrl_f_uses_vim_paging_only_in_normal_mode(vim, monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1" if vim else "0")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        actions = []
        monkeypatch.setattr(app, "action_scroll_log_page_down", lambda: actions.append("page"))
        monkeypatch.setattr(app, "action_search_transcript", lambda: actions.append("search"))
        await pilot.press("ctrl+f")
        assert actions == ["page" if vim else "search"]
        if vim:
            await pilot.press("i", "ctrl+f")
            assert actions == ["page", "search"]


async def test_vim_off_ctrl_e_retains_composer_line_end(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "An ordinary task"
        prompt.cursor_position = 3
        await pilot.press("ctrl+e")
        assert prompt.cursor_position == len(prompt.value)
        assert not app._vim_editor_shortcut_active()


async def test_vim_off_custom_letter_binding_is_not_reserved(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    keymap = theme_bridge._CONFIG_PATH.parent / "keybindings.json"
    keymap.parent.mkdir(parents=True)
    keymap.write_text(json.dumps({"app": {"command_palette": "h"}}))
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        assert not app._keymap.warnings
        assert any(
            binding.action == "command_palette"
            for binding in app._bindings.key_to_bindings.get("h", [])
        )
        await pilot.press("h")
        assert app.query_one("#prompt-input").value == "h"
        app.action_sidebar_files()
        await pilot.pause()
        app.query_one("#sidebar").focus()
        await pilot.press("h")
        assert app.query("CommandPalette.show-palette")
        assert app.query_one("#sidebar").current_view == "files"
        await pilot.press("escape")


async def test_vim_external_editor_respects_existing_keymap_override(monkeypatch):
    monkeypatch.setenv("EDITOR", "my-editor")
    keymap = theme_bridge._CONFIG_PATH.parent / "keybindings.json"
    keymap.parent.mkdir(parents=True)
    keymap.write_text(json.dumps({"app": {"open_editor": "alt+v"}}))
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Edit this draft"
        called = []
        monkeypatch.setattr(app, "action_open_editor", lambda: called.append(True))
        assert not app._keymap.warnings
        await pilot.press("alt+v")
        assert called == [True]
        await pilot.press("ctrl+e")
        assert called == [True]


async def test_restart_during_vim_command_restores_task_instead_of_command(tmp_path):
    from superqode.app.draft_recovery import DraftStore

    app = SuperQodeApp()
    app._draft_store = DraftStore(tmp_path)
    original = "# Unsent task\n\nPreserve this context"
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = original
        prompt.cursor_position = 5
        app._attached_refs = ["@source.py"]
        await pilot.press(":", *"help")
        app._flush_draft_recovery()
        assert app._draft_store.load()["text"] == original
    restarted = SuperQodeApp()
    restarted._draft_store = DraftStore(tmp_path)
    async with restarted.run_test() as pilot:
        prompt = restarted.query_one("#prompt-input", SelectionAwareInput)
        assert prompt.value == original
        assert prompt.cursor_position == 5
        assert restarted._attached_refs == ["@source.py"]
        assert restarted._vim_input_mode == "normal"
