"""Unified Harness Protocol client, wire decoding, and the v1 adapter."""

import json
from pathlib import Path

import httpx
import pytest

from superqode.harness import (
    HarnessCapabilityError,
    HarnessCreateRequest,
    HarnessMessage,
    UHPClient,
    UHPHarnessProtocolAdapter,
)
from superqode.harness.uhp_client import (
    UHPAuthenticationError,
    UHPError,
    UHPHarnessError,
    UHPRateLimitError,
    UHPResponse,
)

BASE_URL = "https://uhp.test"


def _sse(events):
    """Render UHP stream events as an SSE body."""
    chunks = []
    for index, event in enumerate(events):
        payload = {"sequence_number": index, **event}
        chunks.append(f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n")
    return "".join(chunks)


def _response_payload(**overrides):
    payload = {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "model": "gpt-5",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        "metadata": {"session_id": "sess_1"},
    }
    payload.update(overrides)
    return payload


def _client(handler):
    transport = httpx.MockTransport(handler)
    return UHPClient(
        BASE_URL,
        api_key="key-123",
        client=httpx.AsyncClient(transport=transport),
    )


def test_base_url_normalizes_v1_suffix():
    assert UHPClient("https://uhp.test/v1/").base_url == "https://uhp.test"
    assert UHPClient("https://uhp.test/").base_url == "https://uhp.test"


def test_build_response_body_omits_unset_fields():
    client = UHPClient(BASE_URL)
    body = client.build_response_body("fix the test", harness_id="chrn_a")

    assert body == {
        "input": "fix the test",
        "stream": False,
        "store": True,
        "metadata": {"harness_id": "chrn_a"},
    }


def test_response_extracts_text_files_and_calls():
    response = UHPResponse.from_payload(
        _response_payload(
            output=[
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "write_file",
                    "arguments": '{"path": "a.txt"}',
                },
                {"type": "function_call_output", "call_id": "call_1", "output": "written"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "saved ",
                            "annotations": [
                                {
                                    "type": "container_file_citation",
                                    "container_id": "cont_1",
                                    "file_id": "file_1",
                                    "filename": "a.txt",
                                    "download_url": "https://uhp.test/a.txt",
                                }
                            ],
                        },
                        {"type": "output_text", "text": "the file"},
                    ],
                },
            ]
        )
    )

    assert response.output_text == "saved the file"
    assert response.session_id == "sess_1"
    assert [citation.filename for citation in response.file_citations] == ["a.txt"]
    call = response.function_calls[0]
    assert call.name == "write_file"
    assert call.parsed_arguments() == {"path": "a.txt"}
    assert call.output == "written"


def test_response_raise_for_error_uses_declared_type():
    response = UHPResponse.from_payload(
        _response_payload(
            status="failed",
            error={"type": "rate_limit_error", "code": "slow_down", "message": "Too many"},
        )
    )

    with pytest.raises(UHPRateLimitError) as excinfo:
        response.raise_for_error()
    assert excinfo.value.code == "slow_down"


def test_failed_status_without_error_object_still_raises():
    response = UHPResponse.from_payload(_response_payload(status="failed", output=[]))

    with pytest.raises(UHPHarnessError):
        response.raise_for_error()


@pytest.mark.asyncio
async def test_list_harnesses_sends_bearer_and_parses_envelope():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "object": "list",
                "harnesses": [
                    {
                        "id": "chrn_codex",
                        "name": "Codex",
                        "base": "codex",
                        "baseLabel": "Codex CLI",
                        "defaultModel": "gpt-5",
                        "disabledTools": ["shell"],
                    }
                ],
            },
        )

    async with _client(handler) as client:
        harnesses = await client.list_harnesses()

    assert seen["url"] == "https://uhp.test/v1/harnesses"
    assert seen["auth"] == "Bearer key-123"
    assert harnesses[0].id == "chrn_codex"
    assert harnesses[0].base_label == "Codex CLI"
    assert harnesses[0].disabled_tools == ("shell",)


@pytest.mark.asyncio
async def test_http_error_envelope_maps_to_typed_exception():
    def handler(request):
        return httpx.Response(
            401,
            json={
                "error": {
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                    "message": "The API key is invalid.",
                }
            },
        )

    async with _client(handler) as client:
        with pytest.raises(UHPAuthenticationError) as excinfo:
            await client.list_harnesses()

    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "invalid_api_key"


@pytest.mark.asyncio
async def test_create_response_posts_harness_metadata():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response_payload())

    async with _client(handler) as client:
        response = await client.create_response(
            "ship it",
            harness_id="chrn_codex",
            model="gpt-5",
            previous_response_id="resp_0",
        )

    assert seen["body"]["metadata"]["harness_id"] == "chrn_codex"
    assert seen["body"]["previous_response_id"] == "resp_0"
    assert seen["body"]["stream"] is False
    assert response.output_text == "done"
    assert response.usage.total_tokens == 14


@pytest.mark.asyncio
async def test_stream_response_yields_events_and_stops_at_terminal():
    body = _sse(
        [
            {"type": "response.created", "response": _response_payload(status="in_progress")},
            {"type": "response.output_text.delta", "delta": "he"},
            {"type": "response.output_text.delta", "delta": "llo"},
            {"type": "response.completed", "response": _response_payload()},
            {"type": "response.output_text.delta", "delta": "ignored"},
        ]
    )

    def handler(request):
        assert request.headers["accept"] == "text/event-stream"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with _client(handler) as client:
        events = [event async for event in client.stream_response("hi")]

    assert [event.type for event in events] == [
        "response.created",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.completed",
    ]
    assert events[-1].response.id == "resp_1"


@pytest.mark.asyncio
async def test_stream_error_event_preserves_code_and_message():
    body = _sse([{"type": "error", "code": "harness_crashed", "message": "Harness died."}])

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with _client(handler) as client:
        with pytest.raises(UHPError) as excinfo:
            async for _event in client.stream_response("hi"):
                pass

    assert excinfo.value.code == "harness_crashed"
    assert excinfo.value.message == "Harness died."


@pytest.mark.asyncio
async def test_stream_error_event_uses_nested_error_type_when_present():
    body = _sse(
        [
            {
                "type": "error",
                "error": {
                    "type": "harness_error",
                    "code": "harness_crashed",
                    "message": "Harness died.",
                },
            }
        ]
    )

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with _client(handler) as client:
        with pytest.raises(UHPHarnessError):
            async for _event in client.stream_response("hi"):
                pass


@pytest.mark.asyncio
async def test_latest_response_id_reads_session_turns():
    def handler(request):
        return httpx.Response(
            200,
            json={"turns": [{"response_id": "resp_1"}, {"response_id": "resp_2"}]},
        )

    async with _client(handler) as client:
        assert await client.latest_response_id("sess_1") == "resp_2"


@pytest.mark.asyncio
async def test_adapter_streams_canonical_events():
    body = _sse(
        [
            {"type": "response.created", "response": _response_payload(status="in_progress")},
            {
                "type": "response.output_item.added",
                "item": {"type": "function_call", "call_id": "call_1", "name": "write_file"},
            },
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call_output", "call_id": "call_1", "output": "ok"},
            },
            {"type": "response.reasoning_summary_text.delta", "delta": "planning"},
            {"type": "response.output_text.delta", "delta": "done"},
            {
                "type": "response.completed",
                "response": _response_payload(
                    output=[
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "done",
                                    "annotations": [
                                        {
                                            "type": "container_file_citation",
                                            "container_id": "cont_1",
                                            "file_id": "file_1",
                                            "filename": "a.txt",
                                            "download_url": "https://uhp.test/a.txt",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                ),
            },
        ]
    )

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(
        HarnessCreateRequest(
            harness_id="uhp",
            provider="uhp",
            model="gpt-5",
            working_directory=Path.cwd(),
        )
    )
    events = [event async for event in adapter.send(session, HarnessMessage("user", "hi"))]
    await adapter.aclose()

    assert [event.type for event in events] == [
        "model.requested",
        "tool.requested",
        "tool.completed",
        "model.thinking",
        "message.delta",
        "artifact.created",
        "model.completed",
        "message.created",
    ]
    assert events[1].data["tool_name"] == "write_file"
    assert events[5].data["name"] == "a.txt"
    assert events[6].data["usage"]["total_tokens"] == 14
    assert events[7].data["content"] == "done"


@pytest.mark.asyncio
async def test_adapter_threads_previous_response_id_across_turns():
    bodies = [
        _sse([{"type": "response.completed", "response": _response_payload(id="resp_1")}]),
        _sse([{"type": "response.completed", "response": _response_payload(id="resp_2")}]),
    ]
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=bodies[len(sent) - 1],
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    async for _event in adapter.send(session, HarnessMessage("user", "first")):
        pass
    async for _event in adapter.send(session, HarnessMessage("user", "second")):
        pass
    await adapter.aclose()

    assert "previous_response_id" not in sent[0]
    assert sent[1]["previous_response_id"] == "resp_1"


@pytest.mark.asyncio
async def test_adapter_create_falls_back_to_first_advertised_harness():
    def handler(request):
        return httpx.Response(200, json={"harnesses": [{"id": "chrn_first", "base": "codex"}]})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    await adapter.aclose()

    assert session.metadata["uhp_harness_id"] == "chrn_first"


@pytest.mark.asyncio
async def test_adapter_resume_recovers_from_session_turns():
    def handler(request):
        return httpx.Response(200, json={"turns": [{"response_id": "resp_9"}]})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(
        HarnessCreateRequest(
            harness_id="uhp",
            metadata={"external_session_id": "sess_1"},
        )
    )
    resumed = await adapter.resume(session)
    await adapter.aclose()

    assert resumed.session_id == session.session_id


@pytest.mark.asyncio
async def test_adapter_resume_without_uhp_session_is_declined():
    def handler(request):
        return httpx.Response(200, json={"turns": []})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))

    with pytest.raises(HarnessCapabilityError):
        await adapter.resume(session)
    await adapter.aclose()


@pytest.mark.asyncio
async def test_adapter_cancel_targets_the_active_response():
    cancelled = []

    def handler(request):
        if request.url.path.endswith("/cancel"):
            cancelled.append(request.url.path)
            return httpx.Response(200, json=_response_payload(status="cancelled"))
        return httpx.Response(
            200,
            text=_sse(
                [
                    {
                        "type": "response.created",
                        "response": _response_payload(status="in_progress"),
                    },
                    {"type": "response.completed", "response": _response_payload()},
                ]
            ),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(
        HarnessCreateRequest(harness_id="uhp", metadata={"external_session_id": "sess_1"})
    )
    async for _event in adapter.send(session, HarnessMessage("user", "hi")):
        pass

    await adapter.cancel(session)
    await adapter.aclose()

    assert cancelled == ["/v1/sessions/sess_1/cancel"]


@pytest.mark.asyncio
async def test_adapter_declares_honest_capabilities():
    adapter = UHPHarnessProtocolAdapter(BASE_URL)
    capabilities = adapter.descriptor.capabilities

    assert capabilities.streaming and capabilities.resume and capabilities.cancel
    assert not capabilities.steer
    assert not capabilities.checkpoint

    with pytest.raises(HarnessCapabilityError):
        await adapter.checkpoint(
            await adapter.create(
                HarnessCreateRequest(harness_id="uhp", metadata={"harness_id": "x"})
            )
        )
    await adapter.aclose()


# --- Spec envelopes and discovery -------------------------------------------


@pytest.mark.asyncio
async def test_spec_envelopes_are_parsed_for_every_collection():
    """The spec names each collection; `data` is only a fallback."""

    def handler(request):
        path = request.url.path
        if path == "/v1/harnesses":
            return httpx.Response(200, json={"harnesses": [{"id": "chrn_a", "base": "codex"}]})
        if path == "/v1/sessions/sess_1/turns":
            return httpx.Response(200, json={"turns": [{"response_id": "resp_7"}]})
        if path == "/v1/sessions/sess_1/files":
            return httpx.Response(200, json={"files": [{"id": "file_1", "filename": "a.txt"}]})
        if path == "/v1/harnesses/chrn_a/models":
            return httpx.Response(200, json={"models": [{"id": "gpt-5"}]})
        if path == "/v1/models":
            return httpx.Response(
                200,
                json={"backends": {"codex": {"models": [{"id": "gpt-5"}, {"id": "o4"}]}}},
            )
        return httpx.Response(404, json={"error": {"type": "invalid_request_error"}})

    async with _client(handler) as client:
        assert [h.id for h in await client.list_harnesses()] == ["chrn_a"]
        assert await client.latest_response_id("sess_1") == "resp_7"
        assert [f["filename"] for f in await client.list_session_files("sess_1")] == ["a.txt"]
        assert await client.list_models("chrn_a") == ("gpt-5",)
        assert await client.list_models() == ("gpt-5", "o4")


@pytest.mark.asyncio
async def test_data_envelope_still_parses_as_a_fallback():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "chrn_legacy", "base": "codex"}]})

    async with _client(handler) as client:
        assert [h.id for h in await client.list_harnesses()] == ["chrn_legacy"]


@pytest.mark.asyncio
async def test_empty_catalog_is_empty_not_an_error():
    def handler(request):
        return httpx.Response(200, json={"harnesses": []})

    async with _client(handler) as client:
        assert await client.list_harnesses() == ()


@pytest.mark.asyncio
async def test_discovery_reads_the_spec_document():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "object": "uhp.discovery",
                "protocol": "uhp",
                "versions": ["2026-08-11"],
                "default_version": "2026-08-11",
                "conformance_class": "full",
                "capabilities": {"sessions": True, "cancellation": True, "idempotency": False},
                "implementation": {"name": "harnessrouter", "version": "1.0"},
            },
        )

    async with _client(handler) as client:
        discovery = await client.discover()

    assert discovery.default_version == "2026-08-11"
    assert discovery.conformance_class == "full"
    assert discovery.speaks_target_version is True
    assert discovery.supports("cancellation") is True
    assert discovery.supports("idempotency") is False


@pytest.mark.asyncio
async def test_discovery_flags_a_server_on_another_version():
    def handler(request):
        return httpx.Response(
            200,
            json={"protocol": "uhp", "versions": ["2027-01-01"], "default_version": "2027-01-01"},
        )

    async with _client(handler) as client:
        assert (await client.discover()).speaks_target_version is False


# --- Required headers --------------------------------------------------------


@pytest.mark.asyncio
async def test_version_header_is_sent_on_every_request():
    seen = {}

    def handler(request):
        seen[request.url.path] = request.headers.get("uhp-version")
        return httpx.Response(200, json={"harnesses": []})

    async with _client(handler) as client:
        await client.list_harnesses()

    assert seen["/v1/harnesses"] == "2026-08-11"


@pytest.mark.asyncio
async def test_task_submission_carries_an_idempotency_key():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("idempotency-key")
        return httpx.Response(200, json=_response_payload())

    async with _client(handler) as client:
        await client.create_response("hi", idempotency_key="fixed-key")
    assert seen["key"] == "fixed-key"

    async with _client(handler) as client:
        await client.create_response("hi")
    assert seen["key"] and seen["key"] != "fixed-key"


@pytest.mark.asyncio
async def test_streamed_task_also_carries_an_idempotency_key():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("idempotency-key")
        return httpx.Response(
            200,
            text=_sse([{"type": "response.completed", "response": _response_payload()}]),
            headers={"content-type": "text/event-stream"},
        )

    async with _client(handler) as client:
        async for _event in client.stream_response("hi"):
            pass

    assert seen["key"]


# --- Error events do not end the task ---------------------------------------


@pytest.mark.asyncio
async def test_error_event_followed_by_completed_does_not_raise():
    """The spec: an error event did not end the task."""
    body = _sse(
        [
            {"type": "error", "code": "tool_failed", "message": "One tool failed."},
            {"type": "response.completed", "response": _response_payload()},
        ]
    )

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with _client(handler) as client:
        events = [event async for event in client.stream_response("hi")]

    assert [event.type for event in events] == ["error", "response.completed"]
    assert events[-1].response.status == "completed"


@pytest.mark.asyncio
async def test_error_event_followed_by_failed_surfaces_the_failure():
    body = _sse(
        [
            {"type": "error", "code": "harness_crashed", "message": "Harness died."},
            {
                "type": "response.failed",
                "response": _response_payload(
                    status="failed",
                    error={"type": "harness_error", "code": "harness_crashed", "message": "died"},
                ),
            },
        ]
    )

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with _client(handler) as client:
        events = [event async for event in client.stream_response("hi")]

    with pytest.raises(UHPHarnessError):
        events[-1].response.raise_for_error()


@pytest.mark.asyncio
async def test_malformed_stream_without_a_terminal_event_raises_the_error():
    body = _sse([{"type": "error", "code": "boom", "message": "No terminal event follows."}])

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with _client(handler) as client:
        with pytest.raises(UHPError) as excinfo:
            async for _event in client.stream_response("hi"):
                pass

    assert excinfo.value.code == "boom"


def test_usage_absent_stays_absent():
    assert UHPResponse.from_payload(_response_payload(usage=None)).usage is None
    assert UHPResponse.from_payload(_response_payload()).usage.total_tokens == 14


# --- Adapter: durability and disconnect handling -----------------------------


@pytest.mark.asyncio
async def test_session_state_is_handed_back_for_persistence():
    body = _sse(
        [
            {
                "type": "response.completed",
                "response": _response_payload(id="resp_5", metadata={"session_id": "sess_9"}),
            }
        ]
    )

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    async for _event in adapter.send(session, HarnessMessage("user", "hi")):
        pass
    state = adapter.session_state(session)
    await adapter.aclose()

    assert state["uhp_previous_response_id"] == "resp_5"
    assert state["uhp_session_id"] == "sess_9"


@pytest.mark.asyncio
async def test_a_fresh_adapter_resumes_from_persisted_metadata():
    """A restart must still thread the conversation, not start a new one."""
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse([{"type": "response.completed", "response": _response_payload(id="resp_6")}]),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(
        HarnessCreateRequest(
            harness_id="uhp",
            metadata={"uhp_previous_response_id": "resp_5", "uhp_session_id": "sess_9"},
        )
    )
    async for _event in adapter.send(session, HarnessMessage("user", "next")):
        pass
    await adapter.aclose()

    assert sent[0]["previous_response_id"] == "resp_5"


@pytest.mark.asyncio
async def test_stream_ending_early_is_recovered_by_re_reading_the_response():
    """A dropped stream does not stop the task, so the response is the truth."""
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=_response_payload(id="resp_1"))
        return httpx.Response(
            200,
            text=_sse(
                [
                    {
                        "type": "response.created",
                        "response": _response_payload(id="resp_1", status="in_progress"),
                    }
                ]
            ),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    events = [event async for event in adapter.send(session, HarnessMessage("user", "hi"))]
    await adapter.aclose()

    assert ("GET", "/v1/responses/resp_1") in calls
    assert events[-1].data["content"] == "done"


@pytest.mark.asyncio
async def test_abandoned_task_still_running_is_cancelled():
    """A client that gives up must cancel, or the harness keeps editing files."""
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=_response_payload(id="resp_1", status="in_progress"))
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json=_response_payload(id="resp_1", status="cancelled"))
        return httpx.Response(
            200,
            text=_sse(
                [
                    {
                        "type": "response.created",
                        "response": _response_payload(id="resp_1", status="in_progress"),
                    }
                ]
            ),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    with pytest.raises(RuntimeError, match="without a terminal response"):
        async for _event in adapter.send(session, HarnessMessage("user", "hi")):
            pass
    await adapter.aclose()

    assert ("POST", "/v1/responses/resp_1/cancel") in calls


@pytest.mark.asyncio
async def test_cancel_during_a_run_targets_the_active_response():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json=_response_payload(status="cancelled"))
        return httpx.Response(
            200,
            text=_sse(
                [
                    {
                        "type": "response.created",
                        "response": _response_payload(id="resp_1", status="in_progress"),
                    },
                    {"type": "response.output_text.delta", "delta": "wo"},
                    {"type": "response.completed", "response": _response_payload()},
                ]
            ),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    async for event in adapter.send(session, HarnessMessage("user", "hi")):
        if event.type == "message.delta":
            await adapter.cancel(session)
    await adapter.aclose()

    assert "/v1/responses/resp_1/cancel" in calls


@pytest.mark.asyncio
async def test_absent_usage_is_omitted_from_model_completed():
    body = _sse([{"type": "response.completed", "response": _response_payload(usage=None)}])

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    events = [event async for event in adapter.send(session, HarnessMessage("user", "hi"))]
    await adapter.aclose()

    completed = next(event for event in events if event.type == "model.completed")
    assert "usage" not in completed.data


@pytest.mark.asyncio
async def test_error_event_is_recorded_without_ending_the_run():
    body = _sse(
        [
            {"type": "error", "code": "tool_failed", "message": "One tool failed."},
            {"type": "response.completed", "response": _response_payload()},
        ]
    )

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    events = [event async for event in adapter.send(session, HarnessMessage("user", "hi"))]
    await adapter.aclose()

    recorded = next(event for event in events if event.type == "validation.completed")
    assert recorded.data["code"] == "tool_failed"
    assert events[-1].type == "message.created"


@pytest.mark.asyncio
async def test_controller_persists_uhp_ids_so_a_restart_resumes(tmp_path):
    """The whole point of session_state: a new process threads the same task."""
    from superqode.harness import FileHarnessStore, HarnessProtocolController

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        index = len(sent)
        return httpx.Response(
            200,
            text=_sse(
                [
                    {
                        "type": "response.completed",
                        "response": _response_payload(
                            id=f"resp_{index}", metadata={"session_id": "sess_9"}
                        ),
                    }
                ]
            ),
            headers={"content-type": "text/event-stream"},
        )

    store_dir = tmp_path / "protocol"

    first = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    controller = HarnessProtocolController([first], store=FileHarnessStore(store_dir))
    session = await controller.create(HarnessCreateRequest(harness_id="uhp"))
    async for _event in controller.send(session, "first"):
        pass
    await first.aclose()

    # A second process: new adapter, new controller, same durable store.
    second = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    restarted = HarnessProtocolController([second], store=FileHarnessStore(store_dir))
    async for _event in restarted.send(session.session_id, "second"):
        pass
    await second.aclose()

    assert "previous_response_id" not in sent[0]
    assert sent[1]["previous_response_id"] == "resp_1"


# --- Hardening -------------------------------------------------------------


def test_session_id_is_read_from_metadata_or_the_response_object():
    """Servers differ on where they put it, and resume needs either."""
    in_metadata = UHPResponse.from_payload(_response_payload(metadata={"session_id": "sess_m"}))
    at_root = UHPResponse.from_payload(
        {**_response_payload(), "session_id": "sess_r", "metadata": {}}
    )
    neither = UHPResponse.from_payload({**_response_payload(), "metadata": {}})

    assert in_metadata.session_id == "sess_m"
    assert at_root.session_id == "sess_r"
    assert neither.session_id is None


@pytest.mark.asyncio
async def test_root_level_session_id_still_reaches_session_state():
    body = _sse(
        [
            {
                "type": "response.completed",
                "response": {
                    **_response_payload(id="resp_3"),
                    "session_id": "sess_r",
                    "metadata": {},
                },
            }
        ]
    )

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp"))
    async for _event in adapter.send(session, HarnessMessage("user", "hi")):
        pass
    state = adapter.session_state(session)
    await adapter.aclose()

    assert state["uhp_session_id"] == "sess_r"


@pytest.mark.asyncio
async def test_a_failed_state_write_warns_instead_of_failing_silently(tmp_path, caplog):
    """A silent write failure would look like resume working, then restart fresh."""
    import logging

    from superqode.harness import FileHarnessStore, HarnessProtocolController

    def handler(request):
        return httpx.Response(
            200,
            text=_sse([{"type": "response.completed", "response": _response_payload(id="resp_1")}]),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    store = FileHarnessStore(tmp_path / "protocol")
    controller = HarnessProtocolController([adapter], store=store)
    session = await controller.create(HarnessCreateRequest(harness_id="uhp"))

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    store.open_session = explode

    with caplog.at_level(logging.WARNING):
        async for _event in controller.send(session, "hi"):
            pass
    await adapter.aclose()

    assert any("resume will not survive a restart" in record.message for record in caplog.records)


# --- The server owns the model ----------------------------------------------


@pytest.mark.asyncio
async def test_a_local_default_model_never_overrides_the_server():
    """`harness run` defaults --model, and that must not reach the server."""
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse([{"type": "response.completed", "response": _response_payload()}]),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp", model="gpt-4o-mini"))
    async for _event in adapter.send(session, HarnessMessage("user", "hi")):
        pass
    await adapter.aclose()

    assert "model" not in sent[0]


@pytest.mark.asyncio
async def test_an_explicitly_chosen_model_is_sent():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=_sse([{"type": "response.completed", "response": _response_payload()}]),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(
        HarnessCreateRequest(
            harness_id="uhp",
            model="z-ai/glm-5.2:free",
            metadata={"model_explicit": True},
        )
    )
    async for _event in adapter.send(session, HarnessMessage("user", "hi")):
        pass
    await adapter.aclose()

    assert sent[0]["model"] == "z-ai/glm-5.2:free"


@pytest.mark.asyncio
async def test_the_requested_event_says_when_the_server_chooses():
    def handler(request):
        return httpx.Response(
            200,
            text=_sse([{"type": "response.completed", "response": _response_payload()}]),
            headers={"content-type": "text/event-stream"},
        )

    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    session = await adapter.create(HarnessCreateRequest(harness_id="uhp", model="gpt-4o-mini"))
    events = [event async for event in adapter.send(session, HarnessMessage("user", "hi"))]
    await adapter.aclose()

    assert events[0].data["model"] == "(server default)"
