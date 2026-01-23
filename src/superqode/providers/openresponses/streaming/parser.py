"""
Streaming Event Parser for Open Responses.

Handles 45+ streaming event types from the Open Responses API.
Converts SSE events to StreamChunk objects for the gateway.

Event Categories:
- Response lifecycle: created, in_progress, completed, failed, incomplete
- Output items: added, done
- Content parts: added, done
- Text: delta, done
- Reasoning: delta, done
- Function calls: arguments.delta, arguments.done
- Code interpreter: code.delta, code.done, output
- File search: results
- Web search: results
- Rate limits: updated
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ...gateway.base import StreamChunk, Usage


@dataclass
class ParsedEvent:
    """Parsed streaming event with extracted data."""

    event_type: str
    content: Optional[str] = None
    thinking_content: Optional[str] = None
    tool_call_delta: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    error_message: Optional[str] = None


def parse_sse_event(line: str) -> Optional[Tuple[str, str]]:
    """
    Parse a single SSE line.

    Returns:
        Tuple of (field_name, value) or None if not a valid SSE line
    """
    if not line or line.startswith(":"):
        # Comment or empty line
        return None

    if ":" in line:
        field_name, _, value = line.partition(":")
        # Remove leading space from value (per SSE spec)
        if value.startswith(" "):
            value = value[1:]
        return (field_name, value)

    return None


class StreamingEventParser:
    """
    Parser for Open Responses streaming events.

    Accumulates SSE events and converts them to StreamChunk objects.
    Handles the full range of 45+ event types.

    Usage:
        parser = StreamingEventParser()

        async for line in response.aiter_lines():
            chunk = parser.parse_line(line)
            if chunk:
                yield chunk
    """

    def __init__(self):
        self._event_type: Optional[str] = None
        self._event_data: List[str] = []
        self._accumulated_content: str = ""
        self._accumulated_thinking: str = ""
        self._tool_calls: Dict[str, Dict[str, Any]] = {}
        self._current_tool_call_id: Optional[str] = None

    def reset(self) -> None:
        """Reset parser state for a new stream."""
        self._event_type = None
        self._event_data = []
        self._accumulated_content = ""
        self._accumulated_thinking = ""
        self._tool_calls = {}
        self._current_tool_call_id = None

    def parse_line(self, line: str) -> Optional[StreamChunk]:
        """
        Parse a single SSE line and return a StreamChunk if ready.

        Args:
            line: Raw SSE line

        Returns:
            StreamChunk if an event is complete, None otherwise
        """
        line = line.strip()

        # Empty line indicates end of event
        if not line:
            if self._event_data:
                chunk = self._process_event()
                self._event_type = None
                self._event_data = []
                return chunk
            return None

        # Parse SSE field
        parsed = parse_sse_event(line)
        if not parsed:
            return None

        field_name, value = parsed

        if field_name == "event":
            self._event_type = value
        elif field_name == "data":
            self._event_data.append(value)

        return None

    def _process_event(self) -> Optional[StreamChunk]:
        """Process accumulated event data and return a StreamChunk."""
        if not self._event_data:
            return None

        # Combine multi-line data
        data_str = "\n".join(self._event_data)

        # Handle [DONE] signal
        if data_str == "[DONE]":
            return StreamChunk(finish_reason="stop")

        # Parse JSON data
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return None

        event_type = self._event_type or data.get("type", "")

        # Route to appropriate handler
        return self._handle_event(event_type, data)

    def _handle_event(self, event_type: str, data: Dict[str, Any]) -> Optional[StreamChunk]:
        """Handle a specific event type."""

        # Response lifecycle events
        if event_type == "response.created":
            return None  # No content to emit

        elif event_type == "response.in_progress":
            return None  # No content to emit

        elif event_type == "response.completed":
            response = data.get("response", {})
            usage_data = response.get("usage", {})
            usage = None
            if usage_data:
                usage = Usage(
                    prompt_tokens=usage_data.get("input_tokens", 0),
                    completion_tokens=usage_data.get("output_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )
            return StreamChunk(finish_reason="stop", usage=usage)

        elif event_type == "response.failed":
            response = data.get("response", {})
            error = response.get("error", {})
            error_msg = error.get("message", "Unknown error")
            # Return error as content
            return StreamChunk(content=f"[Error: {error_msg}]", finish_reason="error")

        elif event_type == "response.incomplete":
            details = data.get("response", {}).get("incomplete_details", {})
            reason = details.get("reason", "unknown")
            return StreamChunk(finish_reason=f"incomplete:{reason}")

        # Output item events
        elif event_type == "response.output_item.added":
            return None  # No content to emit

        elif event_type == "response.output_item.done":
            return None  # No content to emit

        # Content part events
        elif event_type == "response.content_part.added":
            return None  # No content to emit

        elif event_type == "response.content_part.done":
            return None  # No content to emit

        # Text delta events
        elif event_type == "response.output_text.delta":
            delta = data.get("delta", "")
            if delta:
                self._accumulated_content += delta
                return StreamChunk(content=delta)
            return None

        elif event_type == "response.output_text.done":
            return None  # Already handled via deltas

        # Reasoning/thinking events
        elif event_type == "response.reasoning.delta":
            delta = data.get("delta", "")
            if delta:
                self._accumulated_thinking += delta
                return StreamChunk(thinking_content=delta)
            return None

        elif event_type == "response.reasoning.done":
            return None  # Already handled via deltas

        # Function call events
        elif event_type == "response.function_call_arguments.delta":
            call_id = data.get("call_id", "")
            delta = data.get("delta", "")
            output_index = data.get("output_index", 0)

            if call_id:
                if call_id not in self._tool_calls:
                    self._tool_calls[call_id] = {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "",
                            "arguments": "",
                        },
                        "index": output_index,
                    }
                self._tool_calls[call_id]["function"]["arguments"] += delta

            return None  # Don't emit until done

        elif event_type == "response.function_call_arguments.done":
            call_id = data.get("call_id", "")
            name = data.get("name", "")
            arguments = data.get("arguments", "{}")

            if call_id:
                if call_id not in self._tool_calls:
                    self._tool_calls[call_id] = {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                else:
                    self._tool_calls[call_id]["function"]["name"] = name
                    if not self._tool_calls[call_id]["function"]["arguments"]:
                        self._tool_calls[call_id]["function"]["arguments"] = arguments

                # Emit the completed tool call
                tool_call = self._tool_calls[call_id].copy()
                return StreamChunk(tool_calls=[tool_call])

            return None

        # Code interpreter events
        elif event_type == "response.code_interpreter_call.code.delta":
            # Code delta - treat as content for now
            delta = data.get("delta", "")
            if delta:
                return StreamChunk(content=f"```\n{delta}")
            return None

        elif event_type == "response.code_interpreter_call.code.done":
            return StreamChunk(content="\n```\n")

        elif event_type == "response.code_interpreter_call.output":
            output = data.get("output", "")
            if output:
                return StreamChunk(content=f"\n[Output]: {output}\n")
            return None

        # File search events
        elif event_type == "response.file_search_call.results":
            results = data.get("results", [])
            if results:
                result_text = "\n".join(
                    f"- {r.get('filename', 'unknown')}: {r.get('text', '')[:100]}..."
                    for r in results[:5]
                )
                return StreamChunk(content=f"\n[File Search Results]:\n{result_text}\n")
            return None

        # Web search events
        elif event_type == "response.web_search_call.results":
            results = data.get("results", [])
            if results:
                result_text = "\n".join(
                    f"- [{r.get('title', '')}]({r.get('url', '')})" for r in results[:5]
                )
                return StreamChunk(content=f"\n[Web Search Results]:\n{result_text}\n")
            return None

        # Rate limit events
        elif event_type == "rate_limits.updated":
            # Could log rate limit info, but don't emit content
            return None

        # Error events
        elif event_type == "error":
            error = data.get("error", {})
            message = error.get("message", "Unknown error")
            return StreamChunk(content=f"\n[Error: {message}]\n", finish_reason="error")

        # Unknown event type
        else:
            # Log unknown events for debugging
            return None

    def get_accumulated_content(self) -> str:
        """Get all accumulated content."""
        return self._accumulated_content

    def get_accumulated_thinking(self) -> str:
        """Get all accumulated thinking/reasoning."""
        return self._accumulated_thinking

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """Get all accumulated tool calls."""
        return list(self._tool_calls.values())

    def has_tool_calls(self) -> bool:
        """Check if any tool calls have been accumulated."""
        return bool(self._tool_calls)
