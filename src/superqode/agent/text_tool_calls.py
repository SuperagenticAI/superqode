"""Prompt-based tool calling: catalog rendering + in-text call extraction.

Some local models have no native tool-calling head at all — they can only
emit tool calls as text. The harness ``tool_call_format: prompt`` mode
serves them: tool schemas are rendered into the system prompt and the
model is instructed to emit

    <tool_call>{"name": "read_file", "arguments": {"path": "src/main.py"}}</tool_call>

blocks, which the loop extracts and executes exactly like native calls.
The LiteLLM gateway already strips in-band calls for local-shaped
providers; this module is the loop-level equivalent so prompt mode works
on any provider, and the renderer that teaches the model the format.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Tuple

# Formats that mean "no native tool channel - use the prompt".
PROMPT_FORMATS = ("prompt", "prompt-json", "in-text", "text", "xml")

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def is_prompt_format(value: Any) -> bool:
    return str(value or "").strip().lower() in PROMPT_FORMATS


def _normalize_prompt_argument(value: Any) -> Any:
    """Repair common double-escaped strings from prompt-mode local models."""
    if isinstance(value, str):
        return (
            value.replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\r", "\r")
        )
    if isinstance(value, list):
        return [_normalize_prompt_argument(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_prompt_argument(item) for key, item in value.items()}
    return value


def render_tool_catalog(tool_defs: List[Any]) -> str:
    """System-prompt section teaching the model the available tools + format."""
    if not tool_defs:
        return ""
    lines = [
        "",
        "# Tools",
        "",
        "You can use tools. To call one, emit exactly this block (one per call):",
        '<tool_call>{"name": "<tool_name>", "arguments": {<json arguments>}}</tool_call>',
        "Emit the block alone, then stop - the result will be returned to you.",
        "",
        "Available tools:",
    ]
    for tool in tool_defs:
        schema = json.dumps(getattr(tool, "parameters", {}) or {}, separators=(",", ":"))
        description = str(getattr(tool, "description", "")).split("\n")[0][:200]
        lines.append(f"- {tool.name}: {description}")
        lines.append(f"  parameters: {schema}")
    return "\n".join(lines)


def extract_text_tool_calls(content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract ``<tool_call>`` blocks from model text.

    Returns ``(content_without_blocks, tool_calls)`` in the standard
    OpenAI-dict shape the loop already executes. Malformed blocks are left
    in the text untouched (the model sees its own mistake in history).
    """
    if "<tool_call>" not in (content or ""):
        return content, []

    from .tool_args import parse_tool_arguments

    tool_calls: List[Dict[str, Any]] = []
    consumed_spans: List[Tuple[int, int]] = []
    for match in _TOOL_CALL_RE.finditer(content):
        payload, error = parse_tool_arguments(match.group(1))
        if error is not None or not isinstance(payload, dict):
            continue
        envelope = payload
        function = payload.get("function")
        if isinstance(function, dict):
            envelope = {**payload, **function}
        name = str(envelope.get("name") or envelope.get("tool") or "")
        if not name:
            continue
        arguments = envelope.get("arguments", envelope.get("parameters", {}))
        if isinstance(arguments, str):
            arguments, _err = parse_tool_arguments(arguments)
        if not isinstance(arguments, dict):
            arguments = {}
        arguments = _normalize_prompt_argument(arguments)
        tool_calls.append(
            {
                "id": f"text-{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        )
        consumed_spans.append(match.span())

    if not tool_calls:
        return content, []

    cleaned_parts: List[str] = []
    cursor = 0
    for start, end in consumed_spans:
        cleaned_parts.append(content[cursor:start])
        cursor = end
    cleaned_parts.append(content[cursor:])
    return "".join(cleaned_parts).strip(), tool_calls


__all__ = [
    "PROMPT_FORMATS",
    "extract_text_tool_calls",
    "is_prompt_format",
    "render_tool_catalog",
]
