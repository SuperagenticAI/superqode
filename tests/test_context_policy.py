import json
from dataclasses import replace

import pytest

from superqode.harness.context_artifacts import ContextArtifactStore
from superqode.harness.context_policy import ContextItem, ContextPolicy, ContextPolicyEngine


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


class SelectingClient:
    calls = 0
    model = "pinned-selector"

    async def evaluate(self, state, questions):
        self.calls += 1

        class Answers:
            def noul(self, key):
                return 0.01

        return Answers()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "task",
        "instructions",
        "evidence",
        "arguments",
        "error",
        "edit-step",
        "remove-step",
        "long-step",
        "tool-call",
        "small-result",
        "branch",
        "instruction-version",
        "model",
        "pressure",
    ],
)
async def test_changed_relevance_rescores_instead_of_reusing_or_restoring(tmp_path, change):
    client = SelectingClient()
    items = history()
    policy = ContextPolicy(
        mode="enforce",
        selector="jev",
        recent_messages=1,
        pressure_chars=sum(len(v.text) for v in items) + 10,
    )
    engine = ContextPolicyEngine(
        ContextArtifactStore(tmp_path / "e.sqlite"), "scope", policy, client=client
    )
    first = await engine.prepare(items, run_key="run")
    assert first.replacements
    kwargs = {}
    if change == "task":
        items[1] = replace(items[1], text="Fix payments")
    elif change == "instructions":
        items[0] = replace(items[0], text="Never edit payment files")
    elif change == "evidence":
        items[3] = replace(items[3], identity="new-result", text=items[3].text + "changed")
    elif change == "arguments":
        items[3] = replace(items[3], identity="new-result", arguments={"path": "payments.py"})
    elif change == "error":
        items.insert(-1, ContextItem("failure", "assistant", "Error: test failed", is_error=True))
    elif change == "edit-step":
        items[5] = replace(items[5], text="Reconsider the full evidence")
    elif change == "remove-step":
        del items[2]
    elif change == "long-step":
        items.insert(-1, ContextItem("reasoning", "assistant", "reasoning " * 101))
    elif change == "tool-call":
        items.insert(
            -1, ContextItem("call", "assistant", "", arguments={"tool_calls": [{"name": "bash"}]})
        )
    elif change == "small-result":
        items.insert(-1, ContextItem("result-2", "tool", "new fact", "read_file", "call-4"))
    elif change == "branch":
        kwargs["branch"] = "fork"
    elif change == "instruction-version":
        kwargs["instruction_version"] = "updated"
    elif change == "model":
        client.model = "changed-selector"
    elif change == "pressure":
        items.insert(-1, ContextItem("step", "assistant", "A slightly longer step"))
    second = await engine.prepare(items, run_key="run", **kwargs)
    assert not second.trace["cache_hit"]
    assert second.trace["scorer_calls"] == 1
    assert second.replacements and client.calls == 2


@pytest.mark.asyncio
async def test_reused_steps_become_part_of_restart_invalidation(tmp_path):
    store = ContextArtifactStore(tmp_path / "e.sqlite")
    client = SelectingClient()
    policy = ContextPolicy(mode="enforce", selector="jev", recent_messages=1)
    engine = ContextPolicyEngine(store, "scope", policy, client=client)
    await engine.prepare(history(), run_key="run")
    items = history()
    items.insert(-1, ContextItem("step", "assistant", "Continue"))
    assert (await engine.prepare(items, run_key="run")).trace["cache_hit"]
    restarted = ContextPolicyEngine(store, "scope", policy, client=client)
    items[-2] = replace(items[-2], text="Reconsider")
    assert not (await restarted.prepare(items, run_key="run")).trace["cache_hit"]
    assert client.calls == 2


@pytest.mark.asyncio
async def test_cached_selection_cannot_replace_newly_denied_or_error_evidence(tmp_path):
    allowed = True
    store = ContextArtifactStore(tmp_path / "e.sqlite", authorize=lambda *_: allowed)
    client = SelectingClient()
    engine = ContextPolicyEngine(
        store,
        "scope",
        ContextPolicy(mode="enforce", selector="jev", recent_messages=1),
        client=client,
    )
    assert (await engine.prepare(history())).replacements
    allowed = False
    denied = await engine.prepare(history())
    assert not denied.replacements and denied.trace["fallback"] == "artifact_unavailable"
    allowed = True
    items = history()
    items[3] = replace(items[3], is_error=True)
    protected = await engine.prepare(items)
    assert not protected.replacements
    assert client.calls == 1


@pytest.mark.asyncio
async def test_successful_selection_survives_small_continuations_and_restart(tmp_path):
    path = tmp_path / "e.sqlite"
    client = SelectingClient()
    policy = ContextPolicy(mode="enforce", selector="jev", recent_messages=1)
    engine = ContextPolicyEngine(ContextArtifactStore(path), "scope", policy, client=client)
    first = await engine.prepare(history(), run_key="run")
    changed = history()
    changed.insert(-1, ContextItem("new", "assistant", "Another small step"))
    second = await engine.prepare(changed, run_key="run")
    assert first.replacements == second.replacements
    assert second.trace["chars_after"] == first.trace["chars_after"] + len("Another small step")
    assert second.trace["cache_hit"] and second.trace["scorer_calls"] == 0
    assert second.trace["input_sha256"] != first.trace["input_sha256"]
    restarted = ContextPolicyEngine(ContextArtifactStore(path), "scope", policy, client=client)
    changed.insert(-1, ContextItem("later", "assistant", "Continue"))
    third = await restarted.prepare(changed, run_key="run")
    assert third.replacements == first.replacements
    assert third.trace["cache_hit"]
    assert client.calls == 1


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
    continuation = await engine.prepare(changed, run_key="run")
    assert continuation.trace["fallback"] == "scorer_failed"
    assert continuation.trace["cache_hit"] and not continuation.replacements
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
