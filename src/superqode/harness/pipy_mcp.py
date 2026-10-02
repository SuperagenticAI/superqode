"""Deferred PiPy tools using SuperQode's shared MCP manager.

The model sees two stable schemas, independent of catalogue size. Discovery
returns schemas on demand; execution resolves and validates the current one.
PiPy keeps its native permission semantics: server declarations are trusted
process configuration, and tools execute with the process's permissions.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from pathlib import Path

import jsonschema

from superqode.mcp.client import MCPClientManager
from superqode.pipy.messages import ImageContent, TextContent
from superqode.pipy.tools.base import AgentTool, AgentToolResult

from superqode.mcp.config import resolve_mcp_config


class PiPyMCPTools:
    def __init__(self, manager: MCPClientManager | None = None) -> None:
        self.manager = manager
        self._startup: dict[str, asyncio.Task[bool]] = {}
        self.sources: dict[str, str] = {}
        self.errors: list[str] = []
        self.tools: tuple[AgentTool, ...] = ()
        if manager is not None:
            self.tools = (
                AgentTool(
                    name="mcp_search",
                    label="Search MCP tools",
                    description="Search connected MCP servers for tool schemas before calling them.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "server": {"type": "string"},
                            "kind": {"type": "string", "enum": ["tool", "resource", "prompt"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    execute_fn=self._search_cancellable,
                    execution_mode="sequential",
                ),
                AgentTool(
                    name="mcp_call",
                    label="Call MCP tool",
                    description="Call a discovered MCP tool, read a resource URI, or get a prompt. Set kind (default tool), server, tool (name or URI), and arguments.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "server": {"type": "string"},
                            "tool": {"type": "string"},
                            "kind": {"type": "string", "enum": ["tool", "resource", "prompt"]},
                            "arguments": {"type": "object"},
                        },
                        "required": ["server", "tool", "arguments"],
                        "additionalProperties": False,
                    },
                    execute_fn=self._call_cancellable,
                    execution_mode="sequential",
                ),
            )

    @classmethod
    async def create(cls, config: dict[str, Any], *, cwd: Path | None = None) -> PiPyMCPTools:
        resolution = resolve_mcp_config(config, cwd=cwd)
        if not resolution.servers:
            instance = cls()
            instance.sources, instance.errors = resolution.sources, resolution.errors
            return instance
        manager = await MCPClientManager().__aenter__()
        instance = cls(manager)
        instance.sources, instance.errors = resolution.sources, resolution.errors
        try:
            for declaration in resolution.servers.values():
                manager.add_server(declaration)
            for sid, server in manager.get_server_configs().items():
                if server.enabled and server.auto_connect:
                    instance._startup[sid] = asyncio.create_task(manager.connect(sid))
            return instance
        except BaseException:
            await instance.close()
            raise

    async def _connected(self, server: str) -> None:
        assert self.manager is not None
        config = self.manager.get_server_configs().get(server)
        if config is None or not config.enabled:
            raise ValueError(f"MCP server {server!r} is unknown or disabled")
        if not await asyncio.wait_for(self.manager.connect(server), timeout=30):
            raise RuntimeError(f"MCP server {server!r} is unavailable")

    async def _cancellable(self, coroutine, signal):
        task = asyncio.create_task(coroutine)
        unsubscribe = signal.add_listener(task.cancel) if signal else lambda: None
        try:
            return await task
        finally:
            unsubscribe()

    async def _search_cancellable(self, call_id, args, signal=None, on_update=None):
        return await self._cancellable(self._search(call_id, args, signal, on_update), signal)

    async def _call_cancellable(self, call_id, args, signal=None, on_update=None):
        return await self._cancellable(self._call(call_id, args, signal, on_update), signal)

    async def _search(
        self, call_id: str, args: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        assert self.manager is not None
        if signal:
            signal.throw_if_aborted()
        server = args.get("server")
        ids = [server] if server else self.manager.configured_server_ids()
        outcomes = await asyncio.gather(
            *(self._connected(sid) for sid in ids), return_exceptions=True
        )
        errors = {
            sid: str(outcome)
            for sid, outcome in zip(ids, outcomes)
            if isinstance(outcome, BaseException)
        }
        kind = args.get("kind", "tool")
        if kind != "tool":
            resources = (
                self.manager.list_all_resources()
                if kind == "resource"
                else self.manager.list_all_prompts()
            )
            words = str(args["query"]).lower().split()
            records = [
                {
                    "server": item.server_id,
                    "name": item.name,
                    "description": item.description or "",
                    **(
                        {"uri": item.uri}
                        if kind == "resource"
                        else {
                            "arguments": [
                                {
                                    "name": a.name,
                                    "required": a.required,
                                    "description": a.description,
                                }
                                for a in item.arguments
                            ]
                        }
                    ),
                }
                for item in resources
                if not server or item.server_id == server
            ]
            selected = [
                r for r in records if not words or any(w in json.dumps(r).lower() for w in words)
            ][: args.get("limit", 5)]
            payload = {kind + "s": selected, "errors": errors}
            return AgentToolResult(content=[TextContent(json.dumps(payload))], details=payload)
        candidates = [
            tool for tool in self.manager.list_all_tools() if not server or tool.server_id == server
        ]
        from superqode.tools.discovery import DiscoverySettings, ToolDescriptor, retrieve

        limit = args.get("limit", 5)
        catalogue = [
            ToolDescriptor(
                id=json.dumps([t.server_id, t.name]),
                exposed_name=t.name,
                original_name=t.name,
                namespace=t.server_id,
                source="mcp",
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in candidates
        ]
        selected, _ = await retrieve(
            str(args["query"]),
            catalogue,
            DiscoverySettings(search_limit=limit, candidate_limit=limit),
        )
        payload = {
            "tools": [
                {
                    "server": c.descriptor.namespace,
                    "name": c.descriptor.original_name,
                    "description": c.descriptor.description,
                    "parameters": dict(c.descriptor.input_schema),
                }
                for c in selected
            ],
            "errors": errors,
        }
        return AgentToolResult(content=[TextContent(json.dumps(payload))], details=payload)

    async def _call(self, call_id: str, args: dict, signal=None, on_update=None) -> AgentToolResult:
        assert self.manager is not None
        if signal:
            signal.throw_if_aborted()
        server, name = args["server"], args["tool"]
        await self._connected(server)
        if args.get("kind") == "resource":
            async with asyncio.timeout(60):
                resource = await self.manager.read_resource(server, name)
            if resource is None:
                raise ValueError("MCP resource is unavailable")
            if resource.blob and (resource.mime_type or "").startswith("image/"):
                content = [ImageContent(data=resource.blob, mime_type=resource.mime_type)]
            else:
                content = [
                    TextContent(
                        resource.text or json.dumps({"uri": resource.uri, "blob": resource.blob})
                    )
                ]
            return AgentToolResult(content=content, details={"server": server, "resource": name})
        if args.get("kind") == "prompt":
            prompt = next(
                (
                    p
                    for p in self.manager.list_all_prompts()
                    if p.server_id == server and p.name == name
                ),
                None,
            )
            if prompt is None:
                raise ValueError("Unknown MCP prompt")
            required = {a.name for a in prompt.arguments if a.required}
            if not required <= args["arguments"].keys() or any(
                not isinstance(v, str) for v in args["arguments"].values()
            ):
                raise ValueError("MCP prompt arguments require named strings")
            async with asyncio.timeout(60):
                result = await self.manager.get_prompt(server, name, args["arguments"])
            if result is None:
                raise ValueError("MCP prompt is unavailable")
            return AgentToolResult(
                content=[TextContent("\n".join(f"{m.role}: {m.content}" for m in result.messages))],
                details={"server": server, "prompt": name},
            )
        tool = self.manager.get_tool(server, name)
        if tool is None:
            raise ValueError(f"Unknown MCP tool {server!r}/{name!r}")
        jsonschema.validate(args["arguments"], tool.input_schema)
        task = asyncio.create_task(
            self.manager.execute_tool(server, name, args["arguments"], timeout=60)
        )
        unsubscribe = signal.add_listener(task.cancel) if signal else lambda: None
        try:
            result = await task
        finally:
            unsubscribe()
        if result.is_error:
            text = "\n".join(
                str(item.get("text", "")) for item in result.content if isinstance(item, dict)
            )
            raise RuntimeError(result.error_message or text or "MCP tool failed")
        blocks = []
        for item in result.content:
            if item.get("type") == "text":
                blocks.append(TextContent(item["text"]))
            elif item.get("type") == "image":
                blocks.append(ImageContent(data=item["data"], mime_type=item["mimeType"]))
            else:
                blocks.append(TextContent(json.dumps(item)))
        if result.structured_content is not None and not any(
            isinstance(b, TextContent) for b in blocks
        ):
            blocks.append(TextContent(json.dumps(result.structured_content)))
        return AgentToolResult(
            content=blocks,
            details={
                "server": server,
                "tool": name,
                "structured_content": result.structured_content,
                "content": result.content,
            },
        )

    async def close(self) -> None:
        for task in self._startup.values():
            task.cancel()
        await asyncio.gather(*self._startup.values(), return_exceptions=True)
        self._startup.clear()
        if self.manager is not None:
            await self.manager.__aexit__(None, None, None)
            self.manager = None

    def status(self) -> dict[str, Any]:
        """Inspect without connecting or exposing credentials."""
        configs = self.manager.get_server_configs() if self.manager else {}
        return {
            "servers": [
                {
                    "id": sid,
                    "enabled": config.enabled,
                    "state": self.manager.get_connection_state(sid).value,
                    "transport": config.config.transport,
                    "source": self.sources.get(sid),
                    "tools": sum(t.server_id == sid for t in self.manager.list_all_tools()),
                }
                for sid, config in sorted(configs.items())
            ],
            "errors": list(self.errors),
        }

    async def control(self, action: str, server: str | None = None) -> dict[str, Any]:
        """Host controls, never exposed as model-callable tools."""
        if action in {"status", "list"}:
            return self.status()
        if not self.manager or server not in self.manager.get_server_configs():
            raise ValueError("Unknown MCP server; inspect status first")
        config = self.manager.get_server_configs()[server]
        if action != "logout" and not config.enabled:
            raise ValueError("MCP server is disabled in configuration")
        if action == "login":
            ok = await self.manager.authenticate_server(server)
            if ok:
                ok = await self.manager.reconnect(server)
        elif action == "logout":
            await self.manager.disconnect(server)
            await self.manager.clear_server_credentials(server)
            ok = True
        elif action == "reconnect":
            ok = await self.manager.reconnect(server)
        else:
            raise ValueError("Use status, login, logout or reconnect")
        return {"action": action, "server": server, "success": ok, **self.status()}
