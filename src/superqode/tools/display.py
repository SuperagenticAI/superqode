"""Compact display helpers for tool calls."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json
import shlex
from typing import Any


_PATH_KEYS = ("path", "file_path", "filePath", "target_file", "directory")


def extract_tool_command(arguments: Mapping[str, Any] | None) -> str:
    """Recover a shell command from common BYOK/ACP argument shapes."""
    args = dict(arguments or {})
    for key in ("command", "cmd", "commandLine", "command_line", "shellCommand", "script", "input"):
        value = args.get(key)
        if isinstance(value, Mapping):
            nested = extract_tool_command(value)
            if nested:
                return nested
        elif isinstance(value, str) and value.strip():
            value = value.strip()
            if value.startswith("{"):
                try:
                    parsed = json.loads(value)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    nested = extract_tool_command(parsed)
                    if nested:
                        return nested
            suffix = args.get("args")
            if key != "input" and isinstance(suffix, (list, tuple)) and suffix:
                return f"{value} {shlex.join(str(part) for part in suffix)}"
            return value
        elif isinstance(value, (list, tuple)) and value:
            return shlex.join(str(part) for part in value)
    argv = args.get("argv")
    if isinstance(argv, (list, tuple)) and argv:
        return shlex.join(str(part) for part in argv)
    return ""


def format_tool_call_compact(
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    max_length: int = 120,
) -> str:
    """Format a tool call as a concise, function-like action label."""
    args = dict(arguments or {})
    name = _normal_tool_name(tool_name)
    details = _tool_details(name, args)
    label = f"{name}({details})" if details else f"{name}()"
    return _clip(label, max_length)


def _tool_details(name: str, args: Mapping[str, Any]) -> str:
    if name in {
        "read_file",
        "write_file",
        "edit_file",
        "insert_text",
        "patch",
        "multi_edit",
        "delete_file",
    }:
        return _path_arg(args)

    if name in {"list_directory", "ls"}:
        return _path_arg(args) or "."

    if name in {"bash", "shell", "execute"}:
        command = _clean(extract_tool_command(args))
        timeout = args.get("timeout") or args.get("timeout_seconds")
        if command and timeout:
            return f"{_quote(command)}, timeout={timeout}"
        return _quote(command) if command else ""

    if name in {"grep", "ripgrep"}:
        pattern = _clean(args.get("pattern") or args.get("query"))
        path = _path_arg(args)
        return _join_args(_quote(pattern) if pattern else "", path)

    if name in {"glob", "find"}:
        pattern = _clean(args.get("pattern") or args.get("include"))
        path = _path_arg(args)
        return _join_args(_quote(pattern) if pattern else "", path)

    if name in {"repo_search", "code_search", "web_search", "search"}:
        query = _clean(args.get("query") or args.get("pattern"))
        return _quote(query) if query else ""

    if name in {"fetch", "web_fetch", "download"}:
        url = _clean(args.get("url") or args.get("uri"))
        return _quote(url) if url else ""

    if name == "python_repl":
        code = str(args.get("code") or args.get("input") or args.get("command") or "")
        if not code:
            return ""
        lines = code.splitlines()
        line_count = len(lines)
        if line_count > 1:
            return f"{line_count} lines: {_quote(lines[0])}"
        return _quote(_clean(code))

    if name in {"todo_write", "todo_read"}:
        todos = args.get("todos")
        if isinstance(todos, list):
            return f"{len(todos)} todo{'s' if len(todos) != 1 else ''}"
        return _first_key_values(args)

    if name in {"batch", "parallel"}:
        calls = args.get("tool_calls") or args.get("calls") or args.get("tasks")
        if isinstance(calls, list):
            return f"{len(calls)} call{'s' if len(calls) != 1 else ''}"
        return _first_key_values(args)

    if name in {"sub_agent", "task_coordinator"}:
        task = _clean(args.get("task") or args.get("description") or args.get("prompt"))
        agent_type = _clean(args.get("agent_type") or args.get("type"))
        return _join_args(agent_type, _quote(task) if task else "")

    path = _path_arg(args)
    if path:
        return path
    return _first_key_values(args)


def _normal_tool_name(tool_name: str) -> str:
    name = str(tool_name or "tool").strip().replace("-", "_").replace(" ", "_").lower()
    aliases = {
        "read": "read_file",
        "write": "write_file",
        "edit": "edit_file",
        "multi_edit_tool": "multi_edit",
        "list": "list_directory",
        "listdir": "list_directory",
        "shell_command": "bash",
        "run_shell": "bash",
    }
    return aliases.get(name, name)


def _path_arg(args: Mapping[str, Any]) -> str:
    for key in _PATH_KEYS:
        value = args.get(key)
        if value:
            return _short_path(str(value))
    return ""


def _short_path(value: str, max_parts: int = 3) -> str:
    value = _clean(value)
    if not value:
        return ""
    path = Path(value).expanduser()
    parts = path.parts
    if len(parts) <= max_parts:
        return value
    if path.is_absolute():
        return str(Path("...").joinpath(*parts[-max_parts:]))
    return str(Path(*parts[-max_parts:]))


def _first_key_values(args: Mapping[str, Any], limit: int = 3) -> str:
    parts: list[str] = []
    for key, value in args.items():
        if value is None or value == "":
            continue
        if key in {"old_text", "new_text", "content", "code"}:
            value = _summarize_multiline(value)
        parts.append(f"{key}={_quote(_clean(value))}")
        if len(parts) >= limit:
            break
    return ", ".join(parts)


def _summarize_multiline(value: Any) -> str:
    text = str(value)
    lines = text.splitlines()
    if len(lines) <= 1:
        return text
    return f"{len(lines)} lines"


def _join_args(*parts: str) -> str:
    return ", ".join(part for part in parts if part)


def _quote(value: str) -> str:
    value = _clip(value.replace('"', '\\"'), 72)
    return f'"{value}"'


def _clean(value: Any) -> str:
    return " ".join(str(value).split())


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
