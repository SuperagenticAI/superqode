"""Attach to an explicitly selected, user-owned loopback Codex app-server."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from urllib.parse import urlsplit

from .codex_transport import CodexTransport


def local_codex_endpoint(endpoint):
    parsed = urlsplit(endpoint)
    try:
        valid = (
            parsed.scheme == "ws"
            and parsed.hostname
            and ipaddress.ip_address(parsed.hostname).is_loopback
            and parsed.port
            and not parsed.username
            and not parsed.password
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "Codex attachment requires ws://127.0.0.1:<port> or ws://[::1]:<port> on this computer"
        )
    return endpoint


class CodexDaemonTransport(CodexTransport):
    def __init__(self, *args, endpoint, **kwargs):
        super().__init__(*args, **kwargs)
        self.endpoint = local_codex_endpoint(endpoint)
        self.socket = None

    async def start(self, argv, *, cwd, env):
        from websockets.asyncio.client import connect

        self.socket = await connect(
            self.endpoint, proxy=None, open_timeout=10, max_size=16 * 1024 * 1024
        )
        self._reader = asyncio.create_task(self._read_socket(), name="codex-daemon-rpc")

    async def _write(self, message):
        if self._failure:
            raise RuntimeError(str(self._failure)) from self._failure
        if self.socket is None or self._closing:
            raise RuntimeError("Codex daemon is not connected")
        async with self._write_lock:
            await self.socket.send(json.dumps(message, ensure_ascii=False))

    async def _read_socket(self):
        try:
            async for message in self.socket:
                self._dispatch(json.loads(message))
            if not self._closing:
                raise RuntimeError("Codex daemon disconnected; requests were not replayed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closing:
                self._failure = exc
                self._fail_pending(exc)
                self.on_error(exc)
                await self.socket.close()

    async def close(self):
        self._closing = True
        self._fail_pending(RuntimeError("Codex daemon connection closed"))
        await self.cancel_server_requests()
        if self.socket:
            await self.socket.close()
            self.socket = None
        if self._reader:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        # The listener belongs to the user. Never terminate it on detach.
