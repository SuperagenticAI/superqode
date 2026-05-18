"""Runtime errors."""

from __future__ import annotations


class RuntimeError_(Exception):
    """Base class for runtime errors. Underscore avoids shadowing the builtin."""


class RuntimeNotInstalledError(RuntimeError_):
    """Optional dependency for a runtime is missing.

    The message should always include the exact `pip install` hint.
    """


class RuntimeNotImplementedError(RuntimeError_):
    """Runtime is recognized but its implementation is reserved for a later version."""


class UnknownRuntimeError(RuntimeError_):
    """Requested runtime name is not registered."""
