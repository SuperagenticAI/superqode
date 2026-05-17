"""Tests for A2 — MCP two-way protocol (elicitation + sampling).

Both directions of MCP's server-to-client request path:

1. ``elicitation/create`` — server asks user for input. Cancel/decline/
   accept paths; dispatcher exception safety; capability advertising.
2. ``sampling/createMessage`` — server asks client to run an LLM call.
   Refusal default; gateway-backed handler routes through chat_completion;
   max_tokens cap; parse tolerance for mixed casings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from superqode.mcp.elicitation import (
    ElicitationAction,
    ElicitationHandler,
    ElicitRequest,
    ElicitResult,
    auto_cancel_elicitation_handler,
    auto_decline_elicitation_handler,
    dispatch_elicitation,
    elicitation_client_capabilities,
    make_callback_elicitation_handler,
    parse_elicitation_request,
)
from superqode.mcp.sampling import (
    SamplingHandler,
    SamplingMessage,
    SamplingRefused,
    SamplingRequest,
    SamplingResult,
    auto_reject_sampling_handler,
    dispatch_sampling,
    make_gateway_sampling_handler,
    parse_sampling_request,
    sampling_client_capabilities,
)


# ---------------------------------------------------------------------------
# Elicitation — types
# ---------------------------------------------------------------------------


def test_elicit_result_accept_with_content():
    """``accept`` carries the structured answer the user gave."""
    r = ElicitResult.accept({"repo": "owner/name"})
    assert r.action == "accept"
    assert r.content == {"repo": "owner/name"}
    assert r.to_dict() == {"action": "accept", "content": {"repo": "owner/name"}}


def test_elicit_result_decline_omits_content():
    """``decline`` and ``cancel`` must NOT include a ``content`` key —
    spec is explicit that absence means "no answer", whereas
    ``content: null`` is parsed as an empty object by some servers."""
    r = ElicitResult.decline()
    assert r.action == "decline"
    assert r.to_dict() == {"action": "decline"}
    assert "content" not in r.to_dict()


def test_elicit_result_cancel_omits_content():
    r = ElicitResult.cancel()
    assert r.to_dict() == {"action": "cancel"}


def test_elicit_result_accept_empty_dict_when_no_content():
    """``accept()`` with no content sends an empty dict — the server
    asked for an answer and got one, just an empty one. Distinct from
    ``decline`` which means "I'm refusing to answer"."""
    r = ElicitResult.accept()
    assert r.to_dict() == {"action": "accept", "content": {}}


# ---------------------------------------------------------------------------
# Elicitation — parsing
# ---------------------------------------------------------------------------


def test_parse_elicitation_request_full_payload():
    req = parse_elicitation_request(
        {
            "message": "Pick a repo",
            "requestedSchema": {"type": "object"},
            "url": "https://example.com/auth",
            "elicitationId": "el-123",
            "_meta": {"agent": "x"},
        }
    )
    assert req.message == "Pick a repo"
    assert req.requested_schema == {"type": "object"}
    assert req.url == "https://example.com/auth"
    assert req.elicitation_id == "el-123"
    assert req.meta == {"agent": "x"}


def test_parse_elicitation_request_tolerates_missing_fields():
    """Real servers vary in which optionals they populate. We should
    return a usable ``ElicitRequest`` even when only ``message`` is
    set — rejecting the call entirely would deny the user a chance
    to see what was asked."""
    req = parse_elicitation_request({"message": "hello"})
    assert req.message == "hello"
    assert req.requested_schema == {}
    assert req.url is None
    assert req.elicitation_id is None
    assert req.meta == {}


def test_parse_elicitation_request_accepts_schema_alias():
    """Some non-canonical servers use ``schema`` instead of
    ``requestedSchema``. Accept both rather than rejecting."""
    req = parse_elicitation_request({"message": "x", "schema": {"type": "string"}})
    assert req.requested_schema == {"type": "string"}


# ---------------------------------------------------------------------------
# Elicitation — dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_cancel_handler_cancels():
    """The unattended-environment default. Servers get a clean refusal."""
    result = await auto_cancel_elicitation_handler(ElicitRequest(message="please respond"))
    assert result.action == "cancel"


@pytest.mark.asyncio
async def test_auto_decline_handler_declines():
    result = await auto_decline_elicitation_handler(ElicitRequest(message="please respond"))
    assert result.action == "decline"


@pytest.mark.asyncio
async def test_dispatch_returns_cancel_when_handler_is_none():
    """Treat "no handler configured" the same as opting out — servers
    may probe optimistically and we don't want to error out."""
    wire = await dispatch_elicitation(None, {"message": "x"})
    assert wire == {"action": "cancel"}


@pytest.mark.asyncio
async def test_dispatch_swallows_handler_exceptions_as_cancel():
    """A buggy handler must not deadlock the MCP connection. The
    server sees a clean refusal; the bug is the host app's problem
    to find via its own logging."""

    async def broken(_request: ElicitRequest) -> ElicitResult:
        raise RuntimeError("handler is broken")

    wire = await dispatch_elicitation(broken, {"message": "x"})
    assert wire == {"action": "cancel"}


@pytest.mark.asyncio
async def test_dispatch_handler_returning_wrong_type_is_cancelled():
    """A handler that returns a dict instead of ElicitResult is
    a contract violation — cancel rather than risk sending garbage
    over the wire."""

    async def bad_type(_request: ElicitRequest):
        return {"action": "accept"}  # right shape, wrong type

    wire = await dispatch_elicitation(bad_type, {"message": "x"})
    assert wire == {"action": "cancel"}


@pytest.mark.asyncio
async def test_dispatch_routes_request_to_callback():
    """The end-to-end path: server payload → ElicitRequest → callback
    → ElicitResult → wire dict."""
    seen: List[ElicitRequest] = []

    async def cb(request: ElicitRequest) -> ElicitResult:
        seen.append(request)
        return ElicitResult.accept({"answer": "yes"})

    handler = make_callback_elicitation_handler(cb)
    wire = await dispatch_elicitation(handler, {"message": "ok?", "elicitationId": "e1"})
    assert wire == {"action": "accept", "content": {"answer": "yes"}}
    assert len(seen) == 1
    assert seen[0].elicitation_id == "e1"


def test_elicitation_client_capabilities_shape():
    """Capability block must be the exact shape spec'd — empty object
    means "present, no sub-fields claimed". Don't accidentally emit
    ``{"elicitation": True}``."""
    assert elicitation_client_capabilities() == {"elicitation": {}}


# ---------------------------------------------------------------------------
# Sampling — types
# ---------------------------------------------------------------------------


def test_sampling_result_to_dict_wraps_text_in_content_block():
    """MCP's content shape is ``{"type": "text", "text": "..."}`` so
    image/audio types plug into the same envelope. Don't emit raw text
    string — older servers fail to parse it."""
    r = SamplingResult(
        role="assistant",
        content_text="hello world",
        model="claude-sonnet-4",
        stop_reason="endTurn",
    )
    wire = r.to_dict()
    assert wire == {
        "role": "assistant",
        "content": {"type": "text", "text": "hello world"},
        "model": "claude-sonnet-4",
        "stopReason": "endTurn",
    }


def test_sampling_result_default_stop_reason():
    r = SamplingResult(role="assistant", content_text="x", model="m")
    assert r.stop_reason == "endTurn"


# ---------------------------------------------------------------------------
# Sampling — parsing
# ---------------------------------------------------------------------------


def test_parse_sampling_request_extracts_text_from_string_content():
    """Most MCP servers send content as a plain string; the spec
    actually requires a structured block but real-world servers
    mix both — accept either."""
    req = parse_sampling_request(
        {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ]
        }
    )
    assert [m.text for m in req.messages] == ["hello", "hi"]
    assert [m.role for m in req.messages] == ["user", "assistant"]


def test_parse_sampling_request_extracts_text_from_block_content():
    req = parse_sampling_request(
        {"messages": [{"role": "user", "content": {"type": "text", "text": "block-form"}}]}
    )
    assert req.messages[0].text == "block-form"


def test_parse_sampling_request_concatenates_multi_block_content():
    """Some servers send the user message as a list of text blocks
    (e.g. when interleaving citations). Concatenate so the handler
    sees the full text."""
    req = parse_sampling_request(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Part one. "},
                        {"type": "text", "text": "Part two."},
                    ],
                }
            ]
        }
    )
    assert req.messages[0].text == "Part one. Part two."


def test_parse_sampling_request_accepts_snake_case_aliases():
    """fast-agent uses MCP-canonical camelCase. Other clients/servers
    sometimes send snake_case. Accept both rather than dropping the
    field on the floor."""
    req = parse_sampling_request(
        {
            "messages": [],
            "max_tokens": 500,
            "system_prompt": "be brief",
            "model_preferences": {"hints": [{"name": "haiku"}]},
            "include_context": "thisServer",
        }
    )
    assert req.max_tokens == 500
    assert req.system_prompt == "be brief"
    assert req.model_preferences == {"hints": [{"name": "haiku"}]}
    assert req.include_context == "thisServer"


def test_parse_sampling_request_camelcase_takes_priority():
    """When both are sent (server using camelCase, client lib echoing
    snake_case), spec form wins. This shouldn't happen in practice
    but proves we're not falling back haphazardly."""
    req = parse_sampling_request(
        {
            "messages": [],
            "maxTokens": 100,
            "max_tokens": 999,
        }
    )
    assert req.max_tokens == 100


def test_parse_sampling_request_handles_non_dict_messages():
    """A malformed entry shouldn't crash the whole parse — skip it
    and keep going with the rest of the messages."""
    req = parse_sampling_request(
        {
            "messages": [
                "not a dict",
                {"role": "user", "content": "valid"},
                None,
            ]
        }
    )
    assert len(req.messages) == 1
    assert req.messages[0].text == "valid"


# ---------------------------------------------------------------------------
# Sampling — dispatcher and default handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_reject_sampling_raises_typed_error():
    """``auto_reject`` raises a typed exception so the wire layer can
    map it to an MCP ``ErrorData`` reply — silent fake success would
    be worse."""
    with pytest.raises(SamplingRefused):
        await auto_reject_sampling_handler(
            SamplingRequest(messages=[SamplingMessage(role="user", text="hi")])
        )


@pytest.mark.asyncio
async def test_dispatch_sampling_raises_when_no_handler_configured():
    """No handler == this client refuses sampling. Servers should see
    a real error, not a fake empty result — they specifically asked
    for compute."""
    with pytest.raises(SamplingRefused):
        await dispatch_sampling(None, {"messages": []})


@pytest.mark.asyncio
async def test_dispatch_sampling_rejects_handler_returning_wrong_type():
    """Contract violation — surface a real error rather than fabricating
    a reply from a dict the handler returned."""

    async def bad_handler(_request: SamplingRequest):
        return {"role": "assistant", "content": "x"}

    with pytest.raises(TypeError):
        await dispatch_sampling(bad_handler, {"messages": [{"role": "user", "content": "hi"}]})


@pytest.mark.asyncio
async def test_dispatch_sampling_round_trips_through_handler():
    async def handler(request: SamplingRequest) -> SamplingResult:
        # Echo back the user's text. Used as a sentinel to confirm
        # the parse path delivered what the server sent.
        return SamplingResult(
            role="assistant",
            content_text=f"echo: {request.messages[-1].text}",
            model="test-model",
            stop_reason="endTurn",
        )

    wire = await dispatch_sampling(
        handler,
        {
            "messages": [{"role": "user", "content": "hello"}],
            "maxTokens": 64,
        },
    )
    assert wire["role"] == "assistant"
    assert wire["content"] == {"type": "text", "text": "echo: hello"}
    assert wire["model"] == "test-model"
    assert wire["stopReason"] == "endTurn"


def test_sampling_client_capabilities_shape():
    assert sampling_client_capabilities() == {"sampling": {}}


# ---------------------------------------------------------------------------
# Sampling — gateway-backed handler
# ---------------------------------------------------------------------------


@dataclass
class _FakeGatewayResponse:
    content: str
    role: str = "assistant"
    model: str = "claude-sonnet-4"
    finish_reason: str = "stop"


class _FakeGateway:
    """Minimal stand-in for LiteLLMGateway. Records the call args so
    tests can assert what the handler shipped to the gateway."""

    def __init__(self, response: _FakeGatewayResponse) -> None:
        self.response = response
        self.calls: List[Dict[str, Any]] = []

    async def chat_completion(self, **kwargs: Any) -> _FakeGatewayResponse:
        self.calls.append(kwargs)
        return self.response


@pytest.mark.asyncio
async def test_gateway_sampling_handler_routes_through_chat_completion():
    """The whole point of this handler: convert MCP sampling format
    into the gateway's Message list, run the call, package the result."""
    gw = _FakeGateway(_FakeGatewayResponse(content="summary text", model="claude-sonnet-4"))
    handler = make_gateway_sampling_handler(
        gw, default_model="claude-sonnet-4", default_provider="anthropic"
    )

    result = await handler(
        SamplingRequest(
            messages=[
                SamplingMessage(role="user", text="summarize this"),
            ],
            system_prompt="You summarize concisely.",
            temperature=0.3,
            max_tokens=200,
        )
    )

    assert result.content_text == "summary text"
    assert result.model == "claude-sonnet-4"
    assert result.role == "assistant"
    assert result.stop_reason == "endTurn"

    # Inspect what we sent down to the gateway.
    assert len(gw.calls) == 1
    call = gw.calls[0]
    msgs = call["messages"]
    assert msgs[0].role == "system"
    assert msgs[0].content == "You summarize concisely."
    assert msgs[1].role == "user"
    assert msgs[1].content == "summarize this"
    assert call["model"] == "claude-sonnet-4"
    assert call["provider"] == "anthropic"
    assert call["temperature"] == 0.3
    assert call["max_tokens"] == 200


@pytest.mark.asyncio
async def test_gateway_sampling_handler_applies_max_tokens_cap():
    """A cap means the host gets to limit per-server cost regardless
    of what the server asked for."""
    gw = _FakeGateway(_FakeGatewayResponse(content="x", model="m"))
    handler = make_gateway_sampling_handler(gw, default_model="m", max_tokens_cap=100)

    await handler(
        SamplingRequest(
            messages=[SamplingMessage(role="user", text="hi")],
            max_tokens=5000,
        )
    )
    assert gw.calls[0]["max_tokens"] == 100


@pytest.mark.asyncio
async def test_gateway_sampling_handler_uses_cap_when_no_request_max():
    """If the server didn't specify max_tokens but a cap exists, apply
    the cap — server should never accidentally exceed the host's
    intended ceiling just by omitting the field."""
    gw = _FakeGateway(_FakeGatewayResponse(content="x", model="m"))
    handler = make_gateway_sampling_handler(gw, default_model="m", max_tokens_cap=50)
    await handler(SamplingRequest(messages=[SamplingMessage(role="user", text="hi")]))
    assert gw.calls[0]["max_tokens"] == 50


@pytest.mark.asyncio
async def test_gateway_sampling_handler_no_cap_honors_request():
    gw = _FakeGateway(_FakeGatewayResponse(content="x", model="m"))
    handler = make_gateway_sampling_handler(gw, default_model="m")
    await handler(
        SamplingRequest(
            messages=[SamplingMessage(role="user", text="hi")],
            max_tokens=9999,
        )
    )
    assert gw.calls[0]["max_tokens"] == 9999


@pytest.mark.asyncio
async def test_gateway_sampling_handler_empty_content_becomes_empty_string():
    """If the model only produced tool calls, ``content`` is empty —
    we still need to return valid JSON to the MCP server. Empty
    string is the right wire value."""
    gw = _FakeGateway(_FakeGatewayResponse(content=""))
    handler = make_gateway_sampling_handler(gw, default_model="m")
    result = await handler(SamplingRequest(messages=[SamplingMessage(role="user", text="hi")]))
    assert result.content_text == ""


@pytest.mark.asyncio
async def test_gateway_sampling_handler_maps_finish_reasons():
    """The spec only knows three stopReasons. The gateway may emit any
    string. Map known synonyms and default unknown to ``endTurn``."""

    async def _call(finish: Optional[str]) -> str:
        gw = _FakeGateway(_FakeGatewayResponse(content="x", finish_reason=finish))
        handler = make_gateway_sampling_handler(gw, default_model="m")
        result = await handler(SamplingRequest(messages=[SamplingMessage(role="user", text="hi")]))
        return result.stop_reason

    assert await _call("length") == "maxTokens"
    assert await _call("max_tokens") == "maxTokens"
    assert await _call("stop_sequence") == "stopSequence"
    assert await _call("stop") == "endTurn"
    assert await _call(None) == "endTurn"
    assert await _call("tool_use") == "endTurn"  # unknown → safe default


@pytest.mark.asyncio
async def test_dispatch_sampling_uses_gateway_handler_end_to_end():
    """Full round-trip: JSON wire payload → parse → gateway handler
    → SamplingResult.to_dict → JSON wire payload. This is the path
    real MCP servers will exercise."""
    gw = _FakeGateway(_FakeGatewayResponse(content="ranked", model="claude-sonnet-4"))
    handler = make_gateway_sampling_handler(gw, default_model="claude-sonnet-4")

    wire = await dispatch_sampling(
        handler,
        {
            "messages": [{"role": "user", "content": "rank these search results"}],
            "systemPrompt": "Score 0-1.",
            "maxTokens": 100,
        },
    )
    assert wire["content"] == {"type": "text", "text": "ranked"}
    assert wire["model"] == "claude-sonnet-4"
    # Confirm the system prompt threaded through.
    assert any(m.role == "system" for m in gw.calls[0]["messages"])
