"""
Log Sinks for SuperQode.

Provides different output destinations for log entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from superqode.logging.unified_log import LogConfig, LogEntry
from superqode.logging.formatter import UnifiedLogFormatter

if TYPE_CHECKING:
    from superqode.app.widgets import ConversationLog


class ConversationLogSink:
    """
    Sink that writes to a ConversationLog widget.

    Bridges the new unified logging system with the existing TUI widget.
    """

    def __init__(self, log_widget: "ConversationLog"):
        self.log = log_widget
        self.formatter = UnifiedLogFormatter()
        self._streaming_started = False

    def emit(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit a log entry to the conversation log."""
        self.formatter.config = config

        # Route to appropriate method based on entry kind
        handlers = {
            "thinking": self._emit_thinking,
            "tool_call": self._emit_tool_call,
            "tool_result": self._emit_tool_result,
            "tool_update": self._emit_tool_update,
            "response_delta": self._emit_response_delta,
            "response_final": self._emit_response_final,
            "code_block": self._emit_code_block,
            "info": self._emit_info,
            "warning": self._emit_warning,
            "error": self._emit_error,
            "system": self._emit_system,
            "user": self._emit_user,
            "assistant": self._emit_assistant,
        }

        handler = handlers.get(entry.kind)
        if handler:
            handler(entry, config)

    def _emit_thinking(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit thinking entry."""
        if not config.show_thinking:
            return

        renderable = self.formatter.format(entry)
        if renderable:
            self.log.write(renderable)

    def _emit_tool_call(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit tool call entry."""
        renderable = self.formatter.format(entry)
        if renderable:
            self.log.write(renderable)

    def _emit_tool_result(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit tool result entry."""
        renderable = self.formatter.format(entry)
        if renderable:
            self.log.write(renderable)

    def _emit_tool_update(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit tool update entry."""
        renderable = self.formatter.format(entry)
        if renderable:
            self.log.write(renderable)

    def _emit_response_delta(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit streaming response chunk."""
        # For streaming, just write plain text
        if entry.text:
            from rich.text import Text

            self.log.write(Text(entry.text))
            self._streaming_started = True

    def _emit_response_final(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit final complete response."""
        # If we were streaming, the content is already displayed
        # Just mark streaming as done
        self._streaming_started = False

    def _emit_code_block(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit code block with syntax highlighting."""
        renderable = self.formatter.format(entry)
        if renderable:
            self.log.write(renderable)

    def _emit_info(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit info message."""
        self.log.add_info(entry.text)

    def _emit_warning(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit warning message."""
        from rich.text import Text

        self.log.write(Text(f"  ⚠️ {entry.text}", style="#f59e0b"))

    def _emit_error(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit error message."""
        self.log.add_error(entry.text)

    def _emit_system(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit system message."""
        self.log.add_system(entry.text)

    def _emit_user(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit user message."""
        self.log.add_user(entry.text)

    def _emit_assistant(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit assistant message."""
        self.log.add_agent(entry.text, entry.agent)


class BufferSink:
    """
    Sink that buffers entries for later processing.

    Useful for testing or delayed rendering.
    """

    def __init__(self):
        self.entries: list[LogEntry] = []

    def emit(self, entry: LogEntry, config: LogConfig) -> None:
        """Store entry in buffer."""
        self.entries.append(entry)

    def clear(self) -> None:
        """Clear buffer."""
        self.entries.clear()

    def get_entries(self, kind: Optional[str] = None) -> list[LogEntry]:
        """Get entries, optionally filtered by kind."""
        if kind:
            return [e for e in self.entries if e.kind == kind]
        return self.entries.copy()


class CallbackSink:
    """
    Sink that calls a callback function for each entry.

    Useful for custom handling or bridging to other systems.
    """

    def __init__(self, callback):
        self.callback = callback
        self.formatter = UnifiedLogFormatter()

    def emit(self, entry: LogEntry, config: LogConfig) -> None:
        """Call the callback with the entry."""
        self.formatter.config = config
        renderable = self.formatter.format(entry)
        self.callback(entry, renderable)
