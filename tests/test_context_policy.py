import json

import pytest

from superqode.harness.context_artifacts import ContextArtifactStore
from superqode.harness.context_policy import ContextItem, ContextPolicy, ContextPolicyEngine
from superqode.systemone.client import StubSystemOneClient


def history():
    return [
        ContextItem("rules", "system", "Never edit secrets"),
        ContextItem("task", "user", "Fix authentication"),
        ContextItem("call", "assistant", "Inspect"),
        ContextItem(
            "result",
            "tool",
            "authentication\n" + "body\n" * 3000,
            "read_file",
            "call-1",
            {"path": "app.py"},
        ),
        ContextItem("error", "tool", "failed\n" * 3000, "bash", "call-2", {}, True),
        ContextItem("next", "assistant", "Now implement"),
        ContextItem("recent", "tool", "recent " * 4000, "read_file", "call-3"),
    ]


@pytest.mark.asyncio
async def test_shadow_enforce_restart_cache_and_protections(tmp_path):
    store = ContextArtifactStore(tmp_path / "e.sqlite")
    shadow = ContextPolicyEngine(store, "scope", ContextPolicy(recent_messages=1))
    plan = await shadow.prepare(history())
    assert plan.replacements == {}
    assert plan.trace["chars_before"] == plan.trace["chars_after"]
    assert plan.trace["proposed_chars_after"] < plan.trace["chars_before"]
    assert len(plan.decisions) == 1
    engine = ContextPolicyEngine(store, "scope", ContextPolicy(mode="enforce", recent_messages=1))
    plan = await engine.prepare(history())
    assert set(plan.replacements) == {3}
    reference = plan.decisions[0].reference
    assert store.read_page("scope", reference).text.startswith("authentication")
    restarted = ContextPolicyEngine(ContextArtifactStore(store.path), "scope", engine.policy)
    assert (await restarted.prepare(history())).trace["cache_hit"]
    changed = history()
    changed[1] = ContextItem("task", "user", "Different goal")
    assert not (await restarted.prepare(changed)).trace["cache_hit"]


@pytest.mark.asyncio
async def test_scorer_failure_uncertainty_and_limits(tmp_path):
    class Client:
        calls = 0

        async def evaluate(self, state, questions):
            self.calls += 1
            assert "authentication" in state["evidence"][0]["preview"]

            class Answers:
                def noul(self, key):
                    return 0.5

            return Answers()

    client = Client()
    engine = ContextPolicyEngine(
        ContextArtifactStore(tmp_path / "e.sqlite"),
        "owner",
        ContextPolicy(mode="enforce", selector="jev", recent_messages=1, max_scorer_calls=1),
        client=client,
    )
    assert not (await engine.prepare(history(), run_key="run")).replacements
    assert (await engine.prepare(history(), run_key="run")).trace["cache_hit"]
    changed = history() + [ContextItem("new", "assistant", "Another step")]
    assert (await engine.prepare(changed, run_key="run")).trace["fallback"] == "scorer_call_limit"
    assert client.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [float("nan"), float("inf"), -1, True, "bad"])
async def test_invalid_score_keeps_evidence(tmp_path, answer):
    class Client:
        async def evaluate(self, state, questions):
            class Answers:
                def noul(self, key):
                    return answer

            return Answers()

    engine = ContextPolicyEngine(
        ContextArtifactStore(tmp_path / "e.sqlite"),
        "owner",
        ContextPolicy(mode="enforce", selector="jev", recent_messages=1),
        client=Client(),
    )
    plan = await engine.prepare(history())
    assert not plan.replacements and plan.trace["fallback"] == "scorer_failed"


@pytest.mark.asyncio
async def test_quota_and_missing_scorer_keep_originals(tmp_path):
    store = ContextArtifactStore(tmp_path / "e.sqlite", max_artifact_bytes=100)
    plan = await ContextPolicyEngine(
        store, "owner", ContextPolicy(mode="enforce", recent_messages=1)
    ).prepare(history())
    assert not plan.replacements and plan.trace["fallback"] == "artifact_unavailable"
    plan = await ContextPolicyEngine(
        ContextArtifactStore(tmp_path / "b.sqlite"),
        "owner",
        ContextPolicy(mode="enforce", selector="jev", recent_messages=1),
    ).prepare(history())
    assert not plan.replacements and plan.trace["fallback"] == "scorer_unavailable"


def test_benchmark_shadow_and_unknown_selector_spend():
    from superqode.benchmarks import context_benchmark_metrics

    trace = {
        "type": "context.selection",
        "data": {
            "chars_before": 1000,
            "chars_after": 1000,
            "proposed_chars_after": 400,
            "scorer_calls": 1,
            "spend_usd": None,
        },
    }
    result = context_benchmark_metrics(json.dumps([trace]))
    assert result["context_metrics"]["actual_chars_saved"] == 0
    assert result["context_metrics"]["proposed_chars_saved"] == 600
    assert result["usage_complete"] is False


@pytest.mark.asyncio
async def test_timeout_is_cached_and_small_steps_do_not_call_selector(tmp_path):
    import asyncio

    class Client:
        calls = 0

        async def evaluate(self, state, questions):
            self.calls += 1
            await asyncio.sleep(1)

    client = Client()
    engine = ContextPolicyEngine(
        ContextArtifactStore(tmp_path / "e.sqlite"),
        "owner",
        ContextPolicy(mode="enforce", selector="jev", recent_messages=1, timeout_ms=10),
        client=client,
    )
    first = await engine.prepare(history(), run_key="run")
    assert not first.replacements and first.trace["fallback"] == "scorer_failed"
    assert (await engine.prepare(history(), run_key="run")).trace["cache_hit"]
    # Keep the latest protected evidence protected as the conversation grows.
    changed = history()
    changed.insert(-1, ContextItem("new", "assistant", "Another small step"))
    assert (await engine.prepare(changed, run_key="run")).trace[
        "fallback"
    ] == "no_selection_trigger"
    assert client.calls == 1


@pytest.mark.asyncio
async def test_selector_cannot_escape_workorder_budget(tmp_path):
    from types import SimpleNamespace
    from superqode.execution_recovery import RecoveryScope, recovery_scope

    class Client:
        async def evaluate(self, state, questions):
            raise AssertionError("A capped WorkOrder must not spend on the selector")

    store = SimpleNamespace(
        get=lambda _: SimpleNamespace(budget=SimpleNamespace(max_cost_usd=1, max_tokens=None))
    )
    engine = ContextPolicyEngine(
        ContextArtifactStore(tmp_path / "e.sqlite"),
        "owner",
        ContextPolicy(mode="enforce", selector="jev", recent_messages=1),
        client=Client(),
    )
    with recovery_scope(RecoveryScope(store, "order", "task", "worker", 1)):
        plan = await engine.prepare(history())
    assert not plan.replacements
    assert plan.trace["fallback"] == "selector_spend_not_reserved"
    assert plan.trace["scorer_calls"] == 0


@pytest.mark.asyncio
async def test_previews_do_not_expose_unsanitized_originals(tmp_path):
    items = history()
    from dataclasses import replace

    items[3] = replace(items[3], text="API_KEY=private-token\n" + items[3].text)
    plan = await ContextPolicyEngine(
        ContextArtifactStore(tmp_path / "e.sqlite"),
        "owner",
        ContextPolicy(mode="enforce", recent_messages=1),
    ).prepare(items)
    assert "private-token" not in plan.replacements[3]
    assert "[redacted]" in plan.replacements[3]
