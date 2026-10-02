"""Opt-in PiPy Monty tool composition through PiPy's existing host boundary."""

from __future__ import annotations

import inspect
import json
import asyncio
import difflib
import jsonschema
from dataclasses import replace
from pathlib import Path

from superqode.execution_recovery import recovery_scope, input_fingerprint, active_recovery
from superqode.pipy.harness_events import ToolCallEvent, ToolResultEvent
from superqode.pipy.messages import TextContent
from superqode.pipy.tools.base import AgentTool, AgentToolResult
from superqode.pipy.tools.registry import READ_ONLY_TOOL_NAMES
from superqode.pipy.validation import validate_tool_arguments
from superqode.tools.monty_program import cancellable_program
from .pipy_governance import _call_policy, _result_policy


class PiPyProgramHost:
    def __init__(self, cwd: Path, config: dict):
        self.cwd = cwd
        self.config = config
        self.harness = None
        self.mcp = None
        self._values = {}
        self._writes = {}
        self._base = {}
        self._program_id = ""

        raw = config.get("monty", {}).get("mcp_tools", [])
        if not isinstance(raw, list) or len(raw) > 32:
            raise ValueError("monty.mcp_tools requires at most 32 explicit capabilities")
        self.remote = {}
        for entry in raw:
            if (
                not isinstance(entry, dict)
                or entry.get("read_only") is not True
                or not isinstance(entry.get("server"), str)
                or not isinstance(entry.get("tool"), str)
            ):
                raise ValueError(
                    "Each Monty MCP capability requires server, tool and read_only: true"
                )
            self.remote[(entry["server"], entry["tool"])] = entry.get("replay_safe") is True

    async def begin_program(self, program_id):
        """Load only successful store commits on the current session branch."""
        self._program_id = program_id
        self._values, self._writes = {}, {}
        if self.harness:
            for entry in await self.harness._session.get_branch():
                if getattr(entry, "custom_type", None) != "python-program-store":
                    continue
                if entry.data["program_id"] == program_id:
                    break  # Reuse validates against this call's original inputs.
                self._values = dict(entry.data["values"])
        self._base = dict(self._values)

    def program_state(self):
        return {"writes": self._writes}

    async def commit_program(self, result):
        writes = result.get("program_state", {}).get("writes", {})
        if not writes or not self.harness:
            return
        branch = await self.harness._session.get_branch()
        if any(
            getattr(e, "custom_type", None) == "python-program-store"
            and e.data["program_id"] == self._program_id
            for e in branch
        ):
            return
        await self.harness._session.append_custom_entry(
            "python-program-store",
            {
                "program_id": self._program_id,
                "values": self._values,
            },
        )

    def _tools(self):
        if self.harness is None:
            raise RuntimeError("PiPy program host is not attached")
        return {
            t.name: t
            for t in self.harness.get_active_tools()
            if t.name in {*READ_ONLY_TOOL_NAMES, "mcp_search", "mcp_call"}
        }

    def identity(self):
        return {
            "config": self.config,
            "store": self._base,
            "tools": {n: dict(t.parameters) for n, t in self._tools().items()},
            "mcp_config": {
                sid: str(config) for sid, config in self.mcp.manager.get_server_configs().items()
            }
            if self.mcp and self.mcp.manager
            else {},
        }

    def _allowed(self, name, arguments):
        tool = self._tools().get(name)
        if tool is None:
            matches = difflib.get_close_matches(str(name), self._tools(), n=3)
            hint = f"; try {', '.join(matches)}" if matches else "; use tool_search first"
            raise ValueError(f"Tool is unavailable to the read-only Monty program: {name}{hint}")
        if name == "mcp_call":
            if (
                arguments.get("kind", "tool") != "tool"
                or (arguments.get("server"), arguments.get("tool")) not in self.remote
            ):
                raise ValueError("MCP program calls require an explicit host read-only capability")
            safe = self.remote[(arguments["server"], arguments["tool"])]
        else:
            safe = name in READ_ONLY_TOOL_NAMES
        denied = _call_policy(tool, arguments)
        if denied is not None:
            raise ValueError(denied.text)
        return tool, safe

    async def prepare(self, function, args, kwargs, call_id):
        # Bind against host-owned signatures; generated code cannot supply IDs,
        # descriptors, policy, ownership, or replay-safety declarations.
        if function in {"store", "load"}:
            signature = _store_signature if function == "store" else _load_signature
            bound = inspect.signature(signature).bind(*args, **kwargs)
            key = bound.arguments["key"]
            if not isinstance(key, str) or not key or len(key.encode()) > 256:
                raise ValueError("Store keys require 1–256 bytes")
            value = bound.arguments.get("value")
            if len(json.dumps(value, allow_nan=False).encode()) > 16_000:
                raise ValueError("Store values are limited to 16,000 bytes")
            return {
                "function": function,
                "key": key,
                "value": value,
                "replay_safe": True,
                "call_id": call_id,
            }
        if function == "tool_parallel":
            bound = inspect.signature(_parallel_signature).bind(*args, **kwargs)
            calls = bound.arguments["calls"]
            if not isinstance(calls, list) or not 1 <= len(calls) <= 8:
                raise ValueError("tool_parallel requires 1–8 native read calls")
            prepared = []
            for index, call in enumerate(calls):
                if not isinstance(call, dict) or call.get("name") not in READ_ONLY_TOOL_NAMES:
                    raise ValueError("Parallel programs require trusted native read tools")
                child = await self.prepare(
                    "tool_call", [call["name"], call.get("arguments", {})], {}, f"{call_id}/{index}"
                )
                if child["name"] not in READ_ONLY_TOOL_NAMES:
                    raise ValueError("Parallel programs require trusted native read tools")
                prepared.append(child)
            return {
                "function": function,
                "calls": prepared,
                "replay_safe": True,
                "call_id": call_id,
            }
        if function == "tool_search":
            bound = inspect.signature(_search_signature).bind(*args, **kwargs)
            bound.apply_defaults()
            query, limit = bound.arguments["query"], bound.arguments["limit"]
            if not isinstance(query, str) or not isinstance(limit, int) or not 1 <= limit <= 20:
                raise ValueError("tool_search requires a string query and limit 1–20")
            return {
                "function": function,
                "query": query,
                "limit": limit,
                "replay_safe": True,
                "call_id": call_id,
            }
        if function != "tool_call":
            raise ValueError(f"Unknown program host function: {function}")
        bound = inspect.signature(_call_signature).bind(*args, **kwargs)
        name, arguments = bound.arguments["name"], bound.arguments["arguments"]
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("tool_call requires a tool name and arguments object")
        tool, _ = self._allowed(name, arguments)
        if tool.prepare_arguments:
            arguments = tool.prepare_arguments(arguments)
        arguments = validate_tool_arguments(name, tool.parameters, arguments)
        outcome = await self.harness._emit_hook(ToolCallEvent(call_id, name, dict(arguments)))
        if outcome and outcome.block:
            raise ValueError(outcome.reason or "Program tool blocked by an extension")
        if outcome and outcome.arguments is not None:
            arguments = validate_tool_arguments(name, tool.parameters, dict(outcome.arguments))
        # An extension may modify server/tool/path. Re-check capabilities and
        # contextual policy after modification, just like the ordinary loop.
        tool, safe = self._allowed(name, arguments)
        remote_schema = None
        if name == "mcp_call" and self.mcp and self.mcp.manager:
            await self.mcp._connected(arguments["server"])
            remote = self.mcp.manager.get_tool(arguments["server"], arguments["tool"])
            if remote is None:
                raise ValueError("Configured MCP program capability is no longer available")
            jsonschema.validate(arguments.get("arguments", {}), remote.input_schema)
            remote_schema = input_fingerprint(remote.input_schema)
        return {
            "function": function,
            "name": name,
            "arguments": arguments,
            "replay_safe": safe,
            "call_id": call_id,
            **({"remote_schema": remote_schema} if remote_schema else {}),
        }

    async def execute(self, prepared, call_id, signal):
        if signal:
            signal.throw_if_aborted()
        if prepared["function"] == "load":
            return self._values.get(prepared["key"])
        if prepared["function"] == "store":
            key, value = prepared["key"], prepared["value"]
            values = {**self._values, key: value}
            if value is None:
                values.pop(key, None)
            if len(json.dumps(values, allow_nan=False).encode()) > 32_000:
                raise ValueError("Program store is limited to 32,000 bytes")
            writes = {**self._writes, key: value}
            if len(json.dumps(writes, allow_nan=False).encode()) > 32_000:
                raise ValueError("Program store writes are limited to 32,000 bytes")
            self._values, self._writes = values, writes
            return None
        if prepared["function"] == "tool_parallel":
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(self.execute(child, child["call_id"], signal))
                    for child in prepared["calls"]
                ]
            return [task.result() for task in tasks]
        if prepared["function"] == "tool_search":
            from superqode.tools.discovery import DiscoverySettings, ToolDescriptor, retrieve

            catalogue = [
                ToolDescriptor(
                    id=t.name,
                    exposed_name=t.name,
                    original_name=t.name,
                    source="native",
                    description=t.description,
                    input_schema=dict(t.parameters),
                )
                for t in self._tools().values()
            ]
            if self.mcp and self.mcp.manager and "mcp_call" in self._tools():
                servers = sorted({sid for sid, _ in self.remote})
                await asyncio.gather(
                    *(self.mcp._connected(sid) for sid in servers), return_exceptions=True
                )
                catalogue.extend(
                    ToolDescriptor(
                        id=json.dumps([tool.server_id, tool.name]),
                        exposed_name="mcp_call",
                        original_name=tool.name,
                        namespace=tool.server_id,
                        source="mcp",
                        description=tool.description,
                        input_schema=tool.input_schema,
                    )
                    for tool in self.mcp.manager.list_all_tools()
                    if (tool.server_id, tool.name) in self.remote
                )
            selected, _ = await retrieve(
                prepared["query"],
                catalogue,
                DiscoverySettings(
                    search_limit=prepared["limit"], candidate_limit=prepared["limit"]
                ),
            )
            return [
                {
                    "name": candidate.descriptor.exposed_name,
                    "description": candidate.descriptor.description,
                    "parameters": dict(candidate.descriptor.input_schema),
                    **(
                        {
                            "server": candidate.descriptor.namespace,
                            "tool": candidate.descriptor.original_name,
                            "call_arguments": {
                                "server": candidate.descriptor.namespace,
                                "tool": candidate.descriptor.original_name,
                                "arguments": {},
                            },
                        }
                        if candidate.descriptor.source == "mcp"
                        else {}
                    ),
                }
                for candidate in selected
            ]
        tool, _ = self._allowed(prepared["name"], prepared["arguments"])
        # The program journal owns this call. Avoid a second, differently
        # shaped AgentTool ledger entry while retaining its policy wrapper.
        with recovery_scope(None):
            result = await tool.execute(call_id, prepared["arguments"], signal)
        value = self._pack(result)
        return await self._project(prepared, call_id, value)

    def _pack(self, result):
        output = result.text.encode()
        details = result.details
        omitted = len(json.dumps(details, default=str).encode()) > 8_000
        return {
            "success": not (isinstance(details, dict) and details.get("governance_denied")),
            "output": output[:8_000].decode(errors="ignore"),
            "details": None if omitted else details,
            "details_omitted": omitted,
            "output_truncated": len(output) > 8_000,
            "images_omitted": sum(not isinstance(b, TextContent) for b in result.content),
            "usage": result.usage.to_dict() if result.usage else None,
        }

    async def _project(self, prepared, call_id, value):
        tool, _ = self._allowed(prepared["name"], prepared["arguments"])
        result = AgentToolResult(
            content=[TextContent(value["output"])], details=value.get("details")
        )
        result = _result_policy(tool, result)
        if isinstance(result.details, dict) and result.details.get("governance_denied"):
            raise ValueError(result.text)
        patch = await self.harness._emit_hook(
            ToolResultEvent(
                call_id,
                tool.name,
                dict(prepared["arguments"]),
                list(result.content),
                result.details,
                not value["success"],
                result.usage,
            )
        )
        if patch:
            result = replace(
                result,
                content=patch.content if patch.content is not None else result.content,
                details=patch.details if patch.details is not None else result.details,
            )
            value = {
                **value,
                **self._pack(result),
                "success": not patch.is_error if patch.is_error is not None else value["success"],
                "images_omitted": max(
                    value["images_omitted"], self._pack(result)["images_omitted"]
                ),
                "output_truncated": value["output_truncated"]
                or self._pack(result)["output_truncated"],
                "details_omitted": value["details_omitted"]
                or self._pack(result)["details_omitted"],
            }
        result = _result_policy(tool, result)
        if isinstance(result.details, dict) and result.details.get("governance_denied"):
            raise ValueError(result.text)
        return value

    async def check_result(self, prepared, value):
        if prepared["function"] in {"load", "store"}:
            current = await self.execute(prepared, prepared["call_id"], None)
            if input_fingerprint(current) != input_fingerprint(value):
                raise ValueError("Recovered program store changed; reconciliation required")
            return
        if prepared["function"] == "tool_parallel":
            if len(value) != len(prepared["calls"]):
                raise ValueError("Recovered parallel result count changed")
            for child, result in zip(prepared["calls"], value):
                await self.check_result(child, result)
            return
        if prepared["function"] == "tool_search":
            # Discovery schemas are tied to the capability fingerprint.
            return
        projected = await self._project(prepared, prepared["call_id"], value)
        if input_fingerprint(projected) != input_fingerprint(value):
            raise ValueError("Recovered program result projection changed; reconciliation required")

    async def check_final(self, value):
        state = value.get("program_state", {})
        if state.get("writes"):
            projected = _result_policy(
                self.tool(), AgentToolResult(content=[TextContent(json.dumps(state))])
            )
            if isinstance(projected.details, dict) and projected.details.get("governance_denied"):
                raise ValueError(projected.text)
        result = _result_policy(
            self.tool(), AgentToolResult(content=[TextContent(value["output"])])
        )
        if isinstance(result.details, dict) and result.details.get("governance_denied"):
            raise ValueError(result.text)

    def tool(self):
        async def execute(call_id, args, signal=None, on_update=None):
            scope = active_recovery()
            program_id = call_id
            if scope and scope.invocation_namespace:
                program_id = f"{scope.invocation_namespace}/{call_id}"
            elif scope is None and getattr(self.harness, "_session", None) is not None:
                program_id = f"{await self.harness._session.get_leaf_id()}/{call_id}"
            result = await cancellable_program(
                program_id, args["code"], self, cwd=self.cwd, signal=signal
            )
            return AgentToolResult(content=[TextContent(result["output"])], details=result)

        return AgentTool(
            name="python_program",
            label="Python tool program",
            description="Run restricted Python with tool_search(query, limit=5), tool_call(name, arguments), tool_parallel(calls), store(key, value), and load(key). Parallel batches allow 1–8 native read calls; MCP calls require explicit host capabilities and run sequentially. Small JSON stores commit only on success and follow the session branch; store(key, None) deletes. Return a final expression or print a concise result. No direct filesystem, shell, network or third-party imports. WorkOrders checkpoint host calls; saved results require current policy.",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string", "minLength": 1, "maxLength": 64000}},
                "required": ["code"],
                "additionalProperties": False,
            },
            execute_fn=execute,
            execution_mode="sequential",
            manages_recovery=True,
            prompt_snippet="Compose read tools in restricted Python; WorkOrders retain interrupted program state.",
        )


def _call_signature(name, arguments): ...


def _search_signature(query, limit=5): ...


def _parallel_signature(calls): ...


def _store_signature(key, value): ...


def _load_signature(key): ...
