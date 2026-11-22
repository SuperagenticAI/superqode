"""Revision cost counts every attempt and optimization; schedules and receipts stay bounded."""
# ruff: noqa: F401, F811

import json

from click.testing import CliRunner
import pytest

from test_factory_definition import project, rewrite, admitted
from test_factory_intake import configured, event
from superqode.commands.factory import factory
from superqode.factory import evidence, improvement, intake


def _cancel(store, order):
    store.cancel(order.work_order_id, actor="test", reason="Fixture finished")


def _usage(store, order, cost):
    store.add_artifact(
        order.work_order_id,
        kind="usage",
        metadata={"usage": {"cost_usd": cost, "cost_currency": "USD", "total_tokens": 10}},
        actor="fixture",
    )


def test_store_list_pages_with_offset(project):
    _, store, _ = admitted(project, request_id="r-0")
    for i in range(1, 5):
        admitted(project, request_id=f"r-{i}")
    everything = [o.work_order_id for o in store.list()]
    paged = [o.work_order_id for k in range(3) for o in store.list(limit=2, offset=2 * k)]
    assert paged == everything and len(everything) == 5
    assert [o.work_order_id for o in store.list(offset=4)] == everything[4:]
    with pytest.raises(ValueError):
        store.list(offset=-1)


def test_outcomes_page_past_the_old_limit_and_count_failed_attempts(project, monkeypatch):
    monkeypatch.setattr(evidence, "PAGE", 2)
    _, store, observed = admitted(project, request_id="observed")
    _usage(store, observed, 0.15)
    _cancel(store, observed)
    evidence.record_outcome(
        project, observed.work_order_id, observation="pilot", outcome="met", actor="test"
    )
    _, _, failed = admitted(project, request_id="failed")
    _usage(store, failed, 0.10)
    _cancel(store, failed)
    for i in range(3):
        admitted(project, request_id=f"queued-{i}")  # never started: zero cost
    [row] = evidence.outcomes(project)["revisions"]
    assert row["runs"] == 1 and row["attempts"]["unobserved"] == 4
    assert row["attempts"]["failed"] == 1
    assert row["cost"] == {
        "observed_runs_usd": 0.15,
        "other_attempts_usd": 0.1,
        "optimization_usd": 0,
    }
    assert row["cost_usd"] == pytest.approx(0.25)
    assert "failed and unobserved attempts" in row["cost_scope"]


def test_unknown_attempt_cost_keeps_the_revision_total_unknown(project):
    _, store, order = admitted(project)
    store.add_artifact(
        order.work_order_id, kind="usage", metadata={"usage": {"total_tokens": 5}}, actor="x"
    )
    _cancel(store, order)
    [row] = evidence.outcomes(project)["revisions"]
    assert row["cost"]["other_attempts_usd"] is None and row["cost_usd"] is None


def test_optimization_experiments_add_to_the_revision_they_ran_against(project, monkeypatch):
    plan, store, order = admitted(project)
    _usage(store, order, 0.2)
    _cancel(store, order)
    revision = plan.snapshot.digest
    for name in ("known", "unknown"):
        (project / improvement.PREFIX / name).mkdir(parents=True)
    monkeypatch.setattr(
        improvement,
        "load",
        lambda root, identity: ({"id": identity, "factory_digest": revision}, None),
    )
    summaries = {
        "known": {"accounted": {"cost_usd": 0.5, "tokens": 100}, "unknown_requests": 0},
        "unknown": {"accounted": {"cost_usd": 0.0, "tokens": 0}, "unknown_requests": 1},
    }
    monkeypatch.setattr(improvement, "budget_summary", lambda root, p: summaries[p["id"]])
    [row] = evidence.outcomes(project)["revisions"]
    assert row["attempts"]["optimization_plans"] == 2
    assert row["cost"]["optimization_usd"] is None and row["cost_usd"] is None
    summaries["unknown"] = summaries["known"]
    [row] = evidence.outcomes(project)["revisions"]
    assert row["cost"]["optimization_usd"] == 1.0
    assert row["cost_usd"] == pytest.approx(1.2)


def test_receipts_keep_the_most_recently_seen_decisions(configured):
    for i in range(256):
        intake._receipt(configured, "monitor", str(i).encode(), "rejected", "stale_event")
    intake._receipt(configured, "monitor", b"0", "rejected", "stale_event")
    intake._receipt(configured, "monitor", b"new", "rejected", "stale_event")
    rows = intake.receipts(configured)["decisions"]
    fingerprints = {r["fingerprint"] for r in rows}
    import hashlib

    assert len(rows) == 256
    assert hashlib.sha256(b"0").hexdigest() in fingerprints
    assert hashlib.sha256(b"1").hexdigest() not in fingerprints


def test_authentication_failures_are_counted_without_content(configured):
    raw, headers = event()
    for _ in range(3):
        with pytest.raises(ValueError, match="authentication"):
            intake.receive(configured, "github", raw, {"X-Hub-Signature-256": "sha256=bad"})
    [row] = intake.receipts(configured)["decisions"]
    assert row["count"] == 3 and row["fingerprint"] == "" and row["run"] == ""
    assert row["reason"] == "authentication_failed"


def test_schedule_queues_once_per_interval(configured):
    rewrite(
        configured,
        lambda d: d["orchestration"]["intake"].update(
            schedules=[{"id": "nightly", "goal": "Run the nightly upkeep", "interval_minutes": 60}]
        ),
    )
    now = 1_800_000_000
    first = intake.tick(configured, now=now)
    assert first["schedules"][0]["status"] == "queued" and not first["execution_started"]
    assert intake.tick(configured, now=now + 60)["schedules"][0]["status"] == "already_queued"
    later = intake.tick(configured, now=now + 3600)["schedules"][0]
    assert (
        later["status"] == "queued"
        and later["work_order_id"] != first["schedules"][0]["work_order_id"]
    )
    reasons = {r["reason"] for r in intake.receipts(configured)["decisions"]}
    assert reasons == {"admitted"}
    cli = CliRunner().invoke(factory, ["intake", "tick", "--project", str(configured)])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.output)["schedules"][0]["status"] in {"queued", "rejected"}


def test_schedule_requires_saved_schedules(configured):
    with pytest.raises(ValueError, match="No schedule"):
        intake.tick(configured)
