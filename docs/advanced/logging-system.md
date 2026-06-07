# SuperQode Unified Logging System

The logging module provides consistent logging across all provider modes (ACP, BYOK, Local) with a pluggable sink architecture.

## Overview

The unified logging system routes agent events through adapters into a central UnifiedLogger that fans out to multiple sinks. Each sink formats and displays entries according to the active verbosity level.

```
Agent Event -> Adapter -> UnifiedLogger -> LogEntry -> Sink (formatted output)
```

## Core API

### LogConfig

Configuration object that controls log filtering and display behavior.

Fields:

| Field | Type | Description |
|---|---|---|
| verbosity | LogVerbosity | MINIMAL, NORMAL, or VERBOSE |
| show_thinking | bool | Show thinking/chain-of-thought entries |
| show_tool_args | bool | Show tool call arguments |
| show_tool_result | bool | Show tool call results |
| max_tool_output_chars | int | Truncation limit for tool output (default 2000) |
| max_thinking_chars | int | Truncation limit for thinking text (default 500) |
| syntax_highlight | bool | Enable syntax highlighting in code blocks |
| code_theme | str | Pygments theme for code highlighting (default "github-dark") |

Factory methods:

- `LogConfig.minimal()` -- Returns config with MINIMAL verbosity, only errors and warnings.
- `LogConfig.normal()` -- Returns config with NORMAL verbosity, default display settings.
- `LogConfig.verbose()` -- Returns config with VERBOSE verbosity, all display flags enabled, maximum character limits.
- `LogConfig.for_source(source)` -- Returns recommended config for the given provider source string ("local", "acp", or "byok").

### LogEntry

The structured log record that flows through the system. Immutable after creation.

Fields: `kind`, `source`, `text`, `data`, `agent`, `ts`, `span_id`, `level`.

Factory methods:

| Method | Description |
|---|---|
| `thinking()` | Creates a thinking/chain-of-thought entry |
| `tool_call()` | Creates a tool invocation entry |
| `tool_result()` | Creates a tool result entry |
| `response()` | Creates an assistant response entry |
| `code_block()` | Creates a code block entry with language metadata |
| `info()` | Creates an informational entry |
| `error()` | Creates an error entry |
| `warning()` | Creates a warning entry |

LogKind types: `user`, `assistant`, `thinking`, `tool_call`, `tool_update`, `tool_result`, `info`, `warning`, `error`, `system`, `response_delta`, `response_final`, `code_block`.

LogSource types: `acp`, `byok`, `local`, `system`.

### UnifiedLogger

Core routing class that gathers events and routes to registered sinks.

Key methods:

| Method | Description |
|---|---|
| `add_sink(sink)` | Register a new sink |
| `remove_sink(sink)` | Unregister a sink |
| `set_verbosity(level)` | Change the active verbosity level |
| `toggle_thinking()` | Toggle show_thinking on/off |
| `log(entry)` | Log a pre-built LogEntry |
| `thinking(text, category)` | Log a thinking entry, returns the entry |
| `tool_call(name, args)` | Log a tool call, returns a span_id |
| `tool_result(name, result, success, span_id)` | Log a tool result |
| `response_chunk(text)` | Log a partial response delta |
| `response_complete(text)` | Log a final response |
| `code_block(code, language)` | Log a code block |
| `info(text)` | Log an info message |
| `error(text)` | Log an error message |
| `warning(text)` | Log a warning message |
| `get_history()` | Return all logged entries |
| `clear()` | Clear all entries from history |

### LogSink Protocol

Any object that implements the sink interface can receive log entries.

```python
class LogSink(Protocol):
    def emit(self, entry: LogEntry, config: LogConfig) -> None: ...
```

## Adapters

Bridge provider-specific callback interfaces into the logging system.

- **BYOKAdapter**: Converts LiteLLM gateway callbacks to log entries. Maps LiteLLM stream events (message, tool_calls, content_block) to LogEntry kinds.
- **LocalAdapter**: Converts local provider streaming callbacks (ollama, openai-compatible) to log entries.
- **ACPAdapter**: Converts ACP protocol callbacks with intelligent thinking buffering. Uses a 150ms debounce to coalesce rapid thinking token updates into single entries.

```python
from superqode.logging import create_adapter

adapter = create_adapter(logger, source="byok")
# adapter exposes source-specific callback methods
```

## Sinks

- **ConversationLogSink**: Writes to the TUI ConversationLog RichText widget. Handles all LogKind types with appropriate Rich formatting (color, panels, syntax highlighting). This is the primary sink used in the terminal UI.
- **BufferSink**: In-memory buffer for testing or deferred processing. Methods: `clear()`, `get_entries(kind)` to filter by LogKind.
- **CallbackSink**: Calls a user-provided callback with `(entry, renderable)` tuple. The renderable is the Rich formatted object. Useful for custom handling, forwarding, or integration with external logging systems.

## TUI Integration

`TUILoggerManager` manages logging for the Textual TUI application. It wraps a UnifiedLogger and provides thread-safe callbacks via `app.call_from_thread` to ensure UI updates happen on the correct event loop.

```python
from superqode.logging import create_tui_logger, LogVerbosity

# Inside a Textual app
self.logger_manager = create_tui_logger(
    log_widget=self.query_one(ConversationLog),
    source="byok",
    call_from_thread=self.call_from_thread,
    verbosity=LogVerbosity.NORMAL,
)
callbacks = self.logger_manager.get_byok_callbacks()
```

## Formatting

`UnifiedLogFormatter` converts LogEntry objects into Rich renderables. Each LogKind receives distinct formatting:

- **thinking**: emoji icon + category label + italic muted text. Verbose prefix stripping applied.
- **tool_call**: action verb display with color coding. Shows file path, command, or argument depending on tool type.
- **tool_result**: status icon (checkmark/cross) + tool name. Intelligent JSON formatting for structured results including todo lists, file results, task lists, error results, and plan entries.
- **code_block**: `rich.Syntax` with line numbers and the configured code theme.
- **info/warning/error/system**: plain text with emoji prefix and color appropriate to severity.
- **user/assistant**: `rich.Panel` with colored borders (user blue, assistant green).

## Basic Usage

```python
from superqode.logging import UnifiedLogger, LogConfig, BufferSink, CallbackSink

logger = UnifiedLogger(config=LogConfig.verbose())
logger.add_sink(BufferSink())
logger.add_sink(CallbackSink(lambda entry, renderable: print(renderable)))

logger.thinking("Analyzing the request...", category="analyzing")
span_id = logger.tool_call("read_file", {"path": "/foo.py"})
logger.tool_result("read_file", "content", success=True, span_id=span_id)
```

```python
from superqode.logging import create_tui_logger, LogVerbosity

# Inside Textual app
self.logger_manager = create_tui_logger(
    log_widget=self.query_one(ConversationLog),
    source="byok",
    call_from_thread=self.call_from_thread,
    verbosity=LogVerbosity.NORMAL,
)
callbacks = self.logger_manager.get_byok_callbacks()
```
