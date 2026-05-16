"""ACP-style tool-call parent linking for SuperQode.

Why this exists
---------------
When a sub-agent (spawned by ``SubAgentTool``) runs, every tool call it makes
should be visually nestable under the sub-agent's own tool call in any
ACP-style UI. The ACP protocol carries arbitrary fields in ``_meta`` on
``tool_call`` / ``tool_call_update`` messages; fast-agent's convention is
``_meta.parentToolCallId``.

This module ports that convention so:

1. Our agent loop sets the current tool's id into a ``ContextVar`` right
   before calling ``tool.execute(...)``.
2. When ``SubAgentTool`` dispatches the child agent run, it wraps that run
   in ``acp_tool_call_context(parent_tool_call_id=<own id>)`` so every tool
   call inside the child inherits the parent id.
3. Anywhere we record or emit a tool action — locally for display, or
   outward over ACP — we call ``get_acp_tool_call_meta()`` and attach the
   result. Clients that don't honor ``_meta`` are unaffected; clients that
   do can render the tree.

Non-breaking: the ``ContextVar`` defaults to ``None`` and the meta payload
is omitted entirely when there is no parent.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional


@dataclass(frozen=True)
class ACPToolCallContext:
    """Per-async-task metadata to attach to tool-call notifications."""

    parent_tool_call_id: Optional[str] = None

    def to_meta(self) -> Optional[Dict[str, Any]]:
        """Render to an ACP ``_meta`` payload, or ``None`` if empty.

        Returning ``None`` (rather than ``{}``) lets callers do
        ``if meta:`` and only emit the field when there's something useful
        to attach.
        """
        meta: Dict[str, Any] = {}
        if self.parent_tool_call_id:
            meta["parentToolCallId"] = self.parent_tool_call_id
        return meta or None


_acp_tool_call_context: ContextVar[Optional[ACPToolCallContext]] = ContextVar(
    "acp_tool_call_context", default=None
)


def get_acp_tool_call_context() -> Optional[ACPToolCallContext]:
    """Return the current tool-call context for this async task, or ``None``."""
    return _acp_tool_call_context.get()


def get_acp_tool_call_meta() -> Optional[Dict[str, Any]]:
    """Return the ``_meta`` payload to attach to tool-call messages.

    Convenience wrapper — most callers only care about the ready-to-merge
    dict, not the full context object.
    """
    ctx = _acp_tool_call_context.get()
    return ctx.to_meta() if ctx else None


def get_parent_tool_call_id() -> Optional[str]:
    """Shortcut for the most-used field. Returns ``None`` at the top level."""
    ctx = _acp_tool_call_context.get()
    return ctx.parent_tool_call_id if ctx else None


@contextmanager
def acp_tool_call_context(
    *, parent_tool_call_id: Optional[str] = None
) -> Iterator[ACPToolCallContext]:
    """Temporarily set tool-call context for the current async task.

    Fields merge over any existing context so nested ``with`` blocks
    override only what they specify. Restored on exit via ContextVar
    token, so concurrent tasks don't see each other's state.
    """
    current = _acp_tool_call_context.get() or ACPToolCallContext()
    merged = ACPToolCallContext(
        parent_tool_call_id=(
            parent_tool_call_id
            if parent_tool_call_id is not None
            else current.parent_tool_call_id
        ),
    )
    token = _acp_tool_call_context.set(merged)
    try:
        yield merged
    finally:
        _acp_tool_call_context.reset(token)
