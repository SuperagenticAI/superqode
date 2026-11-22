"""Opt-in request accounting propagated through native async evaluation calls."""

from contextlib import contextmanager
from contextvars import ContextVar

_active = ContextVar("superqode_evaluation_usage_scope", default=None)


def current_usage_scope():
    return _active.get()


@contextmanager
def usage_scope(scope):
    token = _active.set(scope)
    try:
        yield scope
    finally:
        _active.reset(token)
