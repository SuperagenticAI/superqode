"""Builtin runtime — thin wrapper around the existing AgentLoop.

Zero behavior change. Exists so callers can use the same factory and Protocol
for all backends.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..agent.loop import AgentLoop, AgentResponse
from ..harness.events import HarnessEvent
from ..tools.base import ToolResult


class BuiltinRuntime:
    """Wraps :class:`superqode.agent.loop.AgentLoop` behind the AgentRuntime Protocol."""

    name = "builtin"

    def __init__(self, **kwargs):
        # ``harness_spec`` is metadata the harness backend passes to every
        # runtime; the builtin AgentLoop doesn't take it directly, but this
        # wrapper uses it for persistent approval memory.
        self._harness_spec = kwargs.pop("harness_spec", None)
        self._loop = AgentLoop(**kwargs)
        if self._harness_spec is not None and self._loop.config.harness_spec is None:
            self._loop.config.harness_spec = self._harness_spec
        self._loop.pause_on_approval = True

    @property
    def loop(self) -> AgentLoop:
        """Escape hatch for code that needs the underlying AgentLoop (e.g. pure_mode)."""
        return self._loop

    async def run(self, prompt: str) -> AgentResponse:
        return await self._loop.run(prompt)

    def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        return self._loop.run_streaming(prompt)

    def get_pending_approvals(self) -> list[dict]:
        pending = self._loop._pending_approval
        if not pending:
            return []
        return [
            {
                **pending,
                "arguments": dict(pending.get("arguments") or {}),
            }
        ]

    async def approve_and_resume(self, index: int = 0, always: bool = False) -> AgentResponse:
        from ..agent.peer_agents import _approve_loop_pending

        return await _approve_loop_pending(
            self._loop, index=index, always=always, harness_spec=self._harness_spec
        )

    async def reject_and_resume(
        self,
        index: int = 0,
        message: str | None = None,
        always: bool = False,
    ) -> AgentResponse:
        if index != 0 or not self._loop._pending_approval:
            raise RuntimeError("No pending approval to reject")
        pending = dict(self._loop._pending_approval)
        self._loop._pending_approval = None
        tool_name = str(pending.get("tool_name") or "")
        if always and self._harness_spec is not None:
            from ..harness.approval_memory import remember_approval_decision

            remember_approval_decision(
                self._harness_spec,
                tool_name=tool_name,
                arguments=dict(pending.get("arguments") or {}),
                action="deny",
            )
        reason = message or f"Permission rejected for tool: {tool_name}"
        return AgentResponse(
            content=reason,
            messages=[],
            tool_calls_made=0,
            iterations=0,
            stopped_reason="complete",
        )

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        """Run with normalized harness events from the native AgentLoop callbacks."""
        pending: list[HarnessEvent] = []
        previous_tool_call = self._loop.on_tool_call
        previous_tool_result = self._loop.on_tool_result
        previous_thinking = self._loop.on_thinking

        def on_tool_call(name: str, args: dict) -> None:
            if previous_tool_call is not None:
                previous_tool_call(name, args)
            pending.append(
                HarnessEvent(
                    type="tool_call",
                    data={"tool_name": name, "arguments": args},
                )
            )

        def on_tool_result(name: str, result: ToolResult) -> None:
            if previous_tool_result is not None:
                previous_tool_result(name, result)
            pending.append(
                HarnessEvent(
                    type="tool_result",
                    data={
                        "tool_name": name,
                        "success": result.success,
                        "output": result.output,
                        "error": result.error,
                        "metadata": dict(result.metadata),
                    },
                )
            )

        async def on_thinking(text: str) -> None:
            if previous_thinking is not None:
                await previous_thinking(text)
            if text:
                pending.append(HarnessEvent(type="thinking", data={"text": text}))

        self._loop.on_tool_call = on_tool_call
        self._loop.on_tool_result = on_tool_result
        self._loop.on_thinking = on_thinking
        yield HarnessEvent(type="model_request", data={"runtime": self.name})
        try:
            async for chunk in self._loop.run_streaming(prompt):
                while pending:
                    yield pending.pop(0)
                if chunk:
                    yield HarnessEvent(type="model_delta", data={"text": chunk})
            while pending:
                yield pending.pop(0)
        finally:
            self._loop.on_tool_call = previous_tool_call
            self._loop.on_tool_result = previous_tool_result
            self._loop.on_thinking = previous_thinking

    def cancel(self) -> None:
        self._loop.cancel()

    def reset_cancellation(self) -> None:
        self._loop.reset_cancellation()
