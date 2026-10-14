"""Native CodeGem lifecycle, sharing PiPy's durable loop and protocol events."""

from __future__ import annotations

import json
from .execution_contract import execution_contract

from dataclasses import replace
from pathlib import Path

from .pipy_adapter import PiPyHarnessProtocolAdapter, translate_event
from .protocol import HarnessCreateRequest, HarnessDescriptor, HarnessSessionRef
from .events import HarnessEvent


class CodeGemHarnessProtocolAdapter(PiPyHarnessProtocolAdapter):
    def __init__(self, *, session_factory=None):
        super().__init__(session_factory=session_factory)
        from superqode.codegem.tools import TOOL_NAMES

        self.descriptor = replace(
            self.descriptor,
            id="codegem",
            name="CodeGem",
            description="Six-tool Python coding harness for Gemini and Gemma",
            metadata={
                "tools": list(TOOL_NAMES),
                "pure_permissions": True,
                "execution_contract": execution_contract(
                    runtime="codegem", continuity="native-resume"
                ).to_dict(),
                "session_format": "codegem-jsonl-v1",
            },
        )

    async def resume(self, session):
        if session.harness_id != "codegem":
            raise ValueError("CodeGem cannot resume another harness's session")
        if session.session_id in self._sessions:
            return self._refs[session.session_id]
        metadata = dict(session.metadata)
        cwd = Path(metadata.get("working_directory") or Path.cwd()).expanduser().resolve()
        if not metadata.get("session_path"):
            from superqode.pipy.config import session_index_for

            root = Path(
                (metadata.get("runtime_config") or {}).get("session_root")
                or cwd / ".superqode" / "codegem" / "sessions"
            )
            index = session_index_for(cwd, root)
            if index.is_file():
                metadata["session_path"] = json.loads(index.read_text()).get(session.session_id)
        request = HarnessCreateRequest(
            harness_id="codegem",
            session_id=session.session_id,
            provider=metadata.get("provider", ""),
            model=metadata.get("model", ""),
            working_directory=cwd,
            metadata=metadata,
        )
        return await self.create(request)

    async def _open(self, request, working_directory, *, session_path=None):
        if self._session_factory:
            return await self._session_factory(request, working_directory, session_path)
        from superqode.codegem.profiles import resolve_profile
        from superqode.codegem.provider import CodeGemStream
        from superqode.codegem.prompt import build_prompt
        from superqode.codegem.tools import create_tools
        from superqode.pipy.ai.models import resolve_model
        from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
        from superqode.pipy.compaction import CompactionSettings
        from .pipy_governance import guard_pipy_tools, mark_policy_denial

        config = dict(request.metadata.get("runtime_config") or {})
        if config.get("mcp") or config.get("mcp_servers"):
            raise ValueError("CodeGem has exactly six tools; MCP extensions are unsupported")
        profile = resolve_profile(request.model, request.provider)
        model = resolve_model(
            request.model,
            provider=request.provider,
            context_window=config.get("context_window"),
            supports_reasoning=profile.thinking,
        )
        if profile.family == "gemma":
            # A model's maximum context is not a sensible default KV allocation
            # on a laptop. Keep local runs bounded and compaction enabled even
            # for imported models absent from the catalog. Users can opt up.
            if config.get("context_window") is None:
                model = replace(model, context_window=min(model.context_window or 32768, 32768))
            if model.context_window < 1024:
                raise ValueError("CodeGem context_window must be at least 1024 tokens")
            config.setdefault("max_output_tokens", min(8192, model.context_window // 4))
        reserve = min(
            int(config.get("reserve_tokens", 32768 if profile.family == "gemini" else 8192)),
            model.context_window // 4 if model.context_window else 32768,
        )
        keep_recent = min(int(config.get("keep_recent_tokens", 8192)), reserve)
        tools = create_tools(working_directory, config=config)
        policy = config.get("execution_policy", {})
        guarded = []
        for tool in tools:
            permission = (
                "allow_shell"
                if tool.name in {"bash", "python"}
                else "allow_write"
                if tool.name in {"write", "edit"}
                else "allow_read"
            )
            if policy.get(permission, True):
                guarded.append(tool)
            else:

                async def denied(call_id, args, signal=None, on_update=None, *, name=tool.name):
                    raise PermissionError(f"CodeGem execution policy denies {name}")

                guarded.append(replace(tool, execute_fn=denied))
        options = CodingSessionOptions(
            cwd=working_directory,
            model=model,
            stream_fn=CodeGemStream(config),
            tool_names=(),
            extra_tools=tuple(guarded),
            tool_transform=guard_pipy_tools,
            custom_prompt=build_prompt(
                working_directory,
                extra=config.get("append_system_prompt", ""),
                context_files=config.get("context_files", True),
            ),
            include_context_files=False,
            include_system_prompt_files=False,
            session_root=Path(
                config.get("session_root")
                or working_directory / ".superqode" / "codegem" / "sessions"
            ),
            max_turns=int(config.get("max_turns", 64)),
            # Reserve output space without imposing Gemini-sized budgets on local Gemma.
            compaction_settings=CompactionSettings(
                reserve_tokens=reserve,
                keep_recent_tokens=keep_recent,
            ),
        )
        path = session_path or request.metadata.get("session_path")
        if path and Path(path).is_file():
            session = await PiPyCodingSession.resume(options, session_path=path)
            from superqode.pipy.session.entries import MessageEntry
            from superqode.pipy.messages import AssistantMessage

            for entry in await session.session.get_branch():
                if isinstance(entry, MessageEntry) and isinstance(entry.message, AssistantMessage):
                    previous = entry.message
                    if (previous.model, previous.provider) != (
                        options.model.id,
                        options.model.provider,
                    ):
                        raise ValueError("Start a new CodeGem session when changing the model")
        else:
            session = await PiPyCodingSession.create(options)
        session.harness.on("tool_result", mark_policy_denial)
        return session

    async def send(self, session, message):
        coding = await self._require(session)
        from superqode.pipy.messages import ImageContent
        from superqode.pipy.ai.gateway import _gateway_content

        images = [
            ImageContent(data=e["data"], mime_type=e["mime_type"])
            for e in message.metadata.get("images", [])
        ]
        if images:
            _gateway_content(images)
        yield HarnessEvent(
            type="model.requested",
            data={
                "provider": session.metadata.get("provider"),
                "model": session.metadata.get("model"),
                "runtime": "codegem",
            },
        )
        yield HarnessEvent(
            type="message.created", data={"role": "user", "content": message.content}
        )
        final = None
        async for event in coding.prompt_events(message.content, images):
            if event.type == "turn_end":
                final = event.message
            if event.type == "agent_end" and final and final.stop_reason != "stop":
                if final.stop_reason in {"toolUse", "length"}:
                    reason = "max_turns" if final.stop_reason == "toolUse" else "max_output_tokens"
                    yield HarnessEvent(
                        type="error",
                        data={"error": f"CodeGem reached {reason}; resume to continue"},
                    )
                yield HarnessEvent(
                    type="run_end",
                    data={
                        "status": "incomplete"
                        if final.stop_reason in {"toolUse", "length"}
                        else "failed"
                    },
                )
                continue
            for translated in translate_event(event, runtime="codegem"):
                yield translated

    async def close(self, session):
        coding = self._sessions.get(session.session_id)
        if coding is not None:
            await coding.abort()
        await super().close(session)
