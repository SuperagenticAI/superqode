"""Pluggable agent runtime backends.

Usage::

    from superqode.runtime import create_runtime

    runtime = create_runtime("builtin", gateway=..., tools=..., config=...)
    response = await runtime.run("write hello.txt")

Available runtimes: see :func:`list_runtimes`.
"""

from .errors import (
    RuntimeNotImplementedError,
    RuntimeNotInstalledError,
    UnknownRuntimeError,
)
from .registry import (
    RuntimeInfo,
    create_runtime,
    is_vendor_cli_runtime,
    known_runtime_names,
    list_runtimes,
    optional_package_installed,
    resolve_runtime_name,
    runtime_documentation_url,
    runtime_extra,
)

__all__ = [
    "AgentRuntime",
    "BuiltinRuntime",
    "RuntimeInfo",
    "RuntimeNotImplementedError",
    "RuntimeNotInstalledError",
    "UnknownRuntimeError",
    "create_runtime",
    "is_vendor_cli_runtime",
    "known_runtime_names",
    "list_runtimes",
    "optional_package_installed",
    "resolve_runtime_name",
    "runtime_documentation_url",
    "runtime_extra",
]


def __getattr__(name):
    if name == "AgentRuntime":
        from .base import AgentRuntime

        return AgentRuntime
    if name == "BuiltinRuntime":
        from .builtin import BuiltinRuntime

        return BuiltinRuntime
    raise AttributeError(name)
