"""Native UHP server: discovery, harness catalog, responses, auth, versioning."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from click.testing import CliRunner

pytest.importorskip("fastapi", reason="UHP server tests require FastAPI")

from superqode.commands.serve import serve
from superqode.harness.uhp_client import UHP_PROTOCOL_VERSION, VERSION_HEADER
from superqode.harness.uhp_server import (
    UHPRunRequest,
    UHPRunResult,
    UHPServer,
    UHPServerConfig,
    create_uhp_server,
    harness_id_from_name,
)


async def _echo_runner(request: UHPRunRequest) -> UHPRunResult:
    if request.cancel_event and request.cancel_event.is_set():
        return UHPRunResult(status="cancelled", model=request.model)
    text = f"echo:{request.prompt}"
    if request.previous_response_id:
        text = f"continued:{request.prompt}"
    return UHPRunResult(
        text=text,
        model=request.model or "test-model",
        status="completed",
        usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3,
               "cache_read_tokens": 0, "cache_write_tokens": 0},
    )


def _server(**kwargs) -> UHPServer:
    config = UHPServerConfig(
        harness_id="chrn_superqode",
        harness_name="SuperQode",
        default_model="test-model",
        model="test-model",
        provider="test",
        api_key=kwargs.pop("api_key", None),
        conformance_class="core",
    )
    return UHPServer(config, runner=kwargs.pop("runner", _echo_runner), **kwargs)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_discovery_and_harness_listing():
    server = _server()
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        discovery = await client.get("/v1/uhp")
        assert discovery.status_code == 200
        assert discovery.headers.get(VERSION_HEADER) == UHP_PROTOCOL_VERSION
        body = discovery.json()
        assert body["protocol"] == "uhp"
        assert body["default_version"] == UHP_PROTOCOL_VERSION
        assert body["conformance_class"] == "core"
        assert body["capabilities"]["streaming"] is True
        assert body["capabilities"]["files_input"] is False
        assert body["capabilities"]["idempotency"] is True

        harnesses = await client.get("/v1/harnesses")
        assert harnesses.status_code == 200
        items = harnesses.json()["harnesses"]
        assert len(items) == 1
        assert items[0]["id"] == "chrn_superqode"
        assert items[0]["base"] == "superqode"

        one = await client.get("/v1/harnesses/chrn_superqode")
        assert one.status_code == 200
        missing = await client.get("/v1/harnesses/chrn_missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "harness_not_found"

        models = await client.get("/v1/models")
        assert models.status_code == 200
        assert "superqode" in models.json()["backends"]

        harness_models = await client.get("/v1/harnesses/chrn_superqode/models")
        assert harness_models.status_code == 200
        assert harness_models.json()["default"] == "test-model"


@pytest.mark.anyio
async def test_create_get_cancel_and_idempotency():
    server = _server()
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            VERSION_HEADER: UHP_PROTOCOL_VERSION,
            "Idempotency-Key": "idem-1",
        }
        created = await client.post(
            "/v1/responses",
            headers=headers,
            json={
                "input": "hello",
                "metadata": {"harness_id": "chrn_superqode"},
                "tools": [{"type": "function"}],
                "include": ["reasoning"],
            },
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["status"] == "completed"
        assert payload["output"][0]["content"][0]["text"] == "echo:hello"
        assert set(payload["metadata"]["ignored_fields"]) == {"tools", "include"}
        assert payload["metadata"]["session_id"].startswith("sess_")
        response_id = payload["id"]
        assert response_id.startswith("resp_")

        fetched = await client.get(f"/v1/responses/{response_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["id"] == response_id

        inputs = await client.get(f"/v1/responses/{response_id}/input_items", headers=headers)
        assert inputs.status_code == 200
        assert inputs.json()["object"] == "list"

        # Idempotent retry returns the same response.
        again = await client.post(
            "/v1/responses",
            headers=headers,
            json={"input": "hello", "metadata": {"harness_id": "chrn_superqode"}},
        )
        assert again.json()["id"] == response_id

        # previous_response_id threads the session.
        follow = await client.post(
            "/v1/responses",
            headers={VERSION_HEADER: UHP_PROTOCOL_VERSION, "Idempotency-Key": "idem-2"},
            json={
                "input": "next",
                "previous_response_id": response_id,
                "metadata": {"harness_id": "chrn_superqode"},
            },
        )
        assert follow.status_code == 200
        follow_body = follow.json()
        assert follow_body["previous_response_id"] == response_id
        assert follow_body["metadata"]["session_id"] == payload["metadata"]["session_id"]
        assert follow_body["output"][0]["content"][0]["text"] == "continued:next"

        cancelled = await client.post(
            f"/v1/responses/{response_id}/cancel",
            headers=headers,
        )
        # Already terminal — cancel is idempotent and leaves status alone.
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "completed"


@pytest.mark.anyio
async def test_streaming_sse():
    server = _server()
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/v1/responses",
            headers={
                VERSION_HEADER: UHP_PROTOCOL_VERSION,
                "Idempotency-Key": "stream-1",
                "Accept": "text/event-stream",
            },
            json={"input": "stream me", "stream": True},
        ) as response:
            assert response.status_code == 200
            body = ""
            async for chunk in response.aiter_text():
                body += chunk
        assert "event: response.created" in body
        assert "event: response.output_text.delta" in body
        assert "event: response.completed" in body
        assert "echo:stream me" in body


@pytest.mark.anyio
async def test_auth_and_version_negotiation():
    server = _server(api_key="secret")
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Discovery stays open.
        assert (await client.get("/v1/uhp")).status_code == 200

        denied = await client.get("/v1/harnesses")
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "missing_credential"

        bad = await client.get(
            "/v1/harnesses", headers={"Authorization": "Bearer wrong"}
        )
        assert bad.status_code == 401
        assert bad.json()["error"]["code"] == "invalid_credential"

        ok = await client.get(
            "/v1/harnesses", headers={"Authorization": "Bearer secret"}
        )
        assert ok.status_code == 200

        unsupported = await client.get(
            "/v1/uhp",
            headers={VERSION_HEADER: "1999-01-01"},
        )
        assert unsupported.status_code == 400
        err = unsupported.json()["error"]
        assert err["code"] == "unsupported_protocol_version"
        assert err["detail"]["supported"] == [UHP_PROTOCOL_VERSION]


@pytest.mark.anyio
async def test_unknown_harness_on_create():
    server = _server()
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/responses",
            headers={VERSION_HEADER: UHP_PROTOCOL_VERSION, "Idempotency-Key": "x"},
            json={"input": "hi", "metadata": {"harness_id": "chrn_other"}},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "harness_not_found"


def test_harness_id_from_name():
    assert harness_id_from_name("superqode-coding") == "chrn_superqode_coding"
    assert harness_id_from_name("chrn_already") == "chrn_already"


def test_create_uhp_server_uses_template_and_cli_help():
    server = create_uhp_server(runner=_echo_runner, model="gpt-test")
    assert server.config.harness_id.startswith("chrn_")
    assert server.config.conformance_class == "core"
    assert server.config.default_model == "gpt-test"

    runner = CliRunner()
    result = runner.invoke(serve, ["uhp", "--help"])
    assert result.exit_code == 0
    assert "--spec" in result.output
    assert "--api-key" in result.output
    assert "UHP" in result.output


@pytest.mark.anyio
async def test_cancel_in_progress():
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_runner(request: UHPRunRequest) -> UHPRunResult:
        started.set()
        await release.wait()
        if request.cancel_event and request.cancel_event.is_set():
            return UHPRunResult(status="cancelled", model=request.model)
        return UHPRunResult(text="done", model=request.model, status="completed")

    server = _server(runner=slow_runner)
    # Drive lifecycle without concurrent ASGI requests (transport serializes).
    record = await server._start_response(
        {"input": "slow", "stream": False},
        idempotency_key="slow",
    )
    assert not isinstance(record, tuple)
    response_id = record["id"]
    await started.wait()
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        cancelled = await client.post(f"/v1/responses/{response_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
    release.set()
    await server._await_response(response_id)
    assert server._responses[response_id]["status"] == "cancelled"
