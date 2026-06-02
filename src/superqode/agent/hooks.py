"""Agent loop lifecycle hooks.

Hook points fire during ``AgentLoop.run``:

==================== =================================================
Hook                  Fired
==================== =================================================
session_start         Once, before the first turn of an AgentLoop run.
user_prompt_submit    After the user message is added, before the loop.
before_llm_call       Right before the gateway request is sent.
after_llm_call        Right after the gateway response is received.
permission_request    When a tool needs approval (manager says ASK).
before_tool_call      Right before a tool's ``execute`` runs.
after_tool_call       Right after a tool returns (or raises).
after_turn_complete   Once per iteration, after all tools have run.
before_compact        Before context compaction runs.
after_compact         After context compaction runs.
stop                  When the loop completes a response.
==================== =================================================

Each hook receives a :class:`LifecycleContext` (session_id, provider, model,
iteration count, working_directory) plus point-specific payload arguments.

Hooks may be sync or async; awaitables are awaited. Exceptions from one
hook are caught and logged - they never abort the loop or other hooks.

Two firing modes:

* :meth:`HookRegistry.fire` - **observer** mode. Return values are ignored;
  hooks only watch. This is the original behaviour and stays unchanged.
* :meth:`HookRegistry.fire_decision` - **handler** mode. Each hook may return
  a :class:`HookDecision` (or a shorthand: ``True``/``False`` for allow/deny,
  a ``dict`` for modified arguments, ``None`` to abstain) that influences the
  loop. Used at gating points: ``permission_request``, ``before_tool_call``,
  ``user_prompt_submit``, and ``before_compact``.

Decision resolution is **deny-precedence**: the first ``DENY`` short-circuits
and wins, so a misconfigured allow can never override an explicit deny. A hook
that *raises* is logged and treated as abstaining (fail-open, consistent with
observer semantics) - hooks must not silently block the loop by crashing.

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
SESSION_START = "session_start"
USER_PROMPT_SUBMIT = "user_prompt_submit"
BEFORE_LLM_CALL = "before_llm_call"
AFTER_LLM_CALL = "after_llm_call"
PERMISSION_REQUEST = "permission_request"
BEFORE_TOOL_CALL = "before_tool_call"
AFTER_TOOL_CALL = "after_tool_call"
AFTER_TURN_COMPLETE = "after_turn_complete"
BEFORE_COMPACT = "before_compact"
AFTER_COMPACT = "after_compact"
STOP = "stop"

ALL_HOOK_POINTS = (
    SESSION_START,
    USER_PROMPT_SUBMIT,
    BEFORE_LLM_CALL,
    AFTER_LLM_CALL,
    PERMISSION_REQUEST,
    BEFORE_TOOL_CALL,
    AFTER_TOOL_CALL,
    AFTER_TURN_COMPLETE,
    BEFORE_COMPACT,
    AFTER_COMPACT,
    STOP,
)

# Hook points that support handler (decision) semantics via ``fire_decision``.
# Other points are observer-only; calling ``fire_decision`` on them still works
# but returned decisions are honoured only at these gating points by the loop.
DECISION_HOOK_POINTS = (
    USER_PROMPT_SUBMIT,
    PERMISSION_REQUEST,
    BEFORE_TOOL_CALL,
    BEFORE_COMPACT,
)

# Decision actions.
CONTINUE = "continue"  # abstain - no opinion (the observer default)
ALLOW = "allow"  # explicitly allow / auto-approve
DENY = "deny"  # block the operation
MODIFY = "modify"  # proceed with replacement payload (e.g. tool arguments)


@dataclass
class HookDecision:
    """A handler hook's verdict for a gating point.

    Hooks may also return shorthands that :func:`normalize_decision` maps here:
    ``None`` -> abstain, ``True`` -> allow, ``False`` -> deny, ``dict`` ->
    modify arguments.
    """

    action: str = CONTINUE
    arguments: Optional[Dict[str, Any]] = None  # MODIFY: replacement tool arguments
    result: Any = None  # DENY: explicit result to return instead
    message: Optional[str] = None  # human/model-facing explanation
    reason: Optional[str] = None  # audit/source reason


@dataclass
class HookOutcome:
    """Resolved verdict after firing every handler hook at a point."""

    action: str = CONTINUE
    arguments: Optional[Dict[str, Any]] = None
    result: Any = None
    message: Optional[str] = None
    reason: Optional[str] = None
    decided_by: Optional[str] = None

    @property
    def denied(self) -> bool:
        return self.action == DENY

    @property
    def allowed(self) -> bool:
        return self.action == ALLOW

    @property
    def modified(self) -> bool:
        return self.action == MODIFY and self.arguments is not None


def normalize_decision(raw: Any) -> Optional[HookDecision]:
    """Map a hook's return value to a :class:`HookDecision` (or ``None``)."""
    if raw is None:
        return None
    if isinstance(raw, HookDecision):
        return raw
    if isinstance(raw, bool):
        return HookDecision(action=ALLOW if raw else DENY)
    if isinstance(raw, dict):
        return HookDecision(action=MODIFY, arguments=raw)
    return None


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
            raise ValueError(f"Unknown hook point {point!r}. Valid: {', '.join(ALL_HOOK_POINTS)}")
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

    async def fire_decision(self, point: str, *args: Any, **kwargs: Any) -> HookOutcome:
        """Fire handler hooks for ``point`` and resolve them to one outcome.

        Each hook may return a :class:`HookDecision` or a shorthand (see
        :func:`normalize_decision`). Resolution is deny-precedence:

        * the first ``DENY`` short-circuits and wins (later allows cannot
          override it);
        * ``MODIFY`` updates the running arguments and proceeds (last writer
          wins if several hooks modify);
        * ``ALLOW`` is recorded only while no stronger verdict exists;
        * abstaining (``None``/``CONTINUE``) leaves the outcome untouched.

        A hook that raises is logged and treated as abstaining (fail-open),
        matching :meth:`fire`. Observer hooks that return ``None`` are safe to
        register here too - they simply abstain.
        """
        outcome = HookOutcome()
        hooks = self._hooks.get(point)
        if not hooks:
            return outcome
        for name, fn in hooks:
            try:
                raw = fn(*args, **kwargs)
                if inspect.isawaitable(raw):
                    raw = await raw
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - hooks are user code; isolate them.
                logger.exception("Decision hook %r at %s raised; treating as abstain.", name, point)
                continue
            decision = normalize_decision(raw)
            if decision is None or decision.action == CONTINUE:
                continue
            if decision.action == DENY:
                return HookOutcome(
                    action=DENY,
                    result=decision.result,
                    message=decision.message,
                    reason=decision.reason,
                    decided_by=name,
                )
            if decision.action == MODIFY:
                outcome.action = MODIFY
                if decision.arguments is not None:
                    outcome.arguments = decision.arguments
                if decision.message:
                    outcome.message = decision.message
                outcome.decided_by = name
            elif decision.action == ALLOW and outcome.action == CONTINUE:
                outcome.action = ALLOW
                outcome.message = decision.message
                outcome.reason = decision.reason
                outcome.decided_by = name
        return outcome


__all__ = [
    # Lifecycle points
    "SESSION_START",
    "USER_PROMPT_SUBMIT",
    "BEFORE_LLM_CALL",
    "AFTER_LLM_CALL",
    "PERMISSION_REQUEST",
    "BEFORE_TOOL_CALL",
    "AFTER_TOOL_CALL",
    "AFTER_TURN_COMPLETE",
    "BEFORE_COMPACT",
    "AFTER_COMPACT",
    "STOP",
    "ALL_HOOK_POINTS",
    "DECISION_HOOK_POINTS",
    # Decision actions + types
    "CONTINUE",
    "ALLOW",
    "DENY",
    "MODIFY",
    "HookDecision",
    "HookOutcome",
    "normalize_decision",
    # Registry
    "HookCallable",
    "HookRegistry",
    "LifecycleContext",
]
