"""Shared type aliases for the PiPy harness."""

from __future__ import annotations

from typing import Any, Literal

JSONPrimitive = str | int | float | bool | None
JSONValue = JSONPrimitive | dict[str, Any] | list[Any]
JSONObject = dict[str, Any]

#: Reasoning effort requested from models that support it. ``xhigh`` and ``max``
#: are only honoured by selected model families.
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]

#: How the tool calls of a single assistant message are executed.
#:
#: - ``sequential``: each call is prepared, executed and finalized before the
#:   next one starts.
#: - ``parallel``: calls are prepared in order, then allowed tools execute
#:   concurrently.
ToolExecutionMode = Literal["sequential", "parallel"]

#: How many queued messages are injected at a loop drain point.
QueueMode = Literal["all", "one-at-a-time"]

__all__ = [
    "JSONObject",
    "JSONPrimitive",
    "JSONValue",
    "QueueMode",
    "ThinkingLevel",
    "ToolExecutionMode",
]
