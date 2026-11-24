"""Gemini 4 and newer get LiteLLM's Gemini 3 handling on the plain Google route."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from superqode.providers.gateway.base import Message, ToolDefinition
from superqode.providers.gateway.litellm_gateway import (
    LiteLLMGateway,
    apply_gemini_next_request_shaping,
)

DUMMY = "c2tpcF90aG91Z2h0X3NpZ25hdHVyZV92YWxpZGF0b3I="


def _request(**extra):
    return {
        "messages": [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "read"}},
                    {"id": "call_2__thought__real", "type": "function", "function": {"name": "a"}},
                ],
            },
        ],
        **extra,
    }


@pytest.mark.parametrize(
    ("model", "effort", "level", "show"),
    [
        ("gemini-4-neon", "medium", "medium", True),
        ("gemini-4-neon", "max", "xhigh", True),
        ("gemini-4-neon", "minimal", "low", True),
        ("gemini-4-neon", "off", "low", False),
        ("gemini/gemini-4-hydrogen", "high", "high", True),
        ("gemini-4-argon", "max", "high", True),
        ("gemini-3.6-flash", "off", "minimal", False),
        ("gemini-3.8-flash", "medium", "medium", True),
    ],
)
def test_thinking_level_maps_to_documented_levels(model, effort, level, show):
    request = _request()
    apply_gemini_next_request_shaping("google", model, request, effort)
    assert request["thinkingConfig"] == {"thinkingLevel": level, "includeThoughts": show}
    assert "reasoning_effort" not in request


def test_gemini_4_gets_temperature_and_signature_fallback_without_touching_signed_calls():
    request = _request()
    original_call = request["messages"][1]["tool_calls"][0]
    apply_gemini_next_request_shaping("google", "gemini-4-neon", request, None)
    assert request["temperature"] == 1.0
    assert "thinkingConfig" not in request  # Google's default level applies
    first, second = request["messages"][1]["tool_calls"]
    assert first["provider_specific_fields"] == {"thought_signature": DUMMY}
    assert "provider_specific_fields" not in second
    # The stored conversation is not changed, only the outgoing request.
    assert "provider_specific_fields" not in original_call


def test_explicit_settings_win_and_other_models_are_untouched():
    request = _request(temperature=0.4, thinkingConfig={"thinkingLevel": "high"})
    apply_gemini_next_request_shaping("google", "gemini-4-neon", request, "low")
    assert request["temperature"] == 0.4
    assert request["thinkingConfig"] == {"thinkingLevel": "high"}
    for provider, model in [
        ("google", "gemini-2.5-flash"),
        ("openai", "gemini-4-neon"),
        ("google", "gemma-4-31b-it"),
    ]:
        request = _request()
        apply_gemini_next_request_shaping(provider, model, request, "medium")
        assert request == _request()
    # Gemini 3 keeps LiteLLM's own temperature and signature handling.
    request = _request()
    apply_gemini_next_request_shaping("google", "gemini-3.8-flash", request, None)
    assert request == _request()


def test_gemini_4_streaming_requests_thought_summaries_by_default():
    request = _request(stream=True)
    apply_gemini_next_request_shaping("google", "gemini-4-neon", request, None)
    assert request["thinkingConfig"] == {"includeThoughts": True}
    assert request["temperature"] == 1.0


def test_load_litellm_defaults_to_local_cost_map(monkeypatch):
    import os
    import superqode.providers.gateway.litellm_gateway as mod

    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    monkeypatch.setattr(mod, "_litellm_module", None)
    mod._load_litellm()
    assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True"


@pytest.mark.parametrize("stream", [False, True])
def test_litellm_sends_gemini_4_level_temperature_and_signature(monkeypatch, stream):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            payload = {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 2,
                },
            }
            if stream:
                body = f"data: {json.dumps(payload)}\n\n".encode()
                content_type = "text/event-stream"
            else:
                body = json.dumps(payload).encode()
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    messages = [
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
        ),
        Message(role="tool", content="x", tool_call_id="call_1"),
    ]
    tools = [ToolDefinition(name="read", description="r", parameters={"type": "object"})]
    gateway = LiteLLMGateway()
    options = {
        "model": "gemini-4-neon",
        "provider": "google",
        "tools": tools,
        "reasoning_effort": "medium",
        "api_base": f"http://127.0.0.1:{server.server_port}",
    }

    async def run():
        if stream:
            return [chunk async for chunk in gateway.stream_completion(messages, **options)]
        return await gateway.chat_completion(messages, **options)

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
    body = seen[-1]
    assert body["generationConfig"]["temperature"] == 1.0
    assert body["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "medium",
        "includeThoughts": True,
    }
    calls = [part for item in body["contents"] for part in item["parts"] if "function_call" in part]
    assert calls and calls[0]["thoughtSignature"] == DUMMY
