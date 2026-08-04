"""Tool argument coercion and validation.

Port of ``packages/ai/src/utils/validation.ts`` from earendil-works/pi (MIT).

Pi validates against TypeBox schemas; PiPy validates the equivalent JSON Schema
with ``jsonschema``. The coercion table and the error envelope are ported
directly, so a model that gets ``"3"`` where an integer belongs is corrected the
same way, and a genuinely invalid call gets the same shape of feedback.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import jsonschema

from .types import JSONObject


class ToolArgumentError(ValueError):
    """Raised when tool arguments cannot be validated against the schema."""


def _schema_types(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return []
    declared = schema.get("type")
    if isinstance(declared, str):
        return [declared]
    if isinstance(declared, list):
        return [item for item in declared if isinstance(item, str)]
    return []


def _matches_json_type(value: Any, json_type: str) -> bool:
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "null":
        return value is None
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    return False


def _coerce_primitive(value: Any, json_type: str) -> Any:
    if json_type in ("number", "integer"):
        if value is None:
            return 0
        if isinstance(value, str) and value.strip():
            try:
                parsed = float(value)
            except ValueError:
                return value
            if json_type == "integer":
                return int(parsed) if parsed.is_integer() else value
            return parsed
        if isinstance(value, bool):
            return 1 if value else 0
        return value
    if json_type == "boolean":
        if value is None:
            return False
        if value == "true":
            return True
        if value == "false":
            return False
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value == 1:
                return True
            if value == 0:
                return False
        return value
    if json_type == "string":
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return value
    if json_type == "null":
        if value == "" or value == 0 or value is False:
            return None
        return value
    return value


def _changed(candidate: Any, original: Any) -> bool:
    """Whether coercion produced a different value, the way JS ``!==`` would.

    Python cannot use ``!=`` here: ``bool`` subclasses ``int``, so ``True != 1``
    and ``False != 0`` are both false and every bool/int coercion would look
    like a no-op and be thrown away.
    """
    if candidate is original:
        return False
    if type(candidate) is not type(original):
        return True
    return bool(candidate != original)


def _coerce_union(value: Any, schemas: list[Any]) -> Any:
    for schema in schemas:
        coerced = _coerce(deepcopy(value), schema)
        try:
            jsonschema.validate(coerced, schema)
        except jsonschema.ValidationError:
            continue
        except jsonschema.SchemaError:
            continue
        return coerced
    return value


def _coerce(value: Any, schema: Any) -> Any:
    if not isinstance(schema, dict):
        return value

    result = value
    for nested in schema.get("allOf") or []:
        result = _coerce(result, nested)
    if isinstance(schema.get("anyOf"), list):
        result = _coerce_union(result, schema["anyOf"])
    if isinstance(schema.get("oneOf"), list):
        result = _coerce_union(result, schema["oneOf"])

    types = _schema_types(schema)
    matches_union_member = len(types) > 1 and any(
        _matches_json_type(result, json_type) for json_type in types
    )
    if types and not matches_union_member:
        for json_type in types:
            candidate = _coerce_primitive(result, json_type)
            if _changed(candidate, result):
                result = candidate
                break

    if "object" in types and isinstance(result, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, property_schema in properties.items():
                if key in result:
                    result[key] = _coerce(result[key], property_schema)
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            defined = set(properties or {})
            for key in list(result):
                if key not in defined:
                    result[key] = _coerce(result[key], additional)

    if "array" in types and isinstance(result, list):
        items = schema.get("items")
        if isinstance(items, list):
            for index, item_schema in enumerate(items):
                if index < len(result):
                    result[index] = _coerce(result[index], item_schema)
        elif isinstance(items, dict):
            for index, item in enumerate(result):
                result[index] = _coerce(item, items)

    return result


def _format_error_path(error: jsonschema.ValidationError) -> str:
    parts = [str(part) for part in error.absolute_path]
    if error.validator == "required":
        missing = _missing_property(error)
        if missing:
            parts.append(missing)
    return ".".join(parts) or "root"


def _missing_property(error: jsonschema.ValidationError) -> str | None:
    # jsonschema reports required failures one property at a time, with the name
    # quoted in the message: "'path' is a required property".
    message = error.message
    if "'" not in message:
        return None
    return message.split("'")[1]


def validate_tool_arguments(
    tool_name: str,
    schema: Any,
    arguments: JSONObject,
) -> JSONObject:
    """Coerce and validate tool arguments, returning the usable arguments.

    Raises :class:`ToolArgumentError` with pi's message envelope when the
    arguments cannot be made to fit the schema.
    """
    args = deepcopy(dict(arguments))
    if isinstance(schema, dict):
        coerced = _coerce(args, schema)
        if isinstance(coerced, dict):
            args = coerced

    validator_cls = jsonschema.validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
    except jsonschema.SchemaError:
        # A tool with an unusable schema should not block its own execution; pi
        # falls back to the raw arguments in the same situation.
        return args

    errors = sorted(validator_cls(schema).iter_errors(args), key=lambda error: list(error.path))
    if not errors:
        return args

    details = "\n".join(f"  - {_format_error_path(error)}: {error.message}" for error in errors)
    received = json.dumps(arguments, indent=2, default=str)
    raise ToolArgumentError(
        f'Validation failed for tool "{tool_name}":\n{details or "Unknown validation error"}'
        f"\n\nReceived arguments:\n{received}"
    )


__all__ = ["ToolArgumentError", "validate_tool_arguments"]
