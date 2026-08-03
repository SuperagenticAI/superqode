"""Push-based event stream with a terminal result.

Port of the ``EventStream`` used by pi's agent loop
(``packages/agent/src/agent-loop.ts`` builds one per run). Producers push events
and the stream ends when the configured terminal predicate matches, carrying a
result that consumers can await independently of iteration.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Generic, TypeVar

TEvent = TypeVar("TEvent")
TResult = TypeVar("TResult")

_SENTINEL = object()


class EventStream(Generic[TEvent, TResult]):
    """An async-iterable queue of events that settles on a terminal event."""

    def __init__(
        self,
        is_end_event: Callable[[TEvent], bool],
        get_result: Callable[[TEvent], TResult],
    ) -> None:
        """Construct a stream. Must be called from inside a running event loop."""
        self._is_end_event = is_end_event
        self._get_result = get_result
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._result: asyncio.Future[TResult] = asyncio.get_running_loop().create_future()
        self._ended = False

    def push(self, event: TEvent) -> None:
        """Queue an event. Ends the stream when it is the terminal event."""
        if self._ended:
            return
        self._queue.put_nowait(event)
        if self._is_end_event(event):
            self.end(self._get_result(event))

    def end(self, result: TResult) -> None:
        """Settle the stream with a result. Later pushes are ignored."""
        if self._ended:
            return
        self._ended = True
        if not self._result.done():
            self._result.set_result(result)
        self._queue.put_nowait(_SENTINEL)

    def fail(self, error: BaseException) -> None:
        """Settle the stream with an error raised to iterators and awaiters."""
        if self._ended:
            return
        self._ended = True
        if not self._result.done():
            self._result.set_exception(error)
        self._queue.put_nowait(error)

    async def result(self) -> TResult:
        """Await the terminal result."""
        return await self._result

    async def __aiter__(self) -> AsyncIterator[TEvent]:
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            if isinstance(item, BaseException):
                raise item
            yield item  # type: ignore[misc]


__all__ = ["EventStream"]
