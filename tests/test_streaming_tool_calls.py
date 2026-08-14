"""Streamed tool-call deltas must merge back into whole calls.

Providers slice tool calls differently. Ollama and Gemini put a finished call
in one delta; llama.cpp sends the name in the first delta and then dribbles the
arguments JSON across six more. Appending each delta as if it were a complete
call produced one usable call plus a run of nameless ones, which then went back
to the model with a null name and made llama.cpp reject the request outright.
"""

import json

from superqode.agent.loop import _StreamedToolCalls
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


def _llamacpp_deltas():
    """One ``run`` call as llama.cpp streams it: name once, then fragments."""
    return [
        [
            {
                "index": 0,
                "id": "U3nfpssUDep3ELBjb0zhS6j65vMDMYA0",
                "type": "function",
                "function": {"name": "run", "arguments": "{"},
            }
        ],
        [{"index": 0, "function": {"arguments": '"cmd":"'}}],
        [{"index": 0, "function": {"arguments": "ls"}}],
        [{"index": 0, "function": {"arguments": " -"}}],
        [{"index": 0, "function": {"arguments": "la"}}],
        [{"index": 0, "function": {"arguments": '"'}}],
        [{"index": 0, "function": {"arguments": "}"}}],
    ]


def _feed(chunks):
    acc = _StreamedToolCalls()
    for chunk in chunks:
        acc.add(chunk)
    return acc.finalize()


def test_fragmented_deltas_merge_into_one_call():
    calls = _feed(_llamacpp_deltas())

    assert len(calls) == 1
    call = calls[0]
    assert call["function"]["name"] == "run"
    assert json.loads(call["function"]["arguments"]) == {"cmd": "ls -la"}
    assert call["id"] == "U3nfpssUDep3ELBjb0zhS6j65vMDMYA0"


def test_no_call_is_left_without_a_name():
    """The failure mode: nameless calls reaching the model as ``name: null``."""
    for call in _feed(_llamacpp_deltas()):
        assert call["function"].get("name")


def test_whole_call_in_one_delta_is_unchanged():
    """Ollama's and Gemini's shape must pass through exactly as it arrived."""
    delta = {
        "id": "call_hl6huiqg",
        "index": 0,
        "type": "function",
        "function": {"name": "run", "arguments": '{"cmd":"ls -la"}'},
    }

    calls = _feed([[delta]])

    assert calls == [delta]


def test_parallel_calls_stay_separate():
    """Distinct indices are distinct calls, however they are chunked."""
    calls = _feed(
        [
            [
                {"index": 0, "id": "a", "type": "function", "function": {"name": "read"}},
                {"index": 1, "id": "b", "type": "function", "function": {"name": "write"}},
            ],
            [{"index": 0, "function": {"arguments": '{"p":1}'}}],
            [{"index": 1, "function": {"arguments": '{"p":2}'}}],
        ]
    )

    assert [c["function"]["name"] for c in calls] == ["read", "write"]
    assert [json.loads(c["function"]["arguments"]) for c in calls] == [{"p": 1}, {"p": 2}]


def test_deltas_without_index_or_id_are_appended():
    """An unrecognised stream shape keeps the previous behaviour."""
    first = {"type": "function", "function": {"name": "one", "arguments": "{}"}}
    second = {"type": "function", "function": {"name": "two", "arguments": "{}"}}

    assert _feed([[first], [second]]) == [first, second]


def test_missing_arguments_finalize_as_valid_json():
    """A call that never received arguments must not emit an empty string."""
    calls = _feed([[{"index": 0, "id": "a", "type": "function", "function": {"name": "ls"}}]])

    assert json.loads(calls[0]["function"]["arguments"]) == {}


class _DeltaFunction:
    """A continuation delta as LiteLLM hands it over: attributes set to None."""

    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _DeltaToolCall:
    def __init__(self, index, function, id=None, type="function"):
        self.index = index
        self.id = id
        self.type = type
        self.function = function


def test_normalization_keeps_index_and_drops_nulls():
    """Without ``index`` the loop cannot group fragments; nulls break llama.cpp."""
    gateway = LiteLLMGateway.__new__(LiteLLMGateway)

    normalized = gateway._normalize_tool_calls(
        [_DeltaToolCall(index=0, function=_DeltaFunction(name=None, arguments='"cmd":"'))]
    )

    assert normalized is not None
    call = normalized[0]
    assert call["index"] == 0
    assert "name" not in call["function"]
    assert call["function"]["arguments"] == '"cmd":"'
    # Nothing may serialize as null: that is what llama.cpp rejects outright.
    assert "null" not in json.dumps(call)


def test_normalized_deltas_merge_end_to_end():
    """Normalization and accumulation together rebuild the original call."""
    gateway = LiteLLMGateway.__new__(LiteLLMGateway)
    raw = [
        _DeltaToolCall(index=0, id="abc", function=_DeltaFunction(name="run", arguments="{")),
        _DeltaToolCall(index=0, function=_DeltaFunction(arguments='"cmd":"ls"')),
        _DeltaToolCall(index=0, function=_DeltaFunction(arguments="}")),
    ]

    acc = _StreamedToolCalls()
    for delta in raw:
        acc.add(gateway._normalize_tool_calls([delta]))
    calls = acc.finalize()

    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "run"
    assert json.loads(calls[0]["function"]["arguments"]) == {"cmd": "ls"}
