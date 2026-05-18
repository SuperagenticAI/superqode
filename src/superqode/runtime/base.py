"""Agent runtime Protocol.

All runtime backends (builtin, ADK, OpenAI Agents) implement this Protocol.
Callers use create_runtime() from runtime.registry to get an instance — they
never import a concrete class directly.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from ..agent.loop import AgentResponse


@runtime_checkable
class AgentRuntime(Protocol):
    """Backend that drives an agent turn end-to-end.

    Implementations live in:
        runtime/builtin.py        -> wraps existing AgentLoop
        runtime/adk.py            -> Google ADK adapter (optional dep)
        runtime/openai_agents.py  -> OpenAI Agents SDK stub (v2)

    The constructor signature is intentionally the same across backends so
    callers don't branch on runtime name when constructing.
    """

    name: str

    async def run(self, prompt: str) -> AgentResponse: ...

    def run_streaming(self, prompt: str) -> AsyncIterator[str]: ...

    def cancel(self) -> None: ...

    def reset_cancellation(self) -> None: ...
