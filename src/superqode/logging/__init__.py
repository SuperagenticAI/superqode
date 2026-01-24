"""
SuperQode Unified Logging System.

Provides consistent logging across all provider modes (ACP, BYOK, Local).
"""

from superqode.logging.unified_log import (
    LogVerbosity,
    LogConfig,
    LogEntry,
    LogKind,
    LogSource,
    UnifiedLogger,
    LogSink,
)
from superqode.logging.formatter import UnifiedLogFormatter
from superqode.logging.sinks import ConversationLogSink, BufferSink, CallbackSink
from superqode.logging.adapters import (
    BYOKAdapter,
    LocalAdapter,
    ACPAdapter,
    create_adapter,
)
from superqode.logging.integration import TUILoggerManager, create_tui_logger

__all__ = [
    # Core
    "LogVerbosity",
    "LogConfig",
    "LogEntry",
    "LogKind",
    "LogSource",
    "UnifiedLogger",
    "LogSink",
    # Formatting
    "UnifiedLogFormatter",
    # Sinks
    "ConversationLogSink",
    "BufferSink",
    "CallbackSink",
    # Adapters
    "BYOKAdapter",
    "LocalAdapter",
    "ACPAdapter",
    "create_adapter",
    # TUI Integration
    "TUILoggerManager",
    "create_tui_logger",
]
