"""Mounted-TUI smoke tests using Textual's run_test() harness.

These catch the class of bug where code updates an *unmounted* widget (e.g.
querying `widgets.status_bar.StatusBar` when the app actually mounts
`ColorfulStatusBar`): a unit test on the widget passes, but the real bar never
updates. Running the actual app and asserting on the mounted widget closes that
gap.
"""

from __future__ import annotations

import pytest

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ColorfulStatusBar, ConversationLog


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


async def test_mounted_status_header_keeps_identity_and_operational_state():
    """The real header reserves two content rows and never looks empty."""
    from superqode import __version__

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
        assert "No model" in rendered
        assert "runtime builtin" not in rendered
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
        await pilot.pause()
        app._welcome_active = False
        log = app.query_one("#log", ConversationLog)
        log.clear()
        log.reset_response_stream("qwen")
        log.write_final_response("Mouse selectable answer body here.", agent="qwen")
        await pilot.pause()
        await pilot.pause()

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
        for _ in range(5):
            await pilot.pause()

        assert copies, "mouse-drag selection did not trigger a clipboard copy"
        assert "select" in copies[0]  # copied a chunk of the answer text


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
        app._show_connect_type_picker(log)
        await pilot.pause()

        for _ in range(6):
            await pilot.press("down")
            await pilot.pause()

        selected_y = next(index for index, line in enumerate(log.lines) if "SELECTED" in line.text)
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

        selected_y = next(index for index, line in enumerate(log.lines) if "SELECTED" in line.text)
        visible_height = log.scrollable_content_region.height

        assert app._byok_highlighted_provider_index == 6
        assert log.scroll_y <= selected_y < log.scroll_y + visible_height


async def test_harness_command_opens_keyboard_catalog_completion():
    app = SuperQodeApp()
    async with app.run_test(size=(100, 32)) as pilot:
        log = app.query_one("#log", ConversationLog)

        app._harness_cmd("", log)
        await pilot.pause()
        await pilot.pause()

        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        values = [candidate.value for candidate in app._prompt_completion_candidates]
        rendered = "\n".join(line.text for line in log.lines)

        assert prompt.value == ":harness use "
        assert app._prompt_completion_visible is True
        assert ":harness use kimi-coding" in values
        assert "Harness Catalog" in rendered


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


async def test_prompt_placeholder_mentions_os_dictation():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one(SelectionAwareInput)
        await pilot.pause()

        assert "dictation" in str(prompt.placeholder).lower()


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


async def test_prompt_ctrl_u_clears_entire_multiline_buffer():
    """Ctrl+U must wipe the whole prompt, not just the current line.

    A user pasted a huge multi-line conversation and could only quit the app to
    get rid of it — TextArea's default Ctrl+U deletes to start of the current
    line only.
    """
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


async def test_grok_profile_selection_routes_to_grok_build_acp(monkeypatch):
    """Selecting "Grok subscription" in the picker connects Grok Build (ACP).

    Since 0.2.x the bare Grok profile runs xAI's own agent, matching Codex and
    Claude. (Picker-feedback visibility is covered by the Codex-profile test
    below.)
    """
    calls = []

    def fake_connect_acp(self, args, log):
        calls.append(args)

    monkeypatch.setattr(SuperQodeApp, "_connect_acp_cmd", fake_connect_acp)

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_type_picker(log)
        await pilot.pause()

        # Navigate to the Grok subscription profile (last entry) and select it.
        for _ in range(6):
            await pilot.press("down")
            await pilot.pause()
        assert app._byok_highlighted_connect_type_index == 6

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
        app._show_connect_type_picker(log)
        await pilot.pause()

        for _ in range(3):  # local, byok, acp → codex at index 3
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
        await pilot.pause()
        await pilot.pause()

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
