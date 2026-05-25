"""Agent loop lifecycle hooks.

Five hook points fire during ``AgentLoop.run``:

================== =================================================
Hook                Fired
================== =================================================
before_llm_call    Right before the gateway request is sent.
after_llm_call     Right after the gateway response is received.
before_tool_call   Right before a tool's ``execute`` runs.
after_tool_call    Right after a tool returns (or raises).
after_turn_complete Once per iteration, after all tools have run.
================== =================================================

Each hook receives a :class:`LifecycleContext` (session_id, provider, model,
iteration count, working_directory) plus point-specific payload arguments.

Hooks may be sync or async; awaitables are awaited. Exceptions from one
hook are caught and logged - they never abort the loop or other hooks.
This is observer-only by design: hooks cannot short-circuit the loop or
mutate gateway/tool inputs in v1. We can extend with "transform" hooks
later if a real use case shows up.

Used by ``plugins.py`` to wire plugin manifest ``event_hooks`` entries
into the loop, but the registry is generic - any caller can register.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


# Hook point names. Use these constants - typos in string literals would
# silently never fire.
BEFORE_LLM_CALL = "before_llm_call"
AFTER_LLM_CALL = "after_llm_call"
BEFORE_TOOL_CALL = "before_tool_call"
AFTER_TOOL_CALL = "after_tool_call"
AFTER_TURN_COMPLETE = "after_turn_complete"

ALL_HOOK_POINTS = (
    BEFORE_LLM_CALL,
    AFTER_LLM_CALL,
    BEFORE_TOOL_CALL,
    AFTER_TOOL_CALL,
    AFTER_TURN_COMPLETE,
)


@dataclass
class LifecycleContext:
    """Context passed to every hook.

    Stable across all hook points so plugins can correlate events from the
    same turn (use ``session_id`` + ``iteration``).
    """

    session_id: str
    provider: str
    model: str
    working_directory: Path
    iteration: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


HookCallable = Callable[..., Any]


class HookRegistry:
    """Per-loop registry of lifecycle hooks.

    Hooks are stored in insertion order and fired in that order. Each hook
    is identified by an optional ``name`` so callers can ``unregister`` later
    (handy for tests; less common in production).
    """

    def __init__(self) -> None:
        self._hooks: Dict[str, List[tuple[str, HookCallable]]] = {
            point: [] for point in ALL_HOOK_POINTS
        }

    def register(
        self,
        point: str,
        fn: HookCallable,
        name: Optional[str] = None,
    ) -> str:
        """Register ``fn`` to fire at ``point``.

        Returns the resolved hook name (auto-generated if not provided) so
        the caller can unregister later.
        """
        if point not in self._hooks:
            raise ValueError(
                f"Unknown hook point {point!r}. Valid: {', '.join(ALL_HOOK_POINTS)}"
            )
        resolved = name or f"{getattr(fn, '__name__', 'hook')}_{len(self._hooks[point])}"
        self._hooks[point].append((resolved, fn))
        return resolved

    def unregister(self, point: str, name: str) -> bool:
        """Remove a hook by name. Returns True if removed."""
        if point not in self._hooks:
            return False
        before = len(self._hooks[point])
        self._hooks[point] = [(n, fn) for n, fn in self._hooks[point] if n != name]
        return len(self._hooks[point]) < before

    def has_hooks(self, point: str) -> bool:
        return bool(self._hooks.get(point))

    def list_hooks(self, point: str) -> List[str]:
        return [name for name, _ in self._hooks.get(point, [])]

    async def fire(self, point: str, *args: Any, **kwargs: Any) -> None:
        """Invoke every hook for ``point`` with the given payload.

        Exceptions are caught per-hook and logged. We never abort the loop
        because of a misbehaving hook.
        """
        hooks = self._hooks.get(point)
        if not hooks:
            return
        for name, fn in hooks:
            try:
                result = fn(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                # Cancellation must propagate so the loop can shut down.
                raise
            except Exception:  # noqa: BLE001 - hooks are user code; isolate them.
                logger.exception("Hook %r at %s raised; continuing.", name, point)


__all__ = [
    "AFTER_LLM_CALL",
    "AFTER_TOOL_CALL",
    "AFTER_TURN_COMPLETE",
    "ALL_HOOK_POINTS",
    "BEFORE_LLM_CALL",
    "BEFORE_TOOL_CALL",
    "HookCallable",
    "HookRegistry",
    "LifecycleContext",
]
