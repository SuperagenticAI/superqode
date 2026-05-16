"""MCP sampling handling (A2 from the fast-agent gap audit).

What MCP sampling is
--------------------
The MCP spec defines another reverse request: ``sampling/createMessage``
— the server asks the *client* to run an LLM completion on its behalf
and return the result. Use cases:

- A code-search MCP server runs semantic ranking on results before
  returning them; it asks the client to score relevance.
- A documentation MCP server summarizes a long doc before returning it;
  it asks the client to summarize.
- A workflow MCP server orchestrates multi-step reasoning across many
  agents; it asks the client to think.

This is the most subtle MCP feature — the server uses *our* LLM key
to run *its* prompts. That's intentional: the user pays for tokens,
the user picks the model, the user enforces budgets. The server gets
intelligence without holding credentials.

Public surface
--------------
- ``SamplingRequest`` — what the server sends.
- ``SamplingResult`` — what we reply.
- ``SamplingHandler`` Protocol.
- ``auto_reject_sampling_handler`` — production-safe default; refuses
  every request. Servers that depend on sampling will fail loudly.
- ``make_gateway_sampling_handler(gateway, default_model)`` — runs
  the request through SuperQode's LiteLLM gateway. Honors per-turn
  ``task_budget``, ``reasoning_effort``, etc. via the same path the
  agent loop uses.

Capability advertisement
------------------------
Advertise ``sampling: {}`` in ``clientCapabilities`` only when a real
handler is wired. Advertising and then auto-rejecting wastes server
work — they may construct a long sampling payload before getting our
"no". Helper: ``sampling_client_capabilities()``.

Why this lives separately from ``elicitation.py``
-------------------------------------------------
They share a shape (reverse JSON-RPC request, dispatcher pattern) but
the semantics are unrelated. Keeping the modules distinct means:
- Test files stay focused.
- ``make_gateway_sampling_handler`` can import the gateway without
  pulling that dependency into elicitation tests.
- A future "sampling without elicitation" or vice-versa config stays
  trivial (just don't wire one of the handlers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SamplingMessage:
    """One message in a sampling request.

    MCP's ``role`` is limited to ``"user"`` / ``"assistant"`` (no
    ``system``; system prompts are passed via ``system_prompt`` on the
    parent ``SamplingRequest``). We don't enforce that here — pass-
    through is safer; the gateway will reject unknown roles loudly.
    """

    role: str
    text: str


@dataclass(frozen=True)
class SamplingRequest:
    """Incoming ``sampling/createMessage`` payload from an MCP server.

    Fields mirror the MCP spec. ``model_preferences`` is a hint from
    the server about which model family it'd like — we treat it as
    advisory and let the handler decide.
    """

    messages: List[SamplingMessage]
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    # Server-suggested model. Most servers leave this empty and trust
    # the client's default; some pass a hint like ``"haiku"`` to nudge
    # us toward a cheaper option for low-stakes work.
    model_preferences: Dict[str, Any] = field(default_factory=dict)
    # Subset of the host's prior context the server thinks is relevant.
    # We pass-through; the handler decides how much to surface.
    include_context: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SamplingResult:
    """Reply to a sampling request.

    ``stop_reason`` mirrors the spec's ``endTurn`` / ``stopSequence`` /
    ``maxTokens`` set — we accept any string and let the server
    interpret. ``model`` should be the actual model id the client ran
    (not the server's preference, which the server already knows).
    """

    role: str
    content_text: str
    model: str
    stop_reason: str = "endTurn"

    def to_dict(self) -> Dict[str, Any]:
        """Wire-format for the JSON-RPC reply.

        MCP wraps text in a ``{"type": "text", "text": ...}`` block so
        future content types (image, audio) plug into the same shape.
        """
        return {
            "role": self.role,
            "content": {"type": "text", "text": self.content_text},
            "model": self.model,
            "stopReason": self.stop_reason,
        }


class SamplingHandler(Protocol):
    """Async callable that turns a ``SamplingRequest`` into a result."""

    async def __call__(self, request: SamplingRequest) -> SamplingResult:
        ...


# ---------------------------------------------------------------------------
# Predefined handlers
# ---------------------------------------------------------------------------


class SamplingRefused(RuntimeError):
    """Raised by ``auto_reject_sampling_handler``.

    A typed exception (rather than a bare ``RuntimeError``) lets the
    MCP wire layer translate it to an MCP ``ErrorData`` with a
    consistent message instead of leaking arbitrary stack trace text
    to servers.
    """


async def auto_reject_sampling_handler(request: SamplingRequest) -> SamplingResult:
    """Refuse every sampling request.

    This is the safest default for hosted environments where the
    user might not want servers consuming their LLM credits. The
    refusal is loud (an exception) rather than silent (a fake empty
    result) so server-side bugs surface clearly.
    """
    raise SamplingRefused(
        "Sampling is not enabled in this SuperQode session. "
        "Configure a sampling handler to allow MCP servers to call "
        "your LLM."
    )


def make_gateway_sampling_handler(
    gateway: Any,
    default_model: str,
    default_provider: Optional[str] = None,
    *,
    max_tokens_cap: Optional[int] = None,
) -> SamplingHandler:
    """Build a handler that runs sampling through a LiteLLMGateway.

    Args:
        gateway: An object with ``chat_completion(messages, model, ...)``.
            The type isn't pinned to ``LiteLLMGateway`` so tests can
            substitute a fake without dragging in LiteLLM.
        default_model: Model id to use when the server doesn't specify
            one (the common case — most servers leave this empty).
        default_provider: Hint for the gateway's provider routing.
        max_tokens_cap: Optional ceiling on ``max_tokens``. Servers can
            request arbitrarily large completions; this is the host's
            chance to cap that. ``None`` = honor whatever the server
            asked for.

    Returns:
        A handler whose calls go through the standard gateway path —
        so prompt caching, the local-model shim, task budgets, and
        reasoning effort all apply transparently.
    """
    # Import here so the elicitation tests don't transitively pull
    # the gateway (which would force LiteLLM on import).
    from superqode.providers.gateway.base import Message

    async def handler(request: SamplingRequest) -> SamplingResult:
        messages: List[Any] = []
        if request.system_prompt:
            messages.append(Message(role="system", content=request.system_prompt))
        for m in request.messages:
            messages.append(Message(role=m.role, content=m.text))

        # Respect the server's max_tokens unless we have a cap.
        max_tok = request.max_tokens
        if max_tokens_cap is not None:
            if max_tok is None or max_tok > max_tokens_cap:
                max_tok = max_tokens_cap

        # Server's model preference is a hint, not a directive. Use it
        # only if it's a non-empty string; otherwise fall back to the
        # host-supplied default. We don't try to translate aliases like
        # ``"haiku"`` into specific Claude model ids — that's host
        # configuration, not handler logic.
        model = default_model
        preferred = request.model_preferences.get("hints") if request.model_preferences else None
        if isinstance(preferred, list) and preferred:
            # MCP defines hints as a list of {"name": "..."} entries.
            first = preferred[0]
            if isinstance(first, dict) and isinstance(first.get("name"), str):
                if first["name"].strip():
                    # Treat as a *preference*, not a hard switch — keep
                    # the default unless the host wants per-request
                    # routing. For now we log-by-no-op: prefer
                    # default_model so behavior is predictable.
                    pass

        response = await gateway.chat_completion(
            messages=messages,
            model=model,
            provider=default_provider,
            temperature=request.temperature,
            max_tokens=max_tok,
        )

        # ``GatewayResponse.content`` may be empty if the model only
        # produced tool calls — but the sampling spec expects text.
        # Fall back to empty string rather than ``None`` so the wire
        # payload stays valid JSON.
        content = response.content or ""
        return SamplingResult(
            role=getattr(response, "role", None) or "assistant",
            content_text=content,
            model=getattr(response, "model", None) or model,
            stop_reason=_map_finish_reason(getattr(response, "finish_reason", None)),
        )

    return handler


def _map_finish_reason(finish: Optional[str]) -> str:
    """Translate the gateway's finish_reason to MCP stopReason values.

    The spec's set is small: ``endTurn`` / ``stopSequence`` /
    ``maxTokens``. Anything else maps to ``endTurn`` so servers don't
    crash on an unknown enum value.
    """
    if not finish:
        return "endTurn"
    f = finish.lower()
    if "length" in f or "max" in f:
        return "maxTokens"
    if "stop" in f and "sequence" in f:
        return "stopSequence"
    return "endTurn"


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------


def sampling_client_capabilities() -> Dict[str, Any]:
    """The block to merge into ``clientCapabilities`` at MCP initialize.

    Empty object signals presence without committing to sub-fields.
    Only advertise when a real handler is wired (auto-reject is a
    valid handler but doesn't deserve to be advertised — that wastes
    server work)."""
    return {"sampling": {}}


def parse_sampling_request(params: Dict[str, Any]) -> SamplingRequest:
    """Build a ``SamplingRequest`` from raw JSON-RPC params.

    Tolerant to:
    - Missing optional fields (most are optional in the spec).
    - Both ``modelPreferences`` and ``model_preferences`` casings —
      some non-MCP-canonical servers send snake_case.
    - Messages whose content is a string vs. a structured block —
      we extract text in both cases so handlers don't have to.
    """
    raw_msgs = params.get("messages") or []
    messages: List[SamplingMessage] = []
    for raw in raw_msgs:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role", "user"))
        content = raw.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, dict):
            text = str(content.get("text", ""))
        elif isinstance(content, list):
            # Concatenate text-typed blocks; ignore others for now.
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            text = "".join(parts)
        else:
            text = ""
        messages.append(SamplingMessage(role=role, text=text))

    return SamplingRequest(
        messages=messages,
        max_tokens=params.get("maxTokens") or params.get("max_tokens"),
        system_prompt=params.get("systemPrompt") or params.get("system_prompt"),
        temperature=params.get("temperature"),
        model_preferences=(
            params.get("modelPreferences") or params.get("model_preferences") or {}
        ),
        include_context=params.get("includeContext") or params.get("include_context"),
        metadata=params.get("metadata") or {},
        meta=params.get("_meta") or {},
    )


async def dispatch_sampling(
    handler: Optional[SamplingHandler], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Run a sampling request through the configured handler.

    Wire-format in, wire-format out. When no handler is configured we
    raise ``SamplingRefused`` so the MCP transport layer can map it
    to an MCP ``ErrorData`` reply — a missing handler is a *real*
    error from the server's perspective (it asked for compute and
    didn't get it), distinct from elicitation where ``cancel`` is a
    valid soft-no.
    """
    if handler is None:
        raise SamplingRefused(
            "No sampling handler configured. To enable sampling, "
            "wire make_gateway_sampling_handler(...) into your MCP client."
        )
    request = parse_sampling_request(params)
    result = await handler(request)
    if not isinstance(result, SamplingResult):
        # Handler returned the wrong type — that's a contract violation,
        # surface as a real error rather than a fake reply.
        raise TypeError(
            f"Sampling handler must return SamplingResult, got {type(result).__name__}"
        )
    return result.to_dict()
