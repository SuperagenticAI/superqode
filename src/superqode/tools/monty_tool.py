"""Monty-backed Python sandbox tool.

Monty (``pydantic-monty``) is an optional, from-scratch Python interpreter that
runs LLM-generated Python in-process with resource limits and *no* host access
(filesystem, env, and network are all denied unless explicitly provided). It
starts in microseconds, so it is the lightest sandbox tier — use it for quick
generated-Python compute, not for shell commands (use ``bash`` for those) or
full project runs (use a remote sandbox for those).

This wraps the real ``pydantic-monty`` API (``Monty(...).run(...)`` with
``ResourceLimits`` and a ``print_callback``). Monty is experimental and supports
only a subset of Python, so the tool degrades gracefully when it is missing or
when a snippet uses an unsupported feature.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any, Dict

from .base import Tool, ToolContext, ToolResult

MAX_OUTPUT = 20000
DEFAULT_MAX_DURATION_SECS = 2.0
DEFAULT_MAX_MEMORY = 32 * 1024 * 1024


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


def _truncate(output: str) -> str:
    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + f"\n\n[Output truncated at {MAX_OUTPUT} characters]"
    return output


def run_monty_snippet(
    module: Any,
    code: str,
    *,
    type_check: bool = False,
    max_duration_secs: float = DEFAULT_MAX_DURATION_SECS,
    max_memory: int = DEFAULT_MAX_MEMORY,
) -> str:
    """Execute a snippet in a fresh Monty sandbox and return captured output.

    Uses the real ``pydantic-monty`` API: build a ``Monty`` with the code and
    call ``.run()`` with ``ResourceLimits`` and a stdout ``print_callback``. Each
    call is isolated (no host filesystem/network access). Raises on Monty errors.
    """
    chunks: list[str] = []

    def _print_callback(_stream: str, text: str) -> None:
        chunks.append(text)

    limits = module.ResourceLimits(
        max_duration_secs=float(max_duration_secs),
        max_memory=int(max_memory),
    )
    runner = module.Monty(code, script_name="superqode_repl.py", type_check=type_check)
    value = runner.run(limits=limits, print_callback=_print_callback)

    printed = "".join(chunks).rstrip()
    parts = [p for p in (printed, repr(value) if value is not None else "") if p]
    return _truncate("\n".join(parts) if parts else "None")


class MontyPythonReplTool(Tool):
    """Run small Python snippets in a Monty sandbox (no host access)."""

    @property
    def name(self) -> str:
        return "python_repl"

    @property
    def description(self) -> str:
        return (
            "Execute a small Python snippet in a Monty sandbox: a fast, "
            "resource-limited Python interpreter with NO access to the host "
            "filesystem, environment, or network. Prefer this over running "
            "`python -c` through bash for quick calculations, data shaping, or "
            "logic checks — it is safer and isolated. Each call runs fresh. Note: "
            "Monty supports a subset of Python (no third-party imports)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code snippet to execute. Use print() to emit output.",
                },
                "type_check": {
                    "type": "boolean",
                    "description": "Type-check the snippet before running it.",
                    "default": False,
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

        type_check = bool(args.get("type_check", False))
        max_duration_secs = float(args.get("max_duration_secs", DEFAULT_MAX_DURATION_SECS))
        max_memory = int(args.get("max_memory", DEFAULT_MAX_MEMORY))

        try:
            output = await asyncio.to_thread(
                run_monty_snippet,
                module,
                code,
                type_check=type_check,
                max_duration_secs=max_duration_secs,
                max_memory=max_memory,
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
                "filesystem": "blocked",
            },
        )
