"""Selection-aware prompt input widget extracted from app_main."""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.widgets import Input, TextArea


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
    DEFAULT_PLACEHOLDER = "Type, paste, or use OS dictation. Type : for commands."

    # A prompt box should behave like an ordinary text field. TextArea's defaults
    # are surprising here: Ctrl+A is line-start and Ctrl+U only deletes to the
    # start of the *current* line — useless for clearing a pasted multi-line
    # prompt (the user had to quit the app to escape one). Re-map both to the
    # field semantics people expect; Home still gives line-start.
    BINDINGS = [
        Binding("ctrl+a", "select_all", "Select all", show=False),
        Binding("ctrl+u", "clear_prompt", "Clear prompt", show=True),
    ]

    def action_clear_prompt(self) -> None:
        """Clear the entire prompt buffer (every line), not just the current line."""
        self.load_text("")
        self._resize_to_content()

    def __init__(self, *args, suggester=None, **kwargs) -> None:
        # TextArea doesn't support Input's suggester API. Accept it so the prompt
        # can keep the existing construction path while using soft wrapping.
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("compact", True)
        kwargs.setdefault("highlight_cursor_line", False)
        kwargs.setdefault("tab_behavior", "focus")
        super().__init__(*args, **kwargs)
        self.suggester = suggester

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
        # Match the text area's usable inner width. The prompt has a fixed
        # symbol column and border, so using the full widget width overestimates
        # how much text fits on a visual line.
        width = max(12, (self.content_size.width or self.size.width or 80) - 1)
        height = self._height_for_text(self.text, width)
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
        update_panel = getattr(self.app, "_update_prompt_completion_panel", None)
        if callable(update_panel):
            update_panel(self.value)

    def on_resize(self, event: events.Resize) -> None:
        self._resize_to_content()

    def _submit_current_value(self, event: events.Key) -> None:
        value = self.value
        event.stop()
        event.prevent_default()
        self.post_message(Input.Submitted(self, value))

    def _is_in_selection_mode_for_number_keys(self, app) -> bool:
        """Check if the app is in a selection mode that supports number key shortcuts.

        Note: BYOK model selection and local model selection are excluded -
        users should type model names/numbers in the input field for those.
        """
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
            # Excluded: _awaiting_byok_model, _awaiting_local_model
            # Users should type in the input for model selection
        )

    def on_key(self, event: events.Key) -> None:
        """Intercept key events for selection navigation and number selection."""
        app = self.app

        if getattr(app, "_prompt_completion_visible", False):
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
