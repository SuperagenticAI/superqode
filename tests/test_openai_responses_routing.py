"""Exercise the real LiteLLM Responses bridge against an offline HTTP transport."""

import json

import httpx
import pytest

from superqode.providers.gateway.base import Message, ToolDefinition
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "openai/gpt-6.1-sol", "gpt-6-astra"])
def test_openai_responses_models_are_provider_qualified(model):
    assert LiteLLMGateway().get_model_string("openai", model) == (
        f"openai/responses/{model.split('/')[-1]}"
    )


def test_other_providers_and_models_keep_their_routes():
    gateway = LiteLLMGateway()
    assert gateway.get_model_string("openai", "gpt-4.1") == "openai/gpt-4.1"
    assert gateway.get_model_string("openrouter", "openai/gpt-6.1-sol") == (
        "openrouter/openai/gpt-6.1-sol"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-4.1", "gpt-5.2"])
async def test_existing_openai_models_still_call_chat_completions(monkeypatch, model):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
    from openai import AsyncOpenAI

    gateway = LiteLLMGateway()
    monkeypatch.setattr(gateway, "_setup_provider_env", lambda provider: None)
    requests = []

    def handle(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == model
        assert body["tools"][0]["function"]["name"] == "read_file"
        return httpx.Response(
            200,
            json={
                "id": "chat_offline",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "answer"},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(AsyncHTTPHandler, "create_client", lambda *args, **kwargs: http_client)
        client = AsyncOpenAI(api_key="offline-test-key", http_client=http_client)
        result = await gateway.chat_completion(
            [Message(role="user", content="Read README")],
            model,
            provider="openai",
            tools=[ToolDefinition("read_file", "Read a file", {"type": "object"})],
            client=client,
        )
    assert result.content == "answer"
    assert len(requests) == 1
    assert gateway.get_model_string("openai", "openai/responses/gpt-6.1-sol") == (
        "openai/responses/gpt-6.1-sol"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_tool_call", [False, True])
async def test_sol_tool_roundtrip_and_streaming_use_responses(monkeypatch, stream_tool_call):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

    gateway = LiteLLMGateway()
    monkeypatch.setattr(gateway, "_setup_provider_env", lambda provider: None)
    requests = []
    tool_call = {
        "id": "fc_read",
        "type": "function_call",
        "call_id": "call_read",
        "name": "read_file",
        "arguments": '{"path":"README.md"}',
        "status": "completed",
    }

    def response(output):
        return {
            "id": "resp_offline",
            "object": "response",
            "created_at": 1,
            "model": "gpt-6.1-sol",
            "status": "completed",
            "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

    def handle(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "gpt-6.1-sol"
        assert not {"temperature", "top_p", "logprobs", "top_logprobs"} & body.keys()
        assert body["tools"][0]["type"] == "function"
        if len(requests) == 1:
            assert body["reasoning"]["effort"] == "max"
            if not stream_tool_call:
                return httpx.Response(200, json=response([tool_call]))
            assert body["stream"] is True
            events = [
                {"type": "response.created", "response": {**response([]), "status": "in_progress"}},
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {**tool_call, "arguments": "", "status": "in_progress"},
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "item_id": "fc_read",
                    "delta": tool_call["arguments"],
                },
                {"type": "response.output_item.done", "output_index": 0, "item": tool_call},
                {"type": "response.completed", "response": response([tool_call])},
            ]
            sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        assert body["reasoning"]["effort"] == "low"
        assert any(
            item.get("type") == "function_call_output"
            and item["call_id"] == "call_read"
            and item["output"] == [{"text": "# SuperQode", "type": "input_text"}]
            for item in body["input"]
        ), body["input"]
        message = {
            "id": "msg_answer",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "SuperQode README", "annotations": []}],
        }
        events = [
            {"type": "response.created", "response": {**response([]), "status": "in_progress"}},
            {"type": "response.output_item.added", "output_index": 0, "item": message},
            {
                "type": "response.output_text.delta",
                "item_id": "msg_answer",
                "output_index": 0,
                "content_index": 0,
                "delta": "SuperQode README",
            },
            {"type": "response.output_item.done", "output_index": 0, "item": message},
            {"type": "response.completed", "response": response([message])},
        ]
        sse = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(AsyncHTTPHandler, "create_client", lambda *args, **kwargs: http_client)
        client = AsyncHTTPHandler()
        tools = [
            ToolDefinition(
                "read_file",
                "Read a file",
                {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            )
        ]
        messages = [Message(role="user", content="What is in README?")]
        if stream_tool_call:
            from superqode.agent.loop import _StreamedToolCalls

            accumulator = _StreamedToolCalls()
            async for chunk in gateway.stream_completion(
                messages,
                "gpt-6.1-sol",
                provider="openai",
                tools=tools,
                client=client,
                temperature=0.7,
                reasoning_effort="max",
            ):
                if chunk.tool_calls:
                    accumulator.add(chunk.tool_calls)
            calls = accumulator.finalize()
        else:
            result = await gateway.chat_completion(
                messages,
                "gpt-6.1-sol",
                provider="openai",
                tools=tools,
                client=client,
                temperature=0.7,
                reasoning_effort="max",
            )
            calls = result.tool_calls
        assert calls[0]["id"] == "call_read"
        assert json.loads(calls[0]["function"]["arguments"]) == {"path": "README.md"}
        messages += [
            Message(role="assistant", content="", tool_calls=calls),
            Message(role="tool", content="# SuperQode", tool_call_id="call_read"),
        ]
        chunks = [
            chunk
            async for chunk in gateway.stream_completion(
                messages,
                "gpt-6.1-sol",
                provider="openai",
                tools=tools,
                client=client,
                temperature=0.7,
                top_p=0.9,
                reasoning_effort="off",
            )
        ]
        assert "".join(chunk.content for chunk in chunks) == "SuperQode README"
    assert len(requests) == 2
