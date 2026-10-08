"""Persistent async JSON-RPC transport for the installed Codex app-server."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any


class CodexRPCError(RuntimeError):
    def __init__(self, method: str, error: dict[str, Any]):
        self.code = error.get("code")
        self.data = error.get("data")
        super().__init__(f"Codex {method}: {error.get('message', 'request failed')}")


class CodexTransport:
    """Read continuously, including while a server request awaits user input.

    This object belongs to one asyncio loop. It never retries an RPC: a lost
    turn/start response can occur after tools have already executed.
    """

    def __init__(
        self,
        on_notification: Callable[[str, dict[str, Any]], None],
        on_request: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
        on_error: Callable[[BaseException], None],
        *,
        request_timeout: float = 60,
    ):
        self.on_notification = on_notification
        self.on_request = on_request
        self.on_error = on_error
        self.request_timeout = request_timeout
        self.process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, tuple[str, asyncio.Future]] = {}
        self._server_tasks: dict[Any, asyncio.Task] = {}
        self._reader: asyncio.Task | None = None
        self._stderr_reader: asyncio.Task | None = None
        self._stderr: deque[str] = deque(maxlen=40)
        self._write_lock = asyncio.Lock()
        self._next_id = 0
        self._closing = False
        self._failure: BaseException | None = None

    async def start(self, argv: list[str], *, cwd: str, env: dict[str, str]) -> None:
        self.process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read(), name="codex-cli-rpc")
        self._stderr_reader = asyncio.create_task(self._drain_stderr(), name="codex-cli-stderr")

    async def _write(self, message: dict[str, Any]) -> None:
        if self._failure:
            raise RuntimeError(str(self._failure)) from self._failure
        proc = self.process
        if self._closing or proc is None or proc.returncode is not None or proc.stdin is None:
            raise RuntimeError("Codex app-server is not running")
        async with self._write_lock:
            proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
            await proc.stdin.drain()

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._write({"method": method, "params": params or {}})

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        rid = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = (method, future)
        try:
            await self._write({"id": rid, "method": method, "params": params or {}})
            return await asyncio.wait_for(future, self.request_timeout)
        except TimeoutError as exc:
            raise RuntimeError(f"Codex {method} timed out; the request was not replayed") from exc
        finally:
            self._pending.pop(rid, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # A write can fail after the reader has already failed this
                # future. Retrieve its exception even when nobody awaits it.
                future.exception()

    async def _answer(self, message: dict[str, Any]) -> None:
        rid = message["id"]
        try:
            result = await self.on_request(message["method"], message.get("params") or {})
            await self._write({"id": rid, "result": result})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closing and not self._failure:
                try:
                    await self._write({"id": rid, "error": {"code": -32603, "message": str(exc)}})
                except Exception:
                    pass
        finally:
            if self._server_tasks.get(rid) is asyncio.current_task():
                self._server_tasks.pop(rid, None)

    async def _read(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise RuntimeError("Codex sent a non-object JSON-RPC message")
                if "method" in message:
                    if "id" in message:
                        rid = message["id"]
                        self._server_tasks[rid] = asyncio.create_task(self._answer(message))
                    else:
                        params = message.get("params") or {}
                        if message["method"] == "serverRequest/resolved":
                            task = self._server_tasks.pop(params.get("requestId"), None)
                            if task:
                                task.cancel()
                        self.on_notification(message["method"], params)
                elif (pending := self._pending.get(message.get("id"))) is not None:
                    method, future = pending
                    if not future.done():
                        if "error" in message:
                            future.set_exception(CodexRPCError(method, message["error"]))
                        else:
                            future.set_result(message.get("result") or {})
            if not self._closing:
                raise RuntimeError("Codex app-server closed stdout unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closing:
                self._failure = exc
                self._fail_pending(exc)
                self.on_error(exc)
                # A protocol failure must not leave an unobserved agent running.
                if self.process.returncode is None:
                    try:
                        self.process.terminate()
                    except ProcessLookupError:
                        pass

    def _fail_pending(self, error: BaseException) -> None:
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(error)

    async def _drain_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        # Chunk reads also drain diagnostics without newlines or with lines
        # larger than StreamReader's limit. Stderr never drives protocol state.
        while chunk := await self.process.stderr.read(4096):
            self._stderr.extend(chunk.decode(errors="replace").splitlines())

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr)

    async def cancel_server_requests(self) -> None:
        tasks = list(self._server_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        self._closing = True
        self._fail_pending(RuntimeError("Codex app-server connection closed"))
        tasks = list(self._server_tasks.values())
        tasks.extend(task for task in (self._reader, self._stderr_reader) if task)
        for task in tasks:
            task.cancel()
        proc = self.process
        if proc is not None:
            if proc.stdin:
                proc.stdin.close()
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._server_tasks.clear()
        self.process = None
