from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from superqode.codegem.provider import CodeGemStream
from superqode.codegem.request_budget import GeminiRequestBudget, RequestBudgetExceeded
from superqode.pipy.messages import UserMessage
from superqode.pipy.stream import Context, Model, StreamOptions

MODEL = "gemini-3.1-flash-lite"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
BODY = {
    "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
    "generationConfig": {"maxOutputTokens": 2048},
}


def budget(tmp_path, **kwargs):
    return GeminiRequestBudget(
        limit_usd=kwargs.pop("limit_usd", 2),
        model=MODEL,
        input_per_million=0.25,
        output_per_million=1.5,
        max_input_tokens=1048576,
        max_output_tokens=65536,
        path=tmp_path / "budget.json",
        **kwargs,
    )


def reply():
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": "done"}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 20,
                "thoughtsTokenCount": 10,
                "totalTokenCount": 130,
            },
        },
    )


async def test_wire_admission_blocks_before_spend_and_persists(tmp_path):
    calls = []
    guard = budget(tmp_path, limit_usd=0.1)
    async with httpx.AsyncClient(
        transport=guard.transport(httpx.MockTransport(lambda r: calls.append(r) or reply()))
    ) as client:
        with pytest.raises(RequestBudgetExceeded, match="remaining budget"):
            await client.post(URL, json=BODY)
    assert not calls
    assert guard.snapshot()["accounted_upper_bound_usd"] <= 0.1
    assert json.loads((tmp_path / "budget.json").read_text())["closed_reason"]


async def test_reservation_settles_at_full_rate_including_thoughts(tmp_path):
    guard = budget(tmp_path)
    async with httpx.AsyncClient(
        transport=guard.transport(httpx.MockTransport(lambda r: reply()))
    ) as client:
        await client.post(URL, json=BODY)
    assert guard.snapshot()["observed_usd"] == 0.00007
    assert guard.snapshot()["pending_reserved_usd"] == 0
    assert guard.snapshot()["attempts"][0]["state"] == "settled"


@pytest.mark.parametrize(
    "kind", ["missing_usage", "http_error", "network_error", "usage_over_limit"]
)
async def test_uncertain_attempt_blocks_every_following_request(tmp_path, kind):
    guard = budget(tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "network_error":
            raise httpx.ReadError("synthetic secret must never be logged")
        if kind == "http_error":
            return httpx.Response(503, text="synthetic secret")
        if kind == "usage_over_limit":
            return httpx.Response(
                200,
                json={"usageMetadata": {"promptTokenCount": 1048577, "candidatesTokenCount": 1}},
            )
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=guard.transport(httpx.MockTransport(handler))) as client:
        for _ in range(2):
            with pytest.raises(RequestBudgetExceeded):
                await client.post(URL, json=BODY)
    assert len(calls) == 1
    assert guard.snapshot()["uncertain_reserved_usd"] > 0
    assert "synthetic secret" not in (tmp_path / "budget.json").read_text()


@pytest.mark.parametrize("kind", ["other_model", "stream", "grounding", "media"])
async def test_unsupported_paid_paths_never_reach_transport(tmp_path, kind):
    calls = []
    guard = budget(tmp_path)
    body = json.loads(json.dumps(BODY))
    url = URL
    if kind == "other_model":
        url = URL.replace(MODEL, "gemini-other")
    elif kind == "stream":
        url = URL.replace(":generateContent", ":streamGenerateContent")
    elif kind == "grounding":
        body["tools"] = [{"googleSearch": {}}]
    else:
        body["contents"][0]["parts"] = [
            {"inlineData": {"mimeType": "image/png", "data": "fixture"}}
        ]
    async with httpx.AsyncClient(
        transport=guard.transport(httpx.MockTransport(lambda r: calls.append(r) or reply()))
    ) as client:
        with pytest.raises(RequestBudgetExceeded):
            await client.post(url, json=body)
    assert not calls


async def test_actual_provider_uses_private_key_and_guards_internal_requests(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    calls = []
    guard = budget(tmp_path, api_key="SYNTHETIC_PRIVATE_KEY")

    def handler(request):
        assert request.headers["x-goog-api-key"] == "SYNTHETIC_PRIVATE_KEY"
        calls.append(request)
        return reply()

    stream = CodeGemStream(
        {"stream": False, "max_attempts": 1, "max_output_tokens": 2048},
        transport=httpx.MockTransport(handler),
    )
    with guard.scope():
        events = [
            event
            async for event in stream(
                Model(MODEL, "google"), Context("", [UserMessage("hello")], []), StreamOptions()
            )
        ]
    assert events[-1].type == "done"
    assert len(calls) == 1
    assert "SYNTHETIC_PRIVATE_KEY" not in (tmp_path / "budget.json").read_text()


async def test_cancellation_keeps_reservation_without_swallowing_cancel(tmp_path):
    guard = budget(tmp_path)
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    async with httpx.AsyncClient(transport=guard.transport(httpx.MockTransport(handler))) as client:
        task = asyncio.create_task(client.post(URL, json=BODY))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert guard.snapshot()["uncertain_reserved_usd"] > 0


def test_existing_ledger_cannot_be_reset(tmp_path):
    budget(tmp_path)
    with pytest.raises(ValueError, match="never reset"):
        budget(tmp_path)


async def test_concurrent_attempts_share_admission_budget(tmp_path):
    guard = budget(tmp_path, limit_usd=1)
    entered, release = [], asyncio.Event()

    async def handler(request):
        entered.append(request)
        await release.wait()
        return reply()

    async with httpx.AsyncClient(transport=guard.transport(httpx.MockTransport(handler))) as client:
        tasks = [asyncio.create_task(client.post(URL, json=BODY)) for _ in range(3)]
        while len(entered) < 2:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert guard.snapshot()["accounted_upper_bound_usd"] <= 1
        assert guard.closed_reason
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert len(entered) == 2
    assert sum(isinstance(value, RequestBudgetExceeded) for value in results) == 1
