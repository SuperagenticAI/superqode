"""Misc keybinding actions."""

from __future__ import annotations
import asyncio
from rich.text import Text
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.design_system import (
    COLORS as SQ_COLORS,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput


class MiscActionsMixin:
    """Copy/editor/undo/redo/checkpoint/rewind/split-view actions."""

    def action_return_to_agent(self) -> None:
        """Restore the conversation after viewing a command or picker screen."""
        reset_connect = getattr(self, "_reset_connect_selection_states", None)
        if callable(reset_connect):
            reset_connect()
        for flag in (
            "_awaiting_session_resume",
            "_awaiting_mode_selection",
            "_awaiting_harness_selection",
            "_awaiting_harness_confirmation",
            "_awaiting_recommendation_selection",
            "_awaiting_free_selection",
            "_awaiting_model_selection",
        ):
            setattr(self, flag, False)

        self._welcome_active = False
        log = self.query_one("#log", ConversationLog)
        log.redraw_conversation()
        try:
            self.query_one("#prompt-input", SelectionAwareInput).focus()
        except Exception:
            pass
        self.set_timer(0.05, self._ensure_input_focus)

    def action_show_help(self):
        """Show help reference (F1 or Leader Key 'h')."""
        log = self.query_one("#log", ConversationLog)
        self._show_help(log)

    def action_show_theme(self):
        """Open theme picker (Leader Key 't')."""
        log = self.query_one("#log", ConversationLog)
        self._handle_theme("", log)

    def action_show_diagnostics(self):
        """Show diagnostics view (Leader Key 'd')."""
        log = self.query_one("#log", ConversationLog)
        self._handle_diagnostics("", log)

    def action_show_select(self):
        """Open selectable transcript view (Leader Key 's')."""
        log = self.query_one("#log", ConversationLog)
        self._handle_select(log, "")

    def action_copy_response(self):
        """Copy last agent response to clipboard (Ctrl+Shift+C)."""
        log = self.query_one("#log", ConversationLog)
        self._handle_copy(log)

    def action_copy_code(self):
        """Copy last fenced code block from agent response to clipboard (Ctrl+Y or Leader 'y')."""
        log = self.query_one("#log", ConversationLog)
        self._handle_copy(log, "code")

    def action_search_history(self):
        """Open interactive prompt history search modal (Ctrl+Shift+R or Leader 'r')."""
        from superqode.widgets.history_search import HistorySearchModal

        history_manager = getattr(self, "_history_manager", None)
        if history_manager is not None:
            history_manager.ensure_loaded()
            entries = history_manager.entries
        else:
            entries = []

        def _on_dismissed(selected: str | None) -> None:
            self.set_timer(0.05, self._ensure_input_focus)
            if selected is not None and selected.strip():
                try:
                    prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
                    prompt_input.load_text(selected)
                    prompt_input.focus()
                except Exception:
                    pass

        self.push_screen(HistorySearchModal(entries=entries), callback=_on_dismissed)

    def action_remove_attachment(self, index: int) -> None:
        self._attach_cmd(f"remove {index}", self.query_one("#log", ConversationLog))
        self._ensure_input_focus()

    def action_voice_input(self) -> None:
        """Keep OS dictation in the editable composer, with platform guidance."""
        import sys
        from rich.text import Text
        from textual.widgets import Static
        from superqode.app.constants import THEME

        if getattr(self, "is_busy", False):
            self.notify(
                "Wait for the current run to finish before dictating.", title="OS Dictation"
            )
            return
        if sys.platform == "darwin":
            hint = "Use your Dictation shortcut · Enable in System Settings → Keyboard → Dictation"
        elif sys.platform == "win32":
            hint = "Press Win+H to start Windows voice typing"
        else:
            hint = "Use your desktop dictation tool to insert text into this terminal"
        panel = self.query_one("#dictation-guide", Static)
        text = Text("◉ OS Dictation  ", style=THEME["purple"])
        text.append(hint, style=THEME["text"])
        text.append(
            "\nEdit your words, then Enter to send · :voice off to hide", style=THEME["muted"]
        )
        panel.update(text)
        panel.add_class("visible")
        if self._vim_enabled():
            self._set_vim_state("insert")
        self._ensure_input_focus()

    def action_open_editor(self):
        """Open external editor for composing message (Ctrl+E)."""
        log = self.query_one("#log", ConversationLog)
        self._handle_edit(log)

    def action_undo_action(self):
        """Undo the last agent operation."""
        if not hasattr(self, "_undo_manager") or not self._undo_manager:
            return

        log = self.query_one("#log", ConversationLog)
        result = self._undo_manager.undo()
        if result:
            text = Text()
            text.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
            text.append("Undone: ", style=SQ_COLORS.text_secondary)
            text.append(result.name, style=f"bold {SQ_COLORS.text_primary}")
            if result.files_changed:
                text.append(f" ({len(result.files_changed)} files)", style=SQ_COLORS.text_dim)
            text.append("\n", style="")
            log.write(text)
        else:
            log.add_info("◇ Nothing to undo")

    def action_redo_action(self):
        """Redo the previously undone operation."""
        if not hasattr(self, "_undo_manager") or not self._undo_manager:
            return

        log = self.query_one("#log", ConversationLog)
        result = self._undo_manager.redo()
        if result:
            text = Text()
            text.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
            text.append("Redone: ", style=SQ_COLORS.text_secondary)
            text.append(result.name, style=f"bold {SQ_COLORS.text_primary}")
            text.append("\n", style="")
            log.write(text)
        else:
            log.add_info("◇ Nothing to redo")

    def action_create_checkpoint(self):
        """Create a manual checkpoint."""
        if not hasattr(self, "_undo_manager") or not self._undo_manager:
            return

        log = self.query_one("#log", ConversationLog)
        checkpoint_id = self._undo_manager.create_checkpoint("Manual checkpoint")
        if checkpoint_id:
            text = Text()
            text.append("  ◆ ", style=f"bold {SQ_COLORS.primary}")
            text.append("Checkpoint created: ", style=SQ_COLORS.text_secondary)
            text.append(checkpoint_id, style=f"bold {SQ_COLORS.text_primary}")
            text.append("\n", style="")
            log.write(text)
        else:
            log.add_info("◇ No changes to checkpoint")

    def action_toggle_split_view(self):
        """Toggle the split view for code + chat."""
        log = self.query_one("#log", ConversationLog)

        # Check if split view is available
        if not hasattr(self, "_split_view_enabled"):
            self._split_view_enabled = False

        self._split_view_enabled = not self._split_view_enabled

        if self._split_view_enabled:
            text = Text()
            text.append("  ◇ ", style=f"bold {SQ_COLORS.primary}")
            text.append("Split view: ", style=SQ_COLORS.text_secondary)
            text.append("ON", style=f"bold {SQ_COLORS.success}")
            text.append(" (use :open <file> to view files)", style=SQ_COLORS.text_dim)
            text.append("\n", style="")
            log.write(text)
        else:
            text = Text()
            text.append("  ◇ ", style=f"bold {SQ_COLORS.primary}")
            text.append("Split view: ", style=SQ_COLORS.text_secondary)
            text.append("OFF", style=SQ_COLORS.text_dim)
            text.append("\n", style="")
            log.write(text)

    def action_cancel_agent(self):
        """Cancel the currently running agent operation."""
        log = self.query_one("#log", ConversationLog)
        if getattr(self, "_cancel_requested", False) and self.is_busy:
            return
        self._cancel_requested = True
        provider, model = self._active_local_provider_model()

        if self._acp_client is not None:
            client = self._acp_client
            cancel_token = object()
            self._acp_cancel_token = cancel_token
            try:
                if self._acp_loop_runner is not None:
                    self._acp_loop_runner.run(self._acp_client.cancel(), timeout=1.0)
                else:
                    asyncio.create_task(self._acp_client.cancel())
            except Exception:
                pass

            def stop_unresponsive_agent():
                # Give session/cancel time to finish the turn. A stale timer
                # must never terminate a replacement agent or a later turn.
                if (
                    self._acp_client is not client
                    or getattr(self, "_acp_cancel_token", None) is not cancel_token
                    or not self.is_busy
                    or not getattr(self, "_cancel_requested", False)
                ):
                    return
                try:
                    process = getattr(client, "_process", None)
                    if process is not None and process.returncode is None:
                        process.terminate()
                        log.add_info(
                            "ACP agent did not stop; its process was terminated. Retry to reconnect."
                        )
                except Exception:
                    pass

            self.set_timer(3.0, stop_unresponsive_agent)
            log.add_info("🛑 Cancelling ACP agent operation...")
            self._stop_stream_animation()
            self._stop_thinking()
            # Keep later prompts out until the ACP worker completes cancellation.
            self.is_busy = True
            return

        if self._agent_process is not None:
            self._cancel_requested = True
            try:
                self._agent_process.terminate()
            except Exception:
                pass
            log.add_info("🛑 Cancelling agent operation...")
            self._stop_stream_animation()
            self._stop_thinking()
        elif self.is_busy:
            pure = getattr(self, "_pure_mode", None)
            if pure is not None and hasattr(pure, "cancel"):
                pure.cancel()
            self._stop_stream_animation()
            self._stop_thinking()
            clear = getattr(self, "_clear_running_tools", None)
            if callable(clear):
                clear(log)
            self.is_busy = False
            log.add_info("🛑 Agent operation cancelled")

        if provider:
            self._teardown_local_model_runtime(provider, model)

    def action_stash_draft(self) -> None:
        """Ctrl+G: set the current prompt draft aside; :stash restores it."""
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
        except Exception:
            return
        draft = input_widget.value.strip()
        log = self.query_one("#log", ConversationLog)
        if not draft:
            if getattr(self, "_draft_stash", []):
                log.add_info("Nothing to stash. Use :stash to restore your last draft.")
            return
        if not hasattr(self, "_draft_stash"):
            self._draft_stash = []
        self._draft_stash.append(draft)
        input_widget.value = ""
        log.add_info(f"📥 Stashed draft ({len(self._draft_stash)} saved). Restore with :stash.")

    def action_search_transcript(self) -> None:
        """Start a transcript search (Ctrl+F).

        Prefilling ``:search`` reuses the existing command path instead of
        adding another modal prompt state, so Enter, Esc, and history keep
        behaving exactly as they do for every other command.
        """
        from superqode.app.inputs import SelectionAwareInput

        from superqode.sidebar import CollapsibleSidebar

        focused = getattr(self, "focused", None)
        if focused is not None:
            sidebar = next(
                (
                    node
                    for node in focused.ancestors_with_self
                    if isinstance(node, CollapsibleSidebar)
                ),
                None,
            )
            if sidebar is not None:
                sidebar.action_toggle_search()
                return

        try:
            prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
        except Exception:
            return
        draft = prompt_input.value
        if draft.strip() and not draft.startswith(":search "):
            if not hasattr(self, "_draft_stash"):
                self._draft_stash = []
            self._draft_stash.append(draft)
        prompt_input.value = ":search "
        prompt_input.cursor_position = len(prompt_input.value)
        prompt_input.focus()

    def action_edit_last_message(self) -> None:
        """Load the previous prompt back into the input to reword it (Ctrl+P)."""
        log = self._conversation_log()
        if log is None:
            return
        self._edit_last_message(log)

    def action_rewind(self) -> None:
        """Open the transcript/rewind overlay (Ctrl+R)."""
        log = self._conversation_log()
        if log is None:
            return
        self._open_rewind_overlay(log)
