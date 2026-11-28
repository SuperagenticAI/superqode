"""Authenticated, loopback MCP bridge for desktop-controlled ACP v2 host tools."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hmac
from pathlib import Path
import secrets
import socket


class HostMcpBridge:
    def __init__(self, root: Path, permission, terminals):
        self.root, self.permission, self.terminals = root, permission, terminals
        self.token = secrets.token_urlsafe(32)
        self.server = None
        self.task = None
        self.socket = None

    async def read_text_file(self, path: str) -> str:
        from .acp_worker import scoped_path

        target = scoped_path(self.root, path)
        if target.stat().st_size > 1_000_000:
            raise ValueError("File exceeds the desktop preview size limit")
        return await asyncio.to_thread(target.read_text, encoding="utf-8")

    async def write_text_file(self, path: str, content: str) -> str:
        from .acp_worker import scoped_path

        target = scoped_path(self.root, path)
        if len(content) > 1_000_000:
            raise ValueError("Write exceeds the desktop preview size limit")
        selected = await self.permission(
            [
                {"kind": "allow_once", "optionId": "allow"},
                {"kind": "reject_once", "optionId": "deny"},
            ],
            {
                "title": "Write " + str(target.relative_to(self.root)),
                "path": str(target),
                "content": content,
            },
        )
        if selected != "allow":
            raise PermissionError("File write denied in the native app")
        # Check again after user interaction, including symlink changes.
        target = scoped_path(self.root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")
        return "Written"

    async def execute(self, command: str, args: list[str], cwd: str = ".") -> dict:
        return await self.terminals.create(
            {"command": command, "args": args, "cwd": cwd, "env": []}
        )

    async def terminal_output(self, terminal_id: str) -> dict:
        return await self.terminals.output({"terminalId": terminal_id})

    async def terminal_wait(self, terminal_id: str) -> dict:
        return await self.terminals.wait_for_exit({"terminalId": terminal_id})

    async def terminal_cancel(self, terminal_id: str) -> dict:
        return await self.terminals.kill({"terminalId": terminal_id})

    async def start(self) -> dict:
        from fastmcp import FastMCP
        import uvicorn

        mcp = FastMCP("SuperQode desktop host")
        for tool in [
            self.read_text_file,
            self.write_text_file,
            self.execute,
            self.terminal_output,
            self.terminal_wait,
            self.terminal_cancel,
        ]:
            mcp.tool(tool)
        application = mcp.http_app(path="/mcp", json_response=True, stateless_http=True)
        token = self.token

        async def authorized(scope, receive, send):
            if scope["type"] == "http":
                headers = dict(scope.get("headers", []))
                supplied = headers.get(b"authorization", b"").decode("latin1")
                if not hmac.compare_digest(supplied, "Bearer " + token):
                    await send({"type": "http.response.start", "status": 401, "headers": []})
                    await send({"type": "http.response.body", "body": b"Unauthorized"})
                    return
            await application(scope, receive, send)

        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        port = self.socket.getsockname()[1]

        class EmbeddedServer(uvicorn.Server):
            @contextmanager
            def capture_signals(self):
                # The desktop worker owns process cancellation, not its HTTP helper.
                yield

        self.server = EmbeddedServer(
            uvicorn.Config(authorized, log_level="error", access_log=False)
        )
        self.task = asyncio.create_task(self.server.serve(sockets=[self.socket]))
        try:
            async with asyncio.timeout(10):
                while not self.server.started:
                    if self.task.done():
                        await self.task
                        raise RuntimeError("Host MCP bridge did not start")
                    await asyncio.sleep(0.01)
        except BaseException:
            await self.close()
            raise
        return {
            "type": "http",
            "name": "superqode-desktop-host",
            "url": f"http://127.0.0.1:{port}/mcp",
            "headers": [{"name": "Authorization", "value": "Bearer " + token}],
        }

    async def close(self):
        if self.server:
            self.server.should_exit = True
        if self.task:
            try:
                await asyncio.wait_for(self.task, 3)
            except asyncio.TimeoutError:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
        if self.socket:
            self.socket.close()
