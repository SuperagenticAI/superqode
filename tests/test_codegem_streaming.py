"""Gemini streamGenerateContent (SSE) for CodeGem, with recorded-style chunks.

The chunks follow the GenerateContentResponse shape Google streams with
alt=sse. No network: every response comes from an httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from superqode.codegem import create_tools
from superqode.codegem.provider import CodeGemStream, parse_sse
from superqode.pipy.messages import UserMessage
from superqode.pipy.stream import Context, Model, StreamOptions


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")


def _chunk(parts=None, finish=None, token=None, usage=None):
    candidate = {"content": {"role": "model", "parts": parts or []}}
    if finish:
        candidate["finishReason"] = finish
    if token:
        candidate["continuationToken"] = token
    chunk = {"candidates": [candidate], "modelVersion": "gemini-4-argon"}
    if usage:
        chunk["usageMetadata"] = usage
    return chunk


def _sse(*chunks):
    body = "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


class _Dropping(httpx.AsyncByteStream):
    """Yields some SSE events, then fails like a dropped connection."""

    def __init__(self, *chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for c in self.chunks:
            yield f"data: {json.dumps(c)}\n\n".encode()
        raise httpx.ReadError("connection reset")

    async def aclose(self):
        pass


def _drop(*chunks):
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=_Dropping(*chunks)
    )


def _stream(responses, config=None, seen=None):
    queue = list(responses)

    def handler(request):
        if seen is not None:
            seen.append((str(request.url), json.loads(request.content)))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    stream = CodeGemStream(
        {"retry_initial_delay": 0.0, **(config or {})}, transport=httpx.MockTransport(handler)
    )
    return stream, queue


async def _run(stream, model="gemini-4-argon", tools=None):
    return [
        e
        async for e in stream(
            Model(model, "google"), Context("", [UserMessage("go")], tools or []), StreamOptions()
        )
    ]


# Parser -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_sse_recorded_style_lines():
    lines = [
        ": keep-alive",
        'data: {"candidates": [{"content": {"parts": [{"text": "Hel"}]}}]}',
        "",
        'data: {"candidates": [{"content": {"parts": [{"text": "lo"}]},',
        'data:  "finishReason": "STOP"}]}\r',
        "",
        "event: ignored",
        'data: {"usageMetadata": {"promptTokenCount": 4}}',
    ]

    async def source():
        for line in lines:
            yield line

    chunks = [c async for c in parse_sse(source())]
    assert chunks[0]["candidates"][0]["content"]["parts"] == [{"text": "Hel"}]
    assert chunks[1]["candidates"][0]["finishReason"] == "STOP"
    assert chunks[2] == {"usageMetadata": {"promptTokenCount": 4}}


# Streaming turns --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_streams_live_and_signed_parts_stay_verbatim(tmp_path):
    seen = []
    call = {
        "functionCall": {"name": "read", "id": "c1", "args": {"path": "a"}},
        "thoughtSignature": "sig-B",
    }
    stream, queue = _stream(
        [
            _sse(
                _chunk([{"text": "Read", "thoughtSignature": "sig-A"}]),
                _chunk(
                    [{"text": "ing "}], usage={"promptTokenCount": 7, "candidatesTokenCount": 1}
                ),
                _chunk([call]),
                _chunk(
                    [{"text": "", "thoughtSignature": "sig-C"}],
                    "STOP",
                    usage={"promptTokenCount": 7, "candidatesTokenCount": 3, "totalTokenCount": 10},
                ),
            )
        ],
        seen=seen,
    )
    events = await _run(stream, tools=create_tools(tmp_path))
    url, body = seen[0]
    assert url.endswith("/models/gemini-4-argon:streamGenerateContent?alt=sse")
    assert body["generationConfig"]["maxOutputTokens"] == 65536
    kinds = [e.type for e in events]
    # Live text arrives before the tool call event and before done.
    assert kinds[:5] == ["start", "text_start", "text_delta", "text_delta", "text_end"]
    assert [e.delta for e in events if e.type == "text_delta"] == ["Read", "ing "]
    assert kinds.count("text_delta") == 2  # not re-emitted at the end
    assert "toolcall_end" in kinds and kinds[-1] == "done" and not queue
    message = events[-1].message
    assert message.provider_content["parts"] == [
        {"text": "Read", "thoughtSignature": "sig-A"},
        {"text": "ing "},
        call,
        {"text": "", "thoughtSignature": "sig-C"},
    ]
    assert message.text == "Reading "
    assert message.tool_calls[0].thought_signature == "sig-B"
    # Usage is cumulative within a stream: the last value wins.
    assert message.usage.input == 7 and message.usage.output == 3


@pytest.mark.asyncio
async def test_retry_applies_before_the_first_chunk_only():
    stream, queue = _stream(
        [
            httpx.Response(503, json={"error": {"message": "busy"}}),
            _drop(),
            _sse(_chunk([{"text": "ok"}], "STOP")),
        ]
    )
    events = await _run(stream)
    assert events[-1].type == "done" and events[-1].message.text == "ok" and not queue


@pytest.mark.asyncio
async def test_drop_after_output_without_checkpoint_is_an_error_not_a_retry():
    stream, queue = _stream(
        [_drop(_chunk([{"text": "partial"}])), _sse(_chunk([{"text": "x"}], "STOP"))]
    )
    events = await _run(stream)
    assert events[-1].type == "error" and len(queue) == 1
    assert "before a checkpoint" in events[-1].error.error_message


@pytest.mark.asyncio
async def test_drop_after_checkpoint_resumes_and_discards_pending_chunks():
    seen = []
    stream, queue = _stream(
        [
            _drop(
                _chunk([{"text": "A"}]),
                _chunk([{"text": "B"}], token="ckpt-1", usage={"candidatesTokenCount": 2}),
                _chunk([{"text": "lost"}]),
            ),
            _sse(
                _chunk(
                    [{"text": "C"}],
                    "STOP",
                    usage={"promptTokenCount": 5, "candidatesTokenCount": 1},
                )
            ),
        ],
        seen=seen,
    )
    events = await _run(stream)
    message = events[-1].message
    assert events[-1].type == "done" and not queue
    assert "continuationToken" not in seen[0][1] and seen[1][1]["continuationToken"] == "ckpt-1"
    assert message.provider_content["parts"] == [{"text": "A"}, {"text": "B"}, {"text": "C"}]
    assert message.text == "ABC"
    # Usage: the dropped stream counts up to its checkpoint, then the resumed one.
    assert message.usage.output == 3


@pytest.mark.asyncio
async def test_continuation_finish_opens_a_new_streamed_hop():
    seen = []
    stream, queue = _stream(
        [
            _sse(
                _chunk([{"text": "", "thoughtSignature": "sig-A"}]),
                _chunk(
                    [],
                    "CONTINUATION",
                    token="tok-1",
                    usage={"promptTokenCount": 10, "candidatesTokenCount": 4},
                ),
            ),
            _sse(
                _chunk(
                    [{"text": "done"}],
                    "STOP",
                    usage={"promptTokenCount": 10, "candidatesTokenCount": 2},
                )
            ),
        ],
        seen=seen,
    )
    events = await _run(stream)
    message = events[-1].message
    assert events[-1].type == "done" and not queue
    assert seen[1][1]["continuationToken"] == "tok-1"
    assert message.provider_content["parts"] == [
        {"text": "", "thoughtSignature": "sig-A"},
        {"text": "done"},
    ]
    assert message.usage.input == 20 and message.usage.output == 6


@pytest.mark.asyncio
async def test_stream_setting_off_uses_generate_content():
    seen = []
    ok = {
        "candidates": [{"content": {"parts": [{"text": "hi"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
    }
    stream, _ = _stream([httpx.Response(200, json=ok)], {"stream": False}, seen=seen)
    events = await _run(stream)
    assert seen[0][0].endswith(":generateContent")
    assert seen[0][1]["generationConfig"]["maxOutputTokens"] == 32768
    assert [e.type for e in events].count("text_delta") == 1


@pytest.mark.asyncio
async def test_streamed_block_reason_is_reported():
    stream, _ = _stream(
        [
            _sse(
                {
                    "promptFeedback": {"blockReason": "SAFETY"},
                    "usageMetadata": {"promptTokenCount": 3},
                }
            )
        ]
    )
    events = await _run(stream)
    assert events[-1].type == "error" and "blocked the prompt" in events[-1].error.error_message


@pytest.mark.asyncio
async def test_streamed_thought_summaries_show_as_thinking():
    stream, _ = _stream(
        [
            _sse(
                _chunk([{"text": "plan", "thought": True}]),
                _chunk([{"text": " more", "thought": True}]),
                _chunk([{"text": "answer"}], "STOP"),
            )
        ]
    )
    events = await _run(stream, "gemini-3.8-flash")
    kinds = [e.type for e in events]
    assert kinds.count("thinking_delta") == 2 and kinds.count("text_delta") == 1
    assert events[-1].message.thinking_text == "plan more"
