"""Native kernel execution for both solver and read-only editor sessions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from ..kernel import init_harness
from ..spec import AgentSpec, HarnessFlavor
from ..store import FileHarnessStore


class NativeExecutor:
    def __init__(self):
        self.sessions = set()

    async def run(
        self, request, *, label, prompt, workspace, overlay, editor=False, event_callback=None
    ):
        spec = request.spec
        config = {
            **spec.runtime.config,
            "context_files": False,
            "skill_directories": [],
            "include_prompt_templates": False,
            "max_turns": request.max_turns,
            "max_output_tokens": request.max_output_tokens,
            "session_root": str(workspace.parent / "sessions"),
            "append_system_prompt": "\n\n".join(
                value
                for value in (spec.runtime.config.get("append_system_prompt", ""), overlay)
                if value
            ),
        }
        spec = replace(spec, runtime=replace(spec.runtime, config=config))
        if editor:
            spec = replace(
                spec,
                flavor=HarnessFlavor.NO_TOOL,
                agents=(
                    AgentSpec(
                        id="editor",
                        system_prompt="You edit coding-harness instructions. Return the requested JSON; tool access is disabled.",
                    ),
                ),
                runtime=replace(
                    spec.runtime, config={**config, "append_system_prompt": "", "max_turns": 1}
                ),
                execution_policy=replace(
                    spec.execution_policy, allow_read=False, allow_write=False, allow_shell=False
                ),
            )
        store = FileHarnessStore(workspace.parent / "native")
        kernel = await init_harness(spec, store=store, event_callback=event_callback)
        session = await kernel.session(
            "refine-" + workspace.parent.parent.parent.name + "-" + label + "-" + uuid4().hex[:12]
        )
        self.sessions.add(session)
        try:
            result = await session.prompt(
                prompt,
                provider=request.provider,
                model=request.model,
                working_directory=workspace,
                sandbox_backend=spec.execution_policy.sandbox,
                metadata={
                    "parent_run_id": workspace.parent.parent.parent.name,
                    "root_run_id": workspace.parent.parent.parent.name,
                    "refinement_stage": label,
                    "refinement_role": "editor" if editor else "solver",
                },
            )
            usage = {
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "total_tokens": result.total_tokens,
                "cost_usd": result.cost_usd,
            }
            if result.response.stopped_reason not in {"complete", "stop"}:
                # Empty error turns have provider default zeros, not measured usage.
                usage = {key: value if value else None for key, value in usage.items()}
            return {
                "content": result.content,
                "status": result.response.stopped_reason,
                "error": result.response.error,
                "run_id": result.run_id,
                "usage": usage,
                "events": [event.to_dict() for event in result.events],
            }
        except BaseException:
            await session.cancel()
            raise
        finally:
            self.sessions.discard(session)

    async def cancel(self):
        await asyncio.gather(
            *(session.cancel() for session in list(self.sessions)), return_exceptions=True
        )
