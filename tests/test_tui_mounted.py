"""Mounted-TUI smoke tests using Textual's run_test() harness.

These catch the class of bug where code updates an *unmounted* widget (e.g.
querying `widgets.status_bar.StatusBar` when the app actually mounts
`ColorfulStatusBar`): a unit test on the widget passes, but the real bar never
updates. Running the actual app and asserting on the mounted widget closes that
gap.
"""

from __future__ import annotations

import os

import pytest

from textual.widgets import Static

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ColorfulStatusBar, ConversationLog


@pytest.fixture(autouse=True)
def _isolate_mounted_app_startup(monkeypatch):
    """Keep interaction tests independent of process-wide startup state."""
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setattr(SuperQodeApp, "_prewarm_litellm", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_models_dev_refresh", lambda self: None)


async def _settle(pilot, frames: int = 6) -> None:
    """Let a registry prompt finish mounting before driving it.

    ``pilot.pause()`` advances one frame. Opening a prompt takes several, so a
    key pressed after a single pause can land before the prompt is listening,
    which made these tests sensitive to unrelated timing changes elsewhere.
    """
    for _ in range(frames):
        await pilot.pause()


async def test_status_setters_update_mounted_status_bar():
    """_set_status_runtime/_set_status_model must update the MOUNTED status bar."""
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        # Sanity: the app mounts ColorfulStatusBar at #status-bar.
        bar = app.query_one("#status-bar", ColorfulStatusBar)

        app._set_status_runtime("codex-sdk")
        app._set_status_model("gpt-5.5")
        await pilot.pause()

        assert bar.active_runtime == "codex-sdk"
        assert bar.active_model == "gpt-5.5"
        rendered = bar.render().plain
        assert "codex-sdk" in rendered
        assert "gpt-5.5" in rendered  # full, not shortened


async def test_mounted_status_header_keeps_identity_and_operational_state(monkeypatch):
    """The real header reserves two content rows and never looks empty."""
    from superqode import __version__

    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    app = SuperQodeApp()
    async with app.run_test(size=(90, 30)) as pilot:
        bar = app.query_one("#status-bar", ColorfulStatusBar)
        await pilot.pause()

        rendered = bar.render().plain
        assert bar.outer_size.height == 3  # top breathing row + content + bottom border
        assert bar.content_region.y == bar.region.y + 1
        assert "\n" not in rendered
        assert f"SuperQode v{__version__}" in rendered
        assert "Harness Engineering frameworks" not in rendered
        assert "Model: not connected" in rendered
        assert "runtime builtin" not in rendered
        assert "h core" in rendered
        assert "BUILD" in rendered


async def test_idle_mode_badge_does_not_reserve_a_prompt_row():
    app = SuperQodeApp()
    async with app.run_test(size=(90, 30)) as pilot:
        badge = app.query_one("#mode-badge")
        await pilot.pause()

        assert badge.display is False
        assert badge.size.height == 0


async def test_mouse_drag_selection_copies_to_clipboard():
    """Dragging the mouse over the answer must auto-copy it to the clipboard.

    Regression guard: ``on_text_selected`` is dispatched by Textual's name-based
    convention. Decorating it with ``@on(events.TextSelected)`` on a plain mixin
    silently disables it (the refactor that moved it into a mixin broke
    mouse-drag copy this way). This drives a real drag through the mounted app
    and asserts the clipboard write actually happens.
    """
    from textual import events
    from textual.geometry import Offset

    copies: list[str] = []
    app = SuperQodeApp()
    app._copy_text_to_clipboard = lambda text: (copies.append(text), True)[1]

    async with app.run_test(size=(100, 40)) as pilot:
        # Let any persisted startup connection finish before creating the
        # controlled transcript used by this interaction test.
        for _ in range(5):
            await _settle(pilot)
        await pilot.pause(0.5)
        app._welcome_active = False
        app._prompts.clear()
        app._reset_connect_selection_states()
        copies.clear()
        log = app.query_one("#log", ConversationLog)
        log.clear()
        log.reset_response_stream("qwen")
        log.write_final_response("Mouse selectable answer body here.", agent="qwen")
        await _settle(pilot)
        await _settle(pilot)

        ty = next(
            y
            for y in range(len(log.lines))
            if "selectable answer" in "".join(s.text for s in log.render_line(y))
        )
        r = log.region
        sy = r.y + ty - log.scroll_offset[1]
        x0 = r.x + 4
        await pilot._post_mouse_events([events.MouseDown], offset=Offset(x0, sy), button=1)
        await pilot._post_mouse_events([events.MouseMove], offset=Offset(x0 + 10, sy), button=1)
        await pilot._post_mouse_events(
            [events.MouseMove, events.MouseUp], offset=Offset(x0 + 24, sy), button=1
        )
        await pilot.pause(0.5)

        assert copies, "mouse-drag selection did not trigger a clipboard copy"
        assert any("select" in copied for copied in copies)  # copied answer text


async def test_status_runtime_hides_builtin():
    """builtin is the default — no runtime badge clutter for it."""
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        bar = app.query_one("#status-bar", ColorfulStatusBar)
        app._set_status_runtime("builtin")
        await pilot.pause()
        assert bar.active_runtime == ""


async def test_connect_picker_keyboard_navigation_keeps_selection_visible():
    """A multiline :connect option must follow keyboard navigation in RichLog."""
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        # The Subscriptions screen is the long one, so it is what can scroll a
        # highlighted option out of view.
        app._show_connect_type_picker(log, menu="subscriptions")
        await pilot.pause()

        for _ in range(6):
            await pilot.press("down")
            await pilot.pause()

        # The highlighted row is marked by a filled click dot.
        selected_y = next(index for index, line in enumerate(log.lines) if "●" in line.text)
        visible_height = log.scrollable_content_region.height

        assert app._byok_highlighted_connect_type_index == 6
        assert log.scroll_y <= selected_y < log.scroll_y + visible_height


async def test_byok_picker_keyboard_navigation_keeps_selection_visible():
    """The provider picker uses the same multiline RichLog navigation path."""
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_byok_providers(log)
        await pilot.pause()

        for _ in range(6):
            await pilot.press("down")
            await pilot.pause()

        # The provider picker keeps the arrow: its rows already carry a
        # status glyph, so a click dot there would be a second circle.
        selected_y = next(index for index, line in enumerate(log.lines) if "▶" in line.text)
        visible_height = log.scrollable_content_region.height

        assert app._byok_highlighted_provider_index == 6
        assert log.scroll_y <= selected_y < log.scroll_y + visible_height


async def test_harness_command_opens_complete_integration_switcher():
    app = SuperQodeApp()
    async with app.run_test(size=(100, 32)) as pilot:
        log = app.query_one("#log", ConversationLog)

        app._harness_cmd("", log)
        await pilot.pause()
        await pilot.pause()

        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        rendered = "\n".join(line.text for line in log.lines)

        assert prompt.value == ""
        assert app._prompt_completion_visible is False
        assert app._awaiting_harness_selection is True
        ids = [entry.id for entry in app._harness_selection_list]
        assert ids[:7] == [
            "core",
            "rlm",
            "pipy",
            "workbench",
            "no-tool",
            "codex",
            "claude",
        ]
        assert app._harness_highlighted_index == 0
        assert "kimi-coding" in ids
        assert "kimi-k3-coding" in ids
        assert "gemma4-coding" in ids
        assert "Select Harness or Coding Agent" in rendered


async def test_harness_all_opens_complete_native_switcher():
    app = SuperQodeApp()
    async with app.run_test(size=(100, 32)) as pilot:
        log = app.query_one("#log", ConversationLog)

        app._harness_cmd("all", log)
        await pilot.pause()
        await pilot.pause()

        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        rendered = "\n".join(line.text for line in log.lines)

        assert prompt.value == ""
        assert app._prompt_completion_visible is False
        assert app._awaiting_harness_selection is True
        assert app._harness_include_all is True
        ids = [entry.id for entry in app._harness_selection_list]
        assert "kimi-k3-coding" in ids
        assert "benchmark-coding" in ids
        assert "All available integrations" in rendered


async def test_claude_agent_badge_on_mounted_status_bar():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        bar = app.query_one("#status-bar", ColorfulStatusBar)
        app._set_status_runtime("claude-agent-sdk")
        app._set_status_model("claude-opus-4-8")
        await pilot.pause()
        assert bar.active_runtime == "claude-agent-sdk"
        assert "claude-opus-4-8" in bar.render().plain


# --- mouse drag-select + copy of agent output (the real blocker) -------------


async def test_conversation_log_selection_yields_text():
    """The crux: a selection over the ConversationLog must extract real text.

    RichLog renders to a RichVisual, so the stock Widget.get_selection returns
    None (no copyable text). ConversationLog overrides it; this proves drag-select
    actually produces text the app can copy.
    """
    from textual.selection import SELECT_ALL, Selection
    from textual.geometry import Offset

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        log.write("ImportError: no module named superqode")
        log.write("Traceback line two of the error")
        await pilot.pause()

        # Full selection extracts the visible text.
        full = log.get_selection(SELECT_ALL)
        assert full is not None
        assert "ImportError: no module named superqode" in full[0]

        # A partial selection extracts just that span (a slice of the full text),
        # not the whole thing — proving selection.extract is honoured.
        partial = log.get_selection(Selection(Offset(0, 0), Offset(11, 0)))
        assert partial is not None
        assert len(partial[0]) == 11
        assert len(partial[0]) < len(full[0])

        # And it flows through the screen-level API the copy handler uses.
        app.screen.selections = {log: SELECT_ALL}
        selected = app.screen.get_selected_text()
        assert selected and "ImportError" in selected


async def test_conversation_log_selection_uses_cell_offsets_for_wide_glyphs():
    """Selection offsets are terminal cells, not Python character indexes."""
    from textual.geometry import Offset
    from textual.selection import Selection

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        log.clear()
        log.write("✅ copied text after a wide glyph")
        await pilot.pause()

        selected = log.get_selection(Selection(Offset(2, 0), Offset(14, 0)))

        assert selected is not None
        assert selected[0] == " copied text"


async def test_conversation_log_selection_style_is_visible():
    """Mouse-selected text must visibly contrast against the black log."""
    from textual.geometry import Offset
    from textual.selection import Selection

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        log.clear()
        log.write("select this visible text")
        app.screen.selections = {log: Selection(Offset(0, 0), Offset(6, 0))}
        await pilot.pause()

        style = log.selection_style

        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == "#2563eb"
        assert style.color is not None
        assert style.color.get_truecolor().hex == "#ffffff"

        rendered_line = log.render_line(0)
        selected_segments = [
            segment
            for segment in rendered_line
            if segment.style
            and segment.style.bgcolor
            and segment.style.bgcolor.get_truecolor().hex == "#2563eb"
        ]
        assert selected_segments
        assert "".join(segment.text for segment in selected_segments) == "select"


async def test_real_mouse_drag_over_conversation_selects_text():
    """End-to-end: an actual mouse drag over the log must create a selection.

    This is the bug the manual-selection tests missed — RichLog segments lacked
    the offset meta Textual needs to *start* a selection, so dragging did nothing
    no matter the connector. ConversationLog.render_line now tags segments;
    a genuine drag should now yield highlighted, extractable text.
    """
    from textual.events import MouseDown, MouseMove, MouseUp

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        log.add_agent(
            "Here is the model response.\nSecond line of the answer.\nThird line of detail.",
            agent="Assistant",
        )
        await pilot.pause()
        await pilot.pause()

        # The compositor can now map a screen cell to a content offset.
        _w, offset = app.screen.get_widget_and_offset_at(log.region.x + 4, log.region.y + 1)
        assert offset is not None, "render_line did not tag segments with offset meta"

        await pilot._post_mouse_events([MouseDown], widget=log, offset=(4, 1), button=1)
        await pilot._post_mouse_events([MouseMove], widget=log, offset=(40, 3), button=1)
        await pilot._post_mouse_events([MouseUp], widget=log, offset=(40, 3), button=1)
        await pilot.pause()

        assert app.screen.selections, "mouse drag created no selection"
        assert app.screen.get_selected_text()


async def test_text_selected_copies_to_clipboard(monkeypatch):
    """on_text_selected must push the selection to the system clipboard."""
    from textual.selection import SELECT_ALL

    copied: list[str] = []
    monkeypatch.setattr(
        SuperQodeApp, "_os_clipboard_copy", staticmethod(lambda text: copied.append(text) or True)
    )

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        log.write("copy me to the clipboard please")
        await pilot.pause()

        app.screen.selections = {log: SELECT_ALL}
        await app.on_text_selected()

        assert copied, "selection was not copied to the OS clipboard"
        assert "copy me to the clipboard please" in copied[-1]


def test_copy_text_to_clipboard_falls_back_to_osc52(monkeypatch):
    """If no OS clipboard backend exists, we still emit OSC 52 (remote/SSH)."""
    monkeypatch.setattr(SuperQodeApp, "_os_clipboard_copy", staticmethod(lambda text: False))

    osc52: list[str] = []
    app = SuperQodeApp()
    monkeypatch.setattr(app, "copy_to_clipboard", lambda text: osc52.append(text))

    assert app._copy_text_to_clipboard("hello") is True
    assert osc52 == ["hello"]
    # Empty text never claims success.
    assert app._copy_text_to_clipboard("") is False


# --- prompt box: select-all + clear (escape a huge pasted blob) ---------------


async def test_prompt_placeholder_points_at_the_first_command(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        await pilot.pause()

        assert str(prompt.placeholder) == "Get started with :connect, or click the buttons below"


async def test_mounted_harness_switcher_uses_keyboard_navigation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()

    async with app.run_test(size=(100, 32)) as pilot:
        prompt = app.query_one(SelectionAwareInput)
        log = app.query_one("#log", ConversationLog)
        app._harness_cmd("switch", log)
        prompt.focus()
        await pilot.pause()

        assert app._awaiting_harness_selection is True
        assert app._harness_selection_list[app._harness_highlighted_index].id == "core"

        await pilot.press("down", "enter")
        await pilot.pause()

        assert app._awaiting_harness_selection is False
        assert app._pure_mode.session.harness_name == "rlm"
        assert "Harness switched: RLM · from Core" in "\n".join(line.text for line in log.lines)


async def test_mounted_harness_switcher_toggles_catalog_and_cancels(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()

    async with app.run_test(size=(78, 28)) as pilot:
        prompt = app.query_one(SelectionAwareInput)
        log = app.query_one("#log", ConversationLog)
        app._harness_cmd("", log)
        prompt.focus()
        await pilot.pause()

        complete_count = len(app._harness_selection_list)
        await pilot.press("r")
        await pilot.pause()

        assert app._harness_include_all is False
        assert len(app._harness_selection_list) < complete_count

        await pilot.press("escape")
        await pilot.pause()

        assert app._awaiting_harness_selection is False
        assert "Harness selection cancelled." in "\n".join(line.text for line in log.lines)


async def test_mounted_vim_mode_switches_between_normal_insert_and_command(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        bar = app.query_one("#status-bar", ColorfulStatusBar)
        input_box = app.query_one("#input-box")
        await _settle(pilot)

        assert prompt.read_only is True
        assert bar.vim_state == "normal"
        assert input_box.border_title == "Task · NORMAL"

        await pilot.press("i")
        await _settle(pilot)
        assert prompt.read_only is False
        assert bar.vim_state == "insert"

        await pilot.press("h")
        assert prompt.text == "h"

        await pilot.press("escape")
        await _settle(pilot)
        assert prompt.read_only is True
        assert prompt.text == "h"
        assert bar.vim_state == "normal"

        prompt.load_text("")
        await pilot.press(":")
        await _settle(pilot)
        assert prompt.text == ":"
        assert prompt.read_only is False
        assert bar.vim_state == "command"

        prompt.insert("vim status")
        await pilot.press("enter")
        await _settle(pilot)
        assert prompt.text == ""
        assert prompt.read_only is True
        assert bar.vim_state == "normal"


async def test_mounted_vim_jk_moves_prompt_completion(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1")
    app = SuperQodeApp()
    moves = []
    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        prompt.focus()
        app._prompt_completion_visible = True
        monkeypatch.setattr(app, "_move_prompt_completion", lambda delta: moves.append(delta))

        await pilot.press("j", "k")
        await _settle(pilot)

        assert moves == [1, -1]
        assert prompt.text == ""


async def test_prompt_accepts_dictated_text_like_normal_input():
    """OS dictation inserts text into the focused editor; keep it as normal text."""
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        prompt.focus()
        prompt.load_text("Please summarize the failing test period")
        await pilot.pause()

        assert prompt.text == "Please summarize the failing test period"
        assert prompt.value == "Please summarize the failing test period"


async def test_local_stop_ds4_submits_from_active_model_picker(monkeypatch):
    """The digit in ds4 remains text instead of becoming model choice 4."""
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    submitted: list[str] = []
    monkeypatch.setattr(app, "_handle_command", lambda text, log: submitted.append(text))

    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        app._awaiting_local_model = True
        app._local_model_list = ["model-one", "model-two"]
        prompt.focus()
        prompt.load_text(":local stop ds")
        prompt.cursor_location = prompt.document.end

        await pilot.press("4", "enter")
        await pilot.pause()

        assert submitted == [":local stop ds4"]


async def test_prompt_ctrl_u_clears_entire_multiline_buffer(monkeypatch):
    """Ctrl+U must wipe the whole prompt, not just the current line.

    A user pasted a huge multi-line conversation and could only quit the app to
    get rid of it — TextArea's default Ctrl+U deletes to start of the current
    line only.
    """
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        prompt.focus()
        prompt.load_text("line one\nline two\nthe rest of a huge pasted blob")
        await pilot.pause()
        assert prompt.text

        await pilot.press("ctrl+u")
        await pilot.pause()
        assert prompt.text == ""


async def test_prompt_ctrl_a_selects_all():
    """Ctrl+A selects the whole prompt so it can be replaced/deleted."""
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        prompt.focus()
        prompt.load_text("select me all")
        await pilot.pause()

        await pilot.press("ctrl+a")
        await pilot.pause()
        assert prompt.selected_text == "select me all"


async def test_grok_profile_selection_routes_to_grok_build_acp(monkeypatch, tmp_path):
    """Selecting "Grok subscription" in the picker connects Grok Build (ACP).

    Since 0.2.x the bare Grok profile runs xAI's own agent, matching Codex and
    Claude. Grok now lives on the Subscriptions screen, so this also covers
    stepping into a submenu with the keyboard. (Picker-feedback visibility is
    covered by the Codex-profile test below.)
    """
    calls = []
    grok_auth = tmp_path / ".grok"
    grok_auth.mkdir()
    (grok_auth / "auth.json").write_text("{}", encoding="utf-8")

    import superqode.providers.connection_profiles as connection_profiles

    original_which = connection_profiles.shutil.which
    monkeypatch.setattr(
        connection_profiles.shutil,
        "which",
        lambda name: "/usr/bin/grok" if name == "grok" else original_which(name),
    )
    monkeypatch.setattr(
        connection_profiles.Path,
        "home",
        staticmethod(lambda: tmp_path),
    )

    def fake_connect_acp(self, args, log):
        calls.append(args)

    monkeypatch.setattr(SuperQodeApp, "_connect_acp_cmd", fake_connect_acp)

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_type_picker(log)
        await pilot.pause()

        from superqode.providers.connection_profiles import (
            CONNECT_MENU_AGENTS,
            CONNECT_MENU_ROOT,
            CONNECT_MENU_SUBSCRIPTIONS,
            display_ordered_profiles,
        )

        # Arrow keys walk the screen, so both hops count rows as drawn rather
        # than entries in the registry.
        root = display_ordered_profiles(CONNECT_MENU_ROOT)
        subscriptions_index = next(i for i, profile in enumerate(root) if profile.id == "agents")
        for _ in range(subscriptions_index):
            await pilot.press("down")
            await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app._connect_menu == CONNECT_MENU_AGENTS

        agent_categories = display_ordered_profiles(CONNECT_MENU_AGENTS)
        subscriptions_index = next(
            i for i, profile in enumerate(agent_categories) if profile.id == "agent-subscriptions"
        )
        for _ in range(subscriptions_index):
            await pilot.press("down")
            await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app._connect_menu == CONNECT_MENU_SUBSCRIPTIONS

        profiles = display_ordered_profiles(CONNECT_MENU_SUBSCRIPTIONS)
        grok_index = next(i for i, profile in enumerate(profiles) if profile.id == "grok")
        for _ in range(grok_index):
            await pilot.press("down")
            await pilot.pause()
        assert app._byok_highlighted_connect_type_index == grok_index

        await pilot.press("enter")
        await pilot.pause()

        assert calls == ["grok"]


async def test_codex_profile_error_visible_after_picker_navigation(monkeypatch):
    """Choosing the Codex profile without the SDK must show the install error.

    Same regression class as the Grok picker: the error was written while the
    picker scroll helpers had left auto_scroll disabled, so the user saw
    nothing happen.
    """
    import superqode.runtime as rt
    from superqode.runtime import RuntimeInfo

    def fake_list_runtimes():
        return [
            RuntimeInfo(
                name="codex-sdk",
                description="Codex SDK runtime",
                installed=False,
                install_hint='uv add "superqode[codex]"',
                implemented=True,
            )
        ]

    monkeypatch.setattr(rt, "list_runtimes", fake_list_runtimes)

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_type_picker(log, menu="subscriptions")
        await pilot.pause()

        # The legacy subscription alias opens the stable vendor screen directly.
        from superqode.providers.connection_profiles import display_ordered_profiles

        codex_index = next(
            index
            for index, profile in enumerate(display_ordered_profiles("vendors"))
            if profile.id == "codex"
        )
        for _ in range(codex_index):
            await pilot.press("down")
            await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        error_y = next(
            index for index, line in enumerate(log.lines) if "not installed" in line.text
        )
        visible_height = log.scrollable_content_region.height
        assert log.scroll_y <= error_y < log.scroll_y + visible_height


async def test_plain_write_panel_visible_after_byok_navigation(monkeypatch):
    """Inline panels written with log.write() must also land in the viewport.

    Arrow navigation runs the picker scroll helpers; they used to leave
    auto_scroll disabled, hiding any later plain-write panel (e.g. the
    "API Key Required" guidance).
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_byok_providers(log)
        await pilot.pause()

        for _ in range(8):
            await pilot.press("down")
            await pilot.pause()

        app._connect_byok_mode("openai", "gpt-5.6", log)
        # The feedback card is re-anchored after Textual completes its wrapped
        # line layout; assert the settled viewport rather than the write tick.
        await pilot.pause(0.1)

        panel_y = next(
            index for index, line in enumerate(log.lines) if "API Key Required" in line.text
        )
        visible_height = log.scrollable_content_region.height
        assert log.scroll_y <= panel_y < log.scroll_y + visible_height


async def test_quit_command_quits_from_harness_wizard(monkeypatch):
    """Typing :quit mid-wizard must reach the quit handler, not become an answer."""
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._start_harness_wizard_flow(log)
        await pilot.pause()
        assert app._awaiting_harness_wizard is True

        exits = []
        monkeypatch.setattr(app, "_do_exit", lambda log: exits.append(True))

        prompt = app.query_one(SelectionAwareInput)
        prompt.focus()
        prompt.load_text(":quit")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert exits == [True]


async def test_disconnect_tears_down_runtime_and_harness(monkeypatch):
    """:disconnect must drop the live runtime, not just reset the view.

    ``:home`` deliberately keeps ``_pure_mode`` warm, so a cosmetic-only reset
    left BYOK/local/SDK sessions connected while the badge claimed otherwise.
    """
    calls = []

    class _FakePureMode:
        def __init__(self):
            self.session = type("S", (), {"connected": True, "harness_name": "review-harness"})()

        def cancel(self):
            calls.append("cancel")

        def disconnect(self):
            calls.append("disconnect")

    monkeypatch.setenv("SUPERQODE_RUNTIME", "codex-sdk")
    monkeypatch.setenv("SUPERQODE_HARNESS", "review-harness")

    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        bar = app.query_one("#status-bar", ColorfulStatusBar)

        app._pure_mode = _FakePureMode()
        app.current_model = "gpt-5.5"
        app.current_provider = "openai"
        bar.active_runtime = "codex-sdk"
        bar.active_model = "gpt-5.5"
        bar.active_harness = "review-harness"
        await pilot.pause()

        app._disconnect_everything(log)
        await pilot.pause()

        # The runtime was cancelled and closed, not merely hidden.
        assert calls == ["cancel", "disconnect"]
        # A fresh launch has no _pure_mode attribute at all; connect paths test
        # with hasattr, so leaving a dead object behind would break reconnects.
        assert not hasattr(app, "_pure_mode")
        assert os.environ.get("SUPERQODE_RUNTIME") is None
        assert os.environ.get("SUPERQODE_HARNESS") is None
        assert bar.active_runtime == ""
        assert bar.active_model == ""
        # "core" is the built-in harness a freshly launched app reports, so the
        # named harness is detached rather than the row being blanked.
        assert bar.active_harness == "core"
        assert app.current_model == ""
        assert app.current_provider == ""


async def test_home_keeps_the_warm_runtime_session_and_shows_it():
    """:home stays a view change, so the live connection must stay on screen.

    Blanking the badge over a still-running session was the half-state that made
    :home look like it had disconnected.
    """
    from superqode.app.widgets import ModeBadge

    class _WarmPureMode:
        session = type("S", (), {"connected": True, "provider": "openai", "model": "gpt-5.5"})()

    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        badge = app.query_one("#mode-badge", ModeBadge)

        app._pure_mode = _WarmPureMode()
        app.current_provider = "openai"
        app.current_model = "gpt-5.5"
        badge.provider = "openai"
        badge.model = "gpt-5.5"
        badge.execution_mode = "byok"
        badge.agent = "codex"
        await pilot.pause()

        app._go_home(log)
        await pilot.pause()

        # The session itself is untouched.
        assert isinstance(app._pure_mode, _WarmPureMode)
        # The connection identity stays visible because it is still live.
        assert app.current_provider == "openai"
        assert app.current_model == "gpt-5.5"
        assert badge.provider == "openai"
        assert badge.model == "gpt-5.5"
        assert badge.execution_mode == "byok"
        # What :home really did tear down is cleared.
        assert badge.agent == ""
        assert app.current_agent == ""
        assert badge.mode == "home"


async def test_home_still_clears_the_badge_without_a_live_session():
    """With nothing warm behind it, :home must not advertise a connection."""
    from superqode.app.widgets import ModeBadge

    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        badge = app.query_one("#mode-badge", ModeBadge)

        app.current_provider = "openai"
        app.current_model = "gpt-5.5"
        badge.provider = "openai"
        badge.model = "gpt-5.5"
        badge.execution_mode = "byok"
        await pilot.pause()

        app._go_home(log)
        await pilot.pause()

        assert app.current_provider == ""
        assert app.current_model == ""
        assert badge.provider == ""
        assert badge.model == ""
        assert badge.execution_mode == ""


async def test_missing_runtime_offers_a_navigable_install_prompt(monkeypatch):
    """Selecting an uninstalled runtime must offer choices, not a dead-end error."""
    from superqode.runtime import RuntimeInfo

    missing = RuntimeInfo(
        name="codex-sdk",
        description="OpenAI Codex Python SDK",
        installed=False,
        install_hint='uv tool install "superqode[codex-sdk]"',
        implemented=True,
        ready=False,
    )

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._awaiting_runtime_selection = True
        app._runtime_selection_list = [missing]
        app._runtime_highlighted_index = 0
        await _settle(pilot)

        app.action_select_highlighted_runtime()
        await _settle(pilot)

        pending = app._awaiting_dependency_install
        assert isinstance(pending, dict)
        assert pending["runtime"] == "codex-sdk"
        assert pending["extra"] == "codex-sdk"
        # The command must pin the running interpreter, otherwise uv can resolve
        # a different environment than the one SuperQode imports from.
        assert "--python" in pending["command"] or "-m pip install" in pending["command"]
        # Opening the prompt closes the picker underneath it so Enter is unambiguous.
        assert app._awaiting_runtime_selection is False

        rendered = "\n".join(line.text for line in log.lines)
        assert "Install it for me" in rendered
        assert "I will install it myself" in rendered

        # Arrow keys move the highlight, which now lives on the prompt stack.
        assert app._prompts.index == 0
        app.action_navigate_dependency_install_down()
        await _settle(pilot)
        assert app._prompts.index == 1
        app.action_navigate_dependency_install_up()
        await _settle(pilot)
        assert app._prompts.index == 0


async def test_missing_copilot_routes_to_the_safe_dependency_picker(monkeypatch):
    """Copilot setup stays inside the TUI without offering an npm install."""
    import superqode.providers.connection_profiles as cp

    monkeypatch.setattr(cp, "_copilot_sdk_ready", lambda: False)
    monkeypatch.setattr(cp, "_copilot_acp_ready", lambda: False)

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._dispatch_connection_profile(cp.get_connection_profile("copilot"), log)
        await _settle(pilot)

        rendered = "\n".join(line.text for line in log.lines)
        assert app._prompts.is_active("dependency_install")
        assert "copilot-sdk is not installed" in rendered
        assert "superqode[copilot-sdk]" in rendered
        assert "Install it for me" in rendered
        assert "I will install it myself" in rendered
        assert "@github/copilot" not in rendered


async def test_choosing_manual_install_shows_the_command_without_installing():
    """'I will install it myself' must not run anything."""
    from superqode.runtime import RuntimeInfo

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        assert app._show_dependency_install_picker("codex-sdk", log) is True
        await pilot.pause()

        app._apply_dependency_install_choice("manual", log=log)
        await pilot.pause()

        assert app._awaiting_dependency_install is None
        rendered = "\n".join(line.text for line in log.lines)
        # The connect screen clears the log, so the command must be written
        # after it or the user loses the one thing they asked for.
        # The dev checkout installs the extra editable, so assert on the extra
        # itself rather than a spec form that only one environment produces.
        assert "[codex-sdk]" in rendered
        assert "pip install" in rendered
        assert "connect" in rendered.lower()


async def test_install_choice_runs_the_command_and_resumes(monkeypatch):
    """Choosing install must run the command and then connect the runtime."""
    import subprocess as _subprocess

    # list_runtimes() probes the antigravity CLI with its own subprocess call,
    # so record every invocation rather than assuming ours is the only one.
    ran = []

    def fake_run(argv, **kwargs):
        ran.append(list(argv))
        return _subprocess.CompletedProcess(argv, 0, "installed ok", "")

    resumed = []

    import superqode.runtime as _runtime_pkg

    installed = _runtime_pkg.RuntimeInfo(
        name="codex-sdk",
        description="OpenAI Codex Python SDK",
        installed=True,
        install_hint=None,
        implemented=True,
        ready=True,
    )

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        monkeypatch.setattr(_subprocess, "run", fake_run)
        monkeypatch.setattr(
            "superqode.providers.env_introspect.extra_install_command",
            lambda extra: f"uv pip install --python /safe/py 'superqode[{extra}]'",
        )
        monkeypatch.setattr(app, "_runtime_cmd", lambda name, log: resumed.append(name))
        # Stand in for the extra becoming importable after a real install.
        monkeypatch.setattr(_runtime_pkg, "list_runtimes", lambda: [installed])

        pending = {
            "runtime": "codex-sdk",
            "extra": "codex-sdk",
            # Prompt state is not trusted by the executor.
            "command": "npm install -g something-unrelated",
        }
        await app._install_runtime_extra_then_continue(pending, log)
        await pilot.pause()

        assert ["uv", "pip", "install", "--python", "/safe/py", "superqode[codex-sdk]"] in ran
        assert not any(argv[:2] == ["npm", "install"] for argv in ran)
        # codex-sdk is self-contained, so it connects directly after installing.
        assert resumed == ["codex-sdk"]


async def test_install_that_leaves_nothing_importable_is_reported(monkeypatch):
    """A zero exit code is not proof the extra is usable.

    superqode[codex-sdk] once pinned openai-codex to a range holding only
    pre-releases: the resolver happily installed an ancient SuperQode instead.
    An install that cannot be imported afterwards must say so here rather than
    failing later inside the runtime.
    """
    import subprocess as _subprocess

    def fake_run(argv, **kwargs):
        return _subprocess.CompletedProcess(argv, 0, "resolved something else", "")

    resumed = []

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        monkeypatch.setattr(_subprocess, "run", fake_run)
        monkeypatch.setattr(app, "_runtime_cmd", lambda name, log: resumed.append(name))

        pending = {
            "runtime": "codex-sdk",
            "extra": "codex-sdk",
            "command": "uv pip install --python /x/py 'superqode[codex-sdk]'",
        }
        await app._install_runtime_extra_then_continue(pending, log)
        await pilot.pause()

        rendered = "\n".join(line.text for line in log.lines)
        assert "still not importable" in rendered
        assert resumed == []


async def test_search_command_finds_transcript_text_without_vim_mode():
    """:search must work for users who never enable Vim mode."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._welcome_active = False
        log.clear()
        log.add_info("first line about widgets")
        log.add_info("second line about parsers")
        await pilot.pause()

        app._search_cmd("parsers", log)
        await pilot.pause()

        assert app._vim_search_query == "parsers"
        assert app._vim_search_matches, "expected a match for text present in the transcript"
        assert app._vim_enabled() is False


async def test_bare_search_advances_to_the_next_match():
    """Repeating :search must step through matches, not restart the search."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._welcome_active = False
        log.clear()
        for _ in range(3):
            log.add_info("repeated needle here")
        await pilot.pause()

        app._search_cmd("needle", log)
        await pilot.pause()
        first = app._vim_search_index

        app._search_cmd("", log)
        await pilot.pause()

        assert len(app._vim_search_matches) >= 2
        assert app._vim_search_index != first


async def test_keys_reference_covers_every_advertised_binding():
    """:keys is generated from BINDINGS, so it cannot drift from the real keys."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._welcome_active = False
        log.clear()

        app._keys_cmd(log)
        await pilot.pause()

        rendered = "\n".join(line.text for line in log.lines)
        advertised = [b.key for b in SuperQodeApp.BINDINGS if getattr(b, "show", False)]
        assert advertised, "expected at least one footer binding"
        for key in advertised:
            assert key in rendered, f"{key} is advertised but missing from :keys"
        assert "ctrl+f" in advertised  # the new search binding is discoverable


async def test_edit_last_message_loads_it_back_into_the_prompt():
    """Ctrl+P/:edit reword flow must repopulate the input, not resend blindly."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        app._last_user_message = "refactor the parser"
        await pilot.pause()

        app._edit_last_message(log)
        await pilot.pause()

        assert prompt.value == "refactor the parser"
        assert prompt.cursor_position == len("refactor the parser")


async def test_edit_last_message_refuses_while_the_agent_runs():
    """Editing mid-run would race the in-flight turn."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        app._last_user_message = "refactor the parser"
        app.is_busy = True
        await pilot.pause()

        app._edit_last_message(log)
        await pilot.pause()

        assert prompt.value == ""


async def test_ctrl_f_and_ctrl_p_are_reachable_as_real_keypresses():
    """Bindings must actually dispatch, not just exist as methods."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        app._last_user_message = "an earlier prompt"
        await pilot.pause()

        await pilot.press("ctrl+f")
        await pilot.pause()
        assert prompt.value == ":search "

        prompt.value = ""
        await pilot.pause()
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert prompt.value == "an earlier prompt"


async def test_no_color_env_var_degrades_the_whole_interface(monkeypatch):
    """NO_COLOR must reach the render pipeline.

    Textual installs a Monochrome filter when NO_COLOR is set, which is what
    makes the ~1300 hardcoded hex literals throughout the UI degrade without
    each one needing to be theme-aware. Nothing else pins that behavior, so a
    Textual upgrade or a custom Console could silently remove it.
    """
    monkeypatch.setenv("NO_COLOR", "1")

    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

        assert app.no_color is True
        filters = [type(f).__name__ for f in app._filters]
        assert "Monochrome" in filters or "NoColor" in filters


async def test_registry_driven_prompt_handles_every_key_path():
    """One PromptSpec registration must cover arrows, Enter, numbers, and Esc.

    Before the registry each of these lived in a separate dispatch site and had
    to be wired by hand; missing one produced a prompt that could not be
    cancelled or whose arrow keys did nothing.
    """
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)

        # Arrows.
        app._show_dependency_install_picker("codex-sdk", log)
        await _settle(pilot)
        assert app._prompts.is_active("dependency_install")
        app._prompts.navigate(1)
        assert app._prompts.index == 1

        # Esc closes it and falls back to the runtime picker underneath.
        assert app._prompts.cancel() is True
        await _settle(pilot)
        assert app._prompts.active is None
        assert app._awaiting_dependency_install is None

        # Numbers select. Option 2 is "manual", which only prints the command.
        app._show_dependency_install_picker("codex-sdk", log)
        await _settle(pilot)
        app._prompts.select_index(1)
        await _settle(pilot)
        assert app._prompts.active is None

        # Typed answers route through the same spec.
        app._show_dependency_install_picker("codex-sdk", log)
        await _settle(pilot)
        assert app._prompts.handle_text("n") is True
        await _settle(pilot)
        assert app._prompts.active is None


async def test_dependency_prompt_arrow_keys_work_as_real_keypresses():
    """Arrows must move the highlight when actually pressed.

    The first version of this prompt called the navigation actions directly in
    tests, which passed while real arrow keys did nothing: the input widget
    routes up/down through its own chain, and the prompt was not in it.
    """
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_dependency_install_picker("claude-agent-sdk", log)
        await _settle(pilot)

        assert app._prompts.is_active("dependency_install")
        assert app._prompts.index == 0

        await pilot.press("down")
        await _settle(pilot)
        assert app._prompts.index == 1, "down arrow did not move the highlight"

        await pilot.press("down")
        await _settle(pilot)
        assert app._prompts.index == 2

        # Clamped at the end rather than wrapping or overflowing.
        await pilot.press("down")
        await _settle(pilot)
        assert app._prompts.index == 2

        await pilot.press("up")
        await _settle(pilot)
        assert app._prompts.index == 1


async def test_dependency_prompt_enter_selects_the_highlighted_row():
    """Enter after arrowing must act on the row the user actually highlighted."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_dependency_install_picker("claude-agent-sdk", log)
        await _settle(pilot)

        # Move to "I will install it myself", which only prints the command.
        await pilot.press("down")
        await _settle(pilot)
        assert app._prompts.index == 1

        await pilot.press("enter")
        await _settle(pilot)

        assert app._prompts.active is None
        rendered = "\n".join(line.text for line in log.lines)
        # "Install it myself" shows the command and lands on the connect screen.
        assert "[claude-agent-sdk]" in rendered
        assert "pip install" in rendered


async def test_dependency_prompt_escape_returns_to_the_connect_screen():
    """Esc must run the prompt's cancel hook, matching the Cancel option."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_dependency_install_picker("claude-agent-sdk", log)
        await _settle(pilot)
        assert app._prompts.is_active("dependency_install")

        await pilot.press("escape")
        await _settle(pilot)

        assert app._prompts.active is None
        rendered = "\n".join(line.text for line in log.lines)
        # The runtime picker would only re-offer the runtime just declined.
        assert "Select Runtime" not in rendered
        assert "connect" in rendered.lower(), "Esc should land on the connection screen"


@pytest.mark.parametrize("entry", ["typed_name", "number_key", "runtime_command"])
async def test_every_route_to_the_install_prompt_accepts_enter(entry, monkeypatch):
    """Enter must install no matter how the prompt was reached.

    Typing the runtime name used to be swallowed by the picker's Enter handler,
    which selected the highlighted row instead, so the prompt never opened at
    all for that route.
    """
    import subprocess as _subprocess

    ran = []

    def fake_run(argv, **kwargs):
        ran.append(list(argv))
        return _subprocess.CompletedProcess(argv, 0, "ok", "")

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.focus()

        if entry == "runtime_command":
            prompt.value = ":runtime claude-agent-sdk"
            await pilot.press("enter")
        else:
            app._show_runtime_picker(log)
            await _settle(pilot)
            if entry == "typed_name":
                prompt.value = "claude-agent-sdk"
                await pilot.press("enter")
            else:
                names = [r.name for r in app._runtime_selection_list]
                await pilot.press(str(names.index("claude-agent-sdk") + 1))
        for _ in range(4):
            await _settle(pilot)

        assert app._prompts.is_active("dependency_install"), f"{entry} did not open the prompt"

        monkeypatch.setattr(_subprocess, "run", fake_run)
        await pilot.press("enter")
        for _ in range(6):
            await _settle(pilot)

        assert any("pip" in argv for argv in ran), f"{entry}: Enter did not start the install"


async def test_cancelling_the_install_prompt_lands_on_the_connect_screen():
    """Cancel must not dump the user back on the runtime they just declined."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_dependency_install_picker("claude-agent-sdk", log)
        await _settle(pilot)

        # Option 3 is Cancel.
        app._prompts.select_index(2)
        for _ in range(3):
            await _settle(pilot)

        assert app._prompts.active is None
        rendered = "\n".join(line.text for line in log.lines)
        assert "Select Runtime" not in rendered
        assert "connect" in rendered.lower()


async def test_agy_models_opens_a_picker_instead_of_printing_a_list(monkeypatch):
    """`:agy models` must be selectable, not just readable."""
    import shutil as _shutil
    import subprocess as _subprocess

    listing = "gemini-3.6-flash-high\ngemini-3.1-pro-low\nclaude-sonnet-4-6\n"

    monkeypatch.setattr(_shutil, "which", lambda name: "/usr/bin/agy" if name == "agy" else None)
    monkeypatch.setattr(
        _subprocess,
        "run",
        lambda argv, **kw: _subprocess.CompletedProcess(argv, 0, listing, ""),
    )

    chosen = []
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        monkeypatch.setattr(app, "_antigravity_model_cmd", lambda m, log: chosen.append(m))

        await app._show_agy_models(log)
        await _settle(pilot)

        assert app._prompts.is_active("vendor_model")
        rendered = "\n".join(line.text for line in log.lines)
        assert "Select Antigravity Model" in rendered
        assert "gemini-3.6-flash-high" in rendered

        # Arrow to the second entry and confirm it, through real keypresses.
        await pilot.press("down")
        await _settle(pilot)
        await pilot.press("enter")
        await _settle(pilot)

        assert chosen == ["gemini-3.1-pro-low"]
        assert app._prompts.active is None


async def test_agy_models_falls_back_to_raw_output_when_nothing_parses(monkeypatch):
    """An unexpected output format must not leave the user with nothing."""
    import shutil as _shutil
    import subprocess as _subprocess

    monkeypatch.setattr(_shutil, "which", lambda name: "/usr/bin/agy" if name == "agy" else None)
    monkeypatch.setattr(
        _subprocess,
        "run",
        lambda argv, **kw: _subprocess.CompletedProcess(argv, 0, "### no models ###\n", ""),
    )

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        await app._show_agy_models(log)
        await _settle(pilot)

        assert app._prompts.active is None
        rendered = "\n".join(line.text for line in log.lines)
        assert "no models" in rendered


async def test_number_keys_select_in_any_registry_prompt(monkeypatch):
    """Number selection is generic, not wired per prompt."""
    import shutil as _shutil
    import subprocess as _subprocess

    listing = "gemini-3.6-flash-high\ngemini-3.1-pro-low\nclaude-sonnet-4-6\n"
    monkeypatch.setattr(_shutil, "which", lambda name: "/usr/bin/agy" if name == "agy" else None)
    monkeypatch.setattr(
        _subprocess,
        "run",
        lambda argv, **kw: _subprocess.CompletedProcess(argv, 0, listing, ""),
    )

    chosen = []
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        monkeypatch.setattr(app, "_antigravity_model_cmd", lambda m, log: chosen.append(m))

        await app._show_agy_models(log)
        await _settle(pilot)
        assert app._prompts.is_active("vendor_model")

        await pilot.press("3")
        for _ in range(3):
            await _settle(pilot)

        assert chosen == ["claude-sonnet-4-6"]


async def test_connect_acp_defaults_to_featured_and_keeps_all_discoverable():
    """First-run stays focused while the complete registry remains explicit."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_acp_cmd("", log)
        for _ in range(12):
            await pilot.pause()

        assert app._awaiting_acp_agent_selection is True
        assert app._acp_catalog_view == "featured"
        default_count = len(app._acp_agent_list)

        app._connect_acp_cmd("all", log)
        for _ in range(12):
            await pilot.pause()

        assert app._acp_catalog_view == "all"
        assert len(app._acp_agent_list) >= default_count
        assert default_count > 0


async def test_arrow_keys_keep_the_chosen_acp_view():
    """Redrawing on navigation used to snap a filtered view back to the default."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_acp_cmd("featured", log)
        for _ in range(12):
            await pilot.pause()

        assert app._acp_catalog_view == "featured"
        featured_count = len(app._acp_agent_list)

        app.action_navigate_acp_agent_down()
        for _ in range(12):
            await pilot.pause()

        assert app._acp_catalog_view == "featured", "navigation changed the view"
        assert len(app._acp_agent_list) == featured_count


async def test_arrow_keys_reuse_the_acp_catalog_snapshot():
    """A highlight move inside the TTL must not re-read every agent file.

    Freshness comes from the background revalidation, not from making every
    keystroke wait on a PATH scan.
    """
    app = SuperQodeApp()
    async with app.run_test(size=(100, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_acp_cmd("featured", log)
        for _ in range(12):
            await pilot.pause()

        rows = len(app._acp_agent_list)
        assert rows > 1

        import superqode.agents.registry as registry

        calls = []
        original = registry.get_all_acp_agents

        async def counted():
            calls.append(1)
            return await original()

        registry.get_all_acp_agents = counted
        try:
            app.action_navigate_acp_agent_down()
            for _ in range(12):
                await pilot.pause()
        finally:
            registry.get_all_acp_agents = original

        assert calls == [], "navigation rebuilt the catalogue instead of reusing it"
        assert len(app._acp_agent_list) == rows
        assert app._acp_highlighted_agent_index == 1


async def test_reopening_the_acp_picker_rebuilds_the_catalog_snapshot():
    """Only navigation reuses the snapshot, so an install is picked up on reopen."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_acp_cmd("featured", log)
        for _ in range(12):
            await pilot.pause()

        import superqode.agents.registry as registry

        calls = []
        original = registry.get_all_acp_agents

        async def counted():
            calls.append(1)
            return await original()

        registry.get_all_acp_agents = counted
        try:
            app._connect_acp_cmd("featured", log)
            for _ in range(12):
                await pilot.pause()
        finally:
            registry.get_all_acp_agents = original

        assert calls, "reopening the picker served a stale catalogue"


def _patch_registry_with_newcomer(monkey_target):
    """Return a ``get_all_acp_agents`` that adds one agent the catalogue lacked."""
    original = monkey_target.get_all_acp_agents

    async def with_newcomer():
        agents = dict(await original())
        agents["newcomer.example"] = {
            "identity": "newcomer.example",
            "name": "Newcomer Agent",
            "short_name": "newcomer",
            "protocol": "acp",
            "catalog_tier": "featured",
        }
        return agents

    return original, with_newcomer


async def test_a_newly_landed_acp_agent_appears_without_reopening_the_picker():
    """An agent installed elsewhere must not stay hidden behind a stale snapshot."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_acp_cmd("all", log)
        for _ in range(12):
            await pilot.pause()

        before = len(app._acp_agent_list)
        assert before > 1

        import superqode.agents.registry as registry

        original, with_newcomer = _patch_registry_with_newcomer(registry)
        registry.get_all_acp_agents = with_newcomer
        # Age the snapshot so the next redraw revalidates instead of serving it.
        app._acp_picker_snapshot_at = 0.0
        try:
            app.action_navigate_acp_agent_down()
            for _ in range(30):
                await pilot.pause()
        finally:
            registry.get_all_acp_agents = original

        assert len(app._acp_agent_list) == before + 1
        assert any(agent_id == "newcomer.example" for agent_id, _ in app._acp_agent_list)


async def test_a_background_catalog_rebuild_keeps_the_same_agent_highlighted():
    """Rows shift when an agent lands; the selection must follow its agent."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_acp_cmd("all", log)
        for _ in range(12):
            await pilot.pause()

        app.action_navigate_acp_agent_down()
        app.action_navigate_acp_agent_down()
        for _ in range(12):
            await pilot.pause()

        anchor = app._acp_agent_list[app._acp_highlighted_agent_index][0]

        import superqode.agents.registry as registry

        original, with_newcomer = _patch_registry_with_newcomer(registry)
        registry.get_all_acp_agents = with_newcomer
        app._acp_picker_snapshot_at = 0.0
        try:
            app._reshow_acp_agents(log)
            for _ in range(30):
                await pilot.pause()
        finally:
            registry.get_all_acp_agents = original

        assert any(agent_id == "newcomer.example" for agent_id, _ in app._acp_agent_list)
        assert app._acp_agent_list[app._acp_highlighted_agent_index][0] == anchor


async def test_an_unchanged_catalog_does_not_repaint_the_picker():
    """Revalidation is silent unless something actually landed."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_acp_cmd("all", log)
        for _ in range(12):
            await pilot.pause()

        repaints = []
        original_reshow = app._reshow_acp_agents
        app._reshow_acp_agents = lambda target: repaints.append(target)
        app._acp_picker_snapshot_at = 0.0
        try:
            app._revalidate_acp_catalog(log)
            for _ in range(30):
                await pilot.pause()
        finally:
            app._reshow_acp_agents = original_reshow

        assert repaints == []
        # The rebuild still ran; it just found nothing worth repainting for.
        assert app._acp_picker_snapshot_at > 0.0


async def test_clicking_an_acp_model_row_selects_that_model():
    """A boxed model row must be clickable, not just drag-selectable text.

    The ACP model pickers draw their rows inside a box and raise
    ``_awaiting_model_selection``. Neither the click gate nor the row pattern
    accounted for that, so a click fell through to the terminal's own text
    selection and the list looked inert.
    """
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app.current_agent = "opencode"
        app._opencode_models = [
            {"id": "openai/gpt-5.2", "name": "gpt-5.2", "desc": "fast"},
            {"id": "anthropic/claude-opus-5", "name": "claude-opus-5", "desc": "deep"},
        ]
        app._show_opencode_models_selection({"name": "OpenCode"}, log)
        await _settle(pilot)
        assert app._awaiting_model_selection is True

        row = next(index for index, line in enumerate(log.lines) if "[2]" in line.text)
        offset = log.region.offset + (6, row - int(log.scroll_offset.y))
        await pilot.click(offset=offset)
        await _settle(pilot)

        assert app.current_model == "anthropic/claude-opus-5"
        assert app._awaiting_model_selection is False


async def test_a_typed_model_number_past_five_is_not_sent_to_the_agent():
    """The old 1-5 gate let a typed "7" fall through and become a prompt."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app.current_agent = "opencode"
        app._opencode_models = [
            {"id": f"vendor/model-{n}", "name": f"model-{n}"} for n in range(1, 9)
        ]
        app._show_opencode_models_selection({"name": "OpenCode"}, log)
        await _settle(pilot)

        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "7"
        await pilot.press("enter")
        await _settle(pilot)

        assert app.current_model == "vendor/model-7"
        assert app._awaiting_model_selection is False


async def test_model_picker_digits_buffer_so_two_digit_rows_are_reachable():
    """Typing 1 then 2 must reach model 12, not select model 1 immediately."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app.current_agent = "opencode"
        app._opencode_models = [
            {"id": f"vendor/model-{n}", "name": f"model-{n}"} for n in range(1, 15)
        ]
        app._show_opencode_models_selection({"name": "OpenCode"}, log)
        await _settle(pilot)

        app._select_by_number_universal(1)
        await _settle(pilot)
        assert app._awaiting_model_selection is True, "the first digit selected a model"

        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        assert prompt.value == "1"


async def test_closing_the_a2a_screen_returns_to_the_protocols_listing():
    """Back from a protocol screen belongs on the list it was opened from.

    The screen is a Textual screen, so it records no history step. Without
    marking the listing as still current, back popped Protocols and landed on
    the connect root instead.
    """
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_PROTOCOLS,
        get_connection_profile,
    )

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_type_picker(log)
        await pilot.pause()
        app._show_connect_type_picker(log, menu=CONNECT_MENU_PROTOCOLS)
        await pilot.pause()
        assert app._connect_menu == CONNECT_MENU_PROTOCOLS

        app._dispatch_connection_profile(get_connection_profile("protocol-a2a"), log)
        await pilot.pause()

        # Close it the way the screen's Back control does.
        app.screen.action_close()
        for _ in range(6):
            await pilot.pause()

        assert app._connect_menu == CONNECT_MENU_PROTOCOLS, "back left the protocols listing"
        assert app._awaiting_connect_type is True, "the listing came back inert"
        rendered = "\n".join(line.text for line in log.lines)
        assert "Agent2Agent" in rendered or "A2A" in rendered


async def test_back_from_the_protocols_listing_still_reaches_the_connect_root():
    """Restoring the listing must not strand the user on it."""
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_PROTOCOLS,
        CONNECT_MENU_ROOT,
        get_connection_profile,
    )

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_type_picker(log)
        await pilot.pause()
        app._show_connect_type_picker(log, menu=CONNECT_MENU_PROTOCOLS)
        await pilot.pause()

        app._dispatch_connection_profile(get_connection_profile("protocol-a2a"), log)
        await pilot.pause()
        app.screen.action_close()
        for _ in range(6):
            await pilot.pause()
        assert app._connect_menu == CONNECT_MENU_PROTOCOLS

        # One more back leaves the protocols listing for the screen above it.
        app._navigate_back()
        await pilot.pause()
        assert app._connect_menu == CONNECT_MENU_ROOT


def _modal_body(app) -> str:
    """Read the text out of the open outcome modal."""
    from textual.widgets import Static

    from superqode.widgets.outcome_screen import OutcomeScreen

    assert isinstance(app.screen, OutcomeScreen), f"no modal, got {type(app.screen).__name__}"
    return app.screen.query_one("#outcome-content").query_one(Static).render().plain


async def test_a_finished_state_change_opens_an_acknowledgeable_modal():
    """A toast for "agent connected" was easy to miss and hard to read."""
    app = SuperQodeApp()
    async with app.run_test(size=(92, 30)) as pilot:
        await _settle(pilot)
        app._announce_transition(
            title="Agent connected",
            primary="OpenCode",
            detail="opencode/big-pickle via ACP",
            severity="success",
        )
        await _settle(pilot)

        body = _modal_body(app)
        assert "Agent connected" in body
        assert "OpenCode" in body
        assert "opencode/big-pickle via ACP" in body
        assert "✅" in body, "severity is not readable at a glance"
        assert "From state change" not in body, "internal plumbing leaked into the modal"


async def test_a_second_announcement_reuses_the_open_modal():
    """Connecting announces more than once; that is still one dismissal."""
    app = SuperQodeApp()
    async with app.run_test(size=(92, 30)) as pilot:
        await _settle(pilot)
        app._announce_transition(
            title="Agent connected", primary="OpenCode", detail="via ACP", severity="success"
        )
        await _settle(pilot)
        depth = len(app.screen_stack)

        app._announce_transition(
            title="Model ready", primary="big-pickle", detail="OpenCode via ACP", severity="success"
        )
        await _settle(pilot)

        assert len(app.screen_stack) == depth, "a second announcement stacked another modal"
        body = _modal_body(app)
        assert "Model ready" in body and "big-pickle" in body
        assert "Agent connected" not in body, "the modal kept stale content"


async def test_enter_dismisses_the_state_change_modal():
    app = SuperQodeApp()
    async with app.run_test(size=(92, 30)) as pilot:
        await _settle(pilot)
        app._announce_transition(
            title="Agent connected", primary="OpenCode", detail="via ACP", severity="success"
        )
        await _settle(pilot)
        assert len(app.screen_stack) == 2

        await pilot.press("enter")
        await _settle(pilot)
        assert len(app.screen_stack) == 1, "Enter did not dismiss the modal"


async def test_a_progress_note_never_demands_a_dismissal():
    """Nothing has finished yet, so stopping the user mid-flow would be worse."""
    app = SuperQodeApp()
    async with app.run_test(size=(92, 30)) as pilot:
        await _settle(pilot)
        app._announce_transition(
            title="Connecting",
            primary="OpenCode",
            detail="Starting ACP session",
            severity="information",
            persist=False,
            popup=True,
        )
        await _settle(pilot)
        assert len(app.screen_stack) == 1, "a progress note opened a modal"


async def test_a_failure_modal_offers_its_recovery_command():
    """An error that names a command should let the user run it from here."""
    app = SuperQodeApp()
    async with app.run_test(size=(92, 30)) as pilot:
        await _settle(pilot)
        app._announce_transition(
            title="Connection failed",
            primary="opencode",
            detail="Model x-preview-f-free is not supported",
            severity="error",
            guidance=":log verbose",
        )
        await _settle(pilot)

        body = _modal_body(app)
        assert "❌" in body
        assert "Connection failed" in body
        assert ":log verbose" in body
        actions = [action.command for action in app.screen.outcome.actions]
        assert ":log verbose" in actions


async def test_acp_plan_updates_fill_the_live_plan_panel():
    """An ACP plan belongs in the pinned panel, not in a one-line count."""
    from superqode.acp.render import plan_entries_to_todos

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        panel = app.query_one("#todo-panel", Static)
        assert "visible" not in panel.classes

        app._set_todos(
            plan_entries_to_todos(
                [
                    {"content": "Read the failing test", "status": "completed"},
                    {"content": "Fix the bug", "status": "in_progress"},
                    {"content": "Run the suite", "status": "pending"},
                ]
            )
        )
        await pilot.pause()

        assert "visible" in panel.classes
        rendered = "\n".join(strip.text for strip in panel.render_lines(panel.size.region))
        assert "1/3 done" in rendered
        assert "Fix the bug" in rendered


async def test_a_finished_acp_plan_hides_the_panel_again():
    """Nothing outstanding means nothing pinned to the top of the screen."""
    from superqode.acp.render import plan_entries_to_todos

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        panel = app.query_one("#todo-panel", Static)
        entries = [{"content": "Fix the bug", "status": "in_progress"}]
        app._set_todos(plan_entries_to_todos(entries))
        await pilot.pause()
        assert "visible" in panel.classes

        entries[0]["status"] = "completed"
        app._set_todos(plan_entries_to_todos(entries))
        await pilot.pause()
        assert "visible" not in panel.classes


async def test_vendor_model_picker_is_shared_across_runtimes():
    """One picker serves every vendor's model list, keyed by (id, label)."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        chosen = []

        opened = app._show_vendor_model_picker(
            log,
            title="Select Test Model",
            entries=[("m-1", "Model One"), ("m-2", "Model Two"), ("m-3", "Model Three")],
            on_choose=chosen.append,
            current="m-2",
        )
        await _settle(pilot)

        assert opened is True
        assert app._prompts.is_active("vendor_model")
        rendered = "\n".join(line.text for line in log.lines)
        assert "Select Test Model" in rendered
        assert "Model One" in rendered
        assert "◀ active" in rendered  # the current model is marked

        for _ in range(6):
            await _settle(pilot)
        await pilot.press("down")
        for _ in range(6):
            await _settle(pilot)
        await pilot.press("enter")
        for _ in range(6):
            await _settle(pilot)

        # The id is chosen, not the label shown.
        assert chosen == ["m-2"]


async def test_vendor_model_picker_reports_an_empty_list():
    """Callers need to fall back to their own message, not show an empty picker."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        assert (
            app._show_vendor_model_picker(
                log, title="Nothing", entries=[], on_choose=lambda _: None
            )
            is False
        )
        await _settle(pilot)
        assert app._prompts.active is None


async def test_claude_model_list_is_selectable(monkeypatch):
    """:claude model printed [1] [2] [3] that did nothing; they must work now."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._claude_model_cmd("", log)
        await _settle(pilot)

        assert app._prompts.is_active("vendor_model")
        rendered = "\n".join(line.text for line in log.lines)
        assert "Select Claude Model" in rendered


async def test_manual_install_differs_from_cancel_and_links_the_vendor_docs():
    """'I will install it myself' must give more than Cancel does.

    Both used to land on the connect screen with near-identical output, so the
    manual choice now carries the command plus a pointer to the vendor's own
    documentation, which outlives any command SuperQode hardcodes.
    """
    app = SuperQodeApp()
    async with app.run_test(size=(100, 50)) as pilot:
        log = app.query_one("#log", ConversationLog)

        app._show_dependency_install_picker("codex-sdk", log)
        await pilot.pause()
        app._apply_dependency_install_choice("manual", pending=app._awaiting_dependency_install)
        await pilot.pause()
        manual = "\n".join(line.text for line in log.lines)

        assert "official documentation" in manual
        assert "https://developers.openai.com/codex/sdk/" in manual
        assert "pip install" in manual

        app._show_dependency_install_picker("codex-sdk", log)
        await pilot.pause()
        app._apply_dependency_install_choice("cancel", pending=app._awaiting_dependency_install)
        await pilot.pause()
        cancelled = "\n".join(line.text for line in log.lines)

        assert "Skipped installing" in cancelled
        assert "official documentation" not in cancelled


async def test_manual_install_omits_the_link_when_none_is_known():
    """No guessed URLs: a runtime with no known docs simply gets the note."""
    app = SuperQodeApp()
    async with app.run_test(size=(100, 50)) as pilot:
        log = app.query_one("#log", ConversationLog)

        app._apply_dependency_install_choice(
            "manual",
            pending={"runtime": "made-up-runtime", "extra": "x", "command": "uv pip install x"},
            log=log,
        )
        await pilot.pause()

        rendered = "\n".join(line.text for line in log.lines)
        assert "official documentation" in rendered
        assert "http" not in rendered.split("official documentation")[1]


async def test_npm_agent_is_manual_only(monkeypatch):
    """Even a simple vendor npm command is never run by SuperQode."""
    agent = {"short_name": "kilo", "name": "Kilo CLI"}

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        monkeypatch.setattr(
            "superqode.agents.registry.get_agent_installation_info",
            lambda data: {"command": "npm install -g @kilocode/cli"},
        )
        assert app._show_agent_install_picker(agent, log) is True
        await _settle(pilot)

        rendered = "\n".join(line.text for line in log.lines)
        assert "Install it for me" not in rendered
        assert "I will install it myself" in rendered
        assert "npm install -g @kilocode/cli" in rendered
        assert "External agent installers are manual-only" in rendered
        assert len(list(app._prompts.active.options())) == 2

        # Enter chooses the manual path; it must only display guidance.
        await pilot.press("enter")
        await _settle(pilot)
        rendered = "\n".join(line.text for line in log.lines)
        assert "Install Kilo CLI yourself with" in rendered


async def test_pipe_to_shell_agent_is_never_offered_for_install(monkeypatch):
    """The option list itself must reflect what SuperQode is willing to run."""
    agent = {"short_name": "kimi", "name": "Kimi Code"}

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        monkeypatch.setattr(
            "superqode.agents.registry.get_agent_installation_info",
            lambda data: {
                "command": "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash"
            },
        )
        assert app._show_agent_install_picker(agent, log) is True
        await _settle(pilot)

        rendered = "\n".join(line.text for line in log.lines)
        assert "Install it for me" not in rendered
        assert "I will install it myself" in rendered
        assert "does not run those for you" in rendered
        # Only the two safe options are selectable.
        assert len(list(app._prompts.active.options())) == 2


async def test_external_agent_install_choice_is_defensively_rejected(monkeypatch):
    """A stale or direct install action cannot execute a vendor installer."""
    agent = {"short_name": "kilo", "name": "Kilo CLI"}

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        from superqode.agents.install_commands import classify_install_command

        install = classify_install_command("npm install -g @kilocode/cli")
        app._apply_agent_install_choice("install", agent_data=agent, install=install, log=log)
        await pilot.pause()

        rendered = "\n".join(line.text for line in log.lines)
        assert "does not automatically install external agents" in rendered


async def test_connect_byok_parses_model_ids_containing_slashes():
    """`:connect byok <provider> <model>` must survive slashes in the model id.

    Open-weight ids are almost always namespaced ("moonshot-ai/Kimi-K3",
    "accounts/fireworks/models/kimi-k3"). Resolving the "/" form before the
    whitespace form read the provider as "baseten moonshot-ai" and failed with
    a confusing "not available from the current models.dev catalog".
    """
    captured = []

    app = SuperQodeApp()
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_byok_mode = lambda p, m, log, *a, **k: captured.append((p, m))

        cases = {
            "baseten moonshot-ai/Kimi-K3": ("baseten", "moonshot-ai/Kimi-K3"),
            "openrouter moonshotai/kimi-k3": ("openrouter", "moonshotai/kimi-k3"),
            "fireworks accounts/fireworks/models/kimi-k3": (
                "fireworks",
                "accounts/fireworks/models/kimi-k3",
            ),
            # The single-token "provider/model" form must keep working.
            "baseten/moonshot-ai/Kimi-K3": ("baseten", "moonshot-ai/Kimi-K3"),
            "anthropic claude-opus-4-8": ("anthropic", "claude-opus-4-8"),
        }
        for args, expected in cases.items():
            captured.clear()
            app._connect_byok_cmd(args, log)
            await pilot.pause()
            assert captured == [expected], f"{args!r} routed to {captured}"


@pytest.fixture
def models_dev_long_tail():
    """Guarantee a models.dev long tail regardless of the machine's cache.

    ``all_provider_ids()`` unions the curated registry with whatever the
    models.dev client has loaded, and that client reads a network-populated
    cache under the user's home directory. A developer machine has one and a
    clean CI runner does not, so tests about collapsing the long tail passed
    locally and failed in CI against the curated set alone. Seed the client so
    the behaviour under test is exercised either way.
    """
    from superqode.providers.models_dev import ProviderInfo, get_models_dev

    client = get_models_dev()
    previous = client._providers.copy()
    # env_vars must be non-empty: the picker treats a host that needs no key as
    # already configured, and configured hosts are deliberately never collapsed.
    synthetic = {
        f"long-tail-host-{index:03d}": ProviderInfo(
            id=f"long-tail-host-{index:03d}",
            name=f"Long Tail Host {index:03d}",
            env_vars=[f"LONG_TAIL_HOST_{index:03d}_API_KEY"],
        )
        for index in range(140)
    }
    # deepinfra is the concrete long-tail host these tests assert on.
    synthetic["deepinfra"] = ProviderInfo(
        id="deepinfra", name="DeepInfra", env_vars=["DEEPINFRA_API_KEY"]
    )
    client._providers = {**previous, **synthetic}
    try:
        yield client
    finally:
        client._providers = previous


async def test_provider_picker_collapses_the_models_dev_long_tail(models_dev_long_tail):
    """models.dev synthesizes ~140 hosts that buried the curated ones."""
    from superqode.providers.dynamic import connect_provider_ids

    app = SuperQodeApp()
    async with app.run_test(size=(110, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_picker(log)
        await pilot.pause()

        shown = [pid for pid, _ in app._byok_connect_list]
        assert len(shown) < len(connect_provider_ids()) / 3, "the long tail is still shown"

        rendered = "\n".join(line.text for line in log.lines)
        assert "more hosts" in rendered
        assert ":connect byok all" in rendered


async def test_connect_byok_all_reveals_every_provider(models_dev_long_tail):
    """The collapsed hosts stay one command away."""
    from superqode.providers.dynamic import connect_provider_ids

    app = SuperQodeApp()
    async with app.run_test(size=(110, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._connect_byok_cmd("all", log)
        await pilot.pause()

        shown = [pid for pid, _ in app._byok_connect_list]
        # Local/self-hosted providers are deliberately excluded from the BYOK
        # picker (they have their own :connect local), so "all" means every
        # cloud provider rather than literally every id.
        assert len(shown) > len(connect_provider_ids()) * 0.8
        assert "deepinfra" in shown, "a long-tail host should be revealed"


async def test_curated_hosts_survive_the_collapse():
    """Every curated Model Host must remain visible by default."""
    from superqode.providers.registry import PROVIDERS, ProviderCategory
    from superqode.providers.dynamic import connect_provider_ids

    app = SuperQodeApp()
    async with app.run_test(size=(110, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_picker(log)
        await pilot.pause()

        shown = {pid for pid, _ in app._byok_connect_list}
        reachable = set(connect_provider_ids())
        curated_hosts = {
            pid
            for pid, p in PROVIDERS.items()
            if p.category is ProviderCategory.MODEL_HOSTS and pid in reachable
        }
        assert curated_hosts <= shown, f"hidden curated hosts: {sorted(curated_hosts - shown)}"


async def test_pinned_hosts_lead_the_model_hosts_section():
    """Baseten sorts 2nd alphabetically, so the order needs an explicit pin."""
    app = SuperQodeApp()
    async with app.run_test(size=(110, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_picker(log)
        await pilot.pause()

        from superqode.providers.registry import (
            PROVIDERS,
            ProviderCategory,
            get_free_providers,
        )

        # Providers with free models render in their own section above the
        # categories, so they take no part in the Model Hosts ordering.
        free = set(get_free_providers())
        hosts = [
            pid
            for pid, _ in app._byok_connect_list
            if pid not in free
            and PROVIDERS.get(pid)
            and PROVIDERS[pid].category is ProviderCategory.MODEL_HOSTS
        ]
        expected = [pid for pid in app._PINNED_MODEL_HOSTS if pid not in free]
        assert hosts[: len(expected)] == expected


async def test_a_configured_long_tail_provider_is_never_hidden(monkeypatch, models_dev_long_tail):
    """Hiding a host whose key is set would look like it is unsupported."""
    app = SuperQodeApp()
    async with app.run_test(size=(110, 60)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_picker(log)
        await pilot.pause()
        assert "deepinfra" not in {pid for pid, _ in app._byok_connect_list}

        monkeypatch.setenv("DEEPINFRA_API_KEY", "sk-test")
        app._show_connect_picker(log)
        await pilot.pause()

        assert "deepinfra" in {pid for pid, _ in app._byok_connect_list}


async def test_clicking_anywhere_on_a_picker_row_selects_it(monkeypatch):
    """Rows list names and paths; a click lands on those, not the number."""
    import re

    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    async with app.run_test(size=(120, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_local_provider_picker(log)
        await pilot.pause()

        rows = [
            (index, "".join(segment.text for segment in strip).rstrip())
            for index, strip in enumerate(log.lines)
            if re.match(r"^\s*[▶●○]?\s*\[\s*\d+\s*\]", "".join(s.text for s in strip))
        ]
        assert rows, "no picker rows rendered"
        assert app._awaiting_local_provider is True

        line_index, text = rows[-1]
        # Far right of the row, past everything carrying a link style.
        y = log.region.y + line_index - int(log.scroll_offset.y)
        x = log.region.x + min(len(text) - 2, log.region.width - 2)
        await pilot.click(offset=(x, y))
        await pilot.pause()

        assert app._awaiting_local_provider is False, "the click did not select the row"


async def test_a_click_off_a_picker_row_selects_nothing(monkeypatch):
    """The row resolver must not turn stray clicks into selections."""
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    async with app.run_test(size=(120, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_local_provider_picker(log)
        await pilot.pause()

        # The heading, which carries no bracketed number.
        await pilot.click(offset=(log.region.x + 2, log.region.y))
        await pilot.pause()

        assert app._awaiting_local_provider is True


async def test_the_status_bar_controls_actually_fire_when_clicked(monkeypatch):
    """A control drawn on the bar is not proof that a click reaches it.

    The bar carries no OSC-8 links, because terminals underline those on hover
    and we cannot turn that off. It maps screen columns to commands itself, so
    the mapping is only right if the columns it records line up with where the
    row is actually painted. Drive real clicks rather than read the text.
    """
    from superqode.app.widgets import ColorfulStatusBar

    ran: list[str] = []
    monkeypatch.setattr(
        SuperQodeApp, "_run_clicked_command", lambda self, command: ran.append(command)
    )
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")

    app = SuperQodeApp()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one("#status-bar", ColorfulStatusBar)

        hits = list(bar._hits)
        assert {"home", "connect", "exit"} <= {action for _, _, action in hits}

        # The bar occupies three screen rows with its content on the middle
        # one, so clicking the widget's own origin lands on the border and
        # misses every control.
        content = bar.content_region
        for start, _end, action in hits:
            column = content.x + start + 1
            assert column < content.right, f"{action} was placed off the row"
            before = len(ran)
            await pilot.click(offset=(column, content.y))
            await pilot.pause()
            assert len(ran) > before, f"clicking {action} did nothing"
            assert ran[-1] == action, f"clicking {action} ran {ran[-1]}"


async def test_clicking_the_wordmark_goes_home(monkeypatch):
    """The logo behaves like a site logo."""
    from superqode.app.widgets import ColorfulStatusBar

    ran: list[str] = []
    monkeypatch.setattr(
        SuperQodeApp, "_run_clicked_command", lambda self, command: ran.append(command)
    )
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")

    app = SuperQodeApp()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one("#status-bar", ColorfulStatusBar)
        assert bar.action_at(2) == "home"
        content = bar.content_region
        await pilot.click(offset=(content.x + 2, content.y))
        await pilot.pause()

    assert ran == ["home"]


async def test_clicking_a_row_never_types_its_number_into_the_prompt(monkeypatch):
    """A click carries its target; only typing needs digit buffering.

    Provider and model pickers buffer typed digits so multi-digit indexes can
    be entered. Clicks used to fall into that same path, so selecting a row
    with the mouse put "1" or "2" in the prompt box and selected nothing.
    """
    import re

    from superqode.app.inputs import SelectionAwareInput

    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    async with app.run_test(size=(120, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_local_provider_picker(log)
        await pilot.pause()

        rows = [
            (index, "".join(segment.text for segment in strip))
            for index, strip in enumerate(log.lines)
            if re.match(r"^\s*[▶●○]?\s*\[\s*\d+\s*\]", "".join(s.text for s in strip))
        ]
        assert len(rows) > 1

        line_index, text = rows[1]
        y = log.region.y + line_index - int(log.scroll_offset.y)
        x = log.region.x + min(len(text.rstrip()) - 2, log.region.width - 2)
        await pilot.click(offset=(x, y))
        await pilot.pause()

        assert app.query_one("#prompt-input", SelectionAwareInput).value == "", (
            "the click was buffered as typing"
        )
        assert app._awaiting_local_provider is False, "the click selected nothing"
