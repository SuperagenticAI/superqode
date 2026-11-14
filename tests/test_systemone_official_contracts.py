"""Official guide/OpenAPI examples, independent of generated adapter fixtures.

These are offline contract checks. No vendor inference or entitlement is implied.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from pathlib import Path

import httpx
import pytest

from superqode.systemone.api_clients import GoogleDecisionClient, OpenAIDecisionClient
from superqode.systemone.client import SystemOneError, SystemOneTimeout
from superqode.systemone.connectivity import check_connection
from superqode.systemone.http_contract import retry_delay
from superqode.systemone.live import LiveSystemOneClient
from superqode.systemone.pack import load_pack
from superqode.systemone.types import coerce_questions, ScoreQuestion, SchemaViolation

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/systemone/official-api-contracts.json").read_text()
)["cases"]
CLIENTS = {
    "typesafe": LiveSystemOneClient,
    "google": GoogleDecisionClient,
    "openai": OpenAIDecisionClient,
}
ENDPOINTS = {
    "typesafe": "https://api.typesafe.ai/v1/systemone",
    "google": "https://generativelanguage.googleapis.com/v1beta/decisions",
    "openai": "https://api.openai.com/v1/decisions",
}
MODELS = {
    "typesafe": ("jev-1.13.0", "jev-1.14.0"),
    "google": ("gemini-decision-1",),
    "openai": ("gpt-6-luna",),
}
CASES = [(case, model) for case in FIXTURES for model in MODELS[case["provider"]]]


@pytest.mark.parametrize(
    "case,model", CASES, ids=[case["id"] + "-" + model for case, model in CASES]
)
async def test_adapter_matches_documentation_request_and_accepts_documented_answer(case, model):
    provider = case["provider"]
    request = deepcopy(case["documented_request"])
    response = deepcopy(case["documented_response"])
    request["model"] = model
    original_id = next(iter(case["local_questions"]))
    if provider == "google":
        request["questions"] = {"q0": request["questions"][original_id]}
        response["answers"] = {"q0": response["answers"][original_id]}
    elif provider == "openai":
        question = request["questions"][0]
        question["name"] = "q0"
        response["answers"][0]["name"] = "q0"
        if question["type"] == "score":
            for index, level in enumerate(question["levels"]):
                level["label"] = str(index)
            for entry in response["answers"][0]["probabilities"]:
                entry["label"] = str(entry["value"])
    else:
        response["model"] = model
    calls = []

    def handler(sent):
        calls.append(sent)
        assert str(sent.url) == ENDPOINTS[provider]
        assert sent.method == "POST"
        assert json.loads(sent.content) == request
        if provider == "google":
            assert sent.headers["x-goog-api-key"] == "fixture-key"
            assert "authorization" not in sent.headers
        else:
            assert sent.headers["authorization"] == "Bearer fixture-key"
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CLIENTS[provider](api_key="fixture-key", model=model, http=http).evaluate(
            case["state"], coerce_questions(case["local_questions"])
        )
    assert len(calls) == 1
    assert result.metadata["provider"] == provider and result.metadata["requested_model"] == model
    kind = next(iter(case["local_questions"].values()))["type"]
    documented = (
        next(iter(case["documented_response"]["answers"].values()))
        if provider != "openai"
        else case["documented_response"]["answers"][0]
    )
    if kind == "noul":
        assert result.noul(original_id) == documented.get("noul", documented.get("probability"))
    elif kind == "choice":
        assert result.choice(original_id).choice == documented["choice"]
    else:
        assert result.score(original_id).score == documented["score"]


def test_retry_after_seconds_dates_and_milliseconds_follow_server_instructions():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    assert retry_delay({"retry-after": "20"}, 0) == 20
    assert retry_delay({"retry-after-ms": "1250"}, 0) == 1.25
    assert (
        retry_delay({"retry-after": format_datetime(now + timedelta(seconds=30))}, 0, now=now) == 30
    )
    assert retry_delay({"retry-after": "NaN"}, 1) == 0.4
    assert retry_delay({"retry-after": "Infinity"}, 1) == 0.4
    assert retry_delay({"retry-after": "garbage"}, 2) == 0.8
    assert retry_delay({"retry-after": "-1"}, 0) == 0


@pytest.mark.parametrize("provider", CLIENTS)
async def test_long_retry_after_obeys_total_deadline_instead_of_retrying_early(provider):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "30"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SystemOneTimeout):
            await CLIENTS[provider](api_key="fixture", http=http, timeout_ms=20).evaluate(
                "Please review this code change.", load_pack("provider_check").questions
            )
    assert len(calls) == 1


@pytest.mark.parametrize("provider", CLIENTS)
async def test_exhausted_billing_is_actionable_and_never_retried(provider):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            429, json={"error": {"code": "insufficient_quota", "message": "PRIVATE_UPSTREAM_TEXT"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SystemOneError, match="billing") as error:
            await CLIENTS[provider](api_key="PRIVATE_API_KEY", http=http).evaluate(
                "Please review this code change.", load_pack("provider_check").questions
            )
    assert len(calls) == 1
    assert "PRIVATE" not in str(error.value)
    assert "Setup: https://" in str(error.value)


async def test_google_reports_invalid_key_even_when_google_uses_http_400():
    body = {
        "error": {
            "code": 400,
            "details": [{"reason": "API_KEY_INVALID"}],
            "message": "PRIVATE_TEXT",
        }
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(400, json=body))
    ) as http:
        with pytest.raises(SystemOneError, match="GEMINI_API_KEY") as error:
            await GoogleDecisionClient(api_key="PRIVATE_KEY", http=http).evaluate(
                "test", load_pack("provider_check").questions
            )
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("provider", CLIENTS)
@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "API"),
        (403, "permissions"),
        (404, "region"),
        (422, "criteria"),
        (429, "rate limit"),
        (503, "temporarily"),
    ],
)
async def test_setup_failures_explain_next_step_without_echoing_input(provider, status, expected):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status, json={"error": "PRIVATE_TEXT"}, headers={"retry-after": "0"}
            )
        )
    ) as http:
        with pytest.raises(SystemOneError, match=expected) as error:
            await CLIENTS[provider](api_key="PRIVATE_KEY", http=http).evaluate(
                "test", load_pack("provider_check").questions
            )
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("control", ["\x7f", "\x85", "\x9f", "\u00a0"])
async def test_google_rejects_option_controls_before_sending(control):
    client = GoogleDecisionClient(api_key="fixture")
    with pytest.raises(SchemaViolation, match="choice keys"):
        await client.evaluate(
            "test",
            {
                "route": {
                    "type": "choice",
                    "instructions": "Route",
                    "criteria": {"a" + control + "b": "A", "other": "B"},
                }
            },
        )
    assert not client.calls


def test_typesafe_rubric_limit_is_checked_without_restricting_custom_endpoints():
    question = {"q": ScoreQuestion(instructions="Rate", criteria=[str(i) for i in range(11)])}
    with pytest.raises(SchemaViolation, match="10 rubric levels"):
        LiveSystemOneClient(api_key="fixture")._payload("test", question)
    assert LiveSystemOneClient(
        url="http://127.0.0.1:9000/v1/systemone", require_api_key=False
    )._payload("test", question)


@pytest.mark.parametrize("provider", CLIENTS)
@pytest.mark.parametrize(
    "invalid",
    [b'{"answers":1e400}', b'{"answers":[],"answers":[]}', b'{"usage":null}', b'{"usage":[]}'],
)
async def test_all_transports_reject_overflow_duplicate_and_malformed_usage(provider, invalid):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=invalid))
    ) as http:
        with pytest.raises((SystemOneError, SchemaViolation)):
            await CLIENTS[provider](api_key="fixture", http=http).evaluate(
                "test", load_pack("provider_check").questions
            )


async def test_connectivity_check_does_not_claim_success_when_one_primitive_is_missing():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"answers": {"q0": {"type": "noul", "noul": 0.99, "confidence": 0.99}}}
            )
        )
    ) as http:
        with pytest.raises(SchemaViolation):
            await check_connection(GoogleDecisionClient(api_key="fixture", http=http))


@pytest.mark.parametrize("provider", CLIENTS)
@pytest.mark.parametrize("key", ["PRIVATE bad key", "PRIVATE\nkey", "PRIVATE中文key"])
async def test_malformed_keys_fail_locally_with_safe_setup_guidance(provider, key):
    def never_send(_):
        raise AssertionError("Invalid credential reached transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(never_send)) as http:
        with pytest.raises(SystemOneError, match="Paste a valid") as error:
            await CLIENTS[provider](api_key=key, http=http).evaluate(
                "test", load_pack("provider_check").questions
            )
    assert "PRIVATE" not in str(error.value)


async def test_typesafe_never_follows_redirect_even_with_injected_client_defaults():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://attacker.invalid/decisions"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as http:
        with pytest.raises(SystemOneError, match="redirected"):
            await LiveSystemOneClient(api_key="fixture", http=http).evaluate(
                "test", load_pack("provider_check").questions
            )
    assert calls == [ENDPOINTS["typesafe"]]


async def test_typesafe_honors_retry_after_before_success(monkeypatch):
    from superqode.systemone import http_contract

    waits = []

    async def fake_sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(http_contract.asyncio, "sleep", fake_sleep)
    count = 0

    def handler(_):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(429, headers={"retry-after": "20"})
        return httpx.Response(200, json={"answers": {"ok": {"type": "noul", "noul": 0.9}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        answers = await LiveSystemOneClient(api_key="fixture", http=http).evaluate(
            "test", {"ok": {"type": "noul", "instructions": "OK?"}}
        )
    assert answers.noul("ok") == 0.9
    assert waits == [20.0] and count == 2


async def test_typesafe_conflicting_answer_type_is_not_accepted():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"answers": {"ok": {"type": "choice", "noul": 0.99}}}
            )
        )
    ) as http:
        with pytest.raises(SchemaViolation, match="wrong decision type"):
            await LiveSystemOneClient(api_key="fixture", http=http).evaluate(
                "test", {"ok": {"type": "noul", "instructions": "OK?"}}
            )


@pytest.mark.parametrize("provider", CLIENTS)
def test_cli_provider_check_uses_real_adapter_and_all_primitives(provider, monkeypatch, tmp_path):
    from click.testing import CliRunner
    from superqode.commands.harness._group import harness
    import superqode.commands.harness.systemone  # Register standalone decision commands.
    from superqode.systemone.providers import get_provider
    from test_systemone_provider_apis import success_body

    monkeypatch.setenv(get_provider(provider).api_key_env, "PRIVATE_KEY")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=success_body(provider, MODELS[provider][0], load_pack("provider_check").questions),
        )

    def factory(settings):
        return CLIENTS[provider](
            api_key="PRIVATE_KEY",
            model=settings.model,
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            record_dir=settings.record_dir,
        )

    monkeypatch.setattr("superqode.systemone.config.build_client", factory)
    result = CliRunner().invoke(
        harness,
        [
            "decision",
            "--provider",
            provider,
            "--pack",
            "provider_check",
            "--prompt",
            "Please review this code change.",
            "--record-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert set(body["answers"]) == {"review", "route", "quality"}
    assert len(calls) == 1
    assert "PRIVATE_KEY" not in result.output
    assert len(list(tmp_path.glob("*.json"))) == 1
