"""Conditional project instructions that survive compaction.

An ``AGENTS.md`` section wrapped in ``sq:when`` is omitted from the always-on
prompt and copied back into the pinned system message whenever a declared
path, tool, or task matches the current transcript. Unmarked text is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_WHEN_OPEN = re.compile(r"<!--\s*sq:when\s+(.*?)\s*-->", re.IGNORECASE | re.DOTALL)
_WHEN_CLOSE = re.compile(r"<!--\s*/sq:when\s*-->", re.IGNORECASE)
_ATTR = re.compile(r"(paths|tools|tasks)\s*=\s*\"([^\"]*)\"", re.IGNORECASE)
_PATH_RE = re.compile(
    r"(?:[A-Za-z0-9_.@-]+/)+[A-Za-z0-9_.@-]+|(?<![\w./-])[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}(?![\w./-])"
)
PIN_START = "<!-- sq:pinned-instructions -->"
PIN_END = "<!-- /sq:pinned-instructions -->"
CONDITIONAL_ENV = "SUPERQODE_CONDITIONAL_INSTRUCTIONS"
_CONDITIONAL_ON = {"1", "true", "yes", "on"}
_PIN_BLOCK = re.compile(re.escape(PIN_START) + r".*?" + re.escape(PIN_END), re.DOTALL)

_TASK_WORDS = {
    "docs": ("document", "documentation", "readme", "changelog", "docs"),
    "deploy": ("deploy", "release"),
    "prose": ("blog", "voice", "style guide"),
}


@dataclass(frozen=True)
class ConditionalFragment:
    """One condition-bound instruction block."""

    source: str
    paths: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    content: str = ""


@dataclass(frozen=True)
class InstructionSet:
    """Unconditional text plus fragments that reload when their condition holds."""

    unconditional: str = ""
    fragments: tuple[ConditionalFragment, ...] = ()


@dataclass(frozen=True)
class InstructionSignals:
    """Paths, tools, and the latest user text visible in the transcript."""

    paths: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    latest_user: str = ""


def conditional_instructions_enabled(environ: dict | None = None) -> bool:
    """True only when conditional AGENTS.md sections were explicitly enabled."""
    import os

    env = os.environ if environ is None else environ
    return str(env.get(CONDITIONAL_ENV) or "").strip().lower() in _CONDITIONAL_ON


def split_instruction_text(text: str, *, source: str = "AGENTS.md") -> InstructionSet:
    """Split ``sq:when`` blocks out of otherwise unconditional instructions.

    A marker that is missing its close, or that names no condition, stays in
    the unconditional text so a typo cannot hide project rules.
    """
    kept: list[str] = []
    fragments: list[ConditionalFragment] = []
    pos = 0
    while True:
        opened = _WHEN_OPEN.search(text, pos)
        if opened is None:
            kept.append(text[pos:])
            break
        kept.append(text[pos : opened.start()])
        closed = _WHEN_CLOSE.search(text, opened.end())
        if closed is None:
            kept.append(text[opened.start() :])
            break
        body = text[opened.end() : closed.start()].strip()
        attrs = _parse_attrs(opened.group(1))
        if body and any(attrs.values()):
            fragments.append(
                ConditionalFragment(
                    source=source,
                    paths=tuple(attrs["paths"]),
                    tools=tuple(attrs["tools"]),
                    tasks=tuple(attrs["tasks"]),
                    content=body,
                )
            )
        elif body:
            kept.append(body)
        pos = closed.end()
    unconditional = "".join(kept).strip()
    return InstructionSet(unconditional=unconditional, fragments=tuple(fragments))


def _parse_attrs(raw: str) -> dict[str, list[str]]:
    found = {"paths": [], "tools": [], "tasks": []}
    for match in _ATTR.finditer(raw):
        key = match.group(1).lower()
        found[key] = [part.strip() for part in match.group(2).split(",") if part.strip()]
    return found


def glob_match(pattern: str, path: str) -> bool:
    """Match a path glob against the path or any directory suffix."""
    pattern = pattern.replace("\\", "/").lstrip("./")
    path = path.replace("\\", "/").lstrip("./")
    if not pattern or not path:
        return False
    parts = path.split("/")
    candidates = ["/".join(parts[index:]) for index in range(len(parts))]
    return any(_glob_fullmatch(pattern, candidate) for candidate in candidates)


def _glob_fullmatch(pattern: str, path: str) -> bool:
    regex: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            regex.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            regex.append(".*")
            index += 2
        elif pattern[index] == "*":
            regex.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            regex.append("[^/]")
            index += 1
        else:
            regex.append(re.escape(pattern[index]))
            index += 1
    return re.fullmatch("".join(regex), path) is not None


def fragment_matches(fragment: ConditionalFragment, signals: InstructionSignals) -> bool:
    """True when any declared path, tool, or task matches."""
    if fragment.paths and any(
        glob_match(pattern, path) for pattern in fragment.paths for path in signals.paths
    ):
        return True
    if fragment.tools and any(
        _glob_fullmatch(pattern, tool) for pattern in fragment.tools for tool in signals.tools
    ):
        return True
    if fragment.tasks and any(_task_match(task, signals.latest_user) for task in fragment.tasks):
        return True
    return False


def _task_match(task: str, text: str) -> bool:
    haystack = text.casefold()
    words = _TASK_WORDS.get(task.casefold(), (task.casefold(),))
    return any(word and word in haystack for word in words)


def signals_from_messages(messages: list[Any]) -> InstructionSignals:
    """Collect paths and tool names already present in the transcript."""
    paths: list[str] = []
    tools: list[str] = []
    users: list[str] = []
    for message in messages:
        role = getattr(message, "role", "")
        content = getattr(message, "content", "")
        if isinstance(content, str):
            if role == "user" and content.strip():
                users.append(content)
            paths.extend(_PATH_RE.findall(content))
        if role == "tool" and getattr(message, "name", None):
            tools.append(str(message.name))
        if role == "assistant" and getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                name, arguments = _call_name_args(tool_call)
                if name:
                    tools.append(name)
                paths.extend(_paths_from_arguments(arguments))
    return InstructionSignals(
        paths=tuple(dict.fromkeys(paths)),
        tools=tuple(dict.fromkeys(tools)),
        latest_user=users[-1] if users else "",
    )


def _call_name_args(tool_call: Any) -> tuple[str, Any]:
    if isinstance(tool_call, dict):
        function = tool_call.get("function") or {}
        if isinstance(function, dict):
            return str(function.get("name") or tool_call.get("name") or ""), function.get(
                "arguments", ""
            )
        return str(tool_call.get("name") or ""), ""
    function = getattr(tool_call, "function", None)
    name = str(getattr(function, "name", "") or getattr(tool_call, "name", "") or "")
    arguments = getattr(function, "arguments", "") if function is not None else ""
    return name, arguments


def _paths_from_arguments(arguments: Any) -> list[str]:
    found: list[str] = []
    if isinstance(arguments, str):
        found.extend(_PATH_RE.findall(arguments))
        stripped = arguments.strip()
        if not stripped or stripped[0] not in "{[":
            return found
        try:
            import json

            arguments = json.loads(stripped)
        except json.JSONDecodeError:
            return found
    if isinstance(arguments, dict):
        for key, value in arguments.items():
            if isinstance(value, str) and (
                key.lower() in {"path", "file", "file_path", "target", "directory"}
                or key.lower().endswith(("path", "file"))
            ):
                found.append(value)
            elif isinstance(value, str):
                found.extend(_PATH_RE.findall(value))
    return found


def _instruction_files(root: str | Path, *, include_globals: bool) -> list[tuple[str, Path]]:
    base = Path(root).expanduser().resolve()
    directories: list[Path] = []
    if include_globals:
        directories.extend([Path.home() / ".superqode", Path.home() / ".config" / "superqode"])
    directories.extend(reversed([base, *base.parents]))
    seen: set[Path] = set()
    files: list[tuple[str, Path]] = []
    for directory in directories:
        if directory in seen:
            continue
        seen.add(directory)
        agents_path = directory / "AGENTS.md"
        claude_path = directory / "CLAUDE.md"
        path = (
            agents_path if agents_path.exists() else claude_path if claude_path.exists() else None
        )
        if path is None:
            continue
        try:
            label = str(path.relative_to(base))
        except ValueError:
            label = path.name
        files.append((label, path))
    return files


_SET_CACHE: dict[tuple[Any, ...], InstructionSet] = {}


def load_instruction_set(root: str | Path = ".", *, include_globals: bool = True) -> InstructionSet:
    """Load unconditional text and conditional fragments for ``root``."""
    base = Path(root).expanduser().resolve()
    files = _instruction_files(base, include_globals=include_globals)
    stamp: list[Any] = [include_globals]
    readable: list[tuple[str, Path]] = []
    for label, path in files:
        try:
            stamp.append((str(path), path.stat().st_mtime_ns, label))
        except OSError:
            continue
        readable.append((label, path))
    key = tuple(stamp)
    cached = _SET_CACHE.get(key)
    if cached is not None:
        return cached
    parts: list[str] = []
    fragments: list[ConditionalFragment] = []
    for label, path in readable:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = split_instruction_text(raw, source=label)
        if parsed.unconditional:
            parts.append(f"## Instructions from {label}\n\n{parsed.unconditional}")
        fragments.extend(parsed.fragments)
    loaded = InstructionSet(unconditional="\n\n".join(parts), fragments=tuple(fragments))
    if len(_SET_CACHE) > 32:
        _SET_CACHE.clear()
    _SET_CACHE[key] = loaded
    return loaded


def active_fragments(
    root: str | Path, signals: InstructionSignals, *, include_globals: bool = True
) -> tuple[ConditionalFragment, ...]:
    """Fragments whose conditions match ``signals``."""
    loaded = load_instruction_set(root, include_globals=include_globals)
    return tuple(item for item in loaded.fragments if fragment_matches(item, signals))


def render_pin(fragments: tuple[ConditionalFragment, ...] | list[ConditionalFragment]) -> str:
    if not fragments:
        return ""
    blocks = [f"### {item.source}\n\n{item.content}" for item in fragments]
    return "\n\n".join(blocks)


def upsert_pin(system_text: str, body: str) -> str:
    """Insert, replace, or remove the pinned instruction block."""
    stripped = body.strip()
    if not stripped:
        return _PIN_BLOCK.sub("", system_text).rstrip()
    replacement = f"{PIN_START}\n{stripped}\n{PIN_END}"
    if _PIN_BLOCK.search(system_text):
        return _PIN_BLOCK.sub(replacement, system_text, count=1)
    suffix = system_text.rstrip()
    if suffix:
        return suffix + "\n\n" + replacement + "\n"
    return replacement + "\n"


def refresh_pinned_instructions(
    messages: list[Any], root: str | Path, *, include_globals: bool = True
) -> list[Any]:
    """Reload matching fragments into the first system message.

    The system message is what compaction keeps. Replacing one delimited block
    avoids duplicating a fragment on later turns.
    """
    try:
        signals = signals_from_messages(messages)
        body = render_pin(active_fragments(root, signals, include_globals=include_globals))
    except OSError:
        return messages
    for index, message in enumerate(messages):
        if getattr(message, "role", "") != "system":
            continue
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            return messages
        updated = upsert_pin(content, body)
        if updated == content:
            return messages
        try:
            replacement = type(message)(
                role=message.role,
                content=updated,
                tool_calls=getattr(message, "tool_calls", None),
                tool_call_id=getattr(message, "tool_call_id", None),
                name=getattr(message, "name", None),
                reasoning_content=getattr(message, "reasoning_content", None),
            )
        except TypeError:
            return messages
        copied = list(messages)
        copied[index] = replacement
        return copied
    return messages


__all__ = [
    "PIN_END",
    "PIN_START",
    "CONDITIONAL_ENV",
    "ConditionalFragment",
    "InstructionSet",
    "InstructionSignals",
    "active_fragments",
    "conditional_instructions_enabled",
    "fragment_matches",
    "glob_match",
    "load_instruction_set",
    "refresh_pinned_instructions",
    "signals_from_messages",
    "split_instruction_text",
    "upsert_pin",
]
