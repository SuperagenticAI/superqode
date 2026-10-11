"""Vim preferences and panel navigation preserve developer data and decisions."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Input, OptionList, Select, TextArea

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
