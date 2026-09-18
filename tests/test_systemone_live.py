"""Live client against an injected HTTP transport. No network."""

from __future__ import annotations

import json

import httpx
import pytest

from superqode.systemone.client import SystemOneError, SystemOneTimeout
from superqode.systemone.live import LiveSystemOneClient
from superqode.systemone.types import NoulQuestion


def _handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode())
    assert body["model"] == "jev-1.13.0"
    assert "Authorization" in request.headers
    qid = next(iter(body["questions"]))
    return httpx.Response(
        200,
        json={
            "model": "jev-1.13.0",
            "answers": {qid: {"type": "noul", "noul": 0.91}},
            "usage": {"input_tokens": 12, "output_tokens": 4},
        },
    )


async def test_live_client_binds_cassette_answers():
    transport = httpx.MockTransport(_handler)
    http = httpx.AsyncClient(transport=transport)
    client = LiveSystemOneClient(api_key="ts_test", http=http)
    answers = await client.evaluate(
        {"tool": "bash"},
        {"urgent": NoulQuestion(instructions="Is this urgent?")},
    )
    assert answers.noul("urgent") == 0.91
    await http.aclose()


async def test_live_client_records_evaluate(tmp_path):
    transport = httpx.MockTransport(_handler)
    http = httpx.AsyncClient(transport=transport)
    client = LiveSystemOneClient(api_key="ts_test", http=http, record_dir=tmp_path)
    await client.evaluate({"tool": "bash"}, {"urgent": NoulQuestion(instructions="yes?")})
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    recorded = json.loads(files[0].read_text(encoding="utf-8"))
    assert recorded["request"]["model"] == "jev-1.13.0"
    assert recorded["response"]["answers"]["urgent"]["noul"] == 0.91
    await http.aclose()


async def test_live_client_maps_timeout():
    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    http = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    client = LiveSystemOneClient(api_key="ts_test", http=http, timeout_ms=50)
    with pytest.raises(SystemOneTimeout):
        await client.evaluate({}, {"q": NoulQuestion(instructions="yes?")})
    await http.aclose()


async def test_live_client_maps_422():
    def bad(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "malformed question"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(bad))
    client = LiveSystemOneClient(api_key="ts_test", http=http)
    with pytest.raises(SystemOneError, match="422"):
        await client.evaluate({}, {"q": NoulQuestion(instructions="yes?")})
    await http.aclose()
