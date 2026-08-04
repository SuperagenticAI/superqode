"""The grep, find and ls tools.

Ported from ``packages/coding-agent/src/core/tools/`` of earendil-works/pi
(MIT).

pi shells out to ripgrep and fd, downloading them when missing. PiPy will not
download binaries, so it falls back in three steps, best first. It falls back in three steps, best first:

1. ``rg`` / ``fd`` on PATH, giving identical results to pi
2. ``git ls-files --cached --others --exclude-standard`` inside a repository,
   which is exact .gitignore semantics straight from git
3. a plain walk with a small default ignore set, outside a repository
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shutil
from pathlib import Path

from ..messages import TextContent
from ..signals import AbortSignal, is_aborted
from ..types import JSONObject
from .base import AgentTool, AgentToolResult, ToolUpdateCallback
from .paths import json_schema, resolve_to_cwd
from .truncate import (
    DEFAULT_MAX_BYTES,
    GREP_MAX_LINE_LENGTH,
    format_size,
    truncate_head,
    truncate_line,
)

GREP_DEFAULT_LIMIT = 100
FIND_DEFAULT_LIMIT = 1000
LS_DEFAULT_LIMIT = 500

#: Used only outside a git repository, where there is no ignore file to honour.
DEFAULT_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        "target",
    }
)


def _abort_if_needed(signal: AbortSignal | None) -> None:
    if is_aborted(signal):
        raise RuntimeError("Operation aborted")


async def _run(command: list[str], cwd: Path) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return process.returncode or 0, stdout.decode("utf-8", errors="replace")


async def _inside_git_repo(directory: Path) -> bool:
    if shutil.which("git") is None:
        return False
    code, output = await _run(["git", "rev-parse", "--is-inside-work-tree"], directory)
    return code == 0 and output.strip() == "true"


async def _candidate_files(directory: Path) -> list[Path]:
    """Files worth searching, respecting .gitignore when git can tell us."""
    if await _inside_git_repo(directory):
        code, output = await _run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"], directory
        )
        if code == 0:
            return [directory / line for line in output.splitlines() if line.strip()]

    results: list[Path] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if name not in DEFAULT_IGNORED_DIRS]
        for name in files:
            results.append(Path(root) / name)
    return results


def _notices(output: str, notices: list[str]) -> str:
    return f"{output}\n\n[{'. '.join(notices)}]" if notices else output


# --------------------------------------------------------------------------- #
# grep
# --------------------------------------------------------------------------- #

GREP_DESCRIPTION = (
    "Search file contents for a pattern. Returns matching lines with file paths and "
    f"line numbers. Respects .gitignore. Output is truncated to {GREP_DEFAULT_LIMIT} "
    f"matches or {DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). Long lines "
    f"are truncated to {GREP_MAX_LINE_LENGTH} chars."
)


def create_grep_tool(cwd: str | Path) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        _abort_if_needed(signal)
        pattern = str(args["pattern"])
        search_root = resolve_to_cwd(str(args.get("path") or "."), cwd)
        glob = args.get("glob")
        ignore_case = bool(args.get("ignoreCase", False))
        literal = bool(args.get("literal", False))
        limit = max(1, int(args.get("limit") or GREP_DEFAULT_LIMIT))

        matches = await _grep(
            pattern,
            search_root,
            glob=str(glob) if glob else None,
            ignore_case=ignore_case,
            literal=literal,
            limit=limit + 1,
            signal=signal,
        )

        limit_reached = len(matches) > limit
        matches = matches[:limit]
        if not matches:
            return AgentToolResult(content=[TextContent(text="No matches found")], details=None)

        lines: list[str] = []
        lines_truncated = False
        base = search_root if search_root.is_dir() else search_root.parent
        for file_path, line_number, line_text in matches:
            sanitized = line_text.replace("\r\n", "\n").replace("\r", "").rstrip("\n")
            text, was_truncated = truncate_line(sanitized)
            lines_truncated = lines_truncated or was_truncated
            try:
                relative = Path(file_path).relative_to(base)
            except ValueError:
                relative = Path(file_path)
            lines.append(f"{relative}:{line_number}: {text}")

        truncation = truncate_head("\n".join(lines), max_lines=2**53)
        notices: list[str] = []
        if limit_reached:
            notices.append(
                f"{limit} matches limit reached. Use limit={limit * 2} for more, or refine pattern"
            )
        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
        if lines_truncated:
            notices.append(
                f"Some lines truncated to {GREP_MAX_LINE_LENGTH} chars. "
                "Use read tool to see full lines"
            )

        return AgentToolResult(
            content=[TextContent(text=_notices(truncation.content, notices))],
            details={"match_count": len(matches)},
        )

    return AgentTool(
        name="grep",
        label="grep",
        description=GREP_DESCRIPTION,
        parameters=json_schema(
            {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (regex or literal string)",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search (default: current directory)",
                },
                "glob": {
                    "type": "string",
                    "description": "Filter files by glob pattern, e.g. '*.ts' or '**/*.spec.ts'",
                },
                "ignoreCase": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false)",
                },
                "literal": {
                    "type": "boolean",
                    "description": (
                        "Treat pattern as literal string instead of regex (default: false)"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 100)",
                },
            },
            ["pattern"],
        ),
        execute_fn=execute,
        prompt_snippet="Search file contents for patterns (respects .gitignore)",
    )


async def _grep(
    pattern: str,
    root: Path,
    *,
    glob: str | None,
    ignore_case: bool,
    literal: bool,
    limit: int,
    signal: AbortSignal | None,
) -> list[tuple[str, int, str]]:
    if shutil.which("rg"):
        command = ["rg", "--line-number", "--color=never", "--hidden", "--no-heading"]
        if ignore_case:
            command.append("--ignore-case")
        if literal:
            command.append("--fixed-strings")
        if glob:
            command += ["--glob", glob]
        command += ["--max-count", str(limit), "--", pattern, str(root)]
        code, output = await _run(command, root if root.is_dir() else root.parent)
        if code in (0, 1):
            results: list[tuple[str, int, str]] = []
            for line in output.splitlines():
                parts = line.split(":", 2)
                if len(parts) == 3 and parts[1].isdigit():
                    results.append((parts[0], int(parts[1]), parts[2]))
                if len(results) >= limit:
                    break
            return results

    flags = re.IGNORECASE if ignore_case else 0
    matcher = re.compile(re.escape(pattern), flags) if literal else re.compile(pattern, flags)
    files = [root] if root.is_file() else await _candidate_files(root)
    results = []
    for path in files:
        _abort_if_needed(signal)
        if glob and not fnmatch.fnmatch(path.name, glob) and not fnmatch.fnmatch(str(path), glob):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.split("\n"), start=1):
            if matcher.search(line):
                results.append((str(path), number, line))
                if len(results) >= limit:
                    return results
    return results


# --------------------------------------------------------------------------- #
# find
# --------------------------------------------------------------------------- #

FIND_DESCRIPTION = (
    "Search for files by glob pattern. Returns matching file paths relative to the "
    "search directory. Respects .gitignore. Output is truncated to "
    f"{FIND_DEFAULT_LIMIT} results or {DEFAULT_MAX_BYTES // 1024}KB (whichever is hit "
    "first)."
)


def create_find_tool(cwd: str | Path) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        _abort_if_needed(signal)
        pattern = str(args["pattern"])
        root = resolve_to_cwd(str(args.get("path") or "."), cwd)
        limit = max(1, int(args.get("limit") or FIND_DEFAULT_LIMIT))

        candidates = await _candidate_files(root)
        results: list[str] = []
        for path in candidates:
            _abort_if_needed(signal)
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if fnmatch.fnmatch(str(relative), pattern) or fnmatch.fnmatch(path.name, pattern):
                results.append(str(relative))
            if len(results) > limit:
                break

        if not results:
            return AgentToolResult(
                content=[TextContent(text="No files found matching pattern")], details=None
            )

        limit_reached = len(results) > limit
        results = sorted(results[:limit])
        truncation = truncate_head("\n".join(results), max_lines=2**53)

        notices: list[str] = []
        if limit_reached:
            notices.append(f"{limit} results limit reached")
        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")

        return AgentToolResult(
            content=[TextContent(text=_notices(truncation.content, notices))],
            details={"result_count": len(results)},
        )

    return AgentTool(
        name="find",
        label="find",
        description=FIND_DESCRIPTION,
        parameters=json_schema(
            {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Glob pattern to match files, e.g. '*.ts', '**/*.json', "
                        "or 'src/**/*.spec.ts'"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: current directory)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 1000)",
                },
            },
            ["pattern"],
        ),
        execute_fn=execute,
        prompt_snippet="Find files by glob pattern (respects .gitignore)",
    )


# --------------------------------------------------------------------------- #
# ls
# --------------------------------------------------------------------------- #

LS_DESCRIPTION = (
    "List directory contents. Returns entries sorted alphabetically, with '/' suffix "
    "for directories. Includes dotfiles. Output is truncated to "
    f"{LS_DEFAULT_LIMIT} entries or {DEFAULT_MAX_BYTES // 1024}KB (whichever is hit "
    "first)."
)


def create_ls_tool(cwd: str | Path) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        _abort_if_needed(signal)
        directory = resolve_to_cwd(str(args.get("path") or "."), cwd)
        limit = max(1, int(args.get("limit") or LS_DEFAULT_LIMIT))

        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        names = sorted(os.listdir(directory), key=str.lower)
        limit_reached = len(names) > limit
        rows: list[str] = []
        for name in names[:limit]:
            try:
                rows.append(f"{name}/" if (directory / name).is_dir() else name)
            except OSError:
                # An entry we cannot stat is still worth listing by name.
                rows.append(name)

        truncation = truncate_head("\n".join(rows), max_lines=2**53)
        notices: list[str] = []
        if limit_reached:
            notices.append(f"{limit} entries limit reached. Use limit={limit * 2} for more")
        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")

        return AgentToolResult(
            content=[TextContent(text=_notices(truncation.content, notices))],
            details={"entry_count": len(rows)},
        )

    return AgentTool(
        name="ls",
        label="ls",
        description=LS_DESCRIPTION,
        parameters=json_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Directory to list (default: current directory)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return (default: 500)",
                },
            },
            [],
        ),
        execute_fn=execute,
        prompt_snippet="List directory contents",
    )


__all__ = [
    "FIND_DEFAULT_LIMIT",
    "FIND_DESCRIPTION",
    "GREP_DEFAULT_LIMIT",
    "GREP_DESCRIPTION",
    "LS_DEFAULT_LIMIT",
    "LS_DESCRIPTION",
    "create_find_tool",
    "create_grep_tool",
    "create_ls_tool",
]
