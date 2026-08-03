"""Bridge SuperQode extensions onto PiPy's harness hooks.

PiPy keeps SuperQode's extension system rather than porting pi's TypeScript one,
so this is where an installed extension gets to observe and shape a PiPy run.

What is deliberately *not* bridged: ``PERMISSION_REQUEST``. That hook point is
SuperQode's approval stack, and PiPy runs with the permissions of the process by
design. An extension may still block a tool through ``BEFORE_TOOL_CALL``,
because pi's own extensions can do exactly that; the difference is that it is
the user's extension deciding, not a policy engine.
"""

from __future__ import annotations

from typing import Any

from ..agent.hooks import (
    AFTER_TOOL_CALL,
    AFTER_TURN_COMPLETE,
    BEFORE_TOOL_CALL,
    SESSION_START,
    STOP,
    USER_PROMPT_SUBMIT,
    HookRegistry,
)

#: Hook points a PiPy run can reach. Everything else in SuperQode's lifecycle
#: either has no PiPy equivalent or belongs to the policy stack PiPy omits.
BRIDGED_HOOK_POINTS: tuple[str, ...] = (
    SESSION_START,
    USER_PROMPT_SUBMIT,
    BEFORE_TOOL_CALL,
    AFTER_TOOL_CALL,
    AFTER_TURN_COMPLETE,
    STOP,
)


def attach_extension_hooks(
    harness: Any,
    hooks: HookRegistry,
    *,
    session_id: str = "",
) -> list[Any]:
    """Wire a :class:`HookRegistry` onto a PiPy harness.

    Returns the unsubscribe callables, so a caller that rebuilds the harness can
    detach cleanly instead of stacking duplicate handlers.
    """
    from superqode.pipy.harness_events import ToolCallResult

    unsubscribes: list[Any] = []

    async def on_before_agent_start(event: Any) -> None:
        await hooks.fire(
            USER_PROMPT_SUBMIT,
            prompt=event.prompt,
            session_id=session_id,
            harness_id="pipy",
        )
        return None

    async def on_tool_call(event: Any) -> ToolCallResult | None:
        outcome = await hooks.fire_decision(
            BEFORE_TOOL_CALL,
            tool_name=event.tool_name,
            arguments=dict(event.input),
            session_id=session_id,
            harness_id="pipy",
        )
        # Only an explicit deny blocks. `allowed` means a hook actively
        # approved; abstaining leaves the outcome on CONTINUE, and treating
        # that as "not allowed" would block every tool call the moment any
        # extension registered an observer here.
        if not outcome.denied:
            return None
        return ToolCallResult(
            block=True,
            reason=str(outcome.message or outcome.reason or "Blocked by an extension"),
        )

    async def on_tool_result(event: Any) -> None:
        await hooks.fire(
            AFTER_TOOL_CALL,
            tool_name=event.tool_name,
            arguments=dict(event.input),
            success=not event.is_error,
            session_id=session_id,
            harness_id="pipy",
        )
        return None

    async def on_event(event: Any) -> None:
        kind = getattr(event, "type", "")
        if kind == "turn_end":
            await hooks.fire(
                AFTER_TURN_COMPLETE,
                session_id=session_id,
                harness_id="pipy",
                stop_reason=getattr(event.message, "stop_reason", "stop"),
            )
        elif kind == "agent_end":
            await hooks.fire(STOP, session_id=session_id, harness_id="pipy")

    unsubscribes.append(harness.on("before_agent_start", on_before_agent_start))
    unsubscribes.append(harness.on("tool_call", on_tool_call))
    unsubscribes.append(harness.on("tool_result", on_tool_result))
    unsubscribes.append(harness.subscribe(on_event))
    return unsubscribes


async def fire_session_start(hooks: HookRegistry, *, session_id: str = "") -> None:
    """Announce a new PiPy session to extensions."""
    await hooks.fire(SESSION_START, session_id=session_id, harness_id="pipy")


__all__ = ["BRIDGED_HOOK_POINTS", "attach_extension_hooks", "fire_session_start"]
