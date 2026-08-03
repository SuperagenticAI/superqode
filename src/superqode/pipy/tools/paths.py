"""Path resolution and the file mutation queue.

Ported from ``path-utils.ts`` and ``file-mutation-queue.ts`` of
earendil-works/pi (MIT).

PiPy runs with the permissions of the process that launched it, matching pi, so
nothing here restricts where a tool may reach. Resolution only makes relative
paths absolute against the working directory.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_mutation_locks: dict[str, asyncio.Lock] = {}


def resolve_to_cwd(path: str, cwd: str | Path) -> Path:
    """Resolve a tool path argument against the working directory."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (Path(cwd) / candidate).resolve()


def display_path(path: Path, cwd: str | Path) -> str:
    """Path as the model should see it: relative to cwd when it is inside."""
    try:
        return str(path.relative_to(Path(cwd).resolve()))
    except ValueError:
        return str(path)


@asynccontextmanager
async def file_mutation_lock(path: Path):
    """Serialise mutations of one file.

    Two parallel tool calls editing the same file would otherwise interleave a
    read and a write and silently drop one of the edits. The loop runs tools
    concurrently by default, so this is load-bearing rather than defensive.
    """
    key = str(path)
    lock = _mutation_locks.setdefault(key, asyncio.Lock())
    async with lock:
        yield


async def with_file_mutation_queue(path: Path, operation: Callable[[], Awaitable[T]]) -> T:
    async with file_mutation_lock(path):
        return await operation()


def json_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Small helper so every tool declares its schema the same way."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


__all__ = [
    "display_path",
    "file_mutation_lock",
    "json_schema",
    "resolve_to_cwd",
    "with_file_mutation_queue",
]
