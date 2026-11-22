"""Durable continuation gates in the shared worker admission transaction."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from superqode.workorders import (
    WorkOrder,
    WorkOrderStore,
    WorkOrderTask,
    WorkOrderStatus,
    WorkTaskStatus,
)


def waiting(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id="gate-work",
        goal="Fix and verify",
        repository=str(tmp_path),
        tasks=(
            WorkOrderTask(task_id="implement", title="Implement", goal="Fix"),
            WorkOrderTask(
                task_id="verify",
                title="Verify",
                goal="Check",
                dependencies=("implement",),
                metadata={"human_gate": True},
            ),
        ),
    )
    store.create(order, queue=True)
    store.claim_next_task(reference="gate-work", worker_id="worker")
    store.add_artifact(
        "gate-work", kind="patch", task_id="implement", content="Fix", digest="patch-1"
    )
    store.complete_task("gate-work", "implement", worker_id="worker")
    assert store.claim_next_task(reference="gate-work", worker_id="worker") is None
    gate = store.get("gate-work").tasks[1]
    assert gate.status == WorkTaskStatus.WAITING
    return store, gate.metadata["gate_digest"]


def test_human_wait_survives_reopen_recovery_and_ordinary_workers(tmp_path):
    store, token = waiting(tmp_path)
    before = store.events("gate-work")
    reopened = WorkOrderStore(store.path)
    reopened.recover_stale("gate-work")
    assert reopened.claim_next_task(reference="gate-work", worker_id="different") is None
    assert reopened.events("gate-work") == before
    assert reopened.get("gate-work").tasks[1].attempts == 0
    with pytest.raises(ValueError, match="Cannot resume"):
        reopened.resume("gate-work")
    with pytest.raises(ValueError):
        reopened.complete_task("gate-work", "verify", worker_id="different")
    with pytest.raises(ValueError, match="changed"):
        reopened.decide_gate(
            "gate-work", "verify", expected_digest="stale", decision="approve", actor="owner"
        )
    approved = reopened.decide_gate(
        "gate-work", "verify", expected_digest=token, decision="approve", actor="owner"
    )
    assert approved.decision is None
    assert (
        reopened.claim_next_task(reference="gate-work", worker_id="different")[1].task_id
        == "verify"
    )


def test_new_evidence_invalidates_continuation_and_requires_a_new_decision(tmp_path):
    store, token = waiting(tmp_path)
    store.decide_gate(
        "gate-work", "verify", expected_digest=token, decision="approve", actor="owner"
    )
    store.add_artifact("gate-work", kind="finding", task_id="implement", content="New evidence")
    assert store.claim_next_task(reference="gate-work", worker_id="worker") is None
    gate = store.get("gate-work").tasks[1]
    assert gate.status == WorkTaskStatus.WAITING
    assert gate.metadata["gate_digest"] != token
    with pytest.raises(ValueError, match="changed"):
        store.decide_gate(
            "gate-work", "verify", expected_digest=token, decision="approve", actor="owner"
        )
    store.decide_gate(
        "gate-work",
        "verify",
        expected_digest=gate.metadata["gate_digest"],
        decision="approve",
        actor="owner",
    )
    assert store.claim_next_task(reference="gate-work", worker_id="worker") is not None


def test_gate_decision_retries_do_not_duplicate_events_or_restart_work(tmp_path):
    store, token = waiting(tmp_path)
    kwargs = dict(expected_digest=token, decision="approve", actor="owner", reason="Inspected")
    store.decide_gate("gate-work", "verify", **kwargs)
    store.claim_next_task(reference="gate-work", worker_id="worker")
    before = store.events("gate-work")
    retry = WorkOrderStore(store.path).decide_gate("gate-work", "verify", **kwargs)
    assert retry.tasks[1].status == WorkTaskStatus.RUNNING
    assert retry.tasks[1].attempts == 1
    assert store.events("gate-work") == before


def test_competing_gate_decisions_record_one_continuation(tmp_path):
    store, token = waiting(tmp_path)

    def approve(actor):
        try:
            WorkOrderStore(store.path).decide_gate(
                "gate-work", "verify", expected_digest=token, decision="approve", actor=actor
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as clients:
        outcomes = list(clients.map(approve, ["owner-one", "owner-two"]))
    assert sum(outcomes) == 1
    assert [event.type for event in store.events("gate-work")].count("task.gate_approve") == 1


def test_cancelled_wait_cannot_be_continued(tmp_path):
    store, token = waiting(tmp_path)
    store.cancel("gate-work", actor="owner", reason="No longer needed")
    assert store.get("gate-work").tasks[1].status == WorkTaskStatus.CANCELLED
    with pytest.raises(ValueError, match="cancelled"):
        store.decide_gate(
            "gate-work", "verify", expected_digest=token, decision="approve", actor="owner"
        )
    assert store.claim_next_task(reference="gate-work", worker_id="worker") is None


def test_fresh_drafts_cannot_smuggle_gate_approvals(tmp_path):
    store, token = waiting(tmp_path)
    fresh = WorkOrder(
        work_order_id="forged",
        goal="Skip the human",
        repository=str(tmp_path),
        tasks=(
            WorkOrderTask(
                task_id="skip",
                title="Skip",
                goal="Skip",
                metadata={"human_gate": True, "gate_approval": {"digest": token}},
            ),
        ),
    )
    with pytest.raises(ValueError, match="preapproved"):
        store.create(fresh, queue=True)
