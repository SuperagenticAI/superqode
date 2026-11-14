"""Native Decisions wire contracts. Every HTTP call uses an injected transport."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from superqode.systemone.api_clients import (
    GoogleDecisionClient,
    OpenAIDecisionClient,
    DecisionRefused,
)
from superqode.systemone.client import SystemOneError, SystemOneTimeout, ReplaySystemOneClient
from superqode.systemone.live import LiveSystemOneClient
from superqode.systemone.providers import get_provider
from superqode.systemone.types import NoulQuestion, ChoiceQuestion, ScoreQuestion, SchemaViolation

MODELS = [
    ("typesafe", "jev-1.13.0"),
    ("typesafe", "jev-1.14.0"),
    ("google", "gemini-decision-1"),
    ("openai", "gpt-6-luna"),
]
CLIENTS = {
    "typesafe": LiveSystemOneClient,
    "google": GoogleDecisionClient,
    "openai": OpenAIDecisionClient,
}


def questions():
    return {
        "binary/确认": NoulQuestion(
            instructions={"question": "Does the task request review?"},
            criteria={"true": {"meaning": "Review requested"}, "false": "Other work"},
        ),
        "route": ChoiceQuestion(
            instructions="Choose a route", criteria={"review": "Review code", "other": "Other work"}
        ),
        "rating": ScoreQuestion(
            instructions="Rate quality", criteria=["weak", "adequate", "strong"]
        ),
    }


def success_body(provider, model, bound=None):
    bound = bound or questions()
    answer_types = {}
    for index, (qid, question) in enumerate(bound.items()):
        if isinstance(question, NoulQuestion):
            answer = {"type": "noul", "noul": 0.91}
            if provider == "google":
                answer["confidence"] = 0.91
        elif isinstance(question, ChoiceQuestion):
            keys = question.options
            probabilities = {
                key: (0.9 if i == 0 else 0.1 / (len(keys) - 1)) for i, key in enumerate(keys)
            }
            answer = {
                "type": "choice",
                "choice": keys[0],
                "probabilities": probabilities,
                "confidence": 0.9,
            }
        else:
            answer = {
                "type": "score",
                "score": 1.1,
                "probabilities": {"0": 0.1, "1": 0.7, "2": 0.2},
                "confidence": 0.7,
                "legend": {str(i): level for i, level in enumerate(question.criteria)},
            }
        key = qid if provider == "typesafe" else f"q{index}"
        if provider == "openai":
            answer["name"] = key
            if answer["type"] == "noul":
                answer = {"type": "predicate", "name": key, "probability": answer["noul"]}
            else:
                answer["probabilities"] = [
                    {
                        "value": value if answer["type"] == "choice" else float(value),
                        "probability": probability,
                        **({"label": value} if answer["type"] == "score" else {}),
                    }
                    for value, probability in answer["probabilities"].items()
                ]
                answer.pop("legend", None)
        answer_types[key] = answer
    usage = {"input_tokens": 123, "output_tokens": 0, "total_tokens": 123}
    if provider == "google":
        usage = {
            "total_input_tokens": 123,
            "total_output_tokens": 0,
            "total_tokens": 123,
            "input_tokens_by_modality": [{"modality": "text", "tokens": 123}],
        }
    return {
        "model": model,
        "answers": list(reversed(list(answer_types.values())))
        if provider == "openai"
        else answer_types,
        "usage": usage,
    }


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    for name in (
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "TYPESAFE_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "SUPERQODE_SYSTEMONE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("provider,model", MODELS)
async def test_all_models_translate_all_primitives_and_record_replay(provider, model, tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        assert str(request.url) == get_provider(provider).endpoint
        assert request.method == "POST"
        if provider == "google":
            assert request.headers["x-goog-api-key"] == "fixture-only"
            assert "authorization" not in request.headers
        else:
            assert request.headers["authorization"] == "Bearer fixture-only"
            assert "x-goog-api-key" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == model
        if provider == "typesafe":
            assert payload["state"] == {"task": "review"}
            assert set(payload["questions"]) == set(questions())
        elif provider == "google":
            assert json.loads(payload["input"]) == {"task": "review"}
            assert set(payload["questions"]) == {"q0", "q1", "q2"}
            assert "true_description" in payload["questions"]["q0"]["criteria"]
            assert isinstance(payload["questions"]["q0"]["instructions"], str)
        else:
            assert [q["type"] for q in payload["questions"]] == ["predicate", "choice", "score"]
            assert "Review requested" in payload["questions"][0]["instructions"]
            assert payload["questions"][1]["choices"][0] == {
                "value": "review",
                "description": "Review code",
            }
            assert payload["questions"][2]["levels"][1] == {"label": "1", "description": "adequate"}
        return httpx.Response(
            200, headers={"x-request-id": "req-fixture"}, json=success_body(provider, model)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CLIENTS[provider](
            model=model, api_key="fixture-only", http=http, record_dir=tmp_path
        ).evaluate({"task": "review"}, questions())
    assert len(seen) == 1
    assert result.noul("binary/确认") == 0.91
    assert result.choice("route").choice == "review"
    assert result.score("rating").score == 1.1
    assert result.metadata["provider"] == provider
    assert result.metadata["model"] == model
    assert result.metadata["usage"]["input_tokens"] == 123
    assert result.metadata["usage"]["output_tokens"] == 0
    assert result.metadata["request_id"] == "req-fixture"
    record = next(tmp_path.glob("*.json"))
    assert "fixture-only" not in record.read_text()
    replay = await ReplaySystemOneClient(record).evaluate({}, questions())
    assert replay.noul("binary/确认") == 0.91
    assert replay.metadata["model"] == model


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize("status", [401, 403, 404, 422])
async def test_permanent_http_errors_never_retry_or_echo_body(provider, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "PRIVATE_UPSTREAM_BODY"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SystemOneError, match=str(status)) as error:
            await CLIENTS[provider](api_key="fixture", http=http).evaluate("review", questions())
    assert len(calls) == 1
    assert "PRIVATE_UPSTREAM_BODY" not in str(error.value)


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
async def test_transient_http_errors_retry_within_one_request(provider, status):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, headers={"retry-after": "0"})
        return httpx.Response(200, json=success_body(provider, get_provider(provider).model))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CLIENTS[provider](api_key="fixture", http=http).evaluate(
            "review", questions()
        )
    assert len(calls) == 2 and result.choice("route").choice == "review"


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_redirect_does_not_forward_credentials(provider):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(307, headers={"location": "https://attacker.invalid/decisions"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as http:
        with pytest.raises(SystemOneError, match="307"):
            await CLIENTS[provider](api_key="private-fixture", http=http).evaluate(
                "review", questions()
            )
    assert hosts == [httpx.URL(get_provider(provider).endpoint).host]


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize(
    "body",
    ['{"answers": [], "answers": []}', '{"answers":NaN}', '{"answers":Infinity}', "not-json", "[]"],
)
async def test_invalid_json_never_becomes_a_decision(provider, body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))
    ) as http:
        with pytest.raises(SystemOneError):
            await CLIENTS[provider](api_key="fixture", http=http).evaluate("review", questions())


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "unknown",
        "duplicate",
        "wrong-type",
        "missing-probabilities",
        "bad-sum",
        "negative",
        "wrong-choice",
        "bad-score",
        "wrong-level",
    ],
)
async def test_malformed_answers_are_rejected(provider, defect):
    body = success_body(provider, get_provider(provider).model)
    if provider == "google":
        values = body["answers"]
        if defect == "missing":
            values.pop("q1")
        elif defect == "unknown":
            values["foreign"] = values.pop("q1")
        elif defect == "duplicate":
            values["q9"] = deepcopy(values["q1"])
        elif defect == "wrong-type":
            values["q1"]["type"] = "noul"
        elif defect == "missing-probabilities":
            values["q1"].pop("probabilities")
        elif defect == "bad-sum":
            values["q1"]["probabilities"] = {"review": 0.9, "other": 0.9}
        elif defect == "negative":
            values["q1"]["probabilities"]["other"] = -0.1
        elif defect == "wrong-choice":
            values["q1"]["choice"] = "other"
        elif defect == "bad-score":
            values["q2"]["score"] = 99
        elif defect == "wrong-level":
            values["q2"]["legend"]["0"] = "different rubric"
    else:
        values = {answer["name"]: answer for answer in body["answers"]}
        if defect == "missing":
            body["answers"].pop()
        elif defect == "unknown":
            values["q1"]["name"] = "foreign"
        elif defect == "duplicate":
            values["q1"]["name"] = "q2"
        elif defect == "wrong-type":
            values["q1"]["type"] = "predicate"
        elif defect == "missing-probabilities":
            values["q1"].pop("probabilities")
        elif defect == "bad-sum":
            values["q1"]["probabilities"][1]["probability"] = 0.9
        elif defect == "negative":
            values["q1"]["probabilities"][1]["probability"] = -0.1
        elif defect == "wrong-choice":
            values["q1"]["choice"] = "other"
        elif defect == "bad-score":
            values["q2"]["score"] = 99
        elif defect == "wrong-level":
            values["q2"]["probabilities"][0]["label"] = "different rubric"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises((SchemaViolation, SystemOneError)):
            await CLIENTS[provider](api_key="fixture", http=http).evaluate("review", questions())


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_safety_block_or_partial_refusal_never_returns_partial_success(provider):
    body = success_body(provider, get_provider(provider).model)
    status = 200
    if provider == "google":
        status, body = 400, {"error": {"code": "safety", "message": "PRIVATE_BODY"}}
    else:
        body["answers"][1] = {"type": "refusal", "name": "q1"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    ) as http:
        with pytest.raises(DecisionRefused):
            await CLIENTS[provider](api_key="fixture", http=http).evaluate("review", questions())


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_total_deadline_covers_backoff_and_slow_body(provider):
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"answers":'
            await asyncio.sleep(2)
            yield b"[]}"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowBody()))
    ) as http:
        with pytest.raises(SystemOneTimeout):
            await CLIENTS[provider](api_key="fixture", timeout_ms=20, http=http).evaluate(
                "review", questions()
            )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"retry-after": "2"}))
    ) as http:
        with pytest.raises(SystemOneTimeout):
            await CLIENTS[provider](api_key="fixture", timeout_ms=20, http=http).evaluate(
                "review", questions()
            )


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_caller_cancellation_is_preserved(provider):
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.sleep(20)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        task = asyncio.create_task(
            CLIENTS[provider](api_key="fixture", http=http).evaluate("review", questions())
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("provider,limit", [("google", 1000), ("openai", 400)])
async def test_unsupported_question_count_and_rubric_never_send(provider, limit):
    calls = []

    def handler(request):
        calls.append(request)
        pytest.fail("Unsupported packs must fail before HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CLIENTS[provider](api_key="fixture", http=http)
        with pytest.raises(SchemaViolation):
            await client.evaluate(
                "review", {str(i): NoulQuestion(instructions="Review?") for i in range(limit + 1)}
            )
        with pytest.raises(SchemaViolation):
            await client.evaluate(
                "review",
                {
                    "score": ScoreQuestion(
                        instructions="Rate",
                        criteria=[str(i) for i in range(256 if provider == "google" else 11)],
                    )
                },
            )
        with pytest.raises(SchemaViolation):
            await client.evaluate("review", {})
    assert not calls


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_request_state_is_redacted_and_oversize_response_rejected(provider):
    def handler(request):
        assert b"PRIVATE_KEY" not in request.content
        return httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SystemOneError, match="size limit"):
            await CLIENTS[provider](api_key="fixture", http=http).evaluate(
                {"api_key": "PRIVATE_KEY"}, questions()
            )


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.openai.com/v1/decisions",
        "https://evil.invalid/decisions",
        "https://api.openai.com/v1/decisions?key=foo",
    ],
)
def test_provider_endpoint_cannot_be_changed_to_an_untrusted_host(provider, endpoint):
    with pytest.raises(ValueError, match="documented"):
        CLIENTS[provider](api_key="fixture", url=endpoint)


@pytest.mark.parametrize("provider,model", MODELS)
async def test_success_records_are_private_and_include_endpoint_attempts_and_usage(
    provider, model, tmp_path
):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(
                429, headers={"retry-after": "0", "x-request-id": "retry-fixture"}
            )
        return httpx.Response(
            200, json=success_body(provider, model), headers={"x-request-id": "success-fixture"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await CLIENTS[provider](
            api_key="PRIVATE_API_KEY", model=model, http=http, record_dir=tmp_path
        ).evaluate({"task": "review", "password": "PRIVATE_STATE"}, questions())
    record = next(tmp_path.glob("*.json"))
    data = json.loads(record.read_text())
    assert data["provider"] == provider and data["status"] == "success"
    assert data["endpoint"] == get_provider(provider).endpoint
    assert [row["http_status"] for row in data["evaluation"]["http_attempts"]] == [429, 200]
    assert data["evaluation"]["usage"]["input_tokens"] == 123
    assert record.stat().st_mode & 0o777 == 0o600
    assert "PRIVATE_API_KEY" not in record.read_text() and "PRIVATE_STATE" not in record.read_text()
    replay = await ReplaySystemOneClient(record).evaluate({}, questions())
    assert replay.metadata["usage"]["input_tokens"] == 123
    assert result.metadata["usage"]["output_tokens"] == 0


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize(
    "case,expected",
    [
        ("invalid-json", "error"),
        ("http-error", "error"),
        ("refusal", "refused"),
        ("timeout", "timeout"),
        ("cancelled", "cancelled"),
        ("schema", "invalid_response"),
        ("invalid-request", "invalid_request"),
    ],
)
async def test_every_failed_evaluation_is_recorded_without_private_error_text(
    provider, case, expected, tmp_path
):
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        if case in {"timeout", "cancelled"}:
            await asyncio.sleep(20)
        if case == "http-error":
            return httpx.Response(401, json={"error": "PRIVATE_PROVIDER_BODY"})
        if case == "invalid-json":
            return httpx.Response(200, text="PRIVATE_PROVIDER_BODY")
        if case == "schema":
            return httpx.Response(200, json={"answers": {}})
        if case == "refusal":
            if provider == "google":
                return httpx.Response(
                    400, json={"error": {"code": "safety", "message": "PRIVATE_PROVIDER_BODY"}}
                )
            return httpx.Response(200, json={"answers": [{"type": "refusal", "name": "q0"}]})
        pytest.fail("Invalid request must not reach HTTP")

    query = {} if case == "invalid-request" else {"yes": NoulQuestion(instructions="Review?")}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CLIENTS[provider](
            api_key="PRIVATE_API_KEY", http=http, timeout_ms=20, record_dir=tmp_path
        )
        if case == "cancelled":
            task = asyncio.create_task(client.evaluate("PRIVATE_INPUT", query))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises((SystemOneError, SchemaViolation)):
                await client.evaluate("PRIVATE_INPUT", query)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["status"] == expected
    assert data["provider"] == provider and data["model"] == get_provider(provider).model
    assert data["evaluation"]["latency_ms"] >= 0
    assert "PRIVATE" not in files[0].read_text()
    assert files[0].stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemOneError, match="failed"):
        ReplaySystemOneClient(files[0])


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_recording_is_opt_in_and_concurrent_attempts_do_not_mix(provider, tmp_path):
    def handler(request):
        return httpx.Response(200, json=success_body(provider, get_provider(provider).model))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CLIENTS[provider](api_key="fixture", http=http)
        results = await asyncio.gather(
            client.evaluate("first", questions()), client.evaluate("second", questions())
        )
        assert [len(result.metadata["http_attempts"]) for result in results] == [1, 1]
        assert not list(tmp_path.iterdir())
        client.record_dir = tmp_path
        await client.evaluate("third", questions())
    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({"record_version": 1, "status": "timeout", "provider": provider}))
    replay = await ReplaySystemOneClient(tmp_path).evaluate({}, questions())
    assert replay.noul("binary/确认") == 0.91


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_missing_key_and_oversize_request_never_reach_transport(provider):
    calls = []

    def handler(request):
        calls.append(request)
        pytest.fail("Invalid local setup must not send a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SystemOneError, match="API_KEY"):
            await CLIENTS[provider](api_key="", http=http).evaluate("review", questions())
        with pytest.raises(SchemaViolation, match="size limit"):
            await CLIENTS[provider](api_key="fixture", http=http).evaluate(
                "review", {"large": NoulQuestion(instructions="x" * (4 * 1024 * 1024))}
            )
    assert not calls


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_retry_exhaustion_records_all_attempts(provider, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SystemOneError, match="429"):
            await CLIENTS[provider](api_key="fixture", http=http, record_dir=tmp_path).evaluate(
                "review", questions()
            )
    data = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert len(calls) == 3 and len(data["evaluation"]["http_attempts"]) == 3
    assert all(row["http_status"] == 429 for row in data["evaluation"]["http_attempts"])


@pytest.mark.parametrize("provider,model", MODELS)
async def test_recording_failure_does_not_lose_successful_decision(provider, model, tmp_path):
    path = tmp_path / "file-not-a-directory"
    path.write_text("occupied")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=success_body(provider, model))
        )
    ) as http:
        result = await CLIENTS[provider](
            api_key="fixture", model=model, http=http, record_dir=path
        ).evaluate("review", questions())
    assert result.metadata["recording_error"] is True
    assert result.choice("route").choice == "review"


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("confidence", True),
        ("confidence", -1),
        ("confidence", 1.1),
        ("probability", True),
        ("probability", "0.9"),
        ("probability", -0.1),
    ],
)
async def test_invalid_numeric_types_cannot_become_confident_results(provider, field, value):
    body = success_body(provider, get_provider(provider).model)
    if field == "confidence":
        answer = (
            body["answers"]["q1"]
            if provider == "google"
            else next(a for a in body["answers"] if a["name"] == "q1")
        )
        answer["confidence"] = value
    else:
        answer = (
            body["answers"]["q0"]
            if provider == "google"
            else next(a for a in body["answers"] if a["name"] == "q0")
        )
        answer["noul" if provider == "google" else "probability"] = value
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises(SchemaViolation):
            await CLIENTS[provider](api_key="fixture", http=http).evaluate("review", questions())


@pytest.mark.parametrize("provider,model", MODELS)
async def test_recording_preserves_token_named_decision_ids_and_masks_known_api_key(
    provider, model, tmp_path
):
    query = {"contains_token": NoulQuestion(instructions="Is the message a code review request?")}
    secret = "ACTUAL_AUTH_FIXTURE_SECRET"

    def handler(request):
        return httpx.Response(200, json=success_body(provider, model, query))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CLIENTS[provider](api_key=secret, model=model, http=http, record_dir=tmp_path)
        await client.evaluate({"message": "review code " + secret}, query)
    file = next(tmp_path.glob("*.json"))
    assert secret not in file.read_text()
    replay = await ReplaySystemOneClient(file).evaluate({}, query)
    assert replay.noul("contains_token") == 0.91
