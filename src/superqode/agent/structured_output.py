"""Schema-validated structured output for headless runs (codex --output-schema).

CI and scripts that consume agent output need a contract, not prose.
``superqode -p --output-schema schema.json "..."`` instructs the model to
answer in JSON, extracts the JSON document from the final message
(tolerating fences and surrounding prose), and validates it against the
JSON Schema. One corrective retry is attempted on validation failure; after
that the errors are reported and the exit code says so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Tuple


def load_schema(path: Path) -> dict:
    """Load a JSON Schema document. Raises ValueError on unusable input."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Could not load output schema {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Output schema {path} must be a JSON object")
    return data


def schema_instruction(schema: dict) -> str:
    """The prompt suffix that pins the model to schema-shaped output."""
    return (
        "\n\nYour final message must be ONLY a JSON document that validates "
        "against this JSON Schema (no prose, no markdown fences):\n"
        + json.dumps(schema, indent=2)
    )


def _scan_balanced(text: str, open_ch: str, close_ch: str) -> Optional[str]:
    start = text.find(open_ch)
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
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_document(text: str) -> Optional[Any]:
    """Pull the first JSON object/array out of model output, leniently."""
    text = (text or "").strip()
    if not text:
        return None
    # Direct parse first (the well-behaved case).
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Strip a fenced block if the whole message is one.
    if text.startswith("```"):
        inner = text.split("\n", 1)[-1]
        if inner.rstrip().endswith("```"):
            inner = inner.rstrip()[:-3]
        try:
            return json.loads(inner.strip())
        except (json.JSONDecodeError, ValueError):
            text = inner
    # First balanced object or array embedded in prose.
    obj_start = text.find("{")
    arr_start = text.find("[")
    candidates = []
    if obj_start >= 0:
        candidates.append((obj_start, "{", "}"))
    if arr_start >= 0:
        candidates.append((arr_start, "[", "]"))
    for _pos, open_ch, close_ch in sorted(candidates):
        block = _scan_balanced(text, open_ch, close_ch)
        if block is not None:
            try:
                return json.loads(block)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def validate_payload(payload: Any, schema: dict) -> List[str]:
    """Validate against a JSON Schema. Returns human-readable error strings."""
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema is not installed; cannot validate (pip install jsonschema)"]
    validator_cls = jsonschema.validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
    except jsonschema.exceptions.SchemaError as e:
        return [f"schema itself is invalid: {e.message}"]
    errors = []
    for error in sorted(validator_cls(schema).iter_errors(payload), key=str):
        location = "/".join(str(p) for p in error.absolute_path) or "<root>"
        errors.append(f"{location}: {error.message}")
    return errors


def check_output(content: str, schema: dict) -> Tuple[Optional[Any], List[str]]:
    """Extract + validate. Returns (payload, errors); payload None when absent."""
    payload = extract_json_document(content)
    if payload is None:
        return None, ["final message contained no parseable JSON document"]
    return payload, validate_payload(payload, schema)


def correction_prompt(errors: List[str], schema: dict) -> str:
    listing = "\n".join(f"- {e}" for e in errors[:10])
    return (
        "Your previous final message did not satisfy the required output "
        f"schema. Validation errors:\n{listing}\n\n"
        "Respond again with ONLY a corrected JSON document that validates "
        "against the schema:\n" + json.dumps(schema, indent=2)
    )


__all__ = [
    "check_output",
    "correction_prompt",
    "extract_json_document",
    "load_schema",
    "schema_instruction",
    "validate_payload",
]
