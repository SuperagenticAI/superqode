"""MCP elicitation handling.

What MCP elicitation is
-----------------------
The MCP spec defines a reverse request: ``elicitation/create`` — the
server asks the *client* to collect a piece of information from the
user. The server provides a message and a JSON-Schema describing what
shape of answer it wants; the client renders a form, the user fills it
in, the client returns the values.

Without this, half the MCP server ecosystem is invisible to us:

- A GitHub MCP server can't ask "which repository?" before fetching.
- A Notion MCP server can't ask "which database id?" before writing.
- A Hugging Face MCP server can't ask "which model?" before searching.

fast-agent supports this via two layers (``mcp/elicitation_handlers.py``
+ ``mcp/elicitation_factory.py``). We mirror the public surface but
keep the implementation a single module since SuperQode's TUI/CLI
delegates form rendering to the host callback rather than to a forms
library.

Public surface
--------------
Three concrete shapes:

- ``ElicitRequest`` — what the MCP server sent us.
- ``ElicitResult`` — what we send back. ``action`` is one of
  ``accept`` / ``decline`` / ``cancel`` (mirrors the spec verbatim).
- ``ElicitationHandler`` — Protocol any handler satisfies.

Two predefined handlers:

- ``auto_cancel_elicitation_handler`` — production-safe default. Says
  "no" to every elicitation. Useful when you want to *advertise*
  elicitation capability (so the server knows the client is modern)
  but reject the prompts (so unattended runs don't hang).
- ``make_callback_elicitation_handler(callback)`` — wraps an async
  user callback so the host app (CLI, TUI) can render its own UI.

Capability advertisement
------------------------
When a handler is configured, advertise ``elicitation: {}`` in the
``clientCapabilities`` block of the MCP ``initialize`` request. Servers
key off this to decide whether to even send these prompts. The helper
``elicitation_client_capabilities()`` returns the right shape so
client code doesn't have to remember the field name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Protocol


# Spec values for ``ElicitResult.action``. Verbatim from MCP's typings —
# making them a Literal here means our handlers can't accidentally
# return some plausible-but-wrong value like ``"reject"``.
ElicitationAction = Literal["accept", "decline", "cancel"]


@dataclass(frozen=True)
class ElicitRequest:
    """Incoming ``elicitation/create`` payload from an MCP server.

    Fields mirror the MCP spec. ``requested_schema`` is a JSON-Schema
    dict the server expects the answer to conform to; we don't validate
    it here — that's the handler's job (or the agent loop's, when an
    agent caller wires schema-aware UI).
    """

    message: str
    requested_schema: Dict[str, Any] = field(default_factory=dict)
    # Some servers attach an out-of-band URL the user can click to
    # complete the request (browser-based OAuth-like flows). When set,
    # the handler should typically just acknowledge ``accept`` and
    # surface the URL to the user.
    url: Optional[str] = None
    # Server-assigned identifier so a server can correlate the response
    # if it sent multiple parallel elicitations.
    elicitation_id: Optional[str] = None
    # Free-form server context — anything the spec adds later or
    # vendor extensions plumb through.
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ElicitResult:
    """Reply to an elicitation request.

    ``content`` is included only when ``action == "accept"`` — for
    ``decline`` / ``cancel`` it's left as ``None`` so the server can't
    confuse a structured decline with a partial answer.
    """

    action: ElicitationAction
    content: Optional[Dict[str, Any]] = None

    @classmethod
    def accept(cls, content: Optional[Dict[str, Any]] = None) -> "ElicitResult":
        return cls(action="accept", content=content or {})

    @classmethod
    def decline(cls) -> "ElicitResult":
        """User said no but didn't abort. Server should treat as a soft
        refusal — try a different path, ask a different question."""
        return cls(action="decline")

    @classmethod
    def cancel(cls) -> "ElicitResult":
        """User aborted the whole interaction. Server should typically
        give up on the current call entirely, not fall back."""
        return cls(action="cancel")

    def to_dict(self) -> Dict[str, Any]:
        """Wire format — what we send back over JSON-RPC.

        We omit ``content`` when it's ``None`` so the payload matches
        the MCP spec's "absent" semantics rather than ``content: null``
        which some implementations parse as an empty object.
        """
        out: Dict[str, Any] = {"action": self.action}
        if self.content is not None:
            out["content"] = self.content
        return out


class ElicitationHandler(Protocol):
    """Any async callable matching this signature can serve as the handler.

    Returning an ``ErrorData``-shaped dict isn't part of the protocol —
    handler exceptions are caught by ``dispatch_elicitation`` and
    translated into a ``cancel`` reply so a buggy handler can't hang
    the connection.
    """

    async def __call__(self, request: ElicitRequest) -> ElicitResult: ...


# ---------------------------------------------------------------------------
# Predefined handlers
# ---------------------------------------------------------------------------


async def auto_cancel_elicitation_handler(request: ElicitRequest) -> ElicitResult:
    """Reject every elicitation with ``cancel``.

    Why this is the right default for unattended environments:
    - Advertising ``elicitation: {}`` capability tells servers you're
      a modern client; some servers silently downgrade behavior
      otherwise.
    - But you don't want a CI run to hang waiting for a human form.
    - ``cancel`` tells the server "give up", not "try again later" —
      so the server returns its error path quickly.
    """
    return ElicitResult.cancel()


async def auto_decline_elicitation_handler(request: ElicitRequest) -> ElicitResult:
    """Soft-refuse every elicitation with ``decline``.

    Use this when you'd rather the server try a fallback path than
    abort outright. Distinct from ``auto_cancel`` because some
    servers branch differently on the two replies.
    """
    return ElicitResult.decline()


def make_callback_elicitation_handler(
    callback: Callable[[ElicitRequest], Awaitable[ElicitResult]],
) -> ElicitationHandler:
    """Wrap a user-supplied async callback in the handler shape.

    The callback owns presentation (TUI form, terminal prompt, browser
    handoff) — this just adapts it. We don't catch exceptions inside
    the callback because the dispatcher does; bubble them and the
    caller sees the actual stack instead of a fake ``cancel`` masking
    a real bug.
    """

    async def handler(request: ElicitRequest) -> ElicitResult:
        return await callback(request)

    return handler


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------


def elicitation_client_capabilities() -> Dict[str, Any]:
    """The block to merge into ``clientCapabilities`` at MCP initialize.

    Empty object signals "capability is present" without committing to
    any sub-fields (the spec leaves room for future expansion). This
    is the same shape fast-agent ships."""
    return {"elicitation": {}}


def parse_elicitation_request(params: Dict[str, Any]) -> ElicitRequest:
    """Build an ``ElicitRequest`` from raw JSON-RPC params.

    Tolerant to missing fields — servers vary in which optional fields
    they actually populate, and we'd rather have a partial request to
    show the user than reject the whole call over a missing
    ``elicitationId``.
    """
    return ElicitRequest(
        message=str(params.get("message", "")),
        requested_schema=params.get("requestedSchema") or params.get("schema") or {},
        url=params.get("url"),
        elicitation_id=params.get("elicitationId"),
        meta=params.get("_meta") or {},
    )


async def dispatch_elicitation(
    handler: Optional[ElicitationHandler], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Run an elicitation request through the configured handler.

    Wire-format in, wire-format out. Any handler exception is
    swallowed into a ``cancel`` so a broken handler can't deadlock the
    MCP connection — the server gets a clean refusal and moves on.

    When no handler is configured we also return ``cancel`` (treat
    "unconfigured" the same as "explicitly opted-out") rather than
    erroring out, since servers may probe optimistically.
    """
    if handler is None:
        return ElicitResult.cancel().to_dict()
    try:
        request = parse_elicitation_request(params)
        result = await handler(request)
    except Exception:
        # Don't propagate — the wire is more important than the
        # specific failure. Logging is the host app's responsibility.
        return ElicitResult.cancel().to_dict()
    if not isinstance(result, ElicitResult):
        # A handler returned the wrong type. Treat as cancel for safety.
        return ElicitResult.cancel().to_dict()
    return result.to_dict()
