"""
Provider Adapters for SuperQode Unified Logging.

These adapters bridge existing callback interfaces to the unified logging system.
Each adapter converts provider-specific events into LogEntry objects.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING
import asyncio

from superqode.logging.unified_log import LogEntry, LogSource, UnifiedLogger

if TYPE_CHECKING:
    from superqode.tools.base import ToolResult


class BYOKAdapter:
    """
    Adapter for BYOK (LiteLLM Gateway) mode.

    Bridges on_tool_call, on_tool_result, and on_thinking callbacks
    to the unified logging system.
    """

    def __init__(self, logger: UnifiedLogger):
        self.logger = logger
        self._span_ids: dict[str, str] = {}  # tool_name -> span_id

    def on_tool_call(self, name: str, args: dict) -> None:
        """Handle tool call - emit to unified logger."""
        span_id = self.logger.tool_call(name, args, source="byok")
        self._span_ids[name] = span_id

    def on_tool_result(self, name: str, result: Any) -> None:
        """Handle tool result - emit to unified logger."""
        from superqode.tools.base import ToolResult

        span_id = self._span_ids.pop(name, None)

        if isinstance(result, ToolResult):
            success = result.success
            output = str(result.output) if result.output else ""
            if not success and result.error:
                output = str(result.error)
        else:
            success = True
            output = str(result) if result else ""

        self.logger.tool_result(name, output, success, source="byok", span_id=span_id)

    async def on_thinking_async(self, text: str) -> None:
        """Handle thinking text - emit to unified logger."""
        if text and text.strip():
            self.logger.thinking(text, source="byok")

    def on_thinking_sync(self, text: str) -> None:
        """Synchronous thinking handler."""
        if text and text.strip():
            self.logger.thinking(text, source="byok")

    def get_callbacks(self) -> dict[str, Callable]:
        """Get callback functions for use with pure_mode."""
        return {
            "on_tool_call": self.on_tool_call,
            "on_tool_result": self.on_tool_result,
            "on_thinking": self.on_thinking_async,
        }


class LocalAdapter:
    """
    Adapter for Local models (Ollama, etc.).

    Handles streaming responses with code block detection and formatting.
    """

    def __init__(self, logger: UnifiedLogger):
        self.logger = logger
        self._response_buffer = ""
        self._in_code_block = False
        self._code_language = ""
        self._code_buffer = ""

    def on_tool_call(self, name: str, args: dict) -> None:
        """Handle tool call."""
        self.logger.tool_call(name, args, source="local")

    def on_tool_result(self, name: str, result: Any) -> None:
        """Handle tool result."""
        from superqode.tools.base import ToolResult

        if isinstance(result, ToolResult):
            self.logger.tool_result(
                name,
                str(result.output) if result.output else "",
                result.success,
                source="local",
            )
        else:
            self.logger.tool_result(name, str(result), True, source="local")

    async def on_thinking_async(self, text: str) -> None:
        """Handle thinking text."""
        if text and text.strip():
            self.logger.thinking(text, source="local")

    def on_response_chunk(self, text: str) -> None:
        """Handle streaming response chunk with code detection."""
        if not text:
            return

        self._response_buffer += text
        self.logger.response_chunk(text, source="local")

    def on_response_complete(self) -> str:
        """Complete response and return full text."""
        response = self._response_buffer
        self._response_buffer = ""
        self.logger.response_complete(source="local")
        return response

    def get_callbacks(self) -> dict[str, Callable]:
        """Get callback functions."""
        return {
            "on_tool_call": self.on_tool_call,
            "on_tool_result": self.on_tool_result,
            "on_thinking": self.on_thinking_async,
        }


class ACPAdapter:
    """
    Adapter for ACP (Agent Client Protocol) mode.

    Bridges ACP session updates to the unified logging system.
    """

    def __init__(self, logger: UnifiedLogger):
        self.logger = logger
        self._span_ids: dict[str, str] = {}  # tool_call_id -> span_id
        self._message_buffer = ""

    async def on_message(self, text: str) -> None:
        """Handle agent message chunks."""
        if text:
            self._message_buffer += text
            self.logger.response_chunk(text, source="acp", agent="Agent")

    async def on_thinking(self, text: str) -> None:
        """Handle agent thinking."""
        if text and text.strip():
            # ACP thinking often comes with prefixes like [agent], strip them
            clean_text = text
            if clean_text.startswith("[agent] "):
                clean_text = clean_text[8:]
            elif clean_text.startswith("["):
                # Remove other prefixes like [startup error], [model switch error], etc.
                bracket_end = clean_text.find("] ")
                if bracket_end > 0:
                    clean_text = clean_text[bracket_end + 2 :]

            self.logger.thinking(clean_text, source="acp")

    async def on_tool_call(self, tool_call: dict) -> None:
        """Handle ACP tool call."""
        title = tool_call.get("title", "tool")
        raw_input = tool_call.get("rawInput", {})
        tool_call_id = tool_call.get("toolCallId", "")

        span_id = self.logger.tool_call(title, raw_input, source="acp")
        if tool_call_id:
            self._span_ids[tool_call_id] = span_id

    async def on_tool_update(self, update: dict) -> None:
        """Handle ACP tool update."""
        status = update.get("status", "")
        tool_call_id = update.get("toolCallId", "")
        output = update.get("rawOutput") or update.get("output") or update.get("result")

        span_id = self._span_ids.get(tool_call_id)
        title = update.get("title", "tool")

        if status in ("completed", "done", "success"):
            self.logger.tool_result(
                title, str(output) if output else "", True, source="acp", span_id=span_id
            )
        elif status in ("error", "failed"):
            self.logger.tool_result(
                title, str(output) if output else "failed", False, source="acp", span_id=span_id
            )

    def on_session_complete(self) -> str:
        """Complete session and return full message."""
        message = self._message_buffer
        self._message_buffer = ""
        self.logger.response_complete(source="acp", agent="Agent")
        return message

    def get_callbacks(self) -> dict[str, Callable]:
        """Get callback functions for use with ACPClient."""
        return {
            "on_message": self.on_message,
            "on_thinking": self.on_thinking,
        }


def create_adapter(
    logger: UnifiedLogger,
    source: LogSource,
) -> BYOKAdapter | LocalAdapter | ACPAdapter:
    """Create an adapter for the given source."""
    if source == "acp":
        return ACPAdapter(logger)
    elif source == "local":
        return LocalAdapter(logger)
    else:
        return BYOKAdapter(logger)
