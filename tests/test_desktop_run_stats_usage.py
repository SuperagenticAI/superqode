"""Token usage collected for desktop runs, including the ACP path."""

from superqode.desktop_service.run_stats import UsageCollector


def harness(name, payload):
    return {"type": "harness_event", "data": {"event": name, "payload": payload}}


def test_acp_usage_events_are_cumulative_not_summed():
    usage = UsageCollector()
    usage.observe(harness("usage", {"inputTokens": 100, "outputTokens": 10}))
    usage.observe(harness("usage", {"inputTokens": 250, "outputTokens": 40}))
    assert usage.result({"status": "completed"}) == {
        "tokens_in": 250,
        "tokens_out": 40,
        "total_tokens": 290,
    }


def test_acp_context_update_keeps_tokens_and_adds_cost():
    usage = UsageCollector()
    usage.observe(harness("usage", {"input_tokens": 120, "output_tokens": 30}))
    usage.observe(
        harness(
            "usage", {"used": 5000, "size": 200000, "cost": {"amount": 0.02, "currency": "USD"}}
        )
    )
    summary = usage.result({"status": "completed"})
    assert summary["tokens_in"] == 120 and summary["tokens_out"] == 30
    assert summary["cost"] == 0.02 and summary["cost_currency"] == "USD"


def test_acp_result_stats_used_when_no_usage_events():
    usage = UsageCollector()
    result = {
        "status": "completed",
        "stats": {"prompt_tokens": 900, "completion_tokens": 80, "thinking_tokens": 0, "cost": 0.0},
    }
    assert usage.result(result) == {"tokens_in": 900, "tokens_out": 80, "total_tokens": 980}


def test_acp_result_stats_and_events_are_not_double_counted():
    usage = UsageCollector()
    usage.observe(harness("usage", {"inputTokens": 900, "outputTokens": 80}))
    result = {
        "status": "completed",
        "stats": {"prompt_tokens": 900, "completion_tokens": 80, "cost": 0.0},
    }
    assert usage.result(result)["tokens_in"] == 900
    assert usage.result(result)["total_tokens"] == 980


def test_zero_stats_mean_not_reported():
    usage = UsageCollector()
    result = {
        "status": "completed",
        "stats": {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0},
    }
    assert usage.result(result) is None


def test_per_call_reports_add_up_and_result_usage_wins():
    usage = UsageCollector()
    usage.observe(harness("model_result", {"usage": {"prompt_tokens": 10, "completion_tokens": 2}}))
    usage.observe(harness("model_result", {"usage": {"prompt_tokens": 5, "completion_tokens": 3}}))
    assert usage.result({})["tokens_in"] == 15
    assert usage.result({"usage": {"input_tokens": 1, "output_tokens": 1}})["tokens_in"] == 1
