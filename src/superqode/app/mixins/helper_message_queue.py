"""Queued input message enqueue/drain."""

from __future__ import annotations
from textual.widgets import Input
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.app.inputs import SelectionAwareInput


class HelperMessageQueueMixin:
    """Queued input message enqueue/drain."""

    def _enqueue_message(self, text: str) -> None:
        """Deliver a message typed while the agent works.

        Builtin (local/BYOK) runs accept live steering: the message is
        injected between the agent's tool calls and shapes the *current* run.
        Anything else (ACP/codex connections, selection flows) falls back to
        the type-ahead queue that sends when the agent is free.
        """
        pure = getattr(self, "_pure_mode", None)
        if (
            pure is not None
            and not self._in_selection_mode()
            and not getattr(self, "_awaiting_agent_question", False)
        ):
            try:
                if pure.steer(text):
                    try:
                        self.query_one("#prompt-input", SelectionAwareInput).value = ""
                    except Exception:
                        pass
                    try:
                        log = self.query_one("#log", ConversationLog)
                        preview = " ".join(str(text).split())
                        if len(preview) > 70:
                            preview = preview[:67].rstrip() + "..."
                        log.add_info(f"↪ steering the current run: {preview}")
                    except Exception:
                        pass
                    return
            except Exception:
                pass

        if not hasattr(self, "_typeahead_queue"):
            self._typeahead_queue = []
        self._typeahead_queue.append(text)
        try:
            self.query_one("#prompt-input", SelectionAwareInput).value = ""
        except Exception:
            pass
        self._render_queued_input()

    def _clear_message_queue(self, log: ConversationLog | None = None) -> None:
        self._typeahead_queue = []
        self._render_queued_input()
        if log is not None:
            log.add_info("Cleared the queued messages.")

    def _drain_message_queue(self) -> None:
        """Send the next queued message if the agent is idle."""
        queue = getattr(self, "_typeahead_queue", [])
        if not queue or getattr(self, "is_busy", False):
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
