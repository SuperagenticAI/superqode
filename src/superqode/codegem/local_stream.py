"""Local Gemma wire streaming without interpreting prose as executable tools."""

from __future__ import annotations

import copy
import json

from superqode.pipy.signals import is_aborted


async def _sse(lines):
    data = []
    async for line in lines:
        if not line:
            if data:
                payload = "\n".join(data)
                data = []
                if payload == "[DONE]":
                    return
                yield json.loads(payload)
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data and "\n".join(data) != "[DONE]":
        yield json.loads("\n".join(data))


def _merge_call(calls, raw, position):
    """OpenAI argument strings are fragments; validate JSON only at completion."""
    index = raw.get("index", position)
    if type(index) is not int or index < 0:
        raise ValueError("Local Gemma tool-call index must be a non-negative integer")
    call = calls.setdefault(index, {"function": {"name": "", "arguments": ""}})
    if raw.get("id"):
        if call.get("id") and call["id"] != raw["id"]:
            raise ValueError("Local Gemma changed a tool-call ID mid-stream")
        call["id"] = raw["id"]
    function = raw.get("function") or {}
    call["function"]["name"] += function.get("name") or ""
    if "arguments" in function:
        arguments = function["arguments"]
        previous = call["function"]["arguments"]
        if isinstance(arguments, str) and isinstance(previous, str):
            call["function"]["arguments"] += arguments
        elif isinstance(arguments, dict) and previous == "":
            call["function"]["arguments"] = copy.deepcopy(arguments)
        else:
            raise ValueError("Local Gemma returned invalid streamed function arguments")


async def local_response(response, *, protocol, live, signal=None):
    """Yield display deltas and one assembled, terminal wire response.

    Native tools are assembled privately until a terminal frame. JSON tool
    envelopes stay hidden until parsed by the caller. A legacy JSON server is
    consumed from the same response, never by replaying the generation request.
    """
    import asyncio

    try:
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type and "ndjson" not in content_type:
            yield "response", (json.loads(await response.aread()), False)
            return
        text, thinking = [], []
        calls = {}
        ollama_calls = []
        final = None
        usage = {}
        metadata = {}
        chunks = (
            _sse(response.aiter_lines())
            if protocol == "openai"
            else _ndjson(response.aiter_lines())
        )
        async for data in chunks:
            if is_aborted(signal):
                raise asyncio.CancelledError("CodeGem request aborted")
            if data.get("error"):
                raise ValueError(str(data["error"]))
            if protocol == "ollama":
                delta = data.get("message") or {}
                ollama_calls.extend(copy.deepcopy(delta.get("tool_calls") or []))
                metadata.update({k: v for k, v in data.items() if k != "message"})
                reason = delta.get("thinking") or ""
            else:
                choice = (data.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if data.get("usage"):
                    usage = data["usage"]
                for position, call in enumerate(delta.get("tool_calls") or []):
                    _merge_call(calls, call, position)
                if choice.get("finish_reason") is not None:
                    final = choice["finish_reason"]
                reason = delta.get("reasoning_content") or delta.get("reasoning") or ""
            content = delta.get("content") or ""
            for kind, value, parts in (("thinking", reason, thinking), ("text", content, text)):
                if not isinstance(value, str):
                    raise ValueError("Local Gemma text deltas must be strings")
                if value:
                    parts.append(value)
                    if live:
                        yield kind, value
            if protocol == "ollama" and data.get("done") is True:
                final = data.get("done_reason") or "stop"
                break
            if protocol == "openai" and final is not None and usage:
                break
        if final is None:
            raise ValueError("Local Gemma stream is incomplete; tool calls will not execute")
        raw = {"content": "".join(text)}
        if protocol == "ollama":
            raw.update(thinking="".join(thinking), tool_calls=ollama_calls)
            result = {**metadata, "done": True, "done_reason": final, "message": raw}
        else:
            raw.update(
                reasoning_content="".join(thinking), tool_calls=[calls[i] for i in sorted(calls)]
            )
            result = {"choices": [{"message": raw, "finish_reason": final}], "usage": usage}
        yield "response", (result, live)
    finally:
        await response.aclose()


async def _ndjson(lines):
    async for line in lines:
        if line.strip():
            yield json.loads(line)
