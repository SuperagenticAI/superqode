"""High-level helpers for driving the Claude Agent SDK from SuperQode.

Wraps the ``claude-agent-sdk`` runtime (API-key auth via ``ANTHROPIC_API_KEY``)
so you can run Claude Code programmatically without hand-building an
:class:`AgentConfig` or calling :func:`create_runtime`.

Requires the extra and a key::

    uv tool install 'superqode[claude-agent-sdk]'   # + the Claude Code CLI
    export ANTHROPIC_API_KEY=...

Quick start::

    from superqode.claude import run_claude, stream_claude, claude_session

    resp = run_claude("Add a docstring to main.py", cwd="myrepo")
    print(resp.content)

    import asyncio
    async def go():
        async for ev in stream_claude("Write tests for utils.py", cwd="myrepo"):
            print(ev.type, ev.data)
    asyncio.run(go())

    with claude_session(cwd="myrepo") as cx:
        a = asyncio.run(cx.run("Summarize the repo"))
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Iterator, Optional

from .agent.loop import AgentConfig, AgentResponse
from .runtime import create_runtime

if TYPE_CHECKING:  # avoid importing the optional SDK at module load
    from .harness.events import HarnessEvent
    from .runtime.claude_agent_sdk import ClaudeAgentSDKRuntime

# Empty default => use Claude Code's configured default model. Override with
# model="claude-opus-4-8" etc.
DEFAULT_CLAUDE_MODEL = ""

__all__ = [
    "make_claude_runtime",
    "run_claude",
    "arun_claude",
    "stream_claude",
    "claude_session",
    "DEFAULT_CLAUDE_MODEL",
]


def make_claude_runtime(
    *,
    model: str = DEFAULT_CLAUDE_MODEL,
    cwd: str | Path = ".",
    tools: bool = True,
    system_prompt: Optional[str] = None,
    permission_manager=None,
    approval_callback=None,
    session_id: Optional[str] = None,
    sandbox_backend: Optional[str] = None,
) -> "ClaudeAgentSDKRuntime":
    """Build a (not-yet-started) Claude Agent SDK runtime (API key).

    Requires the ``claude-agent-sdk`` extra + ``ANTHROPIC_API_KEY``; raises
    ``RuntimeNotInstalledError`` if the SDK is missing.
    """
    config = AgentConfig(
        provider="anthropic",
        model=model,
        working_directory=Path(cwd),
        tools_enabled=tools,
        custom_system_prompt=system_prompt,
        session_id=session_id,
    )
    return create_runtime(
        "claude-agent-sdk",
        config=config,
        permission_manager=permission_manager,
        approval_callback=approval_callback,
        sandbox_backend=sandbox_backend,
    )


async def arun_claude(prompt: str, **kwargs) -> AgentResponse:
    """Async one-shot Claude run. Same kwargs as :func:`make_claude_runtime`."""
    runtime = make_claude_runtime(**kwargs)
    try:
        return await runtime.run(prompt)
    finally:
        runtime.close()


def run_claude(prompt: str, **kwargs) -> AgentResponse:
    """Synchronous one-shot Claude run. Returns an :class:`AgentResponse`.

    Do not call from inside a running event loop (use ``arun_claude`` there).
    """
    return asyncio.run(arun_claude(prompt, **kwargs))


async def stream_claude(prompt: str, **kwargs) -> AsyncIterator["HarnessEvent"]:
    """Async generator of typed harness events for one Claude turn."""
    runtime = make_claude_runtime(**kwargs)
    try:
        async for event in runtime.run_harness_events(prompt):
            yield event
    finally:
        runtime.close()


@contextmanager
def claude_session(**kwargs) -> Iterator["ClaudeAgentSDKRuntime"]:
    """Context manager yielding a Claude runtime for multiple turns on one thread."""
    runtime = make_claude_runtime(**kwargs)
    try:
        yield runtime
    finally:
        runtime.close()
