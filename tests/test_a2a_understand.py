"""Tests for reading a shortlist request with a model.

The model interprets the human. It is never shown the catalogue and never
asked to name a harness, so these tests care most about what it is not
allowed to influence.
"""

from __future__ import annotations

from superqode.a2a.understand import understand_request


def _reply(text):
    def completion(provider, model, messages, **kwargs):
        return text

    return completion


def test_a_model_reply_becomes_constraints():
    constraints, understood = understand_request(
        "We are a Rust shop with a big monorepo and strict compliance rules",
        provider="google",
        model="gemini-flash-latest",
        completion=_reply(
            '{"terms": ["rust", "monorepo"], "capabilities": ["sandbox", "approvals"],'
            ' "open_source_preferred": true}'
        ),
    )
    assert understood
    assert constraints.terms == ("rust", "monorepo")
    assert constraints.capabilities == ("sandbox", "approvals")
    assert constraints.open_source_preferred


def test_a_fenced_reply_is_still_read():
    constraints, understood = understand_request(
        "anything",
        provider="google",
        model="m",
        completion=_reply('```json\n{"terms": ["rust"]}\n```'),
    )
    assert understood
    assert constraints.terms == ("rust",)


def test_invented_capabilities_are_discarded():
    """A model must not create a constraint the catalogue cannot answer.

    "gpu" and "compliance" are not things the Hub records, so keeping them
    would silently filter against a field that does not exist.
    """
    constraints, _ = understand_request(
        "anything",
        provider="google",
        model="m",
        completion=_reply('{"capabilities": ["gpu", "compliance", "sandbox"]}'),
    )
    assert constraints.capabilities == ("sandbox",)


def test_a_failing_model_falls_back_to_keywords():
    """A worse shortlist beats an error page."""

    def explode(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    constraints, understood = understand_request(
        "open source harness with a sandbox",
        provider="google",
        model="m",
        completion=explode,
    )
    assert not understood
    assert constraints.capabilities == ("sandbox",)
    assert constraints.open_source_preferred


def test_a_reply_with_no_json_falls_back_to_keywords():
    constraints, understood = understand_request(
        "needs a sandbox",
        provider="google",
        model="m",
        completion=_reply("I think you should use a popular coding agent!"),
    )
    assert not understood
    assert constraints.capabilities == ("sandbox",)


def test_an_empty_request_does_not_call_the_model():
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return "{}"

    _, understood = understand_request("   ", provider="google", model="m", completion=counted)
    assert not understood
    assert calls == []


def test_the_request_and_reply_are_both_capped():
    """Neither side of the call is allowed to be open ended."""
    seen = {}

    def capture(provider, model, messages, **kwargs):
        seen["user"] = messages[-1]["content"]
        seen["kwargs"] = kwargs
        return "{}"

    understand_request("x" * 5000, provider="google", model="m", completion=capture)
    assert len(seen["user"]) <= 800
    assert seen["kwargs"]["max_tokens"] == 512
    assert seen["kwargs"]["temperature"] == 0
    # Extraction needs no deliberation, and on a thinking model those tokens
    # come out of the same allowance as the answer.
    assert seen["kwargs"]["reasoning_effort"] == "none"


def test_the_catalogue_is_never_sent_to_the_model():
    """Facts come from the Hub. The model only reads the human."""
    seen = {}

    def capture(provider, model, messages, **kwargs):
        seen["messages"] = messages
        return "{}"

    understand_request(
        "which harness should we use", provider="google", model="m", completion=capture
    )
    joined = " ".join(message["content"] for message in seen["messages"]).casefold()
    for vendor in ("claude code", "codex", "cursor", "aider", "superqode", "prime agent"):
        assert vendor not in joined


def test_a_provider_that_rejects_reasoning_effort_is_retried_without_it():
    """Not every provider understands the parameter, and that must not fail."""
    attempts = []

    def picky(provider, model, messages, **kwargs):
        attempts.append(kwargs)
        if "reasoning_effort" in kwargs:
            raise TypeError("unsupported parameter: reasoning_effort")
        return '{"terms": ["rust"]}'

    constraints, understood = understand_request(
        "a rust project", provider="google", model="m", completion=picky
    )
    assert understood
    assert constraints.terms == ("rust",)
    assert len(attempts) == 2
    assert "reasoning_effort" in attempts[0]
    assert "reasoning_effort" not in attempts[1]


def test_an_empty_reply_falls_back_rather_than_erroring():
    """A thinking model can exhaust its budget and return nothing at all."""
    constraints, understood = understand_request(
        "open source harness with a sandbox",
        provider="google",
        model="m",
        completion=_reply(""),
    )
    assert not understood
    assert constraints.capabilities == ("sandbox",)
