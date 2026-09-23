"""Queued input message enqueue/drain."""

from __future__ import annotations
from textual.widgets import Input
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.app.inputs import SelectionAwareInput


class HelperMessageQueueMixin:
    """Queued input message enqueue/drain."""

    def _steer_message(self, text: str, log: ConversationLog) -> bool:
        """Explicitly send to the current run; never silently queue instead."""
        if not text.strip():
            log.add_info("Use :steer <message> while a supported agent is running.")
            return False
        if not getattr(self, "is_busy", False):
            log.add_info("No run is active. Press Enter to send a new message.")
            self._set_prompt_prefill(text)
            return False
        pure = getattr(self, "_pure_mode", None)
        if (
            pure is not None
            and not self._in_selection_mode()
            and not getattr(self, "_awaiting_agent_question", False)
        ):
            try:
                if pure.steer(text):
                    preview = " ".join(str(text).split())
                    if len(preview) > 70:
                        preview = preview[:67].rstrip() + "..."
                    log.add_info(f"↪ steering the current run: {preview}")
                    return True
            except Exception:
                pass
        log.add_warning("This agent cannot accept live steering. Use :queue add <message> instead.")
        self._set_prompt_prefill(text)
        return False

    def _enqueue_message(self, text: str, *, replace_edit: bool = True) -> None:
        """Send after the current run; Enter never changes the current run."""
        if not hasattr(self, "_typeahead_queue"):
            self._typeahead_queue = []
        edit_index = getattr(self, "_queue_edit_index", None)
        if (
            replace_edit
            and isinstance(edit_index, int)
            and 0 <= edit_index < len(self._typeahead_queue)
        ):
            self._typeahead_queue[edit_index] = text
            self._queue_edit_index = None
            if not getattr(self, "is_busy", False):
                self._drain_message_queue()
        else:
            self._typeahead_queue.append(text)
        try:
            self.query_one("#prompt-input", SelectionAwareInput).value = ""
        except Exception:
            pass
        self._render_queued_input()

    def _clear_message_queue(self, log: ConversationLog | None = None) -> None:
        self._typeahead_queue = []
        self._queue_edit_index = None
        self._render_queued_input()
        if log is not None:
            log.add_info("Cleared the queued messages.")

    def _drain_message_queue(self) -> None:
        """Send the next queued message if the agent is idle."""
        queue = getattr(self, "_typeahead_queue", [])
        if not queue or getattr(self, "is_busy", False):
            return
        if getattr(self, "_queue_edit_index", None) is not None:
            return
        # Don't interrupt selection/question flows.
        if getattr(self, "_awaiting_agent_question", False) or self._in_selection_mode():
            return
        text = queue.pop(0)
        self._render_queued_input()
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.value = text
            self.post_message(Input.Submitted(input_widget, text))
        except Exception:
            pass
