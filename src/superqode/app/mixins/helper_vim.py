"""Optional modal navigation for the terminal user interface."""

from __future__ import annotations

import json
import os
from pathlib import Path

from superqode.app.widgets import (
    ConversationLog,
)


class HelperVimMixin:
    """Vim-style modes, navigation, search, and Ex-command history."""

    _VIM_STATES = {"normal", "insert", "command", "search"}

    _VIM_PICKER_ACTIONS = (
        (
            "_awaiting_acp_agent_selection",
            "action_navigate_acp_agent_up",
            "action_navigate_acp_agent_down",
        ),
        ("_awaiting_byok_model", "action_navigate_model_up", "action_navigate_model_down"),
        ("_awaiting_byok_provider", "action_navigate_provider_up", "action_navigate_provider_down"),
        (
            "_awaiting_codex_model",
            "action_navigate_codex_model_up",
            "action_navigate_codex_model_down",
        ),
        (
            "_awaiting_codex_effort",
            "action_navigate_codex_effort_up",
            "action_navigate_codex_effort_down",
        ),
        (
            "_awaiting_connect_type",
            "action_navigate_connect_type_up",
            "action_navigate_connect_type_down",
        ),
        (
            "_awaiting_runtime_selection",
            "action_navigate_runtime_up",
            "action_navigate_runtime_down",
        ),
        (
            "_awaiting_session_resume",
            "action_navigate_session_resume_up",
            "action_navigate_session_resume_down",
        ),
        (
            "_awaiting_harness_selection",
            "action_navigate_harness_up",
            "action_navigate_harness_down",
        ),
        ("_awaiting_mode_selection", "action_navigate_mode_up", "action_navigate_mode_down"),
        (
            "_awaiting_local_provider",
            "action_navigate_local_provider_up",
            "action_navigate_local_provider_down",
        ),
        (
            "_awaiting_local_model",
            "action_navigate_local_model_up",
            "action_navigate_local_model_down",
        ),
        (
            "_awaiting_model_selection",
            "action_navigate_acp_model_up",
            "action_navigate_acp_model_down",
        ),
    )

    _VIM_TEXT_ENTRY_FLAGS = (
        "_awaiting_agent_question",
        "_awaiting_harness_wizard",
        "_awaiting_local_dep_install",
        "_awaiting_local_server_start",
        "_awaiting_local_connect_start",
        "_awaiting_subscription_login",
    )

    @classmethod
    def _vim_config_path(cls) -> Path:
        """Return the user config path, respecting a patched home in tests."""
        return Path.home() / ".superqode" / "config.json"

    def _load_vim_preference(self) -> bool:
        """Load Vim mode from the environment or persisted user config."""
        env_value = os.getenv("SUPERQODE_VIM_MODE")
        if env_value is not None:
            return env_value.strip().lower() in {"1", "true", "yes", "on"}
        try:
            data = json.loads(self._vim_config_path().read_text(encoding="utf-8"))
            return bool(data.get("vim_mode", False))
        except Exception:
            return False

    def _save_vim_preference(self, enabled: bool) -> None:
        """Persist the optional Vim mode without replacing other settings."""
        path = self._vim_config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data: dict = {}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except (json.JSONDecodeError, ValueError):
                    pass
            data["vim_mode"] = bool(enabled)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _sync_vim_state(self) -> None:
        """Apply the current Vim state after the TUI widgets mount."""
        state = getattr(self, "_vim_input_mode", "insert")
        if not self._vim_enabled():
            state = "insert"
        self._set_vim_state(state)

    def _set_vim_state(self, state: str) -> None:
        """Set the modal input state and synchronize visible UI controls."""
        state = str(state or "insert").strip().lower()
        if state not in self._VIM_STATES:
            state = "insert"
        self._vim_input_mode = state
        self._vim_pending_key = ""
        enabled = self._vim_enabled()

        try:
            status = self.query_one("#status-bar")
            status.vim_state = state if enabled else ""
        except Exception:
            pass

        try:
            prompt = self.query_one("#prompt-input")
            prompt.read_only = bool(enabled and state == "normal")
            prompt.placeholder = {
                "normal": "NORMAL: i to insert · : command · / search",
                "insert": prompt.DEFAULT_PLACEHOLDER,
                "command": "Enter an Ex command",
                "search": "Search the transcript",
            }[state]
            prompt.refresh()
        except Exception:
            pass

        try:
            input_box = self.query_one("#input-box")
            input_box.border_title = f"Task · {state.upper()}" if enabled else "Task"
        except Exception:
            pass

    def _vim_picker_active(self) -> bool:
        return any(bool(getattr(self, flag, False)) for flag, _, _ in self._VIM_PICKER_ACTIONS)

    def _vim_picker_move(self, direction: int) -> bool:
        """Move the active picker with Normal-mode j or k."""
        for flag, up_action, down_action in self._VIM_PICKER_ACTIONS:
            if not getattr(self, flag, False):
                continue
            action_name = up_action if direction < 0 else down_action
            action = getattr(self, action_name, None)
            if action is None and flag == "_awaiting_model_selection":
                fallback = (
                    "action_navigate_opencode_model_up"
                    if direction < 0
                    else "action_navigate_opencode_model_down"
                )
                action = getattr(self, fallback, None)
            if callable(action):
                action()
                return True
        return False

    def _vim_requires_text_entry(self) -> bool:
        return any(bool(getattr(self, flag, False)) for flag in self._VIM_TEXT_ENTRY_FLAGS)

    @staticmethod
    def _consume_vim_event(event) -> None:
        try:
            event.stop()
        except Exception:
            pass
        try:
            event.prevent_default()
        except Exception:
            pass

    def _vim_scroll_lines(self, delta: int) -> None:
        log = self.query_one("#log", ConversationLog)
        log.auto_scroll = False
        current = int(getattr(log, "scroll_y", 0) or 0)
        log.scroll_to(y=max(0, current + delta), animate=False)

    def _vim_focus_left_pane(self) -> None:
        """Open and focus the repository sidebar."""
        if not getattr(self, "sidebar_visible", False):
            self.action_toggle_sidebar()
            return
        try:
            sidebar = self.query_one("#sidebar")
            sidebar.focus_tree()
        except Exception:
            pass

    def _vim_focus_main_pane(self) -> None:
        """Return keyboard focus to the main terminal prompt."""
        self._ensure_input_focus()

    def _vim_move_focused_tree(self, direction: int) -> bool:
        """Apply j or k to the focused repository tree instead of the log."""
        try:
            focused = self.focused
        except Exception:
            return False
        if getattr(focused, "id", "") != "file-tree":
            return False
        action_name = "action_cursor_up" if direction < 0 else "action_cursor_down"
        action = getattr(focused, action_name, None)
        if not callable(action):
            return False
        action()
        return True

    def _begin_vim_line_mode(self, prefix: str, state: str, prompt) -> None:
        self._set_vim_state(state)
        prompt.value = prefix
        prompt.cursor_position = len(prefix)
        prompt.focus()

    def _vim_after_submit(self) -> None:
        """Return to Normal mode after a prompt, Ex command, or search submits."""
        if self._vim_enabled():
            self._set_vim_state("normal")

    def _handle_vim_key(self, event, prompt=None) -> bool:
        """Handle one key in the optional modal terminal control layer."""
        if not self._vim_enabled():
            return False

        key = str(getattr(event, "key", "") or "")
        character = getattr(event, "character", None)
        token = character if isinstance(character, str) and character else key

        # Approval and cancellation paths retain priority over modal navigation.
        if getattr(self, "_permission_pending", False):
            return False
        if key in {"escape", "ctrl+["} and (
            getattr(self, "is_busy", False)
            or self._vim_picker_active()
            or self._vim_requires_text_entry()
        ):
            return False

        state = getattr(self, "_vim_input_mode", "normal")

        if self._vim_picker_active() and state == "normal" and token in {"j", "k"}:
            if self._vim_picker_move(-1 if token == "k" else 1):
                self._consume_vim_event(event)
                return True

        # Questions and setup prompts must remain ordinary editable fields.
        if self._vim_requires_text_entry():
            if state == "normal":
                self._set_vim_state("insert")
            return False

        if state in {"insert", "command", "search"}:
            if key in {"escape", "ctrl+["}:
                if prompt is not None and state in {"command", "search"}:
                    prompt.value = ""
                self._set_vim_state("normal")
                self._consume_vim_event(event)
                return True
            return False

        # Normal mode begins here.
        pending = getattr(self, "_vim_pending_key", "")
        if pending == "g":
            self._vim_pending_key = ""
            if token == "g":
                self.action_scroll_log_home()
                self._consume_vim_event(event)
                return True
        elif pending == "q":
            self._vim_pending_key = ""
            if token == ":":
                self._vim_command_history(self.query_one("#log", ConversationLog))
                self._consume_vim_event(event)
                return True
        elif pending == "@":
            self._vim_pending_key = ""
            if token == ":":
                self._repeat_last_ex_command(self.query_one("#log", ConversationLog))
                self._consume_vim_event(event)
                return True
        elif pending == "ctrl+w":
            self._vim_pending_key = ""
            if token == "h":
                self._vim_focus_left_pane()
                self._consume_vim_event(event)
                return True
            if token == "l":
                self._vim_focus_main_pane()
                self._consume_vim_event(event)
                return True

        if prompt is None:
            try:
                prompt = self.query_one("#prompt-input")
            except Exception:
                prompt = None

        if token in {"i", "a", "o"}:
            self._set_vim_state("insert")
            if prompt is not None:
                prompt.focus()
            self._consume_vim_event(event)
            return True
        if token == ":" and prompt is not None:
            self._begin_vim_line_mode(":", "command", prompt)
            self._consume_vim_event(event)
            return True
        if token in {"/", "?"} and prompt is not None:
            self._begin_vim_line_mode(token, "search", prompt)
            self._consume_vim_event(event)
            return True
        if token == "j":
            if not self._vim_move_focused_tree(1):
                self._vim_scroll_lines(1)
            self._consume_vim_event(event)
            return True
        if token == "k":
            if not self._vim_move_focused_tree(-1):
                self._vim_scroll_lines(-1)
            self._consume_vim_event(event)
            return True
        if token == "g":
            self._vim_pending_key = "g"
            self._consume_vim_event(event)
            return True
        if token == "G":
            self.action_scroll_log_end()
            self._consume_vim_event(event)
            return True
        if key in {"ctrl+u", "ctrl+b"}:
            self.action_scroll_log_page_up()
            self._consume_vim_event(event)
            return True
        if key in {"ctrl+d", "ctrl+f"}:
            self.action_scroll_log_page_down()
            self._consume_vim_event(event)
            return True
        if token in {"n", "N"}:
            self._vim_search_next(self.query_one("#log", ConversationLog), reverse=(token == "N"))
            self._consume_vim_event(event)
            return True
        if token == "h":
            self._vim_focus_left_pane()
            self._consume_vim_event(event)
            return True
        if token == "l":
            self._vim_focus_main_pane()
            self._consume_vim_event(event)
            return True
        if key == "ctrl+w":
            self._vim_pending_key = "ctrl+w"
            self._consume_vim_event(event)
            return True
        if key == "space" or token == " ":
            self.action_leader_key()
            self._consume_vim_event(event)
            return True
        if token in {"q", "@"}:
            self._vim_pending_key = token
            self._consume_vim_event(event)
            return True
        if key in {"escape", "ctrl+["}:
            self._consume_vim_event(event)
            return True

        # Normal mode never inserts printable characters into the task prompt.
        if len(token) == 1:
            self._consume_vim_event(event)
            return True
        return False

    def _record_ex_command(self, cmd: str, command_name: str) -> None:
        if not cmd.startswith(":"):
            return
        if command_name in {"vim", "set"}:
            return
        normalized = ":" + cmd[1:].strip()
        if normalized in {":", ":history"}:
            return
        self._last_ex_command = normalized

    def _repeat_last_ex_command(self, log: ConversationLog) -> None:
        command = getattr(self, "_last_ex_command", "")
        if not command:
            log.add_info("No Ex command to repeat yet.")
            return
        log.add_info(f"Repeating {command}")
        self._handle_command(command, log)

    def _try_vim_search_input(self, text: str, log: ConversationLog) -> bool:
        if text in {"n", "N"}:
            self._vim_search_next(log, reverse=(text == "N"))
            return True
        if text.startswith("?") and len(text) > 1:
            self._vim_search(log, text[1:].strip(), reverse=True)
            return True
        if text.startswith("/") and len(text) > 1 and not self._is_known_slash_input(text):
            self._vim_search(log, text[1:].strip(), reverse=False)
            return True
        return False

    def _scroll_to_vim_search_match(self, log: ConversationLog) -> None:
        matches = getattr(self, "_vim_search_matches", [])
        if not matches or self._vim_search_index < 0:
            return
        message_index = matches[self._vim_search_index]
        try:
            log.auto_scroll = False
            messages = list(getattr(log, "_messages", []))
            target_y = 0
            for _role, content, _agent in messages[:message_index]:
                target_y += max(2, len(str(content).splitlines()) + 2)
            visible_height = max(6, int(getattr(getattr(log, "size", None), "height", 18) or 18))
            log.scroll_to(y=max(0, target_y - max(1, visible_height // 3)), animate=False)
        except Exception:
            pass

        query = getattr(self, "_vim_search_query", "")
        self._set_vim_search_highlight(log, query)
        self._vim_search_feedback(
            log,
            f"Match {self._vim_search_index + 1}/{len(matches)} for {query!r}. "
            "Use n/N to navigate.",
        )

    def _set_vim_search_highlight(self, log: ConversationLog, query: str) -> None:
        setter = getattr(log, "set_search_highlight", None)
        if callable(setter):
            setter(query)
