"""Async helpers extracted from app_main: a dedicated loop thread for
long-lived subprocess protocol clients, and a guard that silences the
"Event loop is closed" error from BaseSubprocessTransport.__del__."""

from __future__ import annotations

import asyncio
import asyncio.base_subprocess as _asyncio_base_subprocess
import threading


# Silence the "Event loop is closed" RuntimeError raised by
# BaseSubprocessTransport.__del__ when an asyncio subprocess transport is
# garbage-collected after its loop has been closed on app shutdown
# (https://bugs.python.org/issue39232).
_original_subprocess_transport_del = _asyncio_base_subprocess.BaseSubprocessTransport.__del__


def _safe_subprocess_transport_del(self, *args, **kwargs):
    try:
        _original_subprocess_transport_del(self, *args, **kwargs)
    except (RuntimeError, AttributeError):
        pass


_asyncio_base_subprocess.BaseSubprocessTransport.__del__ = _safe_subprocess_transport_del


class _AsyncLoopThread:
    """Dedicated asyncio loop for long-lived subprocess protocol clients."""

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run, name="superqode-acp-loop", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        loop.run_forever()
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    def run(self, coro, timeout: float | None = None):
        if self._loop is None:
            raise RuntimeError("ACP event loop is not ready")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
