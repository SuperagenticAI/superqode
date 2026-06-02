"""Build an agent-loop :class:`HookRegistry` from a :class:`HarnessSpec`.

This is the bridge between the declarative ``HooksSpec`` (policy that lives in
the harness YAML) and the executable lifecycle hooks in ``agent.hooks`` that run
inside ``AgentLoop``. Two things happen here:

1. **Declared handler hooks** - each ``HookRuleSpec`` resolves a dotted-path
   callable and registers it at its lifecycle point. For tool and permission
   points the handler is wrapped so it only fires when the tool name matches the
   rule's glob ``matcher``. These hooks can deny/allow/modify via
   ``HookRegistry.fire_decision`` (see ``agent.hooks``).

2. **Store forwarders** - when an ``event_sink`` is provided, observer hooks are
   registered for the lifecycle points that the kernel does not already persist
   (permission, compaction, prompt, session, stop). They append normalized
   ``harness.*`` :class:`HarnessEvent`s so the durable run store and TUI timeline
   see them. Forwarders always abstain, so they never change a decision.
"""

from __future__ import annotations

import fnmatch
import importlib
from typing import Any, Callable

from ..agent.hooks import (
    AFTER_COMPACT,
    AFTER_TOOL_CALL,
    BEFORE_COMPACT,
    BEFORE_TOOL_CALL,
    PERMISSION_REQUEST,
    SESSION_START,
    STOP,
    USER_PROMPT_SUBMIT,
    HookRegistry,
)
from .events import HarnessEvent
from .spec import HarnessSpec, HookRuleSpec

# Lifecycle points whose payload is ``(ctx, tool_name, arguments, ...)`` and so
# support tool-name glob matching on a rule's ``matcher``.
_TOOL_NAME_POINTS = frozenset({BEFORE_TOOL_CALL, AFTER_TOOL_CALL, PERMISSION_REQUEST})
_REDACTED = "[redacted]"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
)
_MAX_PREVIEW = 160


def resolve_hook_handler(spec: str) -> Callable[..., Any]:
    """Resolve a ``module:function`` or ``module.function`` path to a callable."""
    text = (spec or "").strip()
    if not text:
        raise ValueError("hook handler path is empty")
    if ":" in text:
        module_name, _, attr = text.partition(":")
    else:
        module_name, _, attr = text.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"invalid hook handler path: {spec!r}")
    module = importlib.import_module(module_name)
    try:
        target = getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(f"{module_name!r} has no attribute {attr!r}") from exc
    if not callable(target):
        raise ValueError(f"hook handler {spec!r} resolved to a non-callable")
    return target


def _matcher_wrapped(point: str, matcher: str, handler: Callable[..., Any]) -> Callable[..., Any]:
    """Gate ``handler`` on a tool-name glob for tool/permission points."""
    if point not in _TOOL_NAME_POINTS or matcher in ("", "*"):
        return handler

    def wrapped(ctx: Any, name: str = "", *args: Any, **kwargs: Any) -> Any:
        if not fnmatch.fnmatch(name, matcher):
            return None
        return handler(ctx, name, *args, **kwargs)

    wrapped.__name__ = getattr(handler, "__name__", "hook")
    return wrapped


def _safe_preview(value: Any, *, key: str = "") -> Any:
    """Return a bounded, secret-aware preview safe for durable event storage."""
    lowered = key.lower()
    if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if isinstance(value, dict):
        return {str(k): _safe_preview(v, key=str(k)) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_safe_preview(item) for item in list(value)[:20]]
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        if len(text) > _MAX_PREVIEW:
            return f"{text[:_MAX_PREVIEW]}... [{len(text)} chars]"
        return text
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return type(value).__name__


def _argument_summary(arguments: Any) -> dict[str, Any]:
    """Summarize tool arguments without writing full raw payloads to the store."""
    if not isinstance(arguments, dict):
        return {"type": type(arguments).__name__}
    return {
        "keys": sorted(str(k) for k in arguments),
        "preview": _safe_preview(arguments),
    }


def register_spec_hooks(
    registry: HookRegistry,
    spec: HarnessSpec,
) -> list[tuple[HookRuleSpec, str]]:
    """Register every declared hook rule. Returns ``(rule, error)`` for failures.

    A single broken rule never blocks the others - its error is collected and
    returned so callers can surface it without aborting the run.
    """
    errors: list[tuple[HookRuleSpec, str]] = []
    if not spec.hooks.enabled:
        return errors
    for rule in spec.hooks.rules:
        try:
            handler = resolve_hook_handler(rule.handler)
            registry.register(
                rule.point,
                _matcher_wrapped(rule.point, rule.matcher, handler),
                name=rule.name or None,
            )
        except Exception as exc:  # noqa: BLE001 - per-rule isolation
            errors.append((rule, str(exc)))
    return errors


def register_store_forwarders(
    registry: HookRegistry,
    event_sink: list[HarnessEvent],
    *,
    session_id: str | None = None,
) -> None:
    """Register observer hooks that push new lifecycle points into ``event_sink``.

    These cover the points the kernel does not already persist (tool start/end
    are emitted elsewhere). All forwarders abstain so decisions are unaffected.
    """

    def emit(event_type: str, data: dict[str, Any]) -> None:
        event_sink.append(HarnessEvent(type=event_type, data=data, session_id=session_id))

    def on_session_start(ctx: Any, prompt: str = "", *_a: Any) -> None:
        emit("harness.session.start", {"session_id": getattr(ctx, "session_id", session_id)})

    def on_prompt_submit(ctx: Any, prompt: str = "", *_a: Any) -> None:
        emit("harness.prompt.submit", {"length": len(prompt or "")})

    def on_permission(ctx: Any, name: str = "", arguments: Any = None, *_a: Any) -> None:
        # Fires for every tool gate (the seam runs on every call so policy can
        # veto allowed tools); the human-prompt path emits approval.* separately.
        emit("harness.permission.check", {"tool": name, "arguments": _argument_summary(arguments)})

    def on_before_compact(ctx: Any, tokens: int = 0, limit: int = 0, *_a: Any) -> None:
        emit("harness.compaction.start", {"tokens": tokens, "limit": limit})

    def on_after_compact(
        ctx: Any, tokens: int = 0, messages: Any = None, strategy: str = "", *_a: Any
    ) -> None:
        emit(
            "harness.compaction.end",
            {
                "tokens_before": tokens,
                "strategy": strategy,
                "message_count": len(messages) if messages is not None else None,
            },
        )

    def on_stop(ctx: Any, response: Any = None, *_a: Any) -> None:
        emit(
            "harness.stop",
            {
                "stopped_reason": getattr(response, "stopped_reason", None),
                "tool_calls_made": getattr(response, "tool_calls_made", None),
                "iterations": getattr(response, "iterations", None),
            },
        )

    registry.register(SESSION_START, on_session_start, name="store_session_start")
    registry.register(USER_PROMPT_SUBMIT, on_prompt_submit, name="store_prompt_submit")
    registry.register(PERMISSION_REQUEST, on_permission, name="store_permission")
    registry.register(BEFORE_COMPACT, on_before_compact, name="store_before_compact")
    registry.register(AFTER_COMPACT, on_after_compact, name="store_after_compact")
    registry.register(STOP, on_stop, name="store_stop")


def build_hook_registry(
    spec: HarnessSpec,
    *,
    event_sink: list[HarnessEvent] | None = None,
    session_id: str | None = None,
) -> tuple[HookRegistry, list[tuple[HookRuleSpec, str]]]:
    """Construct a :class:`HookRegistry` for ``spec``.

    Returns the registry plus a list of ``(rule, error)`` for any declared rule
    that failed to resolve. The registry is always usable - store forwarders are
    added first (when an ``event_sink`` is given), then declared rules.
    """
    registry = HookRegistry()
    if event_sink is not None:
        register_store_forwarders(registry, event_sink, session_id=session_id)
    # Rule-based approval policy registers first so it is evaluated before any
    # custom permission_request rules; deny-precedence still lets a later custom
    # hook deny a call this policy would have allowed.
    from .approval_memory import load_approval_memory_rules

    permission_rules = tuple(spec.execution_policy.permission_rules) + load_approval_memory_rules(
        spec
    )
    if permission_rules:
        from .permissions import build_permission_handler

        registry.register(
            PERMISSION_REQUEST,
            build_permission_handler(permission_rules),
            name="harness_permission_policy",
        )
    errors = register_spec_hooks(registry, spec)
    if errors and event_sink is not None:
        for rule, error in errors:
            event_sink.append(
                HarnessEvent(
                    type="harness.hook.error",
                    data={
                        "point": rule.point,
                        "handler": rule.handler,
                        "name": rule.name or "",
                        "error": error,
                    },
                    session_id=session_id,
                )
            )
    return registry, errors


__all__ = [
    "build_hook_registry",
    "register_spec_hooks",
    "register_store_forwarders",
    "resolve_hook_handler",
]
