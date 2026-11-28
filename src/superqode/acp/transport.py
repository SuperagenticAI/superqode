"""Strict JSON-RPC v2 transport and a stdio pre-router for the existing v1 SDK."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from .protocol import ProtocolError, select_version, validate_envelope


class ReplayReader(asyncio.StreamReader):
    """Preserve the parsed initialization and all bytes buffered by asyncio."""

    def __init__(self, reader: asyncio.StreamReader, initial: bytes):
        super().__init__()
        self.reader, self.initial = reader, initial

    async def readline(self):
        if self.initial:
            line, self.initial = self.initial, b""
            return line
        return await self.reader.readline()


class RpcConnection:
    def __init__(
        self, reader, writer, agent=None, supported_versions=(1, 2), *, agent_factory=None
    ):
        self.reader, self.writer, self.agent = reader, writer, agent
        self.agent_factory = agent_factory
        self.pending: dict[Any, asyncio.Future] = {}
        self.incoming: dict[Any, asyncio.Task] = {}
        self.tasks: set[asyncio.Task] = set()
        self.next_id = 0
        self.lock = asyncio.Lock()
        self.initialized = False
        self.other_request = False
        self.closed = False
        self.closing = False
        self.switch_to_v1: bytes | None = None
        self.supported_versions = supported_versions
        if agent is not None:
            agent.connection = self

    async def send(self, payload):
        if self.closed:
            raise ConnectionError("ACP connection is closed")
        async with self.lock:
            self.writer.write(json.dumps(payload, ensure_ascii=False).encode() + b"\n")
            await self.writer.drain()

    async def notify(self, method, **params):
        await self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method, **params):
        identity = f"agent-{self.next_id}"
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[identity] = future
        try:
            await self.send({"jsonrpc": "2.0", "id": identity, "method": method, "params": params})
            return await future
        except asyncio.CancelledError:
            with contextlib.suppress(ConnectionError, BrokenPipeError):
                await self.notify("$/cancel_request", requestId=identity)
            raise
        finally:
            self.pending.pop(identity, None)

    async def error(self, identity, error):
        await self.send({"jsonrpc": "2.0", "id": identity, "error": error.wire()})

    async def _dispatch(self, message):
        method, params = message["method"], message.get("params", {})
        is_request = "id" in message
        identity = message.get("id")
        try:
            result = await self.agent.handle(method, params)
            if is_request:
                await self.send(
                    {
                        "jsonrpc": "2.0",
                        "id": identity,
                        "result": result if result is not None else {},
                    }
                )
        except ProtocolError as exc:
            if is_request:
                await self.error(identity, exc)
        except asyncio.CancelledError:
            if is_request and not self.closed:
                await self.error(identity, ProtocolError(-32800, "Request cancelled"))
        except Exception:
            if is_request and not self.closed:
                # Do not expose provider credentials or tool arguments through errors.
                await self.error(identity, ProtocolError(-32603, "Agent request failed"))
        finally:
            if is_request:
                self.incoming.pop(identity, None)

    async def run(self):
        try:
            while line := await self.reader.readline():
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    await self.error(None, ProtocolError(-32700, "Invalid JSON"))
                    continue
                try:
                    validate_envelope(message)
                except ProtocolError as exc:
                    if isinstance(message, dict) and (
                        "method" not in message
                        or (
                            exc.code == -32602
                            and "id" not in message
                            and isinstance(message.get("method"), str)
                        )
                    ):
                        # Invalid peer responses and valid notifications never get replies.
                        continue
                    identity = message.get("id") if isinstance(message, dict) else None
                    await self.error(identity if type(identity) in (str, int) else None, exc)
                    continue
                if "method" not in message:
                    future = self.pending.get(message.get("id"))
                    if future and not future.done():
                        if "error" in message:
                            error = message["error"]
                            future.set_exception(
                                ProtocolError(
                                    error.get("code", -32603),
                                    error.get("message", "Client error"),
                                    error.get("data"),
                                )
                            )
                        else:
                            future.set_result(message["result"])
                    continue
                method = message["method"]
                if method == "initialize":
                    if "id" not in message:
                        continue
                    if self.other_request:
                        await self.error(
                            message["id"],
                            ProtocolError(-32600, "Initialization is already complete"),
                        )
                        continue
                    try:
                        version = select_version(
                            message.get("params", {}).get("protocolVersion"),
                            self.supported_versions,
                        )
                        if version == 1:
                            self.switch_to_v1 = line
                            break
                        if self.agent is None:
                            self.agent = self.agent_factory()
                            self.agent.connection = self
                        await self.agent.initialize(message.get("params", {}))
                        result = self.agent.initialization()
                        await self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})
                        self.initialized = True
                    except ProtocolError as exc:
                        await self.error(message["id"], exc)
                    except Exception:
                        await self.error(
                            message["id"], ProtocolError(-32603, "Unable to initialize ACP agent")
                        )
                    continue
                if not self.initialized:
                    if "id" in message:
                        await self.error(
                            message["id"], ProtocolError(-32600, "Initialize the connection first")
                        )
                    continue
                if method == "$/cancel_request":
                    task = self.incoming.get(message.get("params", {}).get("requestId"))
                    if task:
                        task.cancel()
                    continue
                if "id" in message:
                    self.other_request = True
                    if message["id"] in self.incoming:
                        await self.error(
                            message["id"], ProtocolError(-32600, "Request id is already pending")
                        )
                        continue
                task = asyncio.create_task(self._dispatch(message))
                if "id" in message:
                    self.incoming[message["id"]] = task
                self.tasks.add(task)

                def finished(done, message=message):
                    self.tasks.discard(done)
                    identity = message.get("id")
                    if not done.cancelled():
                        done.exception()  # Consume failures when the peer has closed its pipe.
                    if done.cancelled() and identity in self.incoming and not self.closing:
                        self.incoming.pop(identity, None)
                        reply = asyncio.create_task(
                            self.error(identity, ProtocolError(-32800, "Request cancelled"))
                        )
                        self.tasks.add(reply)
                        reply.add_done_callback(self.tasks.discard)

                task.add_done_callback(finished)
        finally:
            self.closing = True
            # Settle requests before cancelling session tasks that might await them.
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("ACP client disconnected"))
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            if self.agent is not None:
                await self.agent.shutdown()
            self.closed = True


async def run_dual_agent(
    v1_agent, v2_factory, *, reader=None, writer=None, supported_versions=(1, 2)
):
    from acp import run_agent
    from acp.stdio import stdio_streams

    if reader is None:
        reader, writer = await stdio_streams(limit=50 * 1024 * 1024)
    # V1 connections must not depend on v2's private storage being writable.
    connection = RpcConnection(
        reader, writer, supported_versions=supported_versions, agent_factory=v2_factory
    )
    await connection.run()
    if connection.switch_to_v1:
        await run_agent(
            v1_agent,
            input_stream=writer,
            output_stream=ReplayReader(reader, connection.switch_to_v1),
        )
