"""
Unified Logging Core for SuperQode.

Provides structured log entries and a unified logger that works consistently
across all provider modes (ACP, BYOK, Local/Ollama).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any, Callable, Literal, Optional, Protocol
import uuid


class LogVerbosity(str, Enum):
    """Log verbosity levels."""

    MINIMAL = "minimal"  # Just status, no content
    NORMAL = "normal"  # Summarized content
    VERBOSE = "verbose"  # Full content (with truncation limits)


LogKind = Literal[
    "user",
    "assistant",
    "thinking",
    "tool_call",
    "tool_update",
    "tool_result",
    "info",
    "warning",
    "error",
    "system",
    "response_delta",
    "response_final",
    "code_block",
]

LogSource = Literal["acp", "byok", "local", "system"]


@dataclass
class LogConfig:
    """Configuration for log display behavior."""

    verbosity: LogVerbosity = LogVerbosity.NORMAL
    show_thinking: bool = True
    show_tool_args: bool = True
    show_tool_result: bool = True
    max_tool_output_chars: int = 2000
    max_thinking_chars: int = 500
    syntax_highlight: bool = True
    code_theme: str = "github-dark"

    @classmethod
    def minimal(cls) -> LogConfig:
        """Create minimal verbosity config."""
        return cls(
            verbosity=LogVerbosity.MINIMAL,
            show_thinking=False,
            show_tool_args=False,
            show_tool_result=False,
        )

    @classmethod
    def normal(cls) -> LogConfig:
        """Create normal verbosity config."""
        return cls(
            verbosity=LogVerbosity.NORMAL,
            show_thinking=True,
            show_tool_args=True,
            show_tool_result=True,
            max_tool_output_chars=200,
        )

    @classmethod
    def verbose(cls) -> LogConfig:
        """Create verbose config."""
        return cls(
            verbosity=LogVerbosity.VERBOSE,
            show_thinking=True,
            show_tool_args=True,
            show_tool_result=True,
            max_tool_output_chars=2000,
        )

    @classmethod
    def for_source(cls, source: LogSource) -> LogConfig:
        """Get recommended config for a source type."""
        if source == "local":
            # Local models can be verbose, default to less thinking display
            return cls(
                verbosity=LogVerbosity.NORMAL,
                show_thinking=False,  # Toggle with Ctrl+T
                show_tool_args=True,
                show_tool_result=True,
                max_tool_output_chars=500,
            )
        elif source == "acp":
            return cls(
                verbosity=LogVerbosity.NORMAL,
                show_thinking=True,
                show_tool_args=True,
                show_tool_result=True,
            )
        else:  # byok
            return cls.normal()


@dataclass
class LogEntry:
    """
    A structured log entry.

    This is the single source of truth for all log events across providers.
    """

    kind: LogKind
    source: LogSource
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    agent: str = "Assistant"
    ts: float = field(default_factory=monotonic)
    span_id: Optional[str] = None
    level: int = 0  # 0=always, 1=normal+verbose, 2=verbose only

    def __post_init__(self):
        if self.span_id is None and self.kind in ("tool_call", "tool_update", "tool_result"):
            self.span_id = str(uuid.uuid4())[:8]

    @property
    def tool_name(self) -> str:
        """Get tool name from data."""
        return self.data.get("tool_name", "")

    @property
    def tool_args(self) -> dict:
        """Get tool arguments from data."""
        return self.data.get("args", {})

    @property
    def tool_result_text(self) -> str:
        """Get tool result text from data."""
        return str(self.data.get("result", ""))

    @property
    def is_success(self) -> bool:
        """Check if tool result was successful."""
        return self.data.get("ok", True)

    @property
    def file_path(self) -> str:
        """Extract file path from tool args."""
        args = self.tool_args
        return args.get("path", args.get("file_path", args.get("filePath", "")))

    @property
    def command(self) -> str:
        """Extract command from tool args."""
        return self.tool_args.get("command", "")

    @classmethod
    def thinking(
        cls,
        text: str,
        source: LogSource = "byok",
        category: str = "general",
    ) -> LogEntry:
        """Create a thinking log entry."""
        return cls(
            kind="thinking",
            source=source,
            text=text,
            data={"category": category},
        )

    @classmethod
    def tool_call(
        cls,
        name: str,
        args: dict,
        source: LogSource = "byok",
        span_id: Optional[str] = None,
    ) -> LogEntry:
        """Create a tool call log entry."""
        return cls(
            kind="tool_call",
            source=source,
            text=f"Calling {name}",
            data={"tool_name": name, "args": args},
            span_id=span_id or str(uuid.uuid4())[:8],
        )

    @classmethod
    def tool_result(
        cls,
        name: str,
        result: Any,
        success: bool = True,
        source: LogSource = "byok",
        span_id: Optional[str] = None,
    ) -> LogEntry:
        """Create a tool result log entry."""
        result_text = str(result) if result else ""
        return cls(
            kind="tool_result",
            source=source,
            text=f"{name} {'completed' if success else 'failed'}",
            data={"tool_name": name, "result": result_text, "ok": success},
            span_id=span_id,
        )

    @classmethod
    def response(
        cls,
        text: str,
        source: LogSource = "byok",
        agent: str = "Assistant",
        is_final: bool = False,
    ) -> LogEntry:
        """Create a response log entry."""
        return cls(
            kind="response_final" if is_final else "response_delta",
            source=source,
            text=text,
            agent=agent,
        )

    @classmethod
    def code_block(
        cls,
        code: str,
        language: str = "",
        source: LogSource = "local",
    ) -> LogEntry:
        """Create a code block log entry for proper syntax highlighting."""
        return cls(
            kind="code_block",
            source=source,
            text=code,
            data={"language": language},
        )

    @classmethod
    def info(cls, text: str, source: LogSource = "system") -> LogEntry:
        """Create an info log entry."""
        return cls(kind="info", source=source, text=text)

    @classmethod
    def error(cls, text: str, source: LogSource = "system") -> LogEntry:
        """Create an error log entry."""
        return cls(kind="error", source=source, text=text)

    @classmethod
    def warning(cls, text: str, source: LogSource = "system") -> LogEntry:
        """Create a warning log entry."""
        return cls(kind="warning", source=source, text=text)


class LogSink(Protocol):
    """Protocol for log output destinations."""

    def emit(self, entry: LogEntry, config: LogConfig) -> None:
        """Emit a log entry."""
        ...


class UnifiedLogger:
    """
    Unified logger that routes events to sinks based on configuration.

    This is the central routing point for all log events across providers.
    """

    def __init__(
        self,
        config: Optional[LogConfig] = None,
        sink: Optional[LogSink] = None,
    ):
        self.config = config or LogConfig.normal()
        self._sinks: list[LogSink] = []
        if sink:
            self._sinks.append(sink)
        self._buffer: list[LogEntry] = []
        self._response_buffer: str = ""
        self._on_entry: Optional[Callable[[LogEntry], None]] = None

    def add_sink(self, sink: LogSink) -> None:
        """Add a log sink."""
        self._sinks.append(sink)

    def remove_sink(self, sink: LogSink) -> None:
        """Remove a log sink."""
        if sink in self._sinks:
            self._sinks.remove(sink)

    def set_verbosity(self, verbosity: LogVerbosity) -> None:
        """Change verbosity level."""
        self.config.verbosity = verbosity
        if verbosity == LogVerbosity.MINIMAL:
            self.config.show_thinking = False
            self.config.show_tool_args = False
            self.config.show_tool_result = False
        elif verbosity == LogVerbosity.NORMAL:
            self.config.show_thinking = True
            self.config.show_tool_args = True
            self.config.show_tool_result = True
            self.config.max_tool_output_chars = 200
        else:  # verbose
            self.config.show_thinking = True
            self.config.show_tool_args = True
            self.config.show_tool_result = True
            self.config.max_tool_output_chars = 2000

    def toggle_thinking(self) -> bool:
        """Toggle thinking display. Returns new state."""
        self.config.show_thinking = not self.config.show_thinking
        return self.config.show_thinking

    def _should_emit(self, entry: LogEntry) -> bool:
        """Check if entry should be emitted based on config."""
        # Check verbosity level
        if entry.level == 2 and self.config.verbosity != LogVerbosity.VERBOSE:
            return False
        if entry.level == 1 and self.config.verbosity == LogVerbosity.MINIMAL:
            return False

        # Check thinking filter
        if entry.kind == "thinking" and not self.config.show_thinking:
            return False

        return True

    def log(self, entry: LogEntry) -> None:
        """Log an entry to all sinks."""
        self._buffer.append(entry)

        if self._on_entry:
            self._on_entry(entry)

        if not self._should_emit(entry):
            return

        for sink in self._sinks:
            try:
                sink.emit(entry, self.config)
            except Exception:
                pass  # Don't let sink errors crash logging

    def thinking(self, text: str, source: LogSource = "byok", category: str = "general") -> None:
        """Log a thinking entry."""
        self.log(LogEntry.thinking(text, source, category))

    def tool_call(
        self,
        name: str,
        args: dict,
        source: LogSource = "byok",
        span_id: Optional[str] = None,
    ) -> str:
        """Log a tool call. Returns span_id for correlation."""
        entry = LogEntry.tool_call(name, args, source, span_id)
        self.log(entry)
        return entry.span_id or ""

    def tool_result(
        self,
        name: str,
        result: Any,
        success: bool = True,
        source: LogSource = "byok",
        span_id: Optional[str] = None,
    ) -> None:
        """Log a tool result."""
        self.log(LogEntry.tool_result(name, result, success, source, span_id))

    def response_chunk(
        self, text: str, source: LogSource = "byok", agent: str = "Assistant"
    ) -> None:
        """Log a response chunk (streaming)."""
        self._response_buffer += text
        self.log(LogEntry.response(text, source, agent, is_final=False))

    def response_complete(self, source: LogSource = "byok", agent: str = "Assistant") -> str:
        """Complete response streaming. Returns full response."""
        full_response = self._response_buffer
        if full_response:
            self.log(LogEntry.response(full_response, source, agent, is_final=True))
        self._response_buffer = ""
        return full_response

    def code_block(self, code: str, language: str = "", source: LogSource = "local") -> None:
        """Log a code block with syntax highlighting."""
        self.log(LogEntry.code_block(code, language, source))

    def info(self, text: str) -> None:
        """Log info message."""
        self.log(LogEntry.info(text))

    def error(self, text: str) -> None:
        """Log error message."""
        self.log(LogEntry.error(text))

    def warning(self, text: str) -> None:
        """Log warning message."""
        self.log(LogEntry.warning(text))

    def get_history(self) -> list[LogEntry]:
        """Get log history."""
        return self._buffer.copy()

    def clear(self) -> None:
        """Clear log history."""
        self._buffer.clear()
        self._response_buffer = ""
