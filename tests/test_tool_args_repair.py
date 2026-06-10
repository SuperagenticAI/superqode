"""Tests for lenient tool-argument parsing (local-model JSON repair)."""

import pytest

from superqode.agent.tool_args import invalid_arguments_message, parse_tool_arguments


def _ok(raw, expected):
    args, error = parse_tool_arguments(raw)
    assert error is None, f"unexpected error: {error}"
    assert args == expected


def test_plain_json():
    _ok('{"path": "src/main.py"}', {"path": "src/main.py"})


def test_already_a_dict():
    _ok({"a": 1}, {"a": 1})


def test_none_and_empty_variants():
    _ok(None, {})
    _ok("", {})
    _ok("   ", {})
    _ok("{}", {})
    _ok("null", {})


def test_double_encoded_json():
    _ok('"{\\"path\\": \\"x.py\\"}"', {"path": "x.py"})


def test_markdown_code_fence():
    _ok('```json\n{"path": "x.py"}\n```', {"path": "x.py"})
    _ok('```\n{"path": "x.py"}\n```', {"path": "x.py"})


def test_python_dict_syntax():
    _ok("{'path': 'x.py', 'flag': True, 'n': None}", {"path": "x.py", "flag": True, "n": None})


def test_trailing_comma():
    _ok('{"path": "x.py",}', {"path": "x.py"})
    _ok('{"items": [1, 2, 3,],}', {"items": [1, 2, 3]})


def test_prose_around_object():
    _ok('Sure! Here are the arguments: {"path": "x.py"} - executing now', {"path": "x.py"})


def test_nested_braces_in_strings():
    _ok('{"code": "if x { y }", "n": 1}', {"code": "if x { y }", "n": 1})


def test_unrecoverable_reports_error():
    args, error = parse_tool_arguments("definitely not json at all")
    assert args == {}
    assert error is not None
    assert "could not parse" in error


def test_non_object_json_reports_error():
    args, error = parse_tool_arguments("[1, 2, 3]")
    assert args == {}
    assert error is not None


def test_wrong_type_reports_error():
    args, error = parse_tool_arguments(42)
    assert args == {}
    assert error is not None


def test_error_preview_is_bounded():
    _, error = parse_tool_arguments("garbage " * 200)
    assert error is not None
    assert len(error) < 500


def test_invalid_arguments_message_mentions_tool_and_format():
    msg = invalid_arguments_message("edit_file", "could not parse tool arguments as JSON: x")
    assert "edit_file" in msg
    assert "not executed" in msg
    assert "JSON" in msg
