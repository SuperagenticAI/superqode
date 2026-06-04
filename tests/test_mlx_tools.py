"""Tests for MLX tool-call parsing (no MLX required)."""

from __future__ import annotations

import json

from superqode.providers.local import mlx_tools


# --- format resolution -------------------------------------------------------


def test_resolve_format_by_family():
    assert mlx_tools.resolve_format("gemma4:31b-mlx-bf16") == "gemma"
    assert mlx_tools.resolve_format("Qwen3-Coder-Next") == "qwen"
    assert mlx_tools.resolve_format("hermes-3") == "qwen"
    assert mlx_tools.resolve_format("some-unknown-model") == "json"


def test_resolve_format_honors_policy():
    # *-json policy -> generic json parser, regardless of family
    assert mlx_tools.resolve_format("gemma4", "strict-json") == "json"
    assert mlx_tools.resolve_format("gemma4", "compact-json") == "json"
    # native -> family default
    assert mlx_tools.resolve_format("gemma4", "native") == "gemma"
    assert mlx_tools.resolve_format("qwen3", "native") == "qwen"
    # explicit format name
    assert mlx_tools.resolve_format("anything", "qwen") == "qwen"


def _first(calls):
    fn = calls[0]["function"]
    return fn["name"], json.loads(fn["arguments"])


# --- qwen / hermes format ----------------------------------------------------


def test_qwen_single_tool_call():
    text = '<tool_call>\n{"name": "list_directory", "arguments": {"path": "."}}\n</tool_call>'
    clean, calls = mlx_tools.parse_tool_calls(text, "qwen")
    assert len(calls) == 1
    name, args = _first(calls)
    assert name == "list_directory" and args == {"path": "."}
    assert calls[0]["type"] == "function" and calls[0]["id"].startswith("call_")
    assert clean == ""


def test_qwen_multiple_tool_calls_with_prose():
    text = (
        "Let me check.\n"
        '<tool_call>{"name": "a", "arguments": {"x": 1}}</tool_call>\n'
        '<tool_call>{"name": "b", "arguments": {}}</tool_call>'
    )
    clean, calls = mlx_tools.parse_tool_calls(text, "qwen")
    assert [c["function"]["name"] for c in calls] == ["a", "b"]
    assert "Let me check." in clean


# --- gemma format ------------------------------------------------------------


def test_gemma_fenced_tool_call():
    text = "Sure.\n```tool_call\n{\"name\": \"bash\", \"arguments\": {\"cmd\": \"ls\"}}\n```"
    clean, calls = mlx_tools.parse_tool_calls(text, "gemma")
    assert len(calls) == 1
    name, args = _first(calls)
    assert name == "bash" and args == {"cmd": "ls"}
    assert "Sure." in clean


def test_gemma_json_fence():
    text = '```json\n{"name": "read_file", "arguments": {"path": "x.py"}}\n```'
    _clean, calls = mlx_tools.parse_tool_calls(text, "gemma")
    assert _first(calls) == ("read_file", {"path": "x.py"})


# --- generic json ------------------------------------------------------------


def test_json_bare_object():
    text = '{"name": "grep", "arguments": {"pattern": "TODO"}}'
    _clean, calls = mlx_tools.parse_tool_calls(text, "json")
    assert _first(calls) == ("grep", {"pattern": "TODO"})


def test_json_parameters_key():
    text = '{"name": "glob", "parameters": {"pattern": "*.py"}}'
    _clean, calls = mlx_tools.parse_tool_calls(text, "json")
    assert _first(calls) == ("glob", {"pattern": "*.py"})


def test_json_nested_function_shape():
    text = '{"function": {"name": "edit", "arguments": {"path": "a"}}}'
    _clean, calls = mlx_tools.parse_tool_calls(text, "json")
    assert _first(calls) == ("edit", {"path": "a"})


def test_arguments_as_json_string():
    text = '{"name": "f", "arguments": "{\\"a\\": 1}"}'
    _clean, calls = mlx_tools.parse_tool_calls(text, "json")
    assert _first(calls) == ("f", {"a": 1})


# --- no tool call ------------------------------------------------------------


def test_plain_text_no_tool_calls():
    text = "There are 18 files in the directory."
    clean, calls = mlx_tools.parse_tool_calls(text, "qwen")
    assert calls == []
    assert clean == text


def test_garbage_does_not_crash():
    clean, calls = mlx_tools.parse_tool_calls("{ not json", "json")
    assert calls == []


# --- module wiring (lazy mlx import; safe to import without mlx) --------------


def test_engine_and_worker_import_without_mlx():
    # These modules must import even when mlx_lm isn't installed (lazy import).
    from superqode.providers.local import mlx_engine

    assert hasattr(mlx_engine, "get_mlx_engine")
    assert hasattr(mlx_engine, "MlxUnavailableError")
