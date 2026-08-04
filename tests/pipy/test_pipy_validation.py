"""Tool argument coercion and validation (checklist L11)."""

from __future__ import annotations

import pytest

from superqode.pipy import ToolArgumentError, validate_tool_arguments

OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "offset": {"type": "integer"},
        "enabled": {"type": "boolean"},
    },
    "required": ["path"],
    "additionalProperties": False,
}


def test_valid_arguments_pass_through():
    args = validate_tool_arguments("read", OBJECT_SCHEMA, {"path": "a.py", "offset": 3})
    assert args == {"path": "a.py", "offset": 3}


def test_original_arguments_are_not_mutated():
    original = {"path": "a.py", "offset": "3"}
    validate_tool_arguments("read", OBJECT_SCHEMA, original)
    assert original == {"path": "a.py", "offset": "3"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"path": "a.py", "offset": "12"}, 12),
        ({"path": "a.py", "offset": True}, 1),
        ({"path": "a.py", "offset": None}, 0),
    ],
)
def test_integer_coercion(raw, expected):
    assert validate_tool_arguments("read", OBJECT_SCHEMA, raw)["offset"] == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("false", False), (1, True), (0, False), (None, False)],
)
def test_boolean_coercion(raw, expected):
    args = validate_tool_arguments("read", OBJECT_SCHEMA, {"path": "a.py", "enabled": raw})
    assert args["enabled"] is expected


def test_string_coercion():
    args = validate_tool_arguments("read", OBJECT_SCHEMA, {"path": 42})
    assert args["path"] == "42"


def test_array_item_coercion():
    schema = {
        "type": "object",
        "properties": {
            "counts": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["counts"],
    }
    args = validate_tool_arguments("many", schema, {"counts": ["1", "2", 3]})
    assert args["counts"] == [1, 2, 3]


def test_nested_object_coercion():
    schema = {
        "type": "object",
        "properties": {
            "edit": {
                "type": "object",
                "properties": {"line": {"type": "integer"}},
            }
        },
    }
    args = validate_tool_arguments("edit", schema, {"edit": {"line": "9"}})
    assert args["edit"]["line"] == 9


def test_missing_required_property_reports_the_property_path():
    with pytest.raises(ToolArgumentError) as error:
        validate_tool_arguments("read", OBJECT_SCHEMA, {})

    message = str(error.value)
    assert message.startswith('Validation failed for tool "read":')
    assert "  - path:" in message
    assert "Received arguments:\n{}" in message


def test_unusable_type_reports_the_field_path():
    with pytest.raises(ToolArgumentError) as error:
        validate_tool_arguments("read", OBJECT_SCHEMA, {"path": "a.py", "offset": {"nested": 1}})

    assert "  - offset:" in str(error.value)


def test_additional_property_is_rejected():
    with pytest.raises(ToolArgumentError) as error:
        validate_tool_arguments("read", OBJECT_SCHEMA, {"path": "a.py", "surprise": 1})

    assert 'Validation failed for tool "read"' in str(error.value)


def test_received_arguments_are_the_raw_ones():
    with pytest.raises(ToolArgumentError) as error:
        validate_tool_arguments("read", OBJECT_SCHEMA, {"offset": "3"})

    # The report shows what the model sent, not the coerced form.
    assert '"offset": "3"' in str(error.value)


def test_broken_schema_does_not_block_execution():
    args = validate_tool_arguments("odd", {"type": "not-a-type"}, {"anything": 1})
    assert args == {"anything": 1}


def test_union_schema_picks_a_matching_member():
    schema = {
        "type": "object",
        "properties": {"value": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
    }
    assert validate_tool_arguments("u", schema, {"value": "5"})["value"] in (5, "5")
