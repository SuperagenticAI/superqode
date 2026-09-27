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
    # None follows the active TUI theme; callers may still pin a Pygments theme.
    code_theme: str | None = None

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


def tool_result_parts(result: Any) -> tuple[str, bool, int, int]:
    """Split a tool result into (output, success, diff_add, diff_del).

    Shared by the BYOK/Local adapters and the TUI manager callbacks so
    native-harness paths (including subscription models served through the
    BYOK gateway) all forward diff stats identically.
    """
    from superqode.tools.base import ToolResult

    if isinstance(result, ToolResult):
        output = str(result.output) if result.output else ""
        if not result.success and result.error:
            output = str(result.error)
        try:
            diff_add = int(result.metadata.get("additions", 0) or 0)
            diff_del = int(result.metadata.get("deletions", 0) or 0)
        except (TypeError, ValueError, AttributeError):
            diff_add, diff_del = 0, 0
        return (output, result.success, diff_add, diff_del)
    return (str(result) if result else "", True, 0, 0)


def acp_diff_stats(update: dict) -> tuple[int, int]:
    """Count (additions, deletions) from an ACP tool update's diff content.

    Compares oldText/newText per diff block with difflib; skips oversized
    payloads (>200KB) to keep the log path cheap. Returns (0, 0) when no
    diff content is present.
    """
    import difflib

    try:
        content = update.get("content") or []
        total_add = 0
        total_del = 0
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "diff":
                continue
            old = block.get("oldText") or ""
            new = block.get("newText") or ""
            if len(old) + len(new) > 200_000:
                continue
            diff_lines = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="")
            # The first two emitted lines are file headers. Skipping by position
            # preserves real source lines beginning with "+++" or "---".
            next(diff_lines, None)
            next(diff_lines, None)
            for line in diff_lines:
                if line.startswith("+"):
                    total_add += 1
                elif line.startswith("-"):
                    total_del += 1
        return (total_add, total_del)
    except Exception:
        return (0, 0)


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
        args = self.data.get("args", {})
        return args if isinstance(args, dict) else {}

    @property
    def tool_result_text(self) -> str:
        """Get tool result text from data."""
        return str(self.data.get("result", ""))

    @property
    def is_success(self) -> bool:
        """Check if tool result was successful."""
        return self.data.get("ok", True)

    @property
    def diff_stats(self) -> tuple[int, int] | None:
        """Return (additions, deletions) if the entry carries diff stats."""
        try:
            add = int(self.data.get("diff_add", 0) or 0)
            dele = int(self.data.get("diff_del", 0) or 0)
        except (TypeError, ValueError):
            return None
        if add <= 0 and dele <= 0:
            return None
        return (add, dele)

    @property
    def file_path(self) -> str:
        """Extract file path from tool args (supports native + ACP key names)."""
        args = self.tool_args
        for key in ("path", "file_path", "filePath", "file", "filename", "target_file", "filepath"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val
        uri = args.get("uri", "")
        if isinstance(uri, str) and uri.strip():
            return uri[7:] if uri.startswith("file://") else uri
        # ACP agents report edited files via locations instead of rawInput
        try:
            locations = self.data.get("locations") or []
            if locations and isinstance(locations[0], dict):
                loc_path = locations[0].get("path", "")
                if isinstance(loc_path, str) and loc_path.strip():
                    return loc_path
        except (AttributeError, IndexError, TypeError):
            pass
        return ""

    @property
    def command(self) -> str:
        """Extract command from tool args (supports native + ACP key names)."""
        args = self.tool_args
        for key in ("command", "cmd", "script", "bash_command", "shell_command"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return ""

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
        extra: Optional[dict] = None,
    ) -> LogEntry:
        """Create a tool call log entry."""
        data: dict[str, Any] = {"tool_name": name, "args": args}
        if extra:
            data.update(extra)
        return cls(
            kind="tool_call",
            source=source,
            text=f"Calling {name}",
            data=data,
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
        diff_add: int = 0,
        diff_del: int = 0,
    ) -> LogEntry:
        """Create a tool result log entry."""
        result_text = str(result) if result else ""
        data: dict[str, Any] = {"tool_name": name, "result": result_text, "ok": success}
        if diff_add > 0 or diff_del > 0:
            data["diff_add"] = diff_add
            data["diff_del"] = diff_del
        return cls(
            kind="tool_result",
            source=source,
            text=f"{name} {'completed' if success else 'failed'}",
            data=data,
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
        extra: Optional[dict[str, Any]] = None,
    ) -> str:
        """Log a tool call. Returns span_id for correlation."""
        entry = LogEntry.tool_call(name, args, source, span_id, extra)
        self.log(entry)
        return entry.span_id or ""

    def tool_result(
        self,
        name: str,
        result: Any,
        success: bool = True,
        source: LogSource = "byok",
        span_id: Optional[str] = None,
        diff_add: int = 0,
        diff_del: int = 0,
    ) -> None:
        """Log a tool result."""
        self.log(LogEntry.tool_result(name, result, success, source, span_id, diff_add, diff_del))

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
