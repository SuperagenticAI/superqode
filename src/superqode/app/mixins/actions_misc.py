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

    def action_copy_response(self):
        """Copy last agent response to clipboard (Ctrl+Shift+C)."""
        log = self.query_one("#log", ConversationLog)
        self._handle_copy(log)
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
        self._cancel_requested = True
        provider, model = self._active_local_provider_model()

        if self._acp_client is not None:
            try:
                if self._acp_loop_runner is not None:
                    self._acp_loop_runner.run(self._acp_client.cancel(), timeout=1.0)
                else:
                    asyncio.create_task(self._acp_client.cancel())
            except Exception:
                pass
            try:
                process = getattr(self._acp_client, "_process", None)
                if process is not None and process.returncode is None:
                    process.terminate()
            except Exception:
                pass
            log.add_info("🛑 Cancelling ACP agent operation...")
            self._stop_stream_animation()
            self._stop_thinking()
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
            self._cancel_requested = True
            log.add_info("🛑 Cancel requested...")

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
    def action_rewind(self) -> None:
        """Open the transcript/rewind overlay (Ctrl+R)."""
        log = self._conversation_log()
        if log is None:
            return
        self._open_rewind_overlay(log)
