"""Lenient parsing of model-emitted tool-call arguments.

Hosted frontier models emit clean JSON arguments; local models frequently
do not. Observed failure shapes include markdown code fences around the
JSON, Python-dict syntax (single quotes, ``True``/``False``/``None``),
trailing commas, double-encoded JSON strings, and prose wrapped around an
otherwise valid object. Silently treating those as ``{}`` (the previous
behavior) executes the tool with no arguments — usually a confusing
failure several steps later.

:func:`parse_tool_arguments` recovers every shape it safely can, and when
it cannot, reports a precise error so the agent loop can hand the problem
back to the model instead of executing a garbage call.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, Optional, Tuple

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_code_fence(text: str) -> str:
    match = _FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text


def _extract_first_object(text: str) -> Optional[str]:
    """Extract the first balanced ``{...}`` block, respecting strings."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_json(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _try_python_literal(text: str) -> Optional[Any]:
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return value


def _coerce_dict(value: Any) -> Optional[Dict[str, Any]]:
    """Accept dicts; unwrap one level of double-encoded JSON strings."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        inner = _try_json(value)
        if isinstance(inner, dict):
            return inner
    return None


def parse_tool_arguments(raw: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Parse tool-call arguments as emitted by a model.

    Returns ``(arguments, error)``. Exactly one of the following holds:
    the parse succeeded (possibly after repair) and ``error`` is ``None``,
    or the arguments were unrecoverable and ``error`` describes why —
    callers should send that error back to the model rather than execute
    the tool with empty arguments.
    """
    if raw is None:
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return {}, f"tool arguments must be a JSON object, got {type(raw).__name__}"

    text = raw.strip()
    if not text or text in ("{}", "null"):
        return {}, None

    # 1. Plain JSON (the well-behaved case), including double-encoded JSON.
    value = _try_json(text)
    coerced = _coerce_dict(value)
    if coerced is not None:
        return coerced, None
    if value is not None and not isinstance(value, str):
        return {}, f"tool arguments must be a JSON object, got {type(value).__name__}"

    # 2. Markdown code fence around the JSON.
    unfenced = _strip_code_fence(text)
    if unfenced != text:
        coerced = _coerce_dict(_try_json(unfenced))
        if coerced is not None:
            return coerced, None
        text = unfenced

    # 3. Python-dict syntax: single quotes, True/False/None, trailing commas.
    literal = _coerce_dict(_try_python_literal(text))
    if literal is not None:
        return literal, None

    # 4. Trailing commas in otherwise valid JSON.
    detrailed = _TRAILING_COMMA_RE.sub(r"\1", text)
    if detrailed != text:
        coerced = _coerce_dict(_try_json(detrailed))
        if coerced is not None:
            return coerced, None

    # 5. Prose or multiple objects around one valid object: take the first
    #    balanced block and run it through the same ladder.
    block = _extract_first_object(text)
    if block is not None and block != text:
        coerced = _coerce_dict(_try_json(block))
        if coerced is None:
            coerced = _coerce_dict(_try_json(_TRAILING_COMMA_RE.sub(r"\1", block)))
        if coerced is None:
            coerced = _coerce_dict(_try_python_literal(block))
        if coerced is not None:
            return coerced, None

    preview = text if len(text) <= 300 else text[:300] + "…"
    return {}, f"could not parse tool arguments as JSON: {preview}"


def invalid_arguments_message(tool_name: str, error: str) -> str:
    """Feedback sent to the model when its tool arguments were unparseable."""
    return (
        f"Tool call '{tool_name}' was not executed: {error}. "
        "Re-issue the tool call with arguments as a single valid JSON object "
        '(double-quoted keys and strings, e.g. {"path": "src/main.py"}), '
        "with no surrounding text or code fences."
    )


__all__ = ["invalid_arguments_message", "parse_tool_arguments"]
