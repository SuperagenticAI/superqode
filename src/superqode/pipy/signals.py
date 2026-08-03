"""Cooperative cancellation for the PiPy harness.

Python has no stdlib equivalent of the web ``AbortController`` that Pi passes
through its loop and into every tool, so this is a small local implementation
with the same surface.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress


class AbortError(RuntimeError):
    """Raised by :meth:`AbortSignal.throw_if_aborted`."""

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or "Operation aborted"
        super().__init__(self.reason)


class AbortSignal:
    """Read-side of an abort. Created by an :class:`AbortController`."""

    __slots__ = ("_aborted", "_listeners", "_reason")

    def __init__(self) -> None:
        self._aborted = False
        self._reason: str | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> str | None:
        return self._reason

    def throw_if_aborted(self) -> None:
        if self._aborted:
            raise AbortError(self._reason)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an abort listener and return its unsubscribe callable."""
        if self._aborted:
            listener()
            return lambda: None
        self._listeners.append(listener)

        def unsubscribe() -> None:
            with suppress(ValueError):
                self._listeners.remove(listener)

        return unsubscribe

    def _abort(self, reason: str | None) -> None:
        if self._aborted:
            return
        self._aborted = True
        self._reason = reason or "Operation aborted"
        listeners, self._listeners = self._listeners, []
        for listener in listeners:
            # One misbehaving listener must not stop the rest from running, and
            # must not turn an abort into a crash.
            with suppress(Exception):
                listener()


class AbortController:
    """Write-side of an abort."""

    __slots__ = ("signal",)

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self, reason: str | None = None) -> None:
        self.signal._abort(reason)


def is_aborted(signal: AbortSignal | None) -> bool:
    """Return whether an optional signal has been aborted."""
    return signal is not None and signal.aborted


__all__ = ["AbortController", "AbortError", "AbortSignal", "is_aborted"]
