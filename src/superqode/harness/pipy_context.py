"""SuperQode context and instruction policy at the independent PiPy boundary."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict, deque
from dataclasses import replace
from types import SimpleNamespace

from .context_artifacts import ContextArtifactStore
from .context_policy import ContextItem, ContextPolicyEngine
from .core_context import configured_context_policy, configured_context_client
from superqode.agent.instructions import (
    split_instruction_text,
    signals_from_messages,
    fragment_matches,
    render_pin,
    upsert_pin,
)


def pipy_signals(messages):
    converted = []
    for message in messages:
        calls = [
            {"id": call.id, "function": {"name": call.name, "arguments": call.arguments}}
            for call in getattr(message, "tool_calls", ())
        ]
        converted.append(
            SimpleNamespace(
                role="tool" if message.role == "toolResult" else message.role,
                content=getattr(message, "text", getattr(message, "summary", "")),
                name=getattr(message, "tool_name", ""),
                tool_calls=calls,
            )
        )
    return signals_from_messages(converted)


def pipy_items(messages):
    from superqode.pipy.messages import TextContent

    calls = {}
    items = []
    for message in messages:
        calls.update({call.id: call for call in getattr(message, "tool_calls", ())})
        call_id = getattr(message, "tool_call_id", "")
        call = calls.get(call_id)
        role = "tool" if message.role == "toolResult" else message.role
        if role == "tool" and call is None:
            call_id = ""
        content = getattr(message, "content", ())
        # Mixed image results must remain intact; do not persist only their text.
        pure_text = isinstance(content, str) or all(isinstance(v, TextContent) for v in content)
        text = (
            getattr(message, "text", getattr(message, "summary", ""))
            if pure_text or role != "tool"
            else ""
        )
        identity = f"{getattr(message, 'timestamp', 0)}:{call_id}:{hashlib.sha256(text.encode()).hexdigest()}"
        items.append(
            ContextItem(
                identity,
                role,
                text,
                getattr(message, "tool_name", ""),
                call_id,
                call.arguments if call else {},
                bool(getattr(message, "is_error", False)),
            )
        )
    return items


class PiPyContextHost:
    def __init__(self, config, *, client=None):
        self.config = dict(config or {})
        self.policy = configured_context_policy(self.config)
        self.conditional = self.config.get("conditional_instructions") is True
        self.client = client or configured_context_client(self.policy)
        from superqode.execution_recovery import active_recovery
        from superqode.workorders.evidence import evidence_config

        recovery = active_recovery()
        self.reader_enabled = bool(
            self.policy
            or (
                recovery
                and evidence_config(recovery.store.get(recovery.work_order_id)).get("enabled")
                is True
            )
        )
        self.store = (
            ContextArtifactStore(self.config.get("store_path")) if self.reader_enabled else None
        )
        self.scope = ""
        self.engine = None
        self.session = None
        self.fragments = ()
        self.diagnostics = []
        self.run_key = ""

    def transform_files(self, files):
        if not self.conditional:
            return files
        fragments, updated = [], []
        for file in files:
            parsed = split_instruction_text(file.content, source=file.path)
            fragments.extend(parsed.fragments)
            updated.append(replace(file, content=parsed.unconditional))
        self.fragments = tuple(fragments)
        return updated

    def reader_tool(self):
        from superqode.pipy.tools.base import AgentTool, AgentToolResult
        from superqode.pipy.messages import TextContent

        async def read(call_id, args, signal=None, on_update=None):
            if signal:
                signal.throw_if_aborted()
            try:
                try:
                    page = self.store.read_page(
                        self.scope,
                        args["chunk_id"],
                        offset=args.get("offset", 0),
                        limit=args.get("limit", 4000),
                    )
                except LookupError:
                    from superqode.execution_recovery import active_recovery
                    from superqode.workorders.evidence import read_workorder_evidence

                    page = read_workorder_evidence(
                        active_recovery(),
                        args["chunk_id"],
                        self.session.cwd,
                        offset=args.get("offset", 0),
                        limit=args.get("limit", 4000),
                    )
                self.diagnostics.append(
                    {
                        "kind": "context_retrieval",
                        "reference": page.reference,
                        "chars": len(page.text),
                        "success": True,
                    }
                )
                return AgentToolResult([TextContent(page.text)], details=page.to_dict())
            except (KeyError, ValueError, LookupError, PermissionError, OSError, sqlite3.Error):
                self.diagnostics.append({"kind": "context_retrieval", "success": False})
                return AgentToolResult(
                    [TextContent("Context evidence unavailable or denied")],
                    details={"retrieval_error": True},
                )

        return AgentTool(
            "read_context_chunk",
            "Read context",
            "Read permitted stored evidence in bounded pages.",
            {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12000},
                },
                "required": ["chunk_id"],
            },
            read,
            replay_safe=False,
        )

    def attach(self, session):
        self.session = session
        # Stable owner identity derived from the actual native session path.
        self.scope = (
            "pipy:" + hashlib.sha256(str(session.session_path.resolve()).encode()).hexdigest()
        )
        if self.policy:
            self.engine = ContextPolicyEngine(
                self.store, self.scope, self.policy, client=self.client
            )
            session.harness.on("context", self.context)
        if self.conditional:
            session.harness.on("system_prompt", self.instructions)
        if self.reader_enabled:
            session.harness.on("tool_result", self.retrieval_result)

    async def context(self, event):
        from superqode.pipy.harness_events import ContextResult
        from superqode.pipy.messages import TextContent

        try:
            self._instruction_signals = pipy_signals(event.messages)
            # Native entry identities prevent collisions between forks. Do not
            # use the changing leaf as a branch ID, which defeats stable reuse.
            entries = await self.session.session.get_branch()
            identities = defaultdict(deque)
            for entry in entries:
                message = getattr(entry, "message", None)
                if message is not None:
                    identities[self._message_identity(message)].append(entry.id)
            items = pipy_items(event.messages)
            items = [
                replace(v, identity=identities[self._message_identity(m)].popleft())
                if identities[self._message_identity(m)]
                else v
                for m, v in zip(event.messages, items)
            ]
            instruction_version = hashlib.sha256(
                repr(self.session.context_files).encode()
            ).hexdigest()
            plan = await self.engine.prepare(
                items, instruction_version=instruction_version, run_key=self.run_key
            )
            self.diagnostics.append(plan.trace)
            return ContextResult(
                [
                    replace(m, content=[TextContent(plan.replacements[i])])
                    if i in plan.replacements
                    else m
                    for i, m in enumerate(event.messages)
                ]
            )
        except Exception as exc:
            self.diagnostics.append({"kind": "context_selection", "fallback": type(exc).__name__})
            return None

    def instructions(self, event):
        from superqode.pipy.harness_events import SystemPromptResult

        signals = getattr(self, "_instruction_signals", None) or pipy_signals(event.messages)
        matches = tuple(f for f in self.fragments if fragment_matches(f, signals))
        return SystemPromptResult(upsert_pin(event.system_prompt, render_pin(matches)))

    @staticmethod
    def _message_identity(message):
        return (
            message.role,
            getattr(message, "timestamp", None),
            getattr(message, "tool_call_id", ""),
            getattr(message, "text", getattr(message, "summary", "")),
        )

    @staticmethod
    def retrieval_result(event):
        from superqode.pipy.harness_events import ToolResultPatch

        if (
            event.tool_name == "read_context_chunk"
            and isinstance(event.details, dict)
            and event.details.get("retrieval_error")
        ):
            return ToolResultPatch(is_error=True)
        return None
