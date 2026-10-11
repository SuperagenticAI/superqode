"""Appearance is reversible, readable and never consumes the developer's draft."""

from dataclasses import replace
import json
import os
import sys
import threading
import asyncio

import pytest
from textual.document._document import Selection
from textual.widgets import Button, Input, OptionList, Select, Static
from textual.widgets import Checkbox, TextArea

from superqode import design_system as ds
from superqode.app import theme_bridge as bridge
from superqode.app.appearance import AppearancePreferences, load_appearance, save_appearance
from superqode.app.constants import THEME
from superqode.app.widgets import ColorfulStatusBar, ConversationLog
from superqode.app_main import SelectionAwareInput, SuperQodeApp
from superqode.theming import load_theme_file, palette_tokens
from superqode.theming.customizer import customize_theme
from superqode.theming.library import theme_rows
from superqode.widgets.appearance_settings import AppearanceSettings
from superqode.widgets.theme_customizer import ThemeCustomizer
from superqode.widgets.theme_picker import ThemePicker
from superqode.app.developer_trial import project_context
from superqode.app.feedback_bundle import feedback_bundle, redact_feedback
from superqode.widgets.developer_trial import DeveloperTrialScreen
from superqode.widgets.feedback_export import FeedbackExportScreen
from superqode.widgets.mcp_connections import MCPConnectionsScreen
from superqode.mcp.client import MCPClientManager, MCPConnectionState
from superqode.mcp.config import MCPServerConfig, MCPStdioConfig, MCPHttpConfig


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    registry = dict(ds.THEMES)
    terminal = dict(bridge._terminal_colors)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bridge, "_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path / "progress"))
    for key in ("SUPERQODE_PROVIDER", "SUPERQODE_MODEL"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
        monkeypatch.delenv(key)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)
    bridge.apply_theme("superqode")
    yield
    ds.THEMES.clear()
    ds.THEMES.update(registry)
    bridge._terminal_colors.clear()
    bridge._terminal_colors.update(terminal)
    bridge.apply_theme("superqode")


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_workspace_preview_cancel_restores_colors_and_draft(size):
    bridge.save_theme("nord")
    saved = bridge._CONFIG_PATH.read_bytes()
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep this draft\nand its selection"
        prompt.selection = Selection((0, 2), (0, 6))
        log = app.query_one("#log", ConversationLog)
        log.add_user("Fix this code")
        log.add_agent("```python\nreturn a + b\n```", "Agent")
        messages = list(log._messages)
        before = dict(THEME)
        app._handle_theme("", log)
        await pilot.pause()
        picker = app.screen
        picker.query_one("#theme-list", OptionList).highlighted = picker._names.index("ayu-light")
        await pilot.pause()
        assert THEME["bg"] == palette_tokens(ds.get_theme("ayu-light"))["bg"]
        assert app._current_theme == "nord"
        assert "(Preview)" in app.query_one("#status-bar", ColorfulStatusBar).render().plain
        await pilot.press("f4")
        await pilot.pause()
        assert picker.has_class("workspace-view")
        assert picker.query_one("Vertical").region.y >= prompt.region.bottom
        await pilot.press("escape")
        await pilot.pause()
        assert dict(THEME) == before
        assert bridge._CONFIG_PATH.read_bytes() == saved
        assert log._messages == messages
        assert prompt.value == "Keep this draft\nand its selection"
        assert prompt.selection == Selection((0, 2), (0, 6))
        assert app.focused is prompt
        assert not app._theme_previews


@pytest.mark.parametrize("format_name", ["superqode", "pi"])
async def test_tui_theme_export_and_compatibility_preserve_draft(tmp_path, format_name):
    import shlex

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my draft"
        path = tmp_path / "portable palette.json"
        log = app.query_one("#log", ConversationLog)
        rendered = []
        original_write = log.write

        def capture(*values, **kwargs):
            rendered.extend(value.plain for value in values if hasattr(value, "plain"))
            return original_write(*values, **kwargs)

        log.write = capture
        app._handle_command(
            f":theme export superqode {shlex.quote(str(path))} --format {format_name}", log
        )
        async with asyncio.timeout(10):
            while not path.exists():
                await pilot.pause(0.1)
        await pilot.pause()
        assert (
            palette_tokens(load_theme_file(path))["purple"]
            == palette_tokens(ds.get_theme("superqode"))["purple"]
        )
        original = path.read_bytes()
        app._handle_command(f":theme compatibility {shlex.quote(str(path))}", log)
        async with asyncio.timeout(10):
            while not any('"valid": true' in value for value in rendered):
                await pilot.pause(0.1)
        await pilot.pause()
        assert any('"valid": true' in value for value in rendered)
        assert path.read_bytes() == original
        assert prompt.value == "Keep my draft"


@pytest.mark.parametrize(
    "command, field_id, widget_type",
    [
        (":theme", "theme-search", Input),
        (":feedback", "feedback-description", TextArea),
    ],
)
async def test_modal_editing_cannot_resolve_hidden_workspace_decisions(
    command, field_id, widget_type, monkeypatch
):
    app = SuperQodeApp()
    decisions, plans = [], []
    monkeypatch.setattr(app, "_handle_permission_input", decisions.append)
    monkeypatch.setattr(app, "_handle_plan", lambda action, log: plans.append(action))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep the draft"
        app._permission_pending = True
        app._pending_plan_status = "pending"
        app._pending_plan_content = "A model-authored plan waiting for review"
        app._handle_command(command, app.query_one("#log", ConversationLog))
        await pilot.pause()
        field = app.screen.query_one(f"#{field_id}", widget_type)
        field.focus()
        await pilot.press("y", "n", "a", "alt+a", "alt+e", "alt+r")
        await pilot.pause()
        assert (field.value if isinstance(field, Input) else field.text) == "yna"
        assert decisions == []
        assert plans == []
        await pilot.press("escape")
        await pilot.pause()
        assert app._permission_pending
        assert prompt.value == "Keep the draft"
        assert decisions == []
        await pilot.press("y")
        assert decisions == ["y"]
        app._permission_pending = False
        await pilot.press("alt+a")
        assert plans == ["approve"]


@pytest.mark.parametrize("key, response", [("y", "allow"), ("n", "deny"), ("a", "allow_all")])
async def test_inline_approval_single_key_restores_draft(key, response):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Draft waiting behind approval"
        prompt.cursor_position = 5
        decision = threading.Event()
        app._permission_response_event = decision
        app._show_permission_prompt(
            "bash", {"command": "pytest -q"}, app.query_one("#log", ConversationLog)
        )
        await pilot.press(key)
        await pilot.pause()
        assert decision.is_set()
        assert app._permission_response == response
        assert not app._permission_pending
        assert prompt.value == "Draft waiting behind approval"
        assert prompt.cursor_position == 5


async def test_catalog_preview_does_not_install_but_confirmation_does():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._handle_theme("", app.query_one("#log", ConversationLog))
        await pilot.pause()
        picker = app.screen
        picker.query_one("#theme-list", OptionList).highlighted = picker._names.index(
            "cobalt-sanctum"
        )
        await pilot.pause()
        row = next(row for row in theme_rows() if row["name"] == "cobalt-sanctum")
        assert not row["installed"]
        assert not bridge.theme_directory().exists()
        assert not bridge._CONFIG_PATH.exists()
        await pilot.press("enter")
        await pilot.pause()
        assert app._current_theme == "cobalt-sanctum"
        assert (bridge.theme_directory() / "cobalt-sanctum.json").is_file()
        assert bridge.load_saved_theme() == "cobalt-sanctum"
        assert ds.THEMES["cobalt-sanctum"].source != "preview"


async def test_favorites_filters_and_recent_undo():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        app._handle_theme("light", log)
        app._handle_theme("nord", log)
        app._handle_theme("previous", log)
        assert app._current_theme == "light"
        app._handle_theme("", log)
        await pilot.pause()
        picker = app.screen
        picker.query_one("#theme-list", OptionList).highlighted = picker._names.index("light")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert load_appearance().favorite_themes == ["light"]
        await pilot.click("#theme-favorites")
        assert picker._names == ["light"]
        await pilot.click("#theme-dark")
        assert picker._names == []
        await pilot.click("#theme-all")
        await pilot.click("#theme-recent")
        assert {"light", "nord"}.issubset(picker._names)
        await pilot.press("escape")
        app._handle_theme("next", log)
        assert app._current_theme == "light"


async def test_nested_settings_gallery_cancel_restores_parent_preview():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Still here"
        app._appearance_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        settings = app.screen
        settings.query_one("#appearance-mode", Select).value = "pair"
        settings.query_one("#appearance-light", Select).value = "ayu-light"
        settings.query_one("#appearance-dark", Select).value = "nord"
        await pilot.pause()
        before = dict(THEME)
        await pilot.click("#appearance-gallery")
        await pilot.pause()
        picker = app.screen
        picker.query_one("#theme-list", OptionList).highlighted = picker._names.index("light")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is settings
        assert dict(THEME) == before
        assert len(app._theme_previews) == 1
        await pilot.press("escape")
        await pilot.pause()
        assert app._current_theme == "auto"
        assert THEME["bg"] == palette_tokens(ds.get_theme("superqode"))["bg"]
        assert prompt.value == "Still here"
        assert not bridge._CONFIG_PATH.exists()


@pytest.mark.parametrize("save", [False, True])
async def test_settings_preview_save_or_cancel(save):
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app._appearance_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        settings = app.screen
        settings.query_one("#appearance-density", Select).value = "compact"
        settings.query_one("#appearance-motion", Select).value = "reduced"
        settings.query_one("#appearance-icons", Select).value = "ascii"
        settings.query_one("#appearance-cursor", Select).value = "steady"
        settings.query_one("#appearance-mouse", Select).value = "off"
        settings.query_one("#appearance-mode", Select).value = "auto"
        await pilot.pause()
        assert app.default_screen.has_class("compact-appearance")
        assert app._appearance.motion == "reduced"
        assert not app.query_one("#prompt-input", SelectionAwareInput).cursor_blink
        assert "🔌" not in app.query_one("#status-bar", ColorfulStatusBar).render().plain
        settings.action_save() if save else settings.action_cancel()
        await pilot.pause()
        assert app._appearance.density == ("compact" if save else "comfortable")
        assert app._appearance.cursor == ("steady" if save else "blink")
        assert app._appearance.mouse == ("off" if save else "on")
        assert app._current_theme == "auto"  # new users start on auto; cancel restores it
        assert bool(bridge._CONFIG_PATH.exists()) is save
        if save:
            assert load_appearance().icons == "ascii"
            assert json.loads(bridge._CONFIG_PATH.read_text())["theme"] == "auto"


async def test_appearance_export_does_not_commit_preview_or_change_draft(tmp_path):
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "unfinished task"
        prompt.cursor_position = 5
        app._appearance_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        settings = app.screen
        path = tmp_path / "appearance.json"
        settings.query_one("#appearance-export-path", Input).value = str(path)
        settings.query_one("#appearance-cursor", Select).value = "steady"
        await pilot.pause()
        settings.action_export()
        assert json.loads(path.read_text())["appearance"]["cursor"] == "steady"
        original = path.read_bytes()
        settings.action_export()
        assert path.read_bytes() == original
        assert not bridge._CONFIG_PATH.exists()
        await pilot.press("escape")
        assert app._appearance.cursor == "blink"
        assert prompt.value == "unfinished task" and prompt.cursor_position == 5


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_mcp_panel_close_reopen_and_cancel_preserve_transport_ownership(size, monkeypatch):
    manager = MCPClientManager()
    manager.add_server(
        MCPServerConfig(id="slow", name="slow", config=MCPStdioConfig(command="unused"))
    )
    started, release = asyncio.Event(), asyncio.Event()

    async def establish(connection):
        started.set()
        await release.wait()

    monkeypatch.setattr(manager, "_establish_connection", establish)
    app = SuperQodeApp()
    try:
        async with app.run_test(size=size) as pilot:
            prompt = app.query_one("#prompt-input", SelectionAwareInput)
            prompt.value = "keep my draft"
            await app.push_screen(MCPConnectionsScreen(manager))
            await pilot.pause()
            panel = app.screen
            assert panel.query_one("#mcp-action-back", Button).region.bottom <= size[1]
            assert panel.query_one("#mcp-action-login", Button).disabled
            await pilot.click("#mcp-action-connect")
            await asyncio.wait_for(started.wait(), 2)
            await pilot.pause()
            assert panel.query_one("#mcp-action-cancel", Button).disabled is False
            await pilot.press("escape")
            await pilot.pause()
            assert not manager._state_callbacks
            assert (
                "slow" in manager._owners
            )  # Closing cancels the waiter, not the shared transport.
            assert prompt.value == "keep my draft"
            await app.push_screen(MCPConnectionsScreen(manager))
            await pilot.pause()
            panel = app.screen
            await pilot.click("#mcp-action-cancel")
            await pilot.pause()
            assert manager.get_connection_state("slow") == MCPConnectionState.DISCONNECTED
            assert not manager._owners
            # Retry after cancellation and retain the established connection when closing.
            release.set()
            await pilot.click("#mcp-action-retry")
            await pilot.pause()
            assert manager.get_connection_state("slow") == MCPConnectionState.CONNECTED
            assert "connected" in panel.query_one("#mcp-detail", TextArea).text
            await pilot.press("escape")
            await pilot.pause()
            assert manager.get_connection_state("slow") == MCPConnectionState.CONNECTED
            assert not manager._state_callbacks
    finally:
        await manager.disconnect_all()


@pytest.mark.skipif(os.name != "posix", reason="POSIX driver mouse escape contract")
def test_mouse_preference_survives_driver_resume():
    from types import SimpleNamespace
    from superqode.app.mixins.appearance import AppearanceMixin
    from textual.drivers.linux_driver import LinuxDriver

    written = []
    driver = object.__new__(LinuxDriver)
    driver._mouse = True
    driver.write = written.append
    driver.flush = lambda: None
    app = SimpleNamespace(_driver=driver, capture_mouse=lambda _: None)
    AppearanceMixin._apply_mouse_preference(app, "off")
    driver._enable_mouse_support()  # Application-mode resume must respect the saved preference.
    assert driver._mouse is False
    assert written and all(sequence.endswith("l") for sequence in written)
    written.clear()
    AppearanceMixin._apply_mouse_preference(app, "on")
    assert driver._mouse is True
    assert written and all(sequence.endswith("h") for sequence in written)


def test_mcp_panel_redacts_configured_and_stored_opaque_credentials(monkeypatch, tmp_path):
    from superqode.mcp.auth_storage import MCPAuthStorage
    from superqode.mcp.oauth import OAuthTokens

    storage = MCPAuthStorage(tmp_path / "auth")
    monkeypatch.setattr("superqode.mcp.auth_storage.get_auth_storage", lambda: storage)
    url = "https://fixture.invalid/mcp"
    storage.for_server("remote").save_tokens(
        url, OAuthTokens("opaque-access-value", refresh_token="opaque-refresh-value")
    )
    manager = MCPClientManager()
    manager.add_server(
        MCPServerConfig(
            id="remote",
            name="remote",
            config=MCPHttpConfig(url=url, headers={"Authorization": "Bearer opaque-header-value"}),
        )
    )
    manager.add_server(
        MCPServerConfig(
            id="local",
            name="local",
            config=MCPStdioConfig(env={"PRIVATE_API_KEY": "opaque-environment-value"}),
        )
    )
    panel = MCPConnectionsScreen(manager)
    safe = panel.diagnostic(
        "remote", "Failed: opaque-access-value opaque-refresh-value opaque-header-value"
    )
    assert "opaque-" not in safe and "Failed" in safe
    assert "opaque-environment-value" not in panel.diagnostic(
        "local", "Failed: opaque-environment-value"
    )


async def test_mcp_panel_closing_login_cleans_up_pending_work(monkeypatch):
    manager = MCPClientManager()
    manager.add_server(
        MCPServerConfig(
            id="remote", name="remote", config=MCPHttpConfig(url="https://fixture.invalid/mcp")
        )
    )
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def authenticate(name):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(manager, "authenticate_server", authenticate)
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(MCPConnectionsScreen(manager))
        await pilot.pause()
        panel = app.screen
        await pilot.click("#mcp-action-login")
        await asyncio.wait_for(started.wait(), 2)
        pending = panel._tasks["remote"]
        await pilot.press("escape")
        await asyncio.wait_for(cancelled.wait(), 2)
        await pilot.pause()
        assert pending.done() and not manager._state_callbacks


async def test_new_commands_reach_their_views_without_starting_connections(monkeypatch):
    from types import SimpleNamespace
    from superqode.runtime.codex_capabilities import CodexCapabilities

    manager = MCPClientManager()

    async def get_manager():
        return manager

    async def forbidden(*args):
        raise AssertionError("Viewing status must not connect or infer")

    monkeypatch.setattr("superqode.mcp.integration.get_mcp_manager", get_manager)
    monkeypatch.setattr(manager, "connect", forbidden)
    monkeypatch.setattr(
        "superqode.app.mixins.connect.get_session", lambda: SimpleNamespace(connected_agent=None)
    )
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._pure_mode = SimpleNamespace(
            runtime_name="codex-cli",
            session=SimpleNamespace(
                connected=True, provider="codex", model="selected", harness_runtime="codex-cli"
            ),
            _runtime=SimpleNamespace(capabilities=CodexCapabilities(methods={"thread/resume": {}})),
        )
        output = []
        monkeypatch.setattr(
            app, "_show_command_output", lambda log, text: output.append(text.plain)
        )
        app._handle_command(":connect capabilities", log)
        assert "Continue: Supported" in output[-1]
        assert "Fork: Unavailable" in output[-1]
        app._handle_command(":mcp panel", log)
        await pilot.pause()
        assert isinstance(app.screen, MCPConnectionsScreen)
        assert "No MCP servers configured" in app.screen.query_one("#mcp-detail", TextArea).text
        await pilot.press("escape")


async def test_mcp_panel_errors_are_redacted_and_retry_recovers(monkeypatch):
    manager = MCPClientManager()
    manager.add_server(
        MCPServerConfig(id="fixture", name="fixture", config=MCPStdioConfig(command="unused"))
    )
    monkeypatch.setenv("TEST_MCP_API_KEY", "private-fixture-secret-value")

    async def fail(connection):
        raise RuntimeError("Server denied private-fixture-secret-value")

    async def success(connection):
        pass

    monkeypatch.setattr(manager, "_establish_connection", fail)
    app = SuperQodeApp()
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(MCPConnectionsScreen(manager))
            await pilot.pause()
            await pilot.click("#mcp-action-connect")
            await pilot.pause()
            panel = app.screen
            detail = panel.query_one("#mcp-detail", TextArea).text
            assert "error" in detail and "denied" in detail
            assert "private-fixture-secret-value" not in detail
            monkeypatch.setattr(manager, "_establish_connection", success)
            await pilot.click("#mcp-action-retry")
            await pilot.pause()
            assert manager.get_connection_state("fixture") == MCPConnectionState.CONNECTED
            assert "denied" not in panel.query_one("#mcp-detail", TextArea).text
    finally:
        await manager.disconnect_all()


@pytest.mark.parametrize("format_name", ["superqode", "pi"])
async def test_customizer_exports_private_json_and_preserves_existing_file(tmp_path, format_name):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app.push_screen(ThemeCustomizer(ds.get_theme()))
        await pilot.pause()
        customizer = app.screen
        customizer.query_one("#custom-accent", Input).value = "#00bbaa"
        customizer.query_one("#custom-export-path", Input).value = str(tmp_path / "export.json")
        customizer.query_one("#custom-export-format", Select).value = format_name
        await pilot.pause()
        assert customizer._candidate is not None
        customizer.action_export()
        path = tmp_path / "export.json"
        exported = load_theme_file(path)
        assert exported.tokens["purple"] == "#00bbaa"
        assert ("earendil-works/pi" in json.loads(path.read_text())["$schema"]) is (
            format_name == "pi"
        )
        before = path.read_bytes()
        customizer.action_export()
        assert path.read_bytes() == before
        customizer.query_one("#custom-accent", Input).value = "not a color"
        await pilot.pause()
        assert customizer.query_one("#custom-save", Button).disabled
        assert "last working preview" in str(
            customizer.query_one("#custom-status", Static).render()
        )
        await pilot.press("escape")
        assert app._current_theme == "auto"
        assert not bridge._CONFIG_PATH.exists()


async def test_customizer_save_installs_a_restorable_theme():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._customize_theme(app.query_one("#log", ConversationLog))
        await pilot.pause()
        customizer = app.screen
        name = customizer._candidate.name
        customizer.action_save()
        await pilot.pause()
        assert app._current_theme == name
        assert bridge.load_saved_theme() == name
        assert ds.THEMES[name].source != "preview"


def test_customizer_corrects_low_contrast_and_roundtrips():
    theme, requested, rendered = customize_theme(
        ds.get_theme("light"),
        "custom-pale",
        accent="#cccccc",
        background="#fafafa",
        surface="#f4f4f5",
        text="#bbbbbb",
    )
    assert requested < 4.5 <= rendered
    assert palette_tokens(theme)["text"] != "#bbbbbb"


@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        "[]",
        '{"appearance":{"density":[],"motion":false,"favorite_themes":[{},"nord","nord"]}}',
    ],
)
def test_invalid_preferences_are_bounded_and_do_not_destroy_config(raw):
    bridge._CONFIG_PATH.write_text(raw)
    preferences = load_appearance()
    assert preferences.density == "comfortable"
    if raw.startswith('{"appearance"'):
        assert preferences.favorite_themes == ["nord"]
    else:
        assert save_appearance({"density": "compact"})
        assert bridge._CONFIG_PATH.read_text() == raw


async def test_reduced_motion_stops_sweeps_and_retains_work_status():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._apply_appearance(replace(AppearancePreferences(), motion="reduced"))
        app._start_stream_animation(app.query_one("#log", ConversationLog))
        await pilot.pause()
        indicator = app.query_one("#streaming-thinking")
        assert indicator.is_active
        assert indicator.auto_refresh is None
        assert not getattr(app, "_wave_burst_running", False)
        assert "Thinking" in indicator.render().plain
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.set_working(True)
        assert getattr(prompt, "_working_timer", None) is None
        assert prompt.placeholder == "Agent working ●"
        app._apply_appearance(replace(app._appearance, icons="ascii"))
        assert prompt.placeholder == "Agent working *"
        assert "🔌" not in app.query_one("#hints").render().plain
        from textual import events

        app.on_app_focus(events.AppFocus())
        assert indicator.auto_refresh is None
        app._stop_stream_animation()


@pytest.mark.parametrize(
    "environment", [{}, {"SSH_TTY": "/dev/pts/1"}, {"TMUX": "/tmp/tmux-1/default,1,0"}]
)
async def test_feedback_export_is_reviewed_private_and_matches_preview(
    tmp_path, monkeypatch, environment
):
    for key in ("SSH_TTY", "SSH_CONNECTION", "TMUX"):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    secret = "private-credential-value"
    monkeypatch.setenv("TEST_API_KEY", secret)
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "unsent confidential draft"
        log = app.query_one("#log", ConversationLog)
        log.add_user("confidential conversation")
        log.add_error(
            f"Request failed: {secret} https://user:password@server/v1?token=sensitive#fragment {tmp_path}/file.py"
        )
        app._feedback_cmd(log)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FeedbackExportScreen)
        assert screen.query_one("#feedback-reviewed", Checkbox).content_size.height >= 1
        path = tmp_path / "feedback.json"
        screen.query_one("#feedback-path", Input).value = str(path)
        await pilot.pause()
        screen.action_export()
        assert not path.exists()
        preview = screen.query_one("#feedback-preview", TextArea).text
        assert not any(
            value in preview
            for value in (secret, "sensitive", "password", str(tmp_path), "confidential")
        )
        assert json.loads(preview)["terminal"]["ssh"] is bool(environment.get("SSH_TTY"))
        assert json.loads(preview)["terminal"]["tmux"] is bool(environment.get("TMUX"))
        screen.query_one("#feedback-reviewed", Checkbox).value = True
        await pilot.pause()
        screen.action_export()
        assert json.loads(path.read_text()) == json.loads(preview)
        if os.name == "posix":
            assert path.stat().st_mode & 0o777 == 0o600
        original = path.read_bytes()
        screen.action_export()
        assert path.read_bytes() == original
        screen.query_one("#feedback-description", TextArea).load_text("New details")
        await pilot.pause()
        assert screen.query_one("#feedback-export", Button).disabled
        assert not screen.query_one("#feedback-reviewed", Checkbox).value
        await pilot.press("escape")
        assert prompt.value == "unsent confidential draft"


def test_feedback_redaction_handles_tokens_headers_keys_and_controls():
    payload = {
        "api_key": "arbitrary-key",
        "notes": (
            "Bearer bare-secret sk-proj-12345678901234567890 ghp_12345678901234567890 "
            "password=another-secret\nhttps://admin:pw@host/path?api_key=hidden#secret "
            "\x1b[31merror\x00\n-----BEGIN RSA PRIVATE KEY-----\nunterminated secret key"
        ),
    }
    result = json.dumps(redact_feedback(payload))
    for value in (
        "arbitrary-key",
        "bare-secret",
        "sk-proj-",
        "ghp_",
        "another-secret",
        "admin",
        "hidden",
        "unterminated",
        "\\u001b",
        "\\u0000",
    ):
        assert value not in result
    assert "https://host/path" in result


async def test_feedback_is_bounded_and_optional_sections_are_excluded(monkeypatch):
    monkeypatch.setenv("TERM", "x" * 10000)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        for number in range(20):
            log.add_error(f"Error {number} " + "é" * 3000)
        bundle = feedback_bundle(app, "é" * 10000)
        assert len(bundle["recent_errors"]) == 10
        assert len(bundle["description"]) == 4000
        assert len(json.dumps(bundle, ensure_ascii=False)) < 30000
        assert "route" not in feedback_bundle(app, include_route=False, include_errors=False)
        assert "recent_errors" not in feedback_bundle(app, include_errors=False)


@pytest.mark.parametrize(
    "content,name",
    [
        (b"binary\x00data", "data.bin"),
        (b"secrets", ".env"),
        (b"-----BEGIN PRIVATE KEY-----", "notes.txt"),
        (b"x" * 262145, "big.txt"),
        (b"\xff", "encoding.txt"),
    ],
    # Short ids: a 256 KiB bytes repr as the id makes tmp_path exceed
    # Windows path limits.
    ids=["binary", "dotenv", "private-key", "oversized", "bad-encoding"],
)
def test_trial_context_rejects_unsuitable_files(tmp_path, content, name):
    (tmp_path / name).write_bytes(content)
    with pytest.raises(ValueError):
        project_context(name, tmp_path)


def test_trial_context_does_not_follow_a_symlink_outside_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("outside")
    try:
        (root / "context.txt").symlink_to(tmp_path / "outside.txt")
    except OSError:
        pytest.skip("Creating file symlinks is unavailable on this host")
    with pytest.raises(ValueError):
        project_context("context.txt", root)


async def test_trial_validates_without_inference_and_cancel_keeps_draft(tmp_path, monkeypatch):
    from superqode.providers.connection_diagnostics import ConnectionCheck

    (tmp_path / "README.md").write_text("Project documentation")
    app = SuperQodeApp()
    checks, runs = [], []

    async def check(provider, model, **kwargs):
        checks.append((provider, model, kwargs))
        return ConnectionCheck(
            "configured", "Credential configured; account access not yet verified.", provider, model
        )

    monkeypatch.setattr("superqode.providers.connection_diagnostics.check_model_connection", check)
    monkeypatch.setattr(app, "_connection_target", lambda: ("model", "test", "model"))
    monkeypatch.setattr(app, "_connection_fingerprint", lambda: ("route",))
    monkeypatch.setattr(app, "_has_live_connection", lambda: True)
    monkeypatch.setattr(app, "_handle_message", lambda *args: runs.append(args))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Original task"
        app._trial_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DeveloperTrialScreen)
        assert not runs and not checks
        await screen.validate_setup().wait()
        screen.attach_context()
        await pilot.pause()
        assert checks == [("test", "model", {"infer": False})]
        assert not screen.query_one("#trial-run", Button).disabled
        assert not runs
        await pilot.press("escape")
        assert "Original task" in prompt.value
        assert "@README.md" in prompt.value


async def test_trial_explicit_run_uses_normal_dispatch_and_stashes_draft(tmp_path, monkeypatch):
    from types import SimpleNamespace

    (tmp_path / "README.md").write_text("Project documentation")
    app = SuperQodeApp()
    monkeypatch.setattr(app, "_connection_target", lambda: ("runtime", "test", "model"))
    monkeypatch.setattr(app, "_connection_fingerprint", lambda: ("route",))
    monkeypatch.setattr(app, "_has_live_connection", lambda: True)
    runs = []
    monkeypatch.setattr(app, "_handle_message", lambda text, log: runs.append(text))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep this original draft"
        app._trial_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        await screen.validate_setup().wait()
        screen.attach_context()
        await pilot.pause()
        screen.action_run()
        await pilot.pause()
        assert len(runs) == 1
        assert "@README.md" in runs[0] and "Read files only" in runs[0]
        assert "Keep this original draft" in app._draft_stash[-1]
        state = app._trial_state()
        assert not state.completed
        app._task_changes_current = SimpleNamespace(id="trial-turn")
        app._bind_trial_task("trial-turn")
        app._record_trial_completion({}, "A real answer")
        assert state.completed and not state.pending
        assert state.outcome.details[0] == "Answer\nA real answer"
        app._handle_stash("", app.query_one("#log", ConversationLog))
        assert "Keep this original draft" in prompt.value


async def test_trial_discards_a_check_when_route_changes(monkeypatch):
    import asyncio
    from superqode.providers.connection_diagnostics import ConnectionCheck

    app = SuperQodeApp()
    route = ["one"]
    started, release = asyncio.Event(), asyncio.Event()

    async def check(*args, **kwargs):
        started.set()
        await release.wait()
        return ConnectionCheck("configured", "Ready", "test", "model")

    monkeypatch.setattr("superqode.providers.connection_diagnostics.check_model_connection", check)
    monkeypatch.setattr(app, "_connection_target", lambda: ("model", "test", "model"))
    monkeypatch.setattr(app, "_connection_fingerprint", lambda: tuple(route))
    monkeypatch.setattr(app, "_has_live_connection", lambda: True)
    async with app.run_test() as pilot:
        app._trial_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        worker = screen.validate_setup()
        await asyncio.wait_for(started.wait(), 2)
        route[0] = "two"
        release.set()
        await worker.wait()
        assert not screen.state.route_ready
        assert "changed" in screen.state.check_message
        assert getattr(app, "_last_connection_check", None) is None


async def test_trial_cannot_obscure_an_approval_and_cannot_run_after_route_changes(monkeypatch):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        app._permission_pending = True
        app._trial_cmd(log)
        assert not isinstance(app.screen, DeveloperTrialScreen)
        app._permission_pending = False
        state = app._trial_state()
        state.checked_route = ("old",)
        state.route_ready = True
        app._trial_cmd(log)
        await pilot.pause()
        assert not state.route_ready
        assert app.screen.query_one("#trial-run", Button).disabled


_WINDOWS_INVALID = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows file names cannot contain quotes or backslashes"
)


@pytest.mark.parametrize(
    "name",
    [
        "docs/first task.md",
        pytest.param('docs/a"quote.md', marks=_WINDOWS_INVALID),
        pytest.param("docs/with\\backslash.md", marks=_WINDOWS_INVALID),
    ],
)
def test_quoted_file_references_expand_the_exact_context(tmp_path, name):
    from superqode.widgets.file_reference import (
        format_file_reference,
        parse_file_references,
        expand_file_references,
    )

    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Exact context")
    reference = format_file_reference(name)
    assert parse_file_references(reference) == [name]
    clean, files = expand_file_references("Use " + reference, tmp_path)
    from pathlib import Path

    assert files == [(str(Path(name)), "Exact context")]
    assert clean == "Use " + name


async def test_trial_attaches_context_with_spaces_without_losing_draft(tmp_path):
    name = "docs/project context.md"
    (tmp_path / "docs").mkdir()
    (tmp_path / name).write_text("Context")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Unfinished task"
        app._trial_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        screen.query_one("#trial-context", Input).value = name
        screen.attach_context()
        from pathlib import Path
        from superqode.widgets.file_reference import format_file_reference

        assert format_file_reference(str(Path(name))) in app._attached_refs
        assert "Unfinished task" in prompt.value


async def test_favorite_catalog_theme_can_be_switched_to_and_installed():
    save_appearance({"favorite_themes": ["alien-candy"]})
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._cycle_favorite_theme(app.query_one("#log", ConversationLog))
        assert app._current_theme == "alien-candy"
        assert (bridge.theme_directory() / "alien-candy.json").exists()


async def test_previous_theme_retains_the_startup_override_after_restart():
    bridge.save_theme("superqode")
    app = SuperQodeApp(theme_selection="nord")
    async with app.run_test() as pilot:
        app._handle_theme("light", app.query_one("#log", ConversationLog))
        assert load_appearance().previous_theme == "nord"
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._restore_previous_theme(app.query_one("#log", ConversationLog))
        assert app._current_theme == "nord"


async def test_trial_accepts_lazy_client_start_but_rejects_actual_route_changes(monkeypatch):
    from types import SimpleNamespace

    app = SuperQodeApp()
    fingerprint = [("acp", "test", ""), "", None, 1, 2, 3, None, "agent", "acp", "core"]
    monkeypatch.setattr(app, "_connection_fingerprint", lambda: tuple(fingerprint))
    async with app.run_test() as pilot:
        state = app._trial_state()
        state.pending = True
        state.submitted_route = app._trial_route_identity()
        app._task_changes_current = SimpleNamespace(id="first-task")
        app._bind_trial_task("first-task")
        fingerprint[6] = 999
        fingerprint[0] = ("acp", "test", "default-model")
        app._record_trial_completion({}, "Task succeeded")
        assert state.completed
        state.pending, state.completed = True, False
        fingerprint[0] = ("acp", "another-agent", "default-model")
        app._record_trial_completion({}, "Stale response")
        assert not state.completed and not state.pending


def test_feedback_strips_osc_payloads_and_obfuscated_tokens():
    value = "Visible \x1b]52;c;hiddenEncodedContent\x07 sk-proj-12345\x1b[31m678901234567890"
    redacted = redact_feedback(value)
    assert "hiddenEncodedContent" not in redacted
    assert "sk-proj-" not in redacted
    assert "Visible" in redacted


@pytest.mark.parametrize("selection", ["auto", "system", "light/nord", "nord/dracula"])
async def test_settings_gallery_retains_automatic_and_previous_paired_selections(selection):
    app = SuperQodeApp(theme_selection=selection)
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        app._appearance_cmd(log)
        await pilot.pause()
        settings = app.screen
        assert settings._selection() == selection
        settings._chosen_theme("light")
        app._previous_theme = selection
        settings._chosen_theme(":previous")
        await pilot.pause()
        assert settings._selection() == selection
        settings.action_save()
        await pilot.pause()
        assert app._current_theme == selection
        assert bridge.load_saved_theme() == selection


async def test_new_palette_and_welcome_actions_are_clickable():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Retained draft"
        for command, screen in (
            ("settings", AppearanceSettings),
            ("trial", DeveloperTrialScreen),
            ("feedback", FeedbackExportScreen),
        ):
            app._run_clicked_command(command)
            await pilot.pause()
            assert isinstance(app.screen, screen)
            await pilot.press("escape")
            assert prompt.value == "Retained draft"


async def test_guided_acp_validation_supports_an_agent_that_starts_on_first_prompt(monkeypatch):
    app = SuperQodeApp()
    monkeypatch.setattr(app, "_connection_target", lambda: ("acp", "lazy-agent", ""))
    monkeypatch.setattr(app, "_connection_fingerprint", lambda: ("lazy-route",))
    monkeypatch.setattr(app, "_has_live_connection", lambda: False)
    async with app.run_test() as pilot:
        app._trial_cmd(app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        await screen.validate_setup().wait()
        assert screen.state.route_ready
        assert "first task" in screen.state.check_message
        assert not screen.state.completed


@pytest.mark.parametrize("base_name", ["superqode", "light", "nord"])
async def test_customizer_never_mutates_source_and_escape_restores_entire_palette(base_name):
    from copy import deepcopy
    from superqode.theming import native_document

    app = SuperQodeApp(theme_selection=base_name)
    async with app.run_test() as pilot:
        base = ds.get_theme()
        before = dict(THEME)
        source = deepcopy(native_document(base))
        app._customize_theme(app.query_one("#log", ConversationLog))
        await pilot.pause()
        screen = app.screen
        screen.query_one("#custom-accent", Input).value = "#00bbaa"
        screen.query_one("#custom-background", Input).value = "#222222"
        screen.query_one("#custom-surface", Input).value = "#282828"
        screen.query_one("#custom-text", Input).value = "#eeeeee"
        await pilot.pause()
        assert native_document(base) == source
        assert THEME != before
        await pilot.press("escape")
        await pilot.pause()
        assert dict(THEME) == before
        assert native_document(base) == source
