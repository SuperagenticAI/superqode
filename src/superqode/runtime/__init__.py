"""Pluggable agent runtime backends.

Usage::

    from superqode.runtime import create_runtime

    runtime = create_runtime("builtin", gateway=..., tools=..., config=...)
    response = await runtime.run("write hello.txt")

Available runtimes: see :func:`list_runtimes`.
"""

from .base import AgentRuntime
from .builtin import BuiltinRuntime
from .errors import (
    RuntimeNotImplementedError,
    RuntimeNotInstalledError,
    UnknownRuntimeError,
)
from .registry import (
    RuntimeInfo,
    create_runtime,
    known_runtime_names,
    list_runtimes,
    resolve_runtime_name,
)

__all__ = [
    "AgentRuntime",
    "BuiltinRuntime",
    "RuntimeInfo",
    "RuntimeNotImplementedError",
    "RuntimeNotInstalledError",
    "UnknownRuntimeError",
    "create_runtime",
    "known_runtime_names",
    "list_runtimes",
    "resolve_runtime_name",
]
