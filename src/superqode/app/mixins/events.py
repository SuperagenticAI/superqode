"""Textual message handlers for custom widgets."""

from __future__ import annotations
from textual.widgets import Input
from textual import on, events
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.widgets.leader_key import LeaderKeyPopup
from superqode.widgets.command_palette import CommandPalette
from superqode.sidebar import (
    ColorfulDirectoryTree,
    CollapsibleSidebar,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput


class EventHandlerMixin:
    """on_* message handlers for custom widgets (non-lifecycle)."""

    def _init_draft_recovery(self) -> None:
        from pathlib import Path
        from superqode.app.draft_recovery import DraftStore
        from superqode.image_input import ImageAttachment

        # Headless probes do not read or overwrite the developer's real draft.
        # Tests can inject a store explicitly to exercise restart behavior.
        store = getattr(self, "_draft_store", None)
        if self.is_headless and store is None:
            return
        self._draft_store = store or DraftStore(Path.cwd())
        self._draft_revision = 0
        state = self._draft_store.load()
        if not state:
            return
        prompt = self.query_one("#prompt-input", SelectionAwareInput)
        if prompt.value:
            return
        self._composer_blocks = state.get("blocks", {})
        self._attached_refs = state["refs"]
        self._attachment_prefill = state["prefill"]
        self._staged_images = {
            ref: ImageAttachment(Path(path), "", "")
            for ref, path in state["images"].items()
            if ref in self._attached_refs
        }
        prompt.value = state["text"]
        prompt.cursor_position = state["cursor"]
        self._refresh_attachment_bar()
        self.query_one("#log", ConversationLog).add_info("Recovered your unsent draft.")

    def _schedule_draft_save(self) -> None:
        if getattr(self, "_draft_store", None) is None:
            return
        self._draft_snapshot()
        timer = getattr(self, "_draft_save_timer", None)
        if timer is not None:
            timer.stop()
        self._draft_save_timer = self.set_timer(0.5, self._save_draft_in_background)

    def _draft_snapshot(self) -> tuple[dict, int]:
        from textual.css.query import NoMatches

        try:
            prompt = self.query_one("#prompt-input", SelectionAwareInput)
        except NoMatches:
            self._draft_revision += 1
            return getattr(self, "_last_draft_snapshot", {}), self._draft_revision
        text, cursor = prompt.value, prompt.cursor_position
        decision = getattr(self, "_decision_draft", None)
        if decision is not None:
            text, (row, column) = decision
            cursor = sum(len(line) + 1 for line in text.split("\n")[:row]) + column
        self._draft_revision += 1
        state = {
            "text": text,
            "cursor": cursor,
            "blocks": {
                key: block
                for key, block in getattr(self, "_composer_blocks", {}).items()
                if f"[Block {key}]" in text
            },
            "refs": list(getattr(self, "_attached_refs", [])),
            "images": {
                ref: str(image.path) for ref, image in getattr(self, "_staged_images", {}).items()
            },
            "prefill": getattr(self, "_attachment_prefill", ""),
        }
        self._last_draft_snapshot = state
        return state, self._draft_revision

    async def _save_draft_in_background(self) -> None:
        import asyncio

        try:
            state, revision = self._draft_snapshot()
            await asyncio.to_thread(self._draft_store.save, state, revision)
        except (OSError, ValueError):
            pass  # Recovery must not interrupt typing on a read-only workspace.

    def _flush_draft_recovery(self) -> None:
        if getattr(self, "_draft_store", None) is None:
            return
        timer = getattr(self, "_draft_save_timer", None)
        if timer is not None:
            timer.stop()
        try:
            state, revision = self._draft_snapshot()
            self._draft_store.save(state, revision)
        except (OSError, ValueError):
            pass

    def on_app_blur(self, event: events.AppBlur) -> None:
        self._wave_window_focused = False
        resume = getattr(self, "_wave_burst_running", False) or getattr(
            self, "_wave_resume_on_focus", False
        )
        self._stop_wave_bursts()
        self._wave_resume_on_focus = resume
        try:
            self.query_one("#prompt-input")._sync_working_animation()
            self.query_one("#streaming-thinking").auto_refresh = None
        except Exception:
            pass

    def on_app_focus(self, event: events.AppFocus) -> None:
        self._wave_window_focused = True
        try:
            self.query_one("#prompt-input")._sync_working_animation()
        except Exception:
            pass
        if getattr(self, "is_busy", False):
            if getattr(self, "_wave_resume_on_focus", False):
                self._begin_wave_bursts()
            try:
                self.query_one("#streaming-thinking").auto_refresh = 1 / 2
            except Exception:
                pass

    def on_unmount(self) -> None:
        from superqode.app.herdr import close

        close(self)
        self._stop_wave_bursts()
        self._flush_draft_recovery()

    def on_command_palette_command_selected(self, event: CommandPalette.CommandSelected) -> None:
        # Name-based dispatch also works when this handler lives on a plain mixin.
        event.stop()
        self.on_command_palette_selected(event)

    def on_command_palette_dismissed(self, event: CommandPalette.Dismissed) -> None:
        event.stop()
        if len(self.screen_stack) == 1:
            self._ensure_input_focus()

    def on_resizable_divider_resized(self, event) -> None:
        """Handle sidebar resize via divider drag."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            current_width = getattr(sidebar, "_width", 34)
            self._set_sidebar_width(current_width + event.delta_x)
        except Exception:
            pass

    def on_resizable_divider_resize_end(self, _event) -> None:
        """Write the chosen width once after dragging, not on every mouse move."""
        self._persist_sidebar_width()

    @on(CommandPalette.CommandSelected)
    def on_command_palette_selected(self, event: CommandPalette.CommandSelected) -> None:
        """Route command palette selections through the existing command dispatcher."""
        log = self.query_one("#log", ConversationLog)
        if event.command.id == "sidebar":
            self.action_toggle_sidebar()
            return
        if event.command.action is not None:
            event.command.action()
            return
        if event.command.prefill:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            if input_widget.value.strip():
                stash = list(getattr(self, "_draft_stash", []))
                stash.append(input_widget.value)
                self._draft_stash = stash[-20:]
            input_widget.value = event.command.command + " "
            input_widget.cursor_position = len(input_widget.value)
            input_widget.focus()
            return

        command = event.command.command
        if command:
            self._handle_command(command, log)
        else:
            log.add_error(f"No handler for palette command: {event.command.label}")

    async def on_text_selected(self) -> None:
        """Automatically copy selected text to the clipboard on mouse-drag select.

        NOTE: dispatched by Textual's name-based convention (``on_<event>``) —
        do NOT add ``@on(events.TextSelected)``. On a plain mixin the decorator's
        registration is not collected, and it also suppresses name-based
        dispatch, so decorating this method silently disables mouse-drag copy.

        Dragging the mouse over the conversation (or anywhere selectable) copies
        the highlighted text straight to the system clipboard — no ``:copy``
        needed. We rely on Textual's ``TextSelected`` event rather than
        intercepting keyboard shortcuts, so Ctrl+C (quit) / Ctrl+Z behavior is
        preserved.
        """
        try:
            selection = self.screen.get_selected_text()
        except Exception:
            selection = None

        if not selection:
            return

        def _announce_or_notify(
            title: str, primary: str, severity: str, *, persist: bool, timeout: int
        ) -> None:
            if hasattr(self, "_announce_transition"):
                self._announce_transition(  # type: ignore[attr-defined]
                    title=title, primary=primary, severity=severity, persist=persist
                )
            else:
                self.notify(primary, title=title, severity=severity, timeout=timeout)

        copy_ok_msg = f"Copied {len(selection)} chars to clipboard"
        copy_fail_msg = "Couldn't reach the clipboard — try :copy or Shift+drag"
        try:
            if self._copy_text_to_clipboard(selection):
                _announce_or_notify("Copied", copy_ok_msg, "information", persist=False, timeout=1)
            else:
                _announce_or_notify(
                    "Copy failed", copy_fail_msg, "warning", persist=False, timeout=3
                )
        except Exception:
            # Best-effort: never let a copy/notify failure crash the UI.
            pass

    @on(LeaderKeyPopup.KeyPressed)
    def on_leader_key_popup_key_pressed(self, event: LeaderKeyPopup.KeyPressed) -> None:
        """Handle leader key selection from popup."""
        self._leader_mode = False
        action = event.action
        log = self.query_one("#log", ConversationLog)

        # Execute the action
        if action == "show_help":
            self._show_help(log)
        elif action == "open_editor":
            self._handle_edit(log)
        elif action == "copy_response":
            self._handle_copy(log)
        elif action == "show_select":
            self._handle_select(log)
        elif action == "show_theme":
            self._handle_theme("", log)
        elif action == "show_diagnostics":
            self._handle_diagnostics(".", log)
        elif action == "toggle_sidebar":
            self.action_toggle_sidebar()
        elif action == "quit_app":
            self.action_quit()

        # Return focus to input
        self.set_timer(0.1, self._ensure_input_focus)

    @on(LeaderKeyPopup.Cancelled)
    def on_leader_key_popup_cancelled(self, event: LeaderKeyPopup.Cancelled) -> None:
        """Handle leader mode cancellation."""
        self._leader_mode = False
        # Return focus to input
        self.set_timer(0.1, self._ensure_input_focus)

    def on_click(self, event: events.Click) -> None:
        """Route mouse clicks on numbered picker links through direct selection."""
        style = getattr(event, "style", None)
        link = getattr(style, "link", None) if style is not None else None
        if link and str(link).startswith("superqode://cmd/"):
            from urllib.parse import unquote

            command = unquote(str(link).split("superqode://cmd/", 1)[1]).strip()
            if command:
                event.stop()
                event.prevent_default()
                self._run_clicked_command(command)
            return
        if not link or not str(link).startswith("superqode://pick/"):
            # No link under the pointer. On a picker screen the click may still
            # have landed on a row, just on text that carries no link style.
            if self._click_selects_picker_row(event):
                event.stop()
                event.prevent_default()
                self.set_timer(0.05, self._ensure_input_focus)
            return
        raw = str(link).rsplit("/", 1)[-1]
        if not raw.isdigit():
            return
        if self._select_picker_number_direct(int(raw)):
            event.stop()
            event.prevent_default()
            self.set_timer(0.05, self._ensure_input_focus)

        # Reset timer
        timer = getattr(self, "_selection_digit_timer", None)
        try:
            if timer:
                timer.stop()
        except Exception:
            pass
        self._selection_digit_timer = self.set_timer(0.35, self._apply_selection_buffer)

    @on(ColorfulDirectoryTree.FileOpenRequested)
    def on_tree_file_open_requested(self, event: ColorfulDirectoryTree.FileOpenRequested) -> None:
        """Handle file open request from tree directly."""
        event.stop()
        log = self.query_one("#log", ConversationLog)
        self._view_file(str(event.path), log)

    def on_input_submitted(self, event: Input.Submitted):
        """Handle input submission - only processes on Enter, doesn't interfere with typing."""
        if event.input.id != "prompt-input":
            return

        # The user is now interacting; the log will hold more than the welcome,
        # so stop re-flowing it on resize.
        self._welcome_active = False

        text = event.value.strip()
        # If a selection digit buffer is active, clear its timer to avoid double-select
        if hasattr(self, "_selection_digit_timer") and self._selection_digit_timer:
            try:
                self._selection_digit_timer.stop()
            except Exception:
                pass
            self._selection_digit_timer = None
            if hasattr(self, "_selection_digit_buffer"):
                self._selection_digit_buffer = ""
        log = self.query_one("#log", ConversationLog)

        if getattr(self, "_permission_pending", False) and not getattr(
            self, "_awaiting_agent_question", False
        ):
            # Approval answers are decisions, never queued coding prompts.
            if text.lower() in {
                "y",
                "yes",
                "allow",
                "ok",
                "n",
                "no",
                "deny",
                "reject",
                "a",
                "all",
                "allow all",
                "yes all",
            }:
                event.input.value = ""
                self._handle_permission_input(text)
            return

        if text:
            # A new prompt/command means the user wants to see its output.
            # Drop any reading lock so the result lands in view instead of
            # silently below the fold (e.g. `:help` then `:agy models`).
            try:
                log.resume_follow()
            except Exception:  # noqa: BLE001 - follow is best effort
                pass

        if getattr(self, "_install_in_progress", False):
            if text.lower() in {":cancel", "/cancel", "cancel"}:
                self._cancel_install()
                event.input.value = ""
                log.add_info("Stopping the installer…")
            else:
                log.add_info(
                    "Installation is running. Your draft stays in the prompt. Esc cancels."
                )
            return

        # Handle Enter key (empty input) for selections
        if not text:
            # Inline setup prompts win first: Enter = install / start with defaults.
            if getattr(self, "_awaiting_harness_install", None):
                self._handle_harness_install_input("", log)
                event.input.value = ""
                return
            if getattr(self, "_prompts", None) is not None and self._prompts.active is not None:
                self._prompts.select()
                event.input.value = ""
                return
            if getattr(self, "_awaiting_local_dep_install", None):
                self._handle_local_dep_install_input("", log)
                event.input.value = ""
                return
            if getattr(self, "_awaiting_local_server_start", None):
                self._handle_local_server_start_input("", log)
                event.input.value = ""
                return
            if getattr(self, "_awaiting_local_connect_start", None):
                self._handle_local_connect_start_input("", log)
                event.input.value = ""
                return
            if getattr(self, "_awaiting_subscription_login", None):
                self._handle_subscription_login_input("", log)
                event.input.value = ""
                return

            if getattr(self, "_awaiting_agent_question", False):
                self._handle_agent_question_input(text, log)
                event.input.value = ""
                return

            if getattr(self, "_awaiting_harness_wizard", False):
                self._handle_harness_wizard_input(text, log)
                event.input.value = ""
                return

            if getattr(self, "_awaiting_harness_confirmation", False):
                self.action_confirm_harness_switch()
                event.input.value = ""
                return

            if getattr(self, "_awaiting_harness_selection", False):
                self.action_select_highlighted_harness()
                event.input.value = ""
                return

            # Check if awaiting ACP agent selection
            if getattr(self, "_awaiting_acp_agent_selection", False):
                self.action_select_highlighted_acp_agent()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting BYOK model selection
            if getattr(self, "_awaiting_byok_model", False):
                self.action_select_highlighted_model()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting BYOK provider selection
            if getattr(self, "_awaiting_byok_provider", False):
                self.action_select_highlighted_provider()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting LOCAL model selection
            if getattr(self, "_awaiting_local_model", False):
                self.action_select_highlighted_local_model()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting LOCAL provider selection
            # CRITICAL: Only auto-select if we're actually awaiting user input, not just showing the picker
            # Don't auto-select on empty input immediately after showing picker
            if getattr(self, "_awaiting_local_provider", False):
                # Check if we just showed the picker - if so, don't auto-select yet
                if not getattr(self, "_just_showed_local_picker", False):
                    self.action_select_highlighted_local_provider()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting connection type selection
            if getattr(self, "_awaiting_connect_type", False):
                self.action_select_highlighted_connect_type()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting runtime selection
            if getattr(self, "_awaiting_runtime_selection", False):
                self.action_select_highlighted_runtime()
                event.input.value = ""  # Clear input
                return

            if getattr(self, "_awaiting_session_resume", False):
                self.action_select_highlighted_session_resume()
                event.input.value = ""
                return

            if getattr(self, "_awaiting_mode_selection", False):
                self.action_select_highlighted_mode()
                event.input.value = ""
                return

            if getattr(self, "_awaiting_free_selection", False):
                self.action_select_highlighted_free()
                event.input.value = ""
                return

            # Empty input with no selection mode - do nothing
            if getattr(self, "_staged_images", {}):
                log.add_info("Image attached. Add a prompt, then press Enter to send.")
            return

        # Clear input immediately after submission (user has pressed Enter)
        event.input.value = ""

        # Ensure input stays focused for next message
        try:
            event.input.focus()
        except Exception:
            pass

        log = self.query_one("#log", ConversationLog)

        if getattr(self, "_awaiting_agent_question", False):
            if self._handle_agent_question_input(text, log):
                return

        if getattr(self, "_awaiting_harness_wizard", False):
            if self._handle_harness_wizard_input(text, log):
                return

        # Check for commands FIRST (before selection handlers) so :home, :back, :cancel work
        # Supports both : (vim-style) and / prefix
        if self._vim_enabled() and text in {"q:", "@:"}:
            if text == "q:":
                self._vim_command_history(log)
            else:
                self._repeat_last_ex_command(log)
            return
        if self._vim_enabled() and self._try_vim_search_input(text, log):
            return

        command_prefix = None
        if text.startswith(":"):
            command_prefix = ":"
        elif text.startswith("/"):
            from superqode.image_input import parse_image_paths

            refs = parse_image_paths(text)
            if not refs or refs[0].start != 0:
                command_prefix = "/"

        if command_prefix:
            cmd = text[len(command_prefix) :].strip().lower()
            if cmd == "back":
                if not self._navigate_back():
                    if self._in_selection_mode():
                        self.action_smart_cancel()
                    else:
                        log.add_info("Nothing to go back to.")
                return
            # Handle navigation commands during selection
            if cmd in ("home", "back", "cancel") and (
                getattr(self, "_awaiting_connect_type", False)
                or getattr(self, "_awaiting_runtime_selection", False)
                or getattr(self, "_awaiting_acp_agent_selection", False)
                or getattr(self, "_awaiting_byok_provider", False)
                or getattr(self, "_awaiting_byok_model", False)
                or getattr(self, "_awaiting_local_provider", False)
                or getattr(self, "_awaiting_local_server_start", None)
                or getattr(self, "_awaiting_local_dep_install", None)
                or getattr(self, "_awaiting_session_resume", False)
                or getattr(self, "_awaiting_mode_selection", False)
                or getattr(self, "_awaiting_harness_wizard", False)
                or getattr(self, "_awaiting_harness_selection", False)
                or getattr(self, "_awaiting_harness_confirmation", False)
                or getattr(self, "_awaiting_harness_install", None)
                or getattr(self, "_awaiting_dependency_install", None)
                or getattr(self, "_awaiting_subscription_login", None)
            ):
                # Cancel selection mode
                self._awaiting_connect_type = False
                self._awaiting_subscription_login = None
                self._awaiting_runtime_selection = False
                self._awaiting_acp_agent_selection = False
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                self._awaiting_local_provider = False
                self._awaiting_session_resume = False
                self._awaiting_mode_selection = False
                self._awaiting_harness_wizard = False
                self._awaiting_harness_selection = False
                self._awaiting_harness_confirmation = False
                self._awaiting_harness_install = None
                self._awaiting_dependency_install = None
                self._clear_key_harness_session()
                self._harness_wizard_state = None
                self._awaiting_local_server_start = None
                self._awaiting_local_dep_install = None
                # Clear selection state
                if hasattr(self, "_byok_connect_list"):
                    delattr(self, "_byok_connect_list")
                if hasattr(self, "_byok_model_list"):
                    delattr(self, "_byok_model_list")
                if hasattr(self, "_byok_selected_provider"):
                    delattr(self, "_byok_selected_provider")
                if hasattr(self, "_acp_agent_list"):
                    delattr(self, "_acp_agent_list")
                if hasattr(self, "_local_provider_list"):
                    delattr(self, "_local_provider_list")
                if hasattr(self, "_session_resume_list"):
                    delattr(self, "_session_resume_list")
                if hasattr(self, "_harness_selection_list"):
                    delattr(self, "_harness_selection_list")
                if hasattr(self, "_harness_pending_entry"):
                    delattr(self, "_harness_pending_entry")
                # Handle the command - call _go_home directly for :home to ensure it always works
                if cmd == "home":
                    self._go_home(log)
                elif cmd in ("back", "cancel"):
                    log.add_info("Selection cancelled.")
                return

            # Record command in history
            self._history_manager.append_sync(
                text,
                mode=self.current_mode if self.current_mode != "home" else None,
                agent=self.current_agent if self.current_agent else None,
            )
            self._handle_command(text, log)
            return

        # Shell command
        if text.startswith(">") or text.startswith("!"):
            cmd = text[1:].strip()
            if cmd:
                self._run_shell(cmd, log)
            return

        # Inline setup prompts take priority over every other selection handler
        # so a typed 'n'/options can never be swallowed by a stale picker flag.
        if getattr(self, "_awaiting_harness_install", None):
            if self._handle_harness_install_input(text, log):
                return
        # Any registry-driven prompt gets typed answers routed to it; prompts
        # without their own text handler fall back to number selection.
        if getattr(self, "_prompts", None) is not None and self._prompts.active is not None:
            if self._prompts.handle_text(text):
                return
        if getattr(self, "_awaiting_local_dep_install", None):
            if self._handle_local_dep_install_input(text, log):
                return
        if getattr(self, "_awaiting_local_server_start", None):
            if self._handle_local_server_start_input(text, log):
                return
        if getattr(self, "_awaiting_local_connect_start", None):
            if self._handle_local_connect_start_input(text, log):
                return
        if getattr(self, "_awaiting_subscription_login", None):
            if self._handle_subscription_login_input(text, log):
                return

        if getattr(self, "_awaiting_harness_confirmation", False):
            choice = text.strip().lower()
            if choice in {"y", "yes", "continue"}:
                self.action_confirm_harness_switch()
            elif choice in {"n", "no", "cancel"}:
                self.action_cancel_harness_selection()
            else:
                log.add_error("Press Enter to continue or Esc to cancel.")
            return

        if getattr(self, "_awaiting_harness_selection", False):
            if self._handle_harness_picker_input(text, log):
                return

        # Number-then-Enter selection, as every other picker supports.
        for flag, items_attr, select, clears in (
            ("_awaiting_harness_preset", "_harness_preset_list", "_clone_harness_preset", True),
            (
                "_awaiting_harness_import",
                "_harness_import_list",
                "_import_harness_selection",
                True,
            ),
            ("_awaiting_explore", "_explore_capabilities", "_select_explore_row", False),
        ):
            if not getattr(self, flag, False):
                continue
            choice = text.strip()
            items = getattr(self, items_attr, [])
            if choice.isdigit() and items and 1 <= int(choice) <= len(items):
                event.input.value = ""
                if clears:
                    log.clear()
                getattr(self, select)(int(choice) - 1, log)
                return
            if choice:
                log.add_error(f"Pick a number between 1 and {len(items)}, or press Esc.")
                event.input.value = ""
                return

        # Check if awaiting connect type selection (profile-driven)
        if getattr(self, "_awaiting_connect_type", False):
            from superqode.providers.connection_profiles import get_connection_profile

            profiles = self._connect_menu_profiles()
            choice = text.strip().lower()
            if choice in {"h", "harness", "harnesses"}:
                event.input.value = ""
                self.action_browse_harnesses_from_connect()
                return
            if choice in {"b", "back"} and self.action_connect_menu_back():
                event.input.value = ""
                return
            profile = None
            if choice.isdigit() and 1 <= int(choice) <= len(profiles):
                profile = profiles[int(choice) - 1]
            else:
                # Names resolve across every menu, so `codex` still works from
                # the root screen without stepping into Subscriptions first.
                profile = get_connection_profile(choice)
            if profile is not None:
                event.input.value = ""
                self._dispatch_connection_profile(profile, log)
                return
            ids = ", ".join(p.id for p in profiles)
            log.add_error(f"Invalid selection. Choose 1-{len(profiles)} or a name ({ids}).")
            return

        # Check if awaiting runtime selection (typed number or name)
        if getattr(self, "_awaiting_runtime_selection", False):
            runtimes = getattr(self, "_runtime_selection_list", [])
            if runtimes:
                choice = text.strip().lower()
                info = None
                if choice.isdigit() and 1 <= int(choice) <= len(runtimes):
                    info = runtimes[int(choice) - 1]
                else:
                    for r in runtimes:
                        if r.name.lower() == choice:
                            info = r
                            break
                if info is not None:
                    if not info.installed:
                        if not self._show_dependency_install_picker(info.name, log):
                            log.add_error(
                                self._runtime_install_message(info.name, info.install_hint)
                            )
                        return
                    if not info.implemented:
                        log.add_error(f"Runtime '{info.name}' is a stub and not yet usable.")
                        return
                    if not info.ready:
                        log.add_error(
                            f"Runtime '{info.name}' is not ready: "
                            f"{info.status_detail or 'check setup'}"
                        )
                        return
                    self._awaiting_runtime_selection = False
                    self._runtime_cmd(info.name, log)
                    if info.name not in self._SELF_CONTAINED_RUNTIMES:
                        self._show_byok_providers(log)
                    return
                names = ", ".join(r.name for r in runtimes)
                log.add_error(f"Invalid runtime. Choose 1-{len(runtimes)} or a name ({names}).")
                return

        if getattr(self, "_awaiting_session_resume", False):
            if self._handle_session_resume_selection(text, log):
                return

        if getattr(self, "_awaiting_mode_selection", False):
            if self._handle_mode_selection(text, log):
                return

        if getattr(self, "_awaiting_free_selection", False):
            if self._handle_free_selection(text, log):
                return

        # Check if awaiting ACP agent selection
        if getattr(self, "_awaiting_acp_agent_selection", False):
            if self._handle_acp_agent_selection(text, log):
                return

        # Numbered model selection. A model list is routinely longer than five
        # entries, and the old fixed 1-5 range meant a typed "7" fell through
        # this branch and was sent to the agent as a prompt. Any number is
        # accepted here; the picker reports one it cannot honour.
        if self._awaiting_model_selection and text.strip().isdigit():
            self._select_model_by_number(int(text.strip()))
            return

        # Check if awaiting BYOK provider selection
        if getattr(self, "_awaiting_byok_provider", False):
            # CRITICAL: Prevent immediate processing if we just showed the picker
            # This prevents "2" from being processed as provider selection right after selecting BYOK
            if getattr(self, "_just_showed_byok_picker", False):
                # Clear the flag and completely ignore this input
                # Don't process it at all - it was meant for connection type selection
                return

            # Also check if this is "2" and we're in a transition state
            # This is an extra safeguard
            if text.strip() == "2" and getattr(self, "_just_showed_byok_picker", False):
                return

            # Check for Enter key - empty input means Enter was pressed
            if not text.strip():
                # Use highlighted provider
                self.action_select_highlighted_provider()
                return
            if self._handle_byok_provider_selection(text, log):
                return

        # Check if awaiting LOCAL provider selection
        if getattr(self, "_awaiting_local_provider", False):
            if self._handle_local_provider_selection(text, log):
                return

        # Check if awaiting LOCAL model selection
        if getattr(self, "_awaiting_local_model", False):
            if self._handle_local_model_selection(text, log):
                return

        # Check if awaiting Codex SDK model selection
        if getattr(self, "_awaiting_codex_model", False):
            if self._handle_codex_model_selection(text, log):
                return

        # Check if awaiting Codex SDK reasoning effort selection
        if getattr(self, "_awaiting_codex_effort", False):
            if self._handle_codex_effort_selection(text, log):
                return

        # Check if awaiting BYOK model selection
        if getattr(self, "_awaiting_byok_model", False):
            if self._handle_byok_model_selection(text, log):
                return

                # Check if awaiting provider selection
                return

                # Check if awaiting model selection
                return
            # Record command in history
            self._history_manager.append_sync(
                text,
                mode=self.current_mode if self.current_mode != "home" else None,
                agent=self.current_agent if self.current_agent else None,
            )
            self._handle_command(text, log)
            return

        # Expand payloads only for a model message, after command/shell routing.
        try:
            text = self._expand_composer_blocks(text)
        except ValueError as exc:
            event.input.value = event.value
            log.add_error(str(exc))
            return
        self._refresh_attachment_bar()

        # Message - record and send
        self._history_manager.append_sync(
            text,
            mode=self.current_mode if self.current_mode != "home" else None,
            agent=self.current_agent if self.current_agent else None,
        )
        self._handle_message(text, log)
