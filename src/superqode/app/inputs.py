"""Selection-aware prompt input widget extracted from app_main."""

from __future__ import annotations

from time import monotonic
from random import sample

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.content import Content
from textual.strip import Strip
from textual.widgets import Input, TextArea

from superqode.app.constants import THEME


class SelectionAwareInput(TextArea):
    """
    Wrapped prompt input that passes selection keys to the parent app.

    Standard Textual input widgets capture up/down arrows for cursor/history navigation,
    which prevents the App's on_key handler from receiving them during
    provider/model selection modes. This subclass intercepts arrow keys and number keys
    and directly calls the app's navigation/selection actions when in selection mode.
    """

    # Start tall enough to invite longer prompts; grow up to the max, then scroll.
    MIN_PROMPT_HEIGHT = 3
    MAX_PROMPT_HEIGHT = 8
    NEWLINE_KEYS = frozenset({"shift+enter", "alt+enter", "ctrl+j", "newline"})
    DEFAULT_PLACEHOLDER = (
        "Get started with :connect · Browse with mouse · Run shell commands with >"
    )
    WORKING_DOT_FRAMES = ("●··", "·●·", "··●")

    def set_working(self, working: bool) -> None:
        """Show activity in an empty composer without changing its draft."""
        if working != getattr(self, "_is_working", False):
            if working:
                self._ready_placeholder = self.placeholder
                self._working_started_at = monotonic()
            else:
                if self.placeholder == getattr(self, "_working_placeholder", None):
                    self.placeholder = self._ready_placeholder
            self._is_working = working
        self._sync_working_animation()

    def _update_working_placeholder(self) -> None:
        if not getattr(self, "_is_working", False) or self.text:
            return
        elapsed = max(0.0, monotonic() - self._working_started_at)
        frame = self.WORKING_DOT_FRAMES[int(elapsed * 2) % len(self.WORKING_DOT_FRAMES)]
        self._working_placeholder = f"Agent working {frame}"
        accents = list(
            dict.fromkeys(THEME[key] for key in ("purple", "pink", "gold", "cyan", "success"))
        )
        colors = sample(accents, min(3, len(accents)))
        content = Text("Agent working ", style=f"bold {THEME['purple']}")
        for index, dot in enumerate(frame):
            content.append(dot, style=f"bold {colors[index % len(colors)]}")
        self._working_content = content
        self.placeholder = self._working_placeholder

    def render_line(self, y: int) -> Strip:
        # TextArea applies its muted placeholder style over rich text. Render
        # only the working hint here so theme accents retain their brightness.
        if (
            getattr(self, "_is_working", False)
            and not self.text
            and self.placeholder == getattr(self, "_working_placeholder", None)
        ):
            lines = Content.from_text(self._working_content).wrap(max(1, self.content_size.width))
            if 0 <= y < len(lines):
                content = lines[y]
                return Strip(content.render_segments(self.visual_style), content.cell_length)
        return super().render_line(y)

    def _sync_working_animation(self) -> None:
        active = (
            getattr(self, "_is_working", False)
            and not self.text
            and getattr(self.app, "_wave_window_focused", True)
        )
        timer = getattr(self, "_working_timer", None)
        if not active:
            if timer is not None:
                timer.stop()
                self._working_timer = None
            return
        self._update_working_placeholder()
        if timer is None:
            self._working_timer = self.set_interval(0.5, self._update_working_placeholder)

    def on_unmount(self) -> None:
        timer = getattr(self, "_working_timer", None)
        if timer is not None:
            timer.stop()
            self._working_timer = None

    # A prompt box should behave like an ordinary text field. TextArea's defaults
    # are surprising here: Ctrl+A is line-start and Ctrl+U only deletes to the
    # start of the *current* line — useless for clearing a pasted multi-line
    # prompt (the user had to quit the app to escape one). Re-map both to the
    # field semantics people expect; Home still gives line-start.
    BINDINGS = [
        Binding("ctrl+a", "select_all", "Select all", show=False),
        Binding("ctrl+u", "clear_prompt", "Clear prompt", show=True),
        Binding("ctrl+c", "interrupt_or_copy", "Interrupt", show=False),
    ]

    def action_interrupt_or_copy(self) -> None:
        """Copy an idle selection; otherwise use the app's interrupt workflow."""
        app = self.app
        waiting = (
            app.is_busy
            or getattr(app, "_permission_pending", False)
            or getattr(app, "_awaiting_agent_question", False)
            or getattr(app, "_install_in_progress", False)
        )
        if not waiting and not self.selection.is_empty:
            self.action_copy()
            return
        app.action_interrupt()

    def action_clear_prompt(self) -> None:
        """Clear the entire prompt buffer (every line), not just the current line."""
        self._history_draft = None
        self._navigating_history = False
        try:
            app = self.app
        except Exception:
            app = getattr(self, "_app", None)
        if app is not None:
            history_mgr = getattr(app, "_history_manager", None)
            if history_mgr is not None and hasattr(history_mgr, "reset_position"):
                history_mgr.reset_position()
        self.load_text("")
        self._resize_to_content()

    def _on_paste(self, event: events.Paste) -> None:
        # Textual dispatches inherited handlers automatically. Stop its default
        # insertion only when the composer successfully stages a path-only drop.
        handler = getattr(self.app, "on_paste", None)
        if handler is not None:
            handler(event)

    def __init__(self, *args, suggester=None, **kwargs) -> None:
        # TextArea doesn't support Input's suggester API. Accept it so the prompt
        # can keep the existing construction path while using soft wrapping.
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("compact", True)
        kwargs.setdefault("highlight_cursor_line", False)
        kwargs.setdefault("tab_behavior", "focus")
        super().__init__(*args, **kwargs)
        self._working_timer = None
        self._is_working = False
        self.suggester = suggester
        self._history_draft: Optional[str] = None
        self._navigating_history: bool = False

    @property
    def value(self) -> str:
        """Input-compatible text value."""
        return self.text

    @value.setter
    def value(self, new_value: str) -> None:
        self.load_text(new_value)
        self._resize_to_content()

    @property
    def cursor_position(self) -> int:
        """Input-compatible absolute cursor offset."""
        row, column = self.cursor_location
        lines = self.text.split("\n")
        return sum(len(line) + 1 for line in lines[:row]) + column

    @cursor_position.setter
    def cursor_position(self, position: int) -> None:
        position = max(0, min(position, len(self.text)))
        offset = 0
        for row, line in enumerate(self.text.split("\n")):
            line_end = offset + len(line)
            if position <= line_end:
                self.move_cursor((row, position - offset))
                return
            offset = line_end + 1
        last_line = self.text.split("\n")[-1]
        self.move_cursor((len(self.text.split("\n")) - 1, len(last_line)))

    def _resize_to_content(self) -> None:
        """Grow the prompt until the configured maximum, then scroll internally."""
        # TextArea already wraps using terminal-cell widths, word boundaries,
        # tabs and its gutter/scrollbars. Reuse that layout instead of a second
        # character-count estimate, which clips wide text and oversizes accents.
        if self.wrap_width:
            height = max(
                self.MIN_PROMPT_HEIGHT,
                min(self.MAX_PROMPT_HEIGHT, self.wrapped_document.height),
            )
        else:
            height = self._height_for_text(self.text, 80)
        self.styles.height = height
        try:
            input_box = self.app.query_one("#input-box")
            input_box.styles.height = height + 2
            symbol = self.app.query_one("#prompt-symbol")
            symbol.styles.height = height
        except Exception:
            pass

    @classmethod
    def _height_for_text(cls, text: str, width: int) -> int:
        visual_lines = 0
        width = max(1, width)
        for line in (text or "").split("\n"):
            visual_lines += max(1, ((len(line) - 1) // width) + 1 if line else 1)
        return max(cls.MIN_PROMPT_HEIGHT, min(cls.MAX_PROMPT_HEIGHT, visual_lines))

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._resize_to_content()
        self._sync_working_animation()
        if getattr(self.app, "_composer_blocks", {}):
            self.app._refresh_attachment_bar()
        schedule = getattr(self.app, "_schedule_draft_save", None)
        if callable(schedule):
            schedule()
        update_panel = getattr(self.app, "_update_prompt_completion_panel", None)
        if callable(update_panel):
            update_panel(self.value)

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        schedule = getattr(self.app, "_schedule_draft_save", None)
        if callable(schedule):
            schedule()

    def on_resize(self, event: events.Resize) -> None:
        # Inherited TextArea handling rewraps after this handler. Size from the
        # completed layout so a wider/narrower terminal uses the new line count.
        self.call_after_refresh(self._resize_to_content)

    def _submit_current_value(self, event: events.Key) -> None:
        value = self.value
        self._history_draft = None
        self._navigating_history = False
        try:
            app = self.app
        except Exception:
            app = getattr(self, "_app", None)
        if app is not None:
            history_mgr = getattr(app, "_history_manager", None)
            if history_mgr is not None and hasattr(history_mgr, "reset_position"):
                history_mgr.reset_position()
        event.stop()
        event.prevent_default()
        self.post_message(Input.Submitted(self, value))
        after_submit = getattr(app, "_vim_after_submit", None) if app else None
        if callable(after_submit):
            after_submit()

    def _is_in_selection_mode_for_number_keys(self, app) -> bool:
        """Check if the app is in a selection mode that supports number key shortcuts.

        Note: BYOK model selection and local model selection are excluded -
        users should type model names/numbers in the input field for those.
        """
        prompts = getattr(app, "_prompts", None)
        if prompts is not None and prompts.active is not None:
            # Registry-driven prompts are short, numbered option lists, so a
            # digit selects immediately rather than being typed into the input.
            return True

        return (
            getattr(app, "_awaiting_acp_agent_selection", False)
            or getattr(app, "_awaiting_byok_provider", False)
            or getattr(app, "_awaiting_codex_effort", False)
            or getattr(app, "_awaiting_codex_model", False)
            or getattr(app, "_awaiting_connect_type", False)
            or getattr(app, "_awaiting_runtime_selection", False)
            or getattr(app, "_awaiting_local_provider", False)
            or getattr(app, "_awaiting_model_selection", False)
            or getattr(app, "_awaiting_session_resume", False)
            or getattr(app, "_awaiting_mode_selection", False)
            or getattr(app, "_awaiting_harness_selection", False)
            or getattr(app, "_awaiting_free_selection", False)
            # Excluded: _awaiting_byok_model, _awaiting_local_model
            # Users should type in the input for model selection
        )

    def _insert_newline(self, event: events.Key) -> None:
        """Replace the active selection (or cursor) with a newline."""
        event.stop()
        event.prevent_default()
        start, end = sorted(self.selection)
        self.replace("\n", start, end, maintain_selection_offset=False)
        self._resize_to_content()

    @classmethod
    def _is_newline_key(cls, event: events.Key) -> bool:
        """Recognize portable and enhanced-terminal multiline shortcuts."""
        return bool(cls.NEWLINE_KEYS.intersection(event.aliases))

    def on_key(self, event: events.Key) -> None:
        """Intercept key events for selection navigation and number selection."""
        # Ctrl+J is available in traditional terminals. Shift/Alt+Enter work in
        # terminals that report modified Enter keys (and in Textual's enhanced
        # keyboard protocol) without changing ordinary Enter-to-submit.
        if self._is_newline_key(event):
            self._insert_newline(event)
            return

        try:
            app = self.app
        except Exception:
            app = getattr(self, "_app", None)
        if app is None:
            return

        if event.key == "alt+a":
            # Let the app-level plan handler approve a ready plan before this
            # composer shortcut can intercept the event for workspace navigation.
            if getattr(app, "_pending_plan_status", "") == "pending" and bool(
                getattr(app, "_pending_plan_content", "").strip()
            ):
                return
            if hasattr(app, "action_return_to_agent"):
                app.action_return_to_agent()
                event.stop()
                event.prevent_default()
                return

        if event.key == "escape" and getattr(app, "_install_in_progress", False):
            app.action_smart_cancel()
            event.stop()
            event.prevent_default()
            return

        if getattr(app, "_prompt_completion_visible", False):
            vim_token = getattr(event, "character", None) or event.key
            if (
                getattr(app, "_vim_enabled", lambda: False)()
                and getattr(app, "_vim_input_mode", "insert") == "normal"
                and vim_token in {"j", "k"}
            ):
                if hasattr(app, "_move_prompt_completion"):
                    app._move_prompt_completion(-1 if vim_token == "k" else 1)
                event.stop()
                event.prevent_default()
                return
            if event.key == "enter":
                enter_action = getattr(app, "_prompt_completion_enter_action", None)
                action = enter_action(self.value) if callable(enter_action) else "accept"
                if action == "submit":
                    self._submit_current_value(event)
                    return
                if action == "accept":
                    if hasattr(app, "_accept_prompt_completion") and app._accept_prompt_completion(
                        self
                    ):
                        event.stop()
                        event.prevent_default()
                        return
            if event.key == "up":
                if hasattr(app, "_move_prompt_completion"):
                    app._move_prompt_completion(-1)
                event.stop()
                event.prevent_default()
                return
            if event.key == "down":
                if hasattr(app, "_move_prompt_completion"):
                    app._move_prompt_completion(1)
                event.stop()
                event.prevent_default()
                return
            if event.key in ("tab", "right"):
                if hasattr(app, "_accept_prompt_completion") and app._accept_prompt_completion(
                    self
                ):
                    event.stop()
                    event.prevent_default()
                    return
            if event.key == "escape":
                if hasattr(app, "_hide_prompt_completion_panel"):
                    app._hide_prompt_completion_panel()
                event.stop()
                event.prevent_default()
                return

        if event.key == "escape" and getattr(app, "_completion_ready_value", None) is None:
            hide_completion = getattr(app, "_hide_prompt_completion_panel", None)
            if callable(hide_completion):
                hide_completion()

        if event.key in {"escape", "ctrl+["} and getattr(self, "_navigating_history", False):
            draft = (
                getattr(self, "_history_draft", None)
                if getattr(self, "_history_draft", None) is not None
                else ""
            )
            self._history_draft = None
            self._navigating_history = False
            history_mgr = getattr(app, "_history_manager", None)
            if history_mgr is not None and hasattr(history_mgr, "reset_position"):
                history_mgr.reset_position()
            self.value = draft
            self.cursor_position = len(draft)
            event.stop()
            event.prevent_default()
            return

        # Key B (or fallback Left Arrow) navigates back when the prompt is
        # empty, matching the visible Back control. Backspace strictly deletes
        # prompt text and never triggers TUI navigation.
        token = (getattr(event, "character", None) or event.key or "").lower()
        if token in {"b", "left"} or event.key in {"b", "B", "left"}:
            go_back = getattr(app, "_navigate_back_from_keyboard", None)
            if callable(go_back) and go_back(self.value):
                event.stop()
                event.prevent_default()
                return

        if event.key in {"escape", "ctrl+["} and (
            getattr(app, "_awaiting_harness_selection", False)
            or getattr(app, "_awaiting_harness_confirmation", False)
        ):
            cancel = getattr(app, "action_cancel_harness_selection", None)
            if callable(cancel):
                cancel()
            event.stop()
            event.prevent_default()
            return

        if getattr(app, "_awaiting_harness_selection", False) and not (self.value or "").strip():
            token = (getattr(event, "character", None) or event.key or "").lower()
            picker_actions = {
                "f": "action_select_highlighted_harness",
                "i": "action_inspect_highlighted_harness",
                "a": "action_show_all_harnesses",
                "r": "action_show_recommended_harnesses",
                "l": "action_show_complete_harness_catalog",
            }
            action_name = picker_actions.get(token)
            if action_name:
                action = getattr(app, action_name, None)
                if callable(action):
                    if token == "f":
                        action(fork=True)
                    else:
                        action()
                event.stop()
                event.prevent_default()
                return

        if getattr(app, "_awaiting_connect_type", False) and not (self.value or "").strip():
            token = (getattr(event, "character", None) or event.key or "").lower()
            if token == "h":
                action = getattr(app, "action_browse_harnesses_from_connect", None)
                if callable(action):
                    action()
                event.stop()
                event.prevent_default()
                return

        handle_vim_key = getattr(app, "_handle_vim_key", None)
        if callable(handle_vim_key) and handle_vim_key(event, self):
            return

        if event.key in ("tab", "right"):
            complete_prompt = getattr(app, "_complete_prompt_input", None)
            if callable(complete_prompt) and complete_prompt(self):
                event.stop()
                event.prevent_default()
                return

        if event.key == "enter":
            # In a selection picker, Enter confirms the highlighted item rather
            # than submitting the (usually empty) prompt buffer. Without this the
            # keystroke is swallowed by _submit_current_value before the app-level
            # on_key handler can act on it.
            if self._handle_selection_enter(app):
                event.stop()
                event.prevent_default()
                return
            self._submit_current_value(event)
            return

        # Handle number keys during selection modes
        if event.key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            # Commands may legitimately contain digits (for example
            # ``:local stop ds4``). Once the prompt starts as a command or
            # shell line, digits are text and must never be diverted into the
            # picker's numeric-selection buffer.
            if (self.value or "").lstrip()[:1] in (":", "/", ">", "!"):
                return
            # For BYOK/local provider/model selection, buffer digits for multi-digit entry
            if (
                getattr(app, "_awaiting_acp_agent_selection", False)
                or getattr(app, "_awaiting_byok_provider", False)
                or getattr(app, "_awaiting_local_provider", False)
                or getattr(app, "_awaiting_byok_model", False)
                or getattr(app, "_awaiting_local_model", False)
                or getattr(app, "_awaiting_harness_selection", False)
                or getattr(app, "_awaiting_free_selection", False)
            ):
                event.stop()
                event.prevent_default()
                if hasattr(app, "_queue_selection_digit"):
                    app._queue_selection_digit(event.key)
                return

            if self._is_in_selection_mode_for_number_keys(app):
                # Prevent the number from being typed into input
                event.stop()
                event.prevent_default()
                # Call the universal selection handler
                num = int(event.key)
                if hasattr(app, "_select_by_number_universal"):
                    app._select_by_number_universal(num)
                return

        # Check if we should handle arrow keys for selection navigation
        if event.key in ("up", "down"):
            # Registry-driven prompts navigate through the prompt stack, so any
            # prompt registered there gets arrow keys without another branch
            # being added below. This chain is one of the dispatch sites the
            # registry exists to collapse.
            prompts = getattr(app, "_prompts", None)
            if prompts is not None and prompts.active is not None:
                if prompts.navigate(-1 if event.key == "up" else 1):
                    event.stop()
                    event.prevent_default()
                    return

            # Check each selection mode and call the appropriate action
            if getattr(app, "_awaiting_acp_agent_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_acp_agent_up()
                else:
                    app.action_navigate_acp_agent_down()
                return

            if getattr(app, "_awaiting_byok_model", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_model_up()
                else:
                    app.action_navigate_model_down()
                return

            if getattr(app, "_awaiting_codex_model", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_codex_model_up()
                else:
                    app.action_navigate_codex_model_down()
                return

            if getattr(app, "_awaiting_codex_effort", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_codex_effort_up()
                else:
                    app.action_navigate_codex_effort_down()
                return

            if getattr(app, "_awaiting_byok_provider", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_provider_up()
                else:
                    app.action_navigate_provider_down()
                return

            if getattr(app, "_awaiting_connect_type", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_connect_type_up()
                else:
                    app.action_navigate_connect_type_down()
                return

            if getattr(app, "_awaiting_harness_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_harness_up()
                else:
                    app.action_navigate_harness_down()
                return

            if getattr(app, "_awaiting_runtime_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_runtime_up()
                else:
                    app.action_navigate_runtime_down()
                return

            if getattr(app, "_awaiting_session_resume", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_session_resume_up()
                else:
                    app.action_navigate_session_resume_down()
                return

            if getattr(app, "_awaiting_mode_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_mode_up()
                else:
                    app.action_navigate_mode_down()
                return

            if getattr(app, "_awaiting_free_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_free_up()
                else:
                    app.action_navigate_free_down()
                return

            # Handle local provider/model arrows here too. Relying on the event
            # bubbling to the app-level handler is unreliable because the
            # underlying TextArea consumes up/down for cursor movement first.
            if getattr(app, "_awaiting_local_provider", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_local_provider_up()
                else:
                    app.action_navigate_local_provider_down()
                return

            if getattr(app, "_awaiting_local_model", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_local_model_up()
                else:
                    app.action_navigate_local_model_down()
                return

            if getattr(app, "_awaiting_model_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    if hasattr(app, "action_navigate_acp_model_up"):
                        app.action_navigate_acp_model_up()
                    else:
                        app.action_navigate_opencode_model_up()
                else:
                    if hasattr(app, "action_navigate_acp_model_down"):
                        app.action_navigate_acp_model_down()
                    else:
                        app.action_navigate_opencode_model_down()
                return

            # Prompt history navigation when not in any selection mode
            history_mgr = getattr(app, "_history_manager", None)
            if history_mgr is not None and not self._is_in_selection_mode_for_number_keys(app):
                lines = self.text.split("\n")
                row, _col = self.cursor_location
                if event.key == "up" and (row == 0 or len(lines) <= 1):
                    if not getattr(self, "_navigating_history", False):
                        self._history_draft = self.value
                        self._navigating_history = True
                    prev_item = history_mgr.get_previous()
                    if prev_item is not None:
                        self.value = prev_item
                        self.cursor_position = len(prev_item)
                        event.stop()
                        event.prevent_default()
                        return
                elif (
                    event.key == "down"
                    and getattr(self, "_navigating_history", False)
                    and (row == len(lines) - 1 or len(lines) <= 1)
                ):
                    next_item = history_mgr.get_next()
                    if next_item:
                        self.value = next_item
                        self.cursor_position = len(next_item)
                        event.stop()
                        event.prevent_default()
                        return
                    else:
                        draft = getattr(self, "_history_draft", None) or ""
                        self._history_draft = None
                        self._navigating_history = False
                        self.value = draft
                        self.cursor_position = len(draft)
                        event.stop()
                        event.prevent_default()
                        return

        # For all other keys or when not in selection mode, let parent handle it
        # TextArea handles normal editing, wrapping, and cursor movement.

    def _handle_selection_enter(self, app) -> bool:
        """Confirm the active picker selection on Enter.

        Returns True when Enter was consumed by a selection picker. Mirrors the
        per-mode dispatch in the app-level on_key handler so behaviour is
        identical whether or not the prompt input holds focus.
        """
        # A typed command/shell line must always win over picker selection, so
        # :exit / :quit / :home / :back / :cancel (and ! shell) work from inside
        # ANY picker (local LM Studio/MLX/Ollama, BYOK, ACP). Without this, Enter
        # confirms the highlighted item and the command is never submitted,
        # trapping the user in the picker.
        typed = (self.value or "").strip()
        if typed[:1] in (":", "/", ">", "!"):
            return False

        # A pending typed-number buffer (BYOK/local pickers) takes priority so
        # Enter commits the digits the user just typed instead of the highlight.
        if getattr(app, "_selection_digit_buffer", ""):
            if hasattr(app, "_apply_selection_buffer"):
                app._apply_selection_buffer()
                return True

        # Registry-driven prompts confirm through the stack. Handling them here
        # as well as in the submit path means Enter lands on the highlighted row
        # regardless of which layer sees the key first.
        prompts = getattr(app, "_prompts", None)
        if prompts is not None and prompts.active is not None:
            if typed:
                # Let a typed answer reach the prompt's own text handler.
                return False
            prompts.select()
            return True

        # A typed runtime name must not be discarded in favour of whatever row
        # happens to be highlighted; let the submit path resolve the text.
        if getattr(app, "_awaiting_runtime_selection", False) and typed:
            return False

        # Same for a typed model number. Without this, typing "7" and pressing
        # Enter in an ACP model picker selected whichever row was highlighted,
        # which is why picking a model felt like it ignored the input.
        if getattr(app, "_awaiting_model_selection", False) and typed.isdigit():
            return False

        if getattr(app, "_awaiting_harness_selection", False) and typed:
            handler = getattr(app, "_handle_harness_picker_input", None)
            if callable(handler):
                try:
                    log = app.query_one("#log")
                    handler(typed, log)
                    self.value = ""
                    return True
                except Exception:
                    pass

        mode_actions = (
            ("_awaiting_acp_agent_selection", "action_select_highlighted_acp_agent"),
            ("_awaiting_byok_model", "action_select_highlighted_model"),
            ("_awaiting_byok_provider", "action_select_highlighted_provider"),
            ("_awaiting_codex_model", "action_select_highlighted_codex_model"),
            ("_awaiting_codex_effort", "action_select_highlighted_codex_effort"),
            ("_awaiting_connect_type", "action_select_highlighted_connect_type"),
            ("_awaiting_runtime_selection", "action_select_highlighted_runtime"),
            ("_awaiting_session_resume", "action_select_highlighted_session_resume"),
            ("_awaiting_mode_selection", "action_select_highlighted_mode"),
            ("_awaiting_free_selection", "action_select_highlighted_free"),
            ("_awaiting_harness_confirmation", "action_confirm_harness_switch"),
            ("_awaiting_harness_selection", "action_select_highlighted_harness"),
            ("_awaiting_local_provider", "action_select_highlighted_local_provider"),
            ("_awaiting_local_model", "action_select_highlighted_local_model"),
            ("_awaiting_model_selection", "action_select_highlighted_acp_model"),
        )
        for flag, action_name in mode_actions:
            if getattr(app, flag, False):
                action = getattr(app, action_name, None)
                if callable(action):
                    action()
                    return True
        return False
