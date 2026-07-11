"""Native agent-loop behavior profiles.

The model-facing harness and the runtime are deliberately separate concepts.
Both built-in profiles use the native Python runtime, while this policy keeps
optional workbench behavior out of the lean core path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NativeLoopPolicy:
    """Feature gates for the native agent loop."""

    reminders: bool = True
    semantic_tool_retry: bool = True
    auto_continue_limit: int = 2
    peer_agents: bool = True
    mcp: bool = True


def core_loop_policy() -> NativeLoopPolicy:
    """Low-context defaults for the built-in core harness."""

    return NativeLoopPolicy(
        reminders=False,
        semantic_tool_retry=False,
        auto_continue_limit=0,
        peer_agents=False,
        mcp=False,
    )


def workbench_loop_policy() -> NativeLoopPolicy:
    """The feature-rich native behavior that predates named harnesses."""

    return NativeLoopPolicy()


__all__ = [
    "NativeLoopPolicy",
    "core_loop_policy",
    "workbench_loop_policy",
]
