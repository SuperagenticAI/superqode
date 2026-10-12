"""Optional modal navigation for the terminal user interface."""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

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
            "_awaiting_dependency_install",
            "action_navigate_dependency_install_up",
            "action_navigate_dependency_install_down",
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
        ("_awaiting_free_selection", "action_navigate_free_up", "action_navigate_free_down"),
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
        "_awaiting_harness_install",
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
        from superqode.app.theme_bridge import _read_theme_config

        try:
            data = _read_theme_config(self._vim_config_path())
            return isinstance(data, dict) and data.get("vim_mode") is True
        except (OSError, ValueError, UnicodeError, RecursionError):
            return False

    def _save_vim_preference(self, enabled: bool) -> str | None:
        """Persist the optional Vim mode without replacing other settings."""
        from superqode.app.theme_bridge import _read_theme_config
        from superqode.theming import ThemeError, atomic_json

        path = self._vim_config_path()
        try:
            data = _read_theme_config(path)
            if not isinstance(data, dict):
                raise ThemeError("Configuration must be a JSON object")
            data["vim_mode"] = bool(enabled)
            atomic_json(path, data)
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            return f"Vim preference could not be saved: {exc}. This change applies to this session; existing configuration was retained."
        return None

    def _panel_vim_target(self):
        """Never interpret panel typing as workspace navigation or decisions."""
        from textual.widgets import Input, TextArea

        if not self._vim_enabled() or len(self.screen_stack) < 2:
            return None
        focused = self.focused
        if focused is None or focused.screen is not self.screen:
            return None
        if isinstance(focused, Input) or (isinstance(focused, TextArea) and not focused.read_only):
            return None
        return focused

    def _navigate_panel_vim(self, motion: str) -> None:
        from superqode.widgets.panel_shortcuts import navigate_panel

        focused = self._panel_vim_target()
        if focused is None:
            self._panel_vim_pending = None
            return
        pending = getattr(self, "_panel_vim_pending", None)
        self._panel_vim_pending = None
        if motion == "g":
            if (
                not pending
                or pending[:2] != (id(self.screen), id(focused))
                or monotonic() - pending[2] > 1
            ):
                self._panel_vim_pending = (id(self.screen), id(focused), monotonic())
                return
            motion = "first"
        navigate_panel(focused, motion)

    def action_panel_vim_down(self) -> None:
        self._navigate_panel_vim("down")

    def action_panel_vim_up(self) -> None:
        self._navigate_panel_vim("up")

    def action_panel_vim_top(self) -> None:
        self._navigate_panel_vim("g")

    def action_panel_vim_bottom(self) -> None:
        self._navigate_panel_vim("last")

    def action_panel_vim_page_up(self) -> None:
        self._navigate_panel_vim("page_up")

    def action_panel_vim_page_down(self) -> None:
        self._navigate_panel_vim("page_down")

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
            status.vim_state = state if enabled else "off"
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
        active = getattr(getattr(self, "_prompts", None), "active", None)
        if active is not None:
            return active.kind == "picker"
        return any(bool(getattr(self, flag, False)) for flag, _, _ in self._VIM_PICKER_ACTIONS)

    def _vim_picker_move(self, direction: int) -> bool:
        """Move the active picker with Normal-mode j or k."""
        prompts = getattr(self, "_prompts", None)
        if prompts is not None and prompts.active is not None:
            return prompts.navigate(direction)
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
        active = getattr(getattr(self, "_prompts", None), "active", None)
        if active is not None:
            return active.kind == "text"
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
        # This is an explicit focus request. The ordinary post-operation guard
        # deliberately leaves sidebar focus alone and must keep doing so.
        if len(self.screen_stack) != 1 or self.query("CommandPalette.show-palette"):
            return
        picker = getattr(self, "_model_picker_widget", None)
        if picker is not None and picker.is_attached:
            return
        self._restore_vim_draft()
        self.query_one("#prompt-input").focus()

    def _vim_workspace_navigation_active(self, key: str = "") -> bool:
        """Reserve pane keys only in Vim Normal mode outside editable fields."""
        from textual.widgets import Input, TextArea

        if (
            not self._vim_enabled()
            or getattr(self, "_vim_input_mode", "insert") != "normal"
            or len(self.screen_stack) != 1
            or getattr(self, "_permission_pending", False)
            or self._vim_picker_active()
            or self._vim_requires_text_entry()
            or self.query("CommandPalette.show-palette")
        ):
            return False
        focused = self.focused
        if focused is None:
            return False
        if focused.id == "prompt-input":
            return key == "ctrl+f"
        if not self._sidebar_has_focus() and focused.id != "log":
            return False
        return not isinstance(focused, Input) and not (
            isinstance(focused, TextArea) and not focused.read_only
        )

    def _vim_editor_shortcut_active(self) -> bool:
        return (
            self._vim_enabled()
            and len(self.screen_stack) == 1
            and self.focused is not None
            and self.focused.id == "prompt-input"
            and not self._vim_picker_active()
            and not self._vim_requires_text_entry()
            and not self._in_selection_mode()
            and not getattr(self, "_permission_pending", False)
        )

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
        if getattr(self, "_vim_suspended_draft", None) is None:
            self._vim_suspended_draft = (
                prompt.value,
                prompt.cursor_position,
                getattr(prompt, "selection", None),
            )
        self._vim_line_mode = state
        self._set_vim_state(state)
        prompt.value = prefix
        prompt.cursor_position = len(prefix)
        prompt.focus()

    def _restore_vim_draft(self, prompt=None, *, cancel_line: bool = False) -> None:
        """Restore the task after a Vim command, without filling a setup field."""
        draft = getattr(self, "_vim_suspended_draft", None)
        if draft is None:
            return
        if not cancel_line and (
            getattr(self, "_vim_line_mode", None)
            or self._vim_picker_active()
            or self._vim_requires_text_entry()
            or self._in_selection_mode()
            or getattr(self, "_permission_pending", False)
            or self.default_screen.has_class("connection-setup")
        ):
            return
        if prompt is None:
            prompt = self.default_screen.query_one("#prompt-input")
        text, cursor, selection = draft
        self._vim_suspended_draft = None
        self._vim_line_mode = None
        if prompt.value and not cancel_line:
            # A command may intentionally install another draft (e.g. :stash).
            # Keep that result and retain the previous task in the existing stash.
            if text and prompt.value != text:
                stash = getattr(self, "_draft_stash", [])
                self._draft_stash = [*stash[-19:], text]
            return
        prompt.value = text
        if selection is not None:
            prompt.selection = selection
        else:
            prompt.cursor_position = cursor

    def _vim_after_submit(self) -> None:
        """Return to Normal mode after a prompt, Ex command, or search submits."""
        if self._vim_enabled():
            self._set_vim_state("normal")

    def _vim_edit_task(self, log: ConversationLog, editor: str) -> None:
        """Round-trip a Vim user's task through their editor before submission."""
        import shlex
        import subprocess
        import tempfile

        if (
            self._vim_picker_active()
            or self._vim_requires_text_entry()
            or self._in_selection_mode()
            or getattr(self, "_permission_pending", False)
        ):
            log.add_info("Return to the task prompt before opening the external editor.")
            return
        prompt = self.default_screen.query_one("#prompt-input")
        draft = getattr(self, "_vim_suspended_draft", None)
        original = draft[0] if draft is not None else prompt.value
        temp_path = None
        try:
            args = shlex.split(editor, posix=os.name != "nt")
            if os.name == "nt":
                args = [
                    arg[1:-1] if arg[:1] in {"'", '"'} and arg[-1:] == arg[:1] else arg
                    for arg in args
                ]
            if not args:
                raise ValueError("Set $EDITOR to an editor command.")
            if (
                Path(args[0]).name.lower()
                in {"code", "code-insiders", "code.cmd", "code-insiders.cmd"}
                and "--wait" not in args
            ):
                args.append("--wait")
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                suffix=".md",
                prefix="superqode_",
                delete=False,
            ) as source:
                source.write(original)
                temp_path = Path(source.name)
            log.add_info(f"Opening {editor}… Save and close to return to your draft.")
            with self.suspend():
                result = subprocess.run([*args, str(temp_path)])
            if result.returncode:
                log.add_error(
                    f"Editor exited with status {result.returncode}. Your draft was retained."
                )
                return
            content = temp_path.read_text(encoding="utf-8")
            self._vim_suspended_draft = None
            self._vim_line_mode = None
            prompt.value = content
            prompt.cursor_position = len(content)
            self._set_vim_state("insert")
            prompt.focus()
            log.add_info("Draft updated. Review it, then press Enter to send.")
        except (OSError, ValueError) as exc:
            log.add_error(f"Could not open editor: {exc}. Your draft was retained.")
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _handle_vim_key(self, event, prompt=None) -> bool:
        """Handle one key in the optional modal terminal control layer."""
        if not self._vim_enabled():
            return False

        if prompt is None:
            from textual.widgets import Input, TextArea

            focused = self.focused if self.screen_stack else None
            if (
                focused is not None
                and focused.id != "prompt-input"
                and (
                    isinstance(focused, Input)
                    or (isinstance(focused, TextArea) and not focused.read_only)
                )
            ):
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

        # Picker numbers belong to selection, even in Normal mode. Enter and
        # other terminal control keys must also reach their ordinary handlers.
        if self._vim_picker_active() and len(key) == 1 and key in "0123456789":
            return False

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
                if state in {"command", "search"}:
                    self._restore_vim_draft(prompt, cancel_line=True)
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
            self._restore_vim_draft(prompt)
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
        if len(token) == 1 and token.isprintable():
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
            focus = getattr(log, "focus_history_match", None)
            if callable(focus) and not getattr(self, "is_busy", False):
                focus(message_index)
            log.auto_scroll = False
            messages = list(getattr(log, "_messages", []))
            target_y = 0
            for _role, content, _agent in messages[
                getattr(log, "_history_start", 0) : message_index
            ]:
                target_y += max(2, len(str(content).splitlines()) + 2)
            visible_height = max(6, int(getattr(getattr(log, "size", None), "height", 18) or 18))
            position = max(0, target_y - max(1, visible_height // 3))
            log.scroll_to(y=position, animate=False)
            if callable(getattr(log, "call_after_refresh", None)):
                log.call_after_refresh(log.scroll_to, y=position, animate=False)
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
