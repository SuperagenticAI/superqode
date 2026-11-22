"""Request accounting, admission, uncertainty and immutable comparison coverage."""

import asyncio

import pytest

from superqode.factory.metering import BudgetLedger, BudgetHalt
from superqode.evaluation.usage_scope import usage_scope
from superqode.providers.gateway.base import GatewayResponse, Usage, Cost
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


@pytest.fixture
def ledger(tmp_path):
    plan = {
        "digest": "sha256:example",
        "max_seconds": 60,
        "max_evals": 3,
        "limits": {"max_seconds": 60, "max_tokens": 20, "max_tool_calls": 4, "max_cost_usd": 1},
    }
    directory = tmp_path / "budget"
    directory.mkdir()
    ledger = BudgetLedger(directory, plan)
    ledger.initialize()
    return ledger


def response(tokens=5, tools=None, cost=0.01):
    return GatewayResponse(
        content="Actual fixture response",
        usage=Usage(prompt_tokens=2, completion_tokens=tokens - 2, total_tokens=tokens),
        cost=Cost(total_cost=cost),
        tool_calls=tools,
    )


async def request(scope, value):
    async def call():
        return value

    with usage_scope(scope):
        return await scope.request(call, "ollama", "test-model")


def settle(ledger, phase="held-in", tokens=5, tools=0):
    scope = ledger.begin(phase, {"task": "fixture", "spec": "spec", "split": phase})
    asyncio.run(request(scope, response(tokens)))
    ledger.finish(scope, {"total_tokens": tokens, "tool_calls": tools})
    return scope


def test_one_budget_covers_reflection_scoring_comparison_and_reopen(ledger):
    settle(ledger, "reflection")
    settle(ledger, "held-in")
    settle(ledger, "held-out")
    reopened = BudgetLedger(ledger.directory, ledger.plan)
    assert reopened.summary()["observed"]["tokens"] == 15
    assert reopened.summary()["request_count"] == 3
    assert {o["phase"] for o in reopened.detail()["operations"]} == {
        "reflection",
        "held-in",
        "held-out",
    }
    assert reopened.summary()["evidence_complete"]


def test_exhaustion_stops_next_request_and_records_inflight_overrun(ledger):
    settle(ledger, tokens=15)
    scope = ledger.begin("held-out", {})
    with pytest.raises(BudgetHalt, match="exceeded"):
        asyncio.run(request(scope, response(tokens=10)))
    ledger.finish(scope, {"total_tokens": 10, "tool_calls": 0})
    assert ledger.summary()["observed"]["tokens"] == 25
    assert ledger.summary()["issues"]
    with pytest.raises(BudgetHalt):
        ledger.begin("reflection", {})


def test_unknown_or_interrupted_usage_never_replays_or_becomes_zero(ledger):
    scope = ledger.begin("reflection", {})
    identity = ledger.begin_request(scope.identity, "openai", "model")
    reopened = BudgetLedger(ledger.directory, ledger.plan)
    assert reopened.summary()["unknown_requests"] == 1
    with pytest.raises(BudgetHalt):
        reopened.begin("held-out", {})
    ledger.finish_request(identity)
    ledger.finish(scope, failed=True)
    assert ledger.detail()["requests"][0]["tokens"] is None
    assert ledger.summary()["unknown_operations"] == 1


def test_shared_wall_time_does_not_reset_between_phases(ledger, monkeypatch):
    settle(ledger)
    started = ledger.summary()["started"]
    monkeypatch.setattr("superqode.factory.metering.time.time", lambda: started + 61)
    with pytest.raises(BudgetHalt, match="wall-time"):
        ledger.begin("held-out", {})


def test_report_coverage_and_frozen_budget_digest(ledger):
    scope = settle(ledger, "held-out")
    report = {
        "variants": [
            {
                "spec": "spec",
                "tasks": [{"id": "fixture", "factory_usage_operation": scope.identity}],
            }
        ]
    }
    ledger.finalize()
    assert not ledger.report_issues(report)
    report["variants"][0]["tasks"][0]["id"] = "different"
    assert ledger.report_issues(report)
    with pytest.raises(BudgetHalt, match="finalized"):
        ledger.begin("held-in", {})


def test_gateway_wrapper_records_requests_only_inside_scope(ledger, monkeypatch):
    gateway = object.__new__(LiteLLMGateway)
    calls = []

    async def call(*args, **kwargs):
        calls.append(kwargs)
        return response()

    monkeypatch.setattr(gateway, "_local_chat_completion", call)
    asyncio.run(gateway.chat_completion([], model="test", provider="ollama"))
    assert ledger.summary()["request_count"] == 0
    scope = ledger.begin("reflection", {})

    async def invoke():
        with usage_scope(scope):
            await gateway.chat_completion([], model="test", provider="ollama")

    asyncio.run(invoke())
    ledger.finish(scope, {"total_tokens": 5, "tool_calls": 0})
    assert ledger.summary()["request_count"] == 1 and len(calls) == 2


def test_pending_operation_excludes_concurrent_admission(ledger):
    ledger.begin("reflection", {})
    with pytest.raises(BudgetHalt, match="unsettled"):
        ledger.begin("held-in", {})


def test_sdk_retries_are_disabled_only_for_metered_requests(ledger, monkeypatch):
    gateway = object.__new__(LiteLLMGateway)
    seen = []

    class Client:
        async def acompletion(self, **kwargs):
            seen.append(kwargs)
            return object()

    monkeypatch.setattr(gateway, "_get_litellm", lambda: Client())
    scope = ledger.begin("reflection", {})

    async def invoke():
        with usage_scope(scope):
            await gateway._acompletion_with_retry({"model": "ollama/test"})

    asyncio.run(invoke())
    assert seen[0]["num_retries"] == 0


def test_unknown_paid_cost_and_remote_local_endpoints_are_held(ledger):
    scope = ledger.begin("reflection", {})

    async def call():
        return response(cost=0)

    with pytest.raises(BudgetHalt, match="unknown"):
        asyncio.run(
            scope.request(call, "ollama", "test-model", endpoint="https://remote-model.invalid")
        )
    request_row = ledger.detail()["requests"][0]
    assert request_row["cost_usd"] is None and request_row["api_cost_kind"] == "gateway-estimate"


def test_cloud_model_alias_is_not_recorded_as_free_local_inference(ledger):
    scope = ledger.begin("reflection", {})
    identity = ledger.begin_request(scope.identity, "ollama", "model:cloud")
    ledger.finish_request(identity, response(cost=0))
    assert ledger.summary()["unknown_requests"] == 1


def test_excess_tool_batch_is_blocked_before_response_is_forwarded(ledger):
    scope = ledger.begin("held-in", {})
    with pytest.raises(BudgetHalt, match="max_tool_calls"):
        asyncio.run(request(scope, response(tools=[{}] * 5)))
    assert ledger.summary()["observed_tool_calls"] == 0
    assert ledger.summary()["reserved_tool_calls"] == 5


def test_shared_cost_admission_uses_estimates_without_zeroing_unknowns(ledger):
    first = ledger.begin("reflection", {})

    async def charge(scope, amount):
        async def call():
            return response(cost=amount)

        return await scope.request(call, "openai", "test-model")

    asyncio.run(charge(first, 0.7))
    ledger.finish(first, {"total_tokens": 5, "tool_calls": 0})
    second = ledger.begin("held-out", {})
    with pytest.raises(BudgetHalt, match="max_cost_usd"):
        asyncio.run(charge(second, 0.4))
    assert ledger.summary()["observed"]["cost_usd"] == pytest.approx(1.1)
    assert ledger.summary()["unknown_requests"] == 0


def test_action_ownership_prevents_search_comparison_interleaving(ledger):
    other = BudgetLedger(ledger.directory, ledger.plan)
    with ledger.action():
        with pytest.raises(ValueError, match="owns this workspace"):
            with other.action():
                pass
    with other.action():
        pass


def test_streamed_factory_calls_have_one_accounted_request(ledger, monkeypatch):
    gateway = object.__new__(LiteLLMGateway)

    async def complete(*args, **kwargs):
        return response()

    monkeypatch.setattr(gateway, "_local_chat_completion", complete)
    scope = ledger.begin("reflection", {})

    async def collect():
        with usage_scope(scope):
            return [
                part
                async for part in gateway.stream_completion(
                    [], model="test-model", provider="ollama"
                )
            ]

    chunks = asyncio.run(collect())
    ledger.finish(scope, {"total_tokens": 5, "tool_calls": 0})
    assert len(chunks) == 1 and chunks[0].content == "Actual fixture response"
    assert ledger.summary()["request_count"] == 1


def test_explicit_positive_cost_is_not_erased_by_local_provider_name(ledger):
    scope = ledger.begin("held-in", {})
    asyncio.run(request(scope, response(cost=0.25)))
    ledger.finish(scope, {"total_tokens": 5, "tool_calls": 0, "cost_usd": 0.25})
    assert ledger.summary()["observed"]["cost_usd"] == 0.25


def test_request_cannot_switch_the_admitted_model_route(ledger):
    scope = ledger.begin("held-in", {"provider": "ollama", "model": "pinned-model"})
    with pytest.raises(BudgetHalt, match="admitted operation route"):
        ledger.begin_request(scope.identity, "openai", "different-model")
    assert ledger.summary()["request_count"] == 0
