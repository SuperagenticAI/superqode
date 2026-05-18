"""Typed output helpers for harness runs."""

from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter, ValidationError

RESULT_START = "---RESULT_START---"
RESULT_END = "---RESULT_END---"


class TypedOutputError(ValueError):
    """Raised when a harness response cannot be parsed as the requested type."""


def build_typed_output_prompt(prompt: str, result_schema: Any | None) -> str:
    """Append typed-output instructions when a schema is requested."""
    if result_schema is None:
        return prompt
    schema = _json_schema(result_schema)
    footer = (
        "\n\nReturn the final structured result as JSON between these exact delimiters:\n"
        f"{RESULT_START}\n"
        '{"example": "replace with a valid result"}\n'
        f"{RESULT_END}\n\n"
        "The JSON must satisfy this schema:\n"
        f"{json.dumps(schema, indent=2, sort_keys=True)}"
    )
    return prompt + footer


def parse_typed_output(content: str, result_schema: Any | None) -> Any | None:
    """Extract and validate typed output from model text."""
    if result_schema is None:
        return None
    raw = _extract_result_json(content)
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TypedOutputError(f"Typed output is not valid JSON: {exc}") from exc
    try:
        return TypeAdapter(result_schema).validate_python(candidate)
    except ValidationError as exc:
        raise TypedOutputError(f"Typed output failed validation: {exc}") from exc


def _extract_result_json(content: str) -> str:
    start = content.find(RESULT_START)
    if start != -1:
        start += len(RESULT_START)
        end = content.find(RESULT_END, start)
        if end == -1:
            raise TypedOutputError(f"Typed output is missing {RESULT_END}")
        return content[start:end].strip()
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    raise TypedOutputError(f"Typed output is missing {RESULT_START}")


def _json_schema(result_schema: Any) -> dict[str, Any]:
    return TypeAdapter(result_schema).json_schema()
