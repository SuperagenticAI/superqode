"""Monty-backed Python REPL tool.

Monty is optional. When ``pydantic-monty`` is installed, this tool gives the
agent a fast, resource-limited Python interpreter without handing it direct host
Python execution.
"""

from __future__ import annotations

import asyncio
import importlib
import threading
from dataclasses import dataclass
from typing import Any, Dict

from .base import Tool, ToolContext, ToolResult

MAX_OUTPUT = 20000
DEFAULT_MAX_DURATION_SECS = 2.0
DEFAULT_MAX_MEMORY = 32 * 1024 * 1024
DEFAULT_MAX_RECURSION_DEPTH = 200


@dataclass
class _ReplState:
    repl: Any
    lock: threading.Lock


_REPLS: dict[str, _ReplState] = {}
_REPLS_LOCK = threading.Lock()


def _load_monty() -> Any | None:
    """Import pydantic_monty if available."""
    try:
        return importlib.import_module("pydantic_monty")
    except ImportError:
        return None


def is_monty_available() -> bool:
    """Return whether the optional Monty dependency can be imported."""
    return _load_monty() is not None


def monty_version() -> str | None:
    """Return the installed Monty version, if available."""
    module = _load_monty()
    if module is None:
        return None
    return str(getattr(module, "__version__", "unknown"))


def reset_monty_repl(session_id: str | None = None) -> None:
    """Reset one Monty REPL session, or all sessions when omitted."""
    with _REPLS_LOCK:
        if session_id is None:
            _REPLS.clear()
        else:
            _REPLS.pop(session_id, None)


def _format_result(value: Any, printed: str) -> str:
    parts: list[str] = []
    if printed:
        parts.append(printed.rstrip())
    if value is not None:
        parts.append(repr(value))
    output = "\n".join(part for part in parts if part)
    if not output:
        output = "None"
    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + f"\n\n[Output truncated at {MAX_OUTPUT} characters]"
    return output


class MontyPythonReplTool(Tool):
    """Run small Python snippets in a Monty sandbox."""

    @property
    def name(self) -> str:
        return "python_repl"

    @property
    def description(self) -> str:
        return (
            "Execute a small Python snippet in a Monty sandboxed REPL. "
            "State persists for this SuperQode session. Filesystem access is disabled "
            "unless explicitly mounted."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code snippet to execute.",
                },
                "reset": {
                    "type": "boolean",
                    "description": "Reset the session REPL before running code.",
                    "default": False,
                },
                "type_check": {
                    "type": "boolean",
                    "description": "Create a fresh type-checking REPL for this snippet.",
                    "default": False,
                },
                "allow_filesystem": {
                    "type": "boolean",
                    "description": (
                        "Mount the workspace at /workspace. Default false keeps filesystem "
                        "access blocked."
                    ),
                    "default": False,
                },
                "mount_mode": {
                    "type": "string",
                    "enum": ["read-only", "overlay", "read-write"],
                    "description": "Filesystem mount mode when allow_filesystem is true.",
                    "default": "overlay",
                },
                "max_duration_secs": {
                    "type": "number",
                    "description": "Maximum execution time in seconds.",
                    "default": DEFAULT_MAX_DURATION_SECS,
                },
                "max_memory": {
                    "type": "integer",
                    "description": "Maximum Monty heap memory in bytes.",
                    "default": DEFAULT_MAX_MEMORY,
                },
            },
            "required": ["code"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        module = _load_monty()
        if module is None:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Monty is not installed. Install optional support with "
                    "`pip install superqode[monty]` or `uv sync --extra monty`."
                ),
                metadata={"missing_dependency": "pydantic-monty"},
            )

        code = str(args.get("code", ""))
        if not code.strip():
            return ToolResult(success=False, output="", error="Code is required")

        reset = bool(args.get("reset", False))
        type_check = bool(args.get("type_check", False))
        allow_filesystem = bool(args.get("allow_filesystem", False))
        mount_mode = str(args.get("mount_mode", "overlay"))
        if mount_mode not in {"read-only", "overlay", "read-write"}:
            return ToolResult(success=False, output="", error=f"Invalid mount_mode: {mount_mode}")

        limits = {
            "max_duration_secs": float(args.get("max_duration_secs", DEFAULT_MAX_DURATION_SECS)),
            "max_memory": int(args.get("max_memory", DEFAULT_MAX_MEMORY)),
            "max_recursion_depth": DEFAULT_MAX_RECURSION_DEPTH,
        }

        try:
            output = await asyncio.to_thread(
                self._run_sync,
                module,
                ctx,
                code,
                reset,
                type_check,
                allow_filesystem,
                mount_mode,
                limits,
            )
        except Exception as exc:  # noqa: BLE001 - Monty raises package-specific exceptions.
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"runtime": "monty", "exception": type(exc).__name__},
            )

        return ToolResult(
            success=True,
            output=output,
            metadata={
                "runtime": "monty",
                "version": str(getattr(module, "__version__", "unknown")),
                "filesystem": "mounted" if allow_filesystem else "blocked",
                "mount_mode": mount_mode if allow_filesystem else None,
            },
        )

    def _run_sync(
        self,
        module: Any,
        ctx: ToolContext,
        code: str,
        reset: bool,
        type_check: bool,
        allow_filesystem: bool,
        mount_mode: str,
        limits: dict[str, Any],
    ) -> str:
        session_key = f"{ctx.session_id}:{ctx.working_directory.resolve()}:{type_check}"
        if reset:
            reset_monty_repl(session_key)

        with _REPLS_LOCK:
            state = _REPLS.get(session_key)
            if state is None:
                repl = module.MontyRepl(
                    script_name="superqode_repl.py",
                    limits=limits,
                    type_check=type_check,
                )
                state = _ReplState(repl=repl, lock=threading.Lock())
                _REPLS[session_key] = state

        collector = module.CollectString()
        mount = None
        if allow_filesystem:
            mount = module.MountDir(
                "/workspace",
                ctx.working_directory,
                mode=mount_mode,
            )

        with state.lock:
            value = state.repl.feed_run(
                code,
                print_callback=collector,
                mount=mount,
            )

        return _format_result(value, str(getattr(collector, "output", "")))
