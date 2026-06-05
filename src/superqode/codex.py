"""High-level helpers for driving the OpenAI Codex Python SDK from SuperQode.

These wrap the ``codex-sdk`` runtime so you can run Codex programmatically without
hand-building an :class:`AgentConfig` or calling :func:`create_runtime` yourself.

Requires the extra::

    pip install superqode[codex-sdk]

Quick start::

    from superqode.codex import run_codex, stream_codex, codex_session

    # one-shot (synchronous)
    resp = run_codex("Add a docstring to main.py", cwd="myrepo")
    print(resp.content)

    # stream typed harness events
    import asyncio
    async def go():
        async for ev in stream_codex("Write tests for utils.py", cwd="myrepo"):
            print(ev.type, ev.data)
    asyncio.run(go())

    # multi-turn session (one Codex thread, reused)
    with codex_session(cwd="myrepo") as cx:
        a = asyncio.run(cx.run("Summarize the repo"))
        b = asyncio.run(cx.run("Now add a README section about it"))
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Iterator, Optional

from .agent.loop import AgentConfig, AgentResponse
from .runtime import create_runtime

if TYPE_CHECKING:  # avoid importing the optional SDK / runtime at module load
    from .harness.events import HarnessEvent
    from .runtime.codex_sdk import CodexSDKRuntime
    from .tools.permissions import PermissionManager

# Empty default => "Codex owns it": defer to the machine's ~/.codex config for the
# model. Override per call with ``model=...`` (use ``codex_session`` + ``cx.models()``
# to list what your account exposes, e.g. gpt-5.5 / gpt-5.4 / gpt-5.4-mini).
DEFAULT_CODEX_MODEL = ""

__all__ = [
    "make_codex_runtime",
    "run_codex",
    "arun_codex",
    "stream_codex",
    "codex_session",
    "DEFAULT_CODEX_MODEL",
]


def make_codex_runtime(
    *,
    model: str = DEFAULT_CODEX_MODEL,
    cwd: str | Path = ".",
    provider: str = "openai",
    tools: bool = True,
    system_prompt: Optional[str] = None,
    require_confirmation: bool = False,
    sandbox_backend: Optional[str] = None,
    approval_callback: Optional[Callable[[str, dict[str, Any]], bool]] = None,
    permission_manager: Optional["PermissionManager"] = None,
    session_id: Optional[str] = None,
) -> "CodexSDKRuntime":
    """Build a (not-yet-started) Codex SDK runtime.

    Args:
        model: Codex model id (default :data:`DEFAULT_CODEX_MODEL`).
        cwd: Working directory the Codex thread operates in.
        provider: Model provider; ``"openai"`` for stock Codex.
        tools: Enable file/command tools (maps to ``workspace-write`` sandbox);
            ``False`` runs read-only.
        system_prompt: Optional developer instructions for the thread.
        require_confirmation: Reserved for parity with other runtimes. The TUI
            provides an interactive Codex approval bridge; programmatic helpers
            use the runtime default, so approval callbacks are denied unless
            Codex policy avoids asking or you build a runtime with an explicit
            ``PermissionManager``/approval callback.
        sandbox_backend: ``"full"``/``"full_access"``/``"none"`` for
            danger-full-access; otherwise SuperQode picks based on ``tools``.
        approval_callback: Optional synchronous callback for SDK approval
            requests. Return ``True`` to accept and ``False`` to reject.
        permission_manager: Optional SuperQode permission policy for
            non-interactive approval handling.
        session_id: Optional SuperQode-side session id for the runtime.

    Requires the ``codex-sdk`` extra; raises ``RuntimeNotInstalledError`` otherwise.
    """
    config = AgentConfig(
        provider=provider,
        model=model,
        working_directory=Path(cwd),
        tools_enabled=tools,
        custom_system_prompt=system_prompt,
        require_confirmation=require_confirmation,
        session_id=session_id,
    )
    return create_runtime(
        "codex-sdk",
        config=config,
        sandbox_backend=sandbox_backend,
        approval_callback=approval_callback,
        permission_manager=permission_manager,
    )


async def arun_codex(prompt: str, **kwargs) -> AgentResponse:
    """Async one-shot Codex run. Accepts the same kwargs as :func:`make_codex_runtime`."""
    runtime = make_codex_runtime(**kwargs)
    try:
        return await runtime.run(prompt)
    finally:
        runtime.close()


def run_codex(prompt: str, **kwargs) -> AgentResponse:
    """Synchronous one-shot Codex run. Returns an :class:`AgentResponse`.

    Convenience over :func:`arun_codex`; do not call from inside a running event
    loop (use ``arun_codex`` there).
    """
    return asyncio.run(arun_codex(prompt, **kwargs))


async def stream_codex(prompt: str, **kwargs) -> AsyncIterator["HarnessEvent"]:
    """Async generator of typed harness events for one Codex turn.

    Yields :class:`HarnessEvent` (``model_delta``, ``tool_result``, ``diff``,
    ``turn_complete``, …). Accepts the same kwargs as :func:`make_codex_runtime`.
    """
    runtime = make_codex_runtime(**kwargs)
    try:
        async for event in runtime.run_harness_events(prompt):
            yield event
    finally:
        runtime.close()


@contextmanager
def codex_session(**kwargs) -> Iterator["CodexSDKRuntime"]:
    """Context manager yielding a Codex runtime for multiple turns on one thread.

    The runtime is closed on exit. Accepts the same kwargs as
    :func:`make_codex_runtime`::

        with codex_session(cwd="myrepo") as cx:
            print(cx.models())              # list available Codex models
            resp = asyncio.run(cx.run("…"))
    """
    runtime = make_codex_runtime(**kwargs)
    try:
        yield runtime
    finally:
        runtime.close()
