"""Builtin runtime — thin wrapper around the existing AgentLoop.

Zero behavior change. Exists so callers can use the same factory and Protocol
for all backends.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..agent.loop import AgentLoop, AgentResponse


class BuiltinRuntime:
    """Wraps :class:`superqode.agent.loop.AgentLoop` behind the AgentRuntime Protocol."""

    name = "builtin"

    def __init__(self, **kwargs):
        self._loop = AgentLoop(**kwargs)

    @property
    def loop(self) -> AgentLoop:
        """Escape hatch for code that needs the underlying AgentLoop (e.g. pure_mode)."""
        return self._loop

    async def run(self, prompt: str) -> AgentResponse:
        return await self._loop.run(prompt)

    def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        return self._loop.run_streaming(prompt)

    def cancel(self) -> None:
        self._loop.cancel()

    def reset_cancellation(self) -> None:
        self._loop.reset_cancellation()
