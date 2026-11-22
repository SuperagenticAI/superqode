"""Triggers cannot create recursive, unmetered or silently replayed experiments."""
# ruff: noqa: F401, F811

import json

import pytest

from test_factory_definition import project, rewrite
from test_factory_improvement import prepared
from test_factory_search_metering import evaluator, model
from superqode.factory import campaigns, improvement
from superqode.factory.definition import load_factory
from superqode.factory.snapshot import digest, canonical


@pytest.fixture
def configured(prepared):
    root, old = prepared
    policy = {
        "triggers": ["incident"],
        "event_sources": {"incident": ".superqode/factory-events/incident.json"},
        "max_experiments": 2,
        "max_seconds": 120,
        "max_tokens": 1000,
        "max_tool_calls": 20,
        "max_cost_usd": 1,
        "cooldown_seconds": 0,
        "max_depth": 0,
        "stop_after_holds": 1,
        "experiment": {
            "binding": "coder",
            "tasks": old["tasks"],
            "fixture": "fixture",
            "target_kind": "workflow",
            "stage": "investigate",
            "reflection_model": "ollama/qwen3-coder",
            "optimizer_engine": "evaluator-optimizer",
            "max_evals": 2,
            "max_seconds": 60,
        },
    }
    rewrite(
        root,
        lambda d: d["improvement"]["optimization"].update(
            automatic_experiments=True, experiment_policy=policy
        ),
    )
    source = root / policy["event_sources"]["incident"]
    source.parent.mkdir()
    source.write_text('{"incident":"example"}')
    return root, policy, source


def admit(root, current, source, *, key="incident-1", parent=""):
    return campaigns.enqueue(
        root,
        current["manifest"]["id"],
        expected=current["manifest"]["digest"],
        kind="incident",
        key=key,
        source=source.relative_to(root).as_posix(),
        source_digest=digest(source.read_text()),
        parent=parent,
    )


def test_opt_in_requires_bounded_policy_and_does_not_execute(project):
    with pytest.raises(ValueError, match="opt-in"):
        campaigns.create(project)
    rewrite(project, lambda d: d["improvement"]["optimization"].update(automatic_experiments=True))
    with pytest.raises(ValueError, match="automatic_experiments"):
        load_factory(root=project)


def test_idempotent_sources_keys_and_recursion_are_fenced(configured):
    root, policy, source = configured
    current = campaigns.create(root)
    first = admit(root, current, source)
    assert not first["deduplicated"]
    assert admit(root, current, source)["deduplicated"]
    assert admit(root, current, source, key="different-key")["deduplicated"]
    source.write_text('{"incident":"next"}')
    with pytest.raises(ValueError, match="key already binds"):
        admit(root, current, source)
    with pytest.raises(ValueError, match="depth"):
        admit(root, current, source, key="next", parent=first["event"]["id"])


def test_trigger_source_and_source_revision_are_verified(configured):
    root, policy, source = configured
    current = campaigns.create(root)
    admit(root, current, source)
    source.write_text('{"incident":"changed"}')
    with pytest.raises(ValueError, match="source changed"):
        campaigns.advance(root, current["manifest"]["id"], current["manifest"]["digest"], live=True)
    assert not campaigns.inspect(root, current["manifest"]["id"])["reserved_experiments"]


def test_campaign_shares_reservations_and_waits_before_adoption(configured, model, monkeypatch):
    root, policy, source = configured
    evaluator(monkeypatch)
    current = campaigns.create(root)
    admit(root, current, source)
    before = (root / ".superqode/factory.yaml").read_bytes()
    result = campaigns.advance(
        root, current["manifest"]["id"], current["manifest"]["digest"], live=True
    )
    assert result["state"]["status"] == "awaiting_review"
    assert result["reserved_experiments"] == 1
    event = result["state"]["events"][0]
    child, _ = improvement.load(root, event["plan"])
    assert child["limits"]["max_tokens"] == 500
    assert child["absolute_deadline"] <= result["state"]["started"] + 120
    assert result["observed"]["tokens"] == 17
    assert not result["adoption_authorized"] and not result["release_authorized"]
    assert (root / ".superqode/factory.yaml").read_bytes() == before
    with pytest.raises(ValueError, match="stopped or held"):
        campaigns.advance(root, current["manifest"]["id"], current["manifest"]["digest"], live=True)


def test_automatic_heldout_cannot_be_reused_by_new_campaign(configured, model, monkeypatch):
    root, policy, source = configured
    evaluator(monkeypatch)
    first = campaigns.create(root)
    admit(root, first, source)
    campaigns.advance(root, first["manifest"]["id"], first["manifest"]["digest"], live=True)
    second = campaigns.create(root)
    admit(root, second, source)
    result = campaigns.advance(
        root, second["manifest"]["id"], second["manifest"]["digest"], live=True
    )
    assert result["state"]["status"] == "held"
    assert "already consumed" in result["state"]["events"][0]["reason"]
    assert "comparison" not in result["state"]["events"][0]


def test_interrupted_action_is_never_replayed(configured, monkeypatch):
    root, policy, source = configured
    current = campaigns.create(root)
    admit(root, current, source)

    def interrupted(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(improvement, "optimize", interrupted)
    with pytest.raises(KeyboardInterrupt):
        campaigns.advance(root, current["manifest"]["id"], current["manifest"]["digest"], live=True)
    saved = campaigns.inspect(root, current["manifest"]["id"])
    assert saved["reserved_experiments"] == 1
    with pytest.raises(ValueError, match="uncertain"):
        campaigns.advance(root, current["manifest"]["id"], current["manifest"]["digest"], live=True)


def test_stop_and_live_confirmation_prevent_work(configured):
    root, policy, source = configured
    current = campaigns.create(root)
    admit(root, current, source)
    with pytest.raises(ValueError, match="--live"):
        campaigns.advance(root, current["manifest"]["id"], current["manifest"]["digest"])
    campaigns.stop(root, current["manifest"]["id"], current["manifest"]["digest"])
    with pytest.raises(ValueError, match="stopped or held"):
        campaigns.advance(root, current["manifest"]["id"], current["manifest"]["digest"], live=True)


def test_campaign_usage_tampering_invalidates_inspection(configured, model, monkeypatch):
    root, policy, source = configured
    evaluator(monkeypatch)
    current = campaigns.create(root)
    admit(root, current, source)
    result = campaigns.advance(
        root, current["manifest"]["id"], current["manifest"]["digest"], live=True
    )
    event = result["state"]["events"][0]
    path = improvement.folder(root, event["plan"]) / "usage.json"
    usage = json.loads(path.read_text())
    usage["requests"][0]["tokens"] = 0
    path.write_text(canonical(usage))
    with pytest.raises(ValueError, match="usage changed"):
        campaigns.inspect(root, current["manifest"]["id"])


@pytest.mark.parametrize(
    "limits",
    [{"max_tokens": True}, {"max_tokens": 0}, {"max_cost_usd": float("nan")}, {"max_workers": 5}],
)
def test_child_cannot_widen_or_corrupt_limits(prepared, limits):
    root, plan = prepared
    with pytest.raises(ValueError, match="budget"):
        improvement.prepare(
            root, binding="coder", tasks=plan["tasks"], fixture="fixture", budget_limits=limits
        )
