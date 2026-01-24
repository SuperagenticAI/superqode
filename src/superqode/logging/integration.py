"""
TUI Integration for SuperQode Unified Logging.

Provides easy integration with the Textual TUI application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional
import asyncio

from superqode.logging.unified_log import (
    LogConfig,
    LogEntry,
    LogSource,
    LogVerbosity,
    UnifiedLogger,
)
from superqode.logging.sinks import ConversationLogSink
from superqode.logging.adapters import BYOKAdapter, LocalAdapter, ACPAdapter

if TYPE_CHECKING:
    from superqode.app.widgets import ConversationLog


class TUILoggerManager:
    """
    Manages unified logging for the TUI application.

    Provides thread-safe logging callbacks for all provider modes.
    """

    def __init__(
        self,
        log_widget: "ConversationLog",
        source: LogSource = "byok",
        call_from_thread: Optional[Callable] = None,
    ):
        self.log_widget = log_widget
        self.source = source
        self._call_from_thread = call_from_thread

        # Determine config based on source
        self.config = LogConfig.for_source(source)

        # Create logger with sink
        self.logger = UnifiedLogger(config=self.config)
        self.sink = ConversationLogSink(log_widget)
        self.logger.add_sink(self.sink)

        # Create appropriate adapter
        if source == "acp":
            self.adapter = ACPAdapter(self.logger)
        elif source == "local":
            self.adapter = LocalAdapter(self.logger)
        else:
            self.adapter = BYOKAdapter(self.logger)

        # Buffers for ACP mode to accumulate streaming content
        self._thinking_buffer = ""
        self._thinking_flush_task: Optional[asyncio.Task] = None
        self._thinking_flush_delay = 0.15  # Flush after 150ms of no new chunks

    def _safe_emit(self, entry: LogEntry) -> None:
        """Emit entry safely from any thread."""

        def _do_emit():
            if self.logger._should_emit(entry):
                self.sink.emit(entry, self.config)

        if self._call_from_thread:
            try:
                self._call_from_thread(_do_emit)
            except RuntimeError as e:
                if "different thread" in str(e).lower():
                    _do_emit()
                else:
                    raise
        else:
            _do_emit()

    def set_verbosity(self, verbosity: LogVerbosity) -> None:
        """Change verbosity level."""
        self.logger.set_verbosity(verbosity)

    def toggle_thinking(self) -> bool:
        """Toggle thinking display. Returns new state."""
        return self.logger.toggle_thinking()

    def get_byok_callbacks(self) -> dict[str, Callable]:
        """
        Get callbacks for BYOK mode that emit through unified logging.

        Returns dict with: on_tool_call, on_tool_result, on_thinking
        """
        adapter = (
            self.adapter if isinstance(self.adapter, BYOKAdapter) else BYOKAdapter(self.logger)
        )

        def on_tool_call(name: str, args: dict) -> None:
            entry = LogEntry.tool_call(name, args, source="byok")
            self._safe_emit(entry)
            adapter._span_ids[name] = entry.span_id or ""

        def on_tool_result(name: str, result: Any) -> None:
            from superqode.tools.base import ToolResult

            span_id = adapter._span_ids.pop(name, None)

            if isinstance(result, ToolResult):
                success = result.success
                output = str(result.output) if result.output else ""
                if not success and result.error:
                    output = str(result.error)
            else:
                success = True
                output = str(result) if result else ""

            entry = LogEntry.tool_result(name, output, success, source="byok", span_id=span_id)
            self._safe_emit(entry)

        async def on_thinking(text: str) -> None:
            if text and text.strip():
                entry = LogEntry.thinking(text, source="byok")
                self._safe_emit(entry)

        return {
            "on_tool_call": on_tool_call,
            "on_tool_result": on_tool_result,
            "on_thinking": on_thinking,
        }

    def get_local_callbacks(self) -> dict[str, Callable]:
        """
        Get callbacks for Local mode (Ollama, etc.).

        Same as BYOK but with 'local' source for different default config.
        """
        adapter = (
            self.adapter if isinstance(self.adapter, LocalAdapter) else LocalAdapter(self.logger)
        )

        def on_tool_call(name: str, args: dict) -> None:
            entry = LogEntry.tool_call(name, args, source="local")
            self._safe_emit(entry)

        def on_tool_result(name: str, result: Any) -> None:
            from superqode.tools.base import ToolResult

            if isinstance(result, ToolResult):
                success = result.success
                output = str(result.output) if result.output else ""
                if not success and result.error:
                    output = str(result.error)
            else:
                success = True
                output = str(result) if result else ""

            entry = LogEntry.tool_result(name, output, success, source="local")
            self._safe_emit(entry)

        async def on_thinking(text: str) -> None:
            if text and text.strip():
                entry = LogEntry.thinking(text, source="local")
                self._safe_emit(entry)

        return {
            "on_tool_call": on_tool_call,
            "on_tool_result": on_tool_result,
            "on_thinking": on_thinking,
        }

    def _flush_thinking_buffer(self) -> None:
        """Flush accumulated thinking buffer to display."""
        if self._thinking_buffer.strip():
            # Clean ACP prefixes
            clean_text = self._thinking_buffer
            if clean_text.startswith("[agent] "):
                clean_text = clean_text[8:]
            elif clean_text.startswith("["):
                bracket_end = clean_text.find("] ")
                if bracket_end > 0:
                    clean_text = clean_text[bracket_end + 2 :]

            # Only emit if we have meaningful content
            clean_text = clean_text.strip()
            if clean_text:
                entry = LogEntry.thinking(clean_text, source="acp")
                self._safe_emit(entry)

        self._thinking_buffer = ""
        self._thinking_flush_task = None

    async def _schedule_thinking_flush(self) -> None:
        """Schedule a flush after delay if no new chunks arrive."""
        await asyncio.sleep(self._thinking_flush_delay)
        self._flush_thinking_buffer()

    def get_acp_callbacks(self) -> dict[str, Callable]:
        """
        Get callbacks for ACP mode.

        Returns dict with: on_message, on_thinking, on_tool_call, on_tool_update
        """
        adapter = self.adapter if isinstance(self.adapter, ACPAdapter) else ACPAdapter(self.logger)

        async def on_message(text: str) -> None:
            if text:
                adapter._message_buffer += text
                entry = LogEntry.response(text, source="acp", agent="Agent", is_final=False)
                self._safe_emit(entry)

        async def on_thinking(text: str) -> None:
            """Buffer thinking chunks and emit complete thoughts."""
            if not text:
                return

            # Add to buffer
            self._thinking_buffer += text

            # Cancel any pending flush
            if self._thinking_flush_task and not self._thinking_flush_task.done():
                self._thinking_flush_task.cancel()

            # Check if we have a natural break point (sentence end, newline)
            if self._thinking_buffer.rstrip().endswith((".", "!", "?", "\n", ":", ";")):
                # Flush immediately on sentence boundaries
                self._flush_thinking_buffer()
            else:
                # Schedule delayed flush
                try:
                    self._thinking_flush_task = asyncio.create_task(self._schedule_thinking_flush())
                except RuntimeError:
                    # No event loop - flush immediately
                    self._flush_thinking_buffer()

        async def on_tool_call(tool_call: dict) -> None:
            # Flush any pending thinking before tool call
            if self._thinking_buffer:
                self._flush_thinking_buffer()

            title = tool_call.get("title", "tool")
            raw_input = tool_call.get("rawInput", {})
            tool_call_id = tool_call.get("toolCallId", "")

            entry = LogEntry.tool_call(title, raw_input, source="acp")
            if tool_call_id:
                adapter._span_ids[tool_call_id] = entry.span_id or ""
            self._safe_emit(entry)

        async def on_tool_update(update: dict) -> None:
            status = update.get("status", "")
            tool_call_id = update.get("toolCallId", "")
            output = update.get("rawOutput") or update.get("output") or update.get("result")
            title = update.get("title", "tool")

            span_id = adapter._span_ids.get(tool_call_id)

            if status in ("completed", "done", "success"):
                entry = LogEntry.tool_result(
                    title, str(output) if output else "", True, source="acp", span_id=span_id
                )
                self._safe_emit(entry)
            elif status in ("error", "failed"):
                entry = LogEntry.tool_result(
                    title, str(output) if output else "failed", False, source="acp", span_id=span_id
                )
                self._safe_emit(entry)

        return {
            "on_message": on_message,
            "on_thinking": on_thinking,
            "on_tool_call": on_tool_call,
            "on_tool_update": on_tool_update,
        }

    def log_thinking(self, text: str, category: str = "general") -> None:
        """Log a thinking entry."""
        entry = LogEntry.thinking(text, source=self.source, category=category)
        self._safe_emit(entry)

    def log_tool_call(self, name: str, args: dict) -> str:
        """Log a tool call. Returns span_id."""
        entry = LogEntry.tool_call(name, args, source=self.source)
        self._safe_emit(entry)
        return entry.span_id or ""

    def log_tool_result(
        self, name: str, result: Any, success: bool = True, span_id: Optional[str] = None
    ) -> None:
        """Log a tool result."""
        entry = LogEntry.tool_result(
            name, str(result), success, source=self.source, span_id=span_id
        )
        self._safe_emit(entry)

    def log_response_chunk(self, text: str, agent: str = "Assistant") -> None:
        """Log a response chunk."""
        entry = LogEntry.response(text, source=self.source, agent=agent, is_final=False)
        self._safe_emit(entry)

    def log_info(self, text: str) -> None:
        """Log an info message."""
        entry = LogEntry.info(text, source=self.source)
        self._safe_emit(entry)

    def log_error(self, text: str) -> None:
        """Log an error message."""
        entry = LogEntry.error(text, source=self.source)
        self._safe_emit(entry)

    def log_code_block(self, code: str, language: str = "") -> None:
        """Log a code block with syntax highlighting."""
        entry = LogEntry.code_block(code, language, source=self.source)
        self._safe_emit(entry)


def create_tui_logger(
    log_widget: "ConversationLog",
    source: LogSource = "byok",
    call_from_thread: Optional[Callable] = None,
    verbosity: Optional[LogVerbosity] = None,
) -> TUILoggerManager:
    """
    Create a TUI logger manager for the given source.

    Args:
        log_widget: The ConversationLog widget to write to
        source: The provider source ("acp", "byok", or "local")
        call_from_thread: Optional thread-safe call function (e.g., app.call_from_thread)
        verbosity: Optional verbosity override

    Returns:
        TUILoggerManager configured for the source
    """
    manager = TUILoggerManager(log_widget, source, call_from_thread)

    if verbosity:
        manager.set_verbosity(verbosity)

    return manager
