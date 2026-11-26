"""Context-local tool operations supplied by an embedding host.

The standalone tools keep their usual behavior when no host supplies operations.
This module depends only on the standard library, without application policy.
"""

from contextlib import contextmanager
from contextvars import ContextVar

_OPERATIONS = ContextVar("pipy_host_tool_operations", default=(None, None))


@contextmanager
def tool_operations_scope(*, validate_path=None, prepare_command=None):
    token = _OPERATIONS.set((validate_path, prepare_command))
    try:
        yield
    finally:
        _OPERATIONS.reset(token)


def validate_path(path):
    operation = _OPERATIONS.get()[0]
    if operation:
        operation(path)


def prepare_command(argv, cwd):
    operation = _OPERATIONS.get()[1]
    return operation(argv, cwd) if operation else argv
