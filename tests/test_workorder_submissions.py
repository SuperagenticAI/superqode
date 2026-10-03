"""Retry-safe WorkOrder admission under crashes and competing clients."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from click.testing import CliRunner

from superqode.main import cli_main
from superqode.workorders import (
    WorkOrder,
    WorkOrderBudget,
    WorkOrderStatus,
    WorkOrderStore,
    WorkOrderTask,
    generate_work_order_id,
)


def contract(root):
    return WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="fix",
        repository=str(root),
        harness="pipy",
        acceptance_tests=("pytest -q",),
        tasks=(WorkOrderTask(task_id="fix", title="Fix", goal="fix"),),
    )


def test_concurrent_retries_admit_one_contract_and_preserve_live_state(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    with ThreadPoolExecutor(max_workers=6) as clients:
        admitted = list(
            clients.map(
                lambda _: store.create(contract(tmp_path), request_id="event-42", queue=True),
                range(6),
            )
        )
    assert len({order.work_order_id for order in admitted}) == 1
    original = admitted[0]
    assert original.status == WorkOrderStatus.QUEUED
    store.claim_next_task(reference=original.work_order_id, worker_id="worker")
    before = store.events(original.work_order_id)
    retry = WorkOrderStore(store.path).create(contract(tmp_path), request_id="event-42", queue=True)
    assert retry.status == WorkOrderStatus.RUNNING
    assert retry.tasks[0].worker_id == "worker"
    assert store.events(original.work_order_id) == before
    assert [event.type for event in before].count("work.created") == 1
    assert [event.type for event in before].count("work.queued") == 1


@pytest.mark.parametrize(
    "change",
    [
        {"goal": "different"},
        {"harness": "core"},
        {"acceptance_tests": ("other",)},
        {"budget": WorkOrderBudget(max_tool_calls=1)},
        {"metadata": {"caller": "different"}},
    ],
)
def test_request_key_conflicts_fail_without_changing_order(tmp_path, change):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    original = store.create(contract(tmp_path), request_id="key", queue=True)
    with pytest.raises(ValueError, match="different WorkOrder contract"):
        store.create(replace(contract(tmp_path), **change), request_id="key", queue=True)
    with pytest.raises(ValueError, match="different WorkOrder contract"):
        store.create(contract(tmp_path), request_id="key", queue=False)
    assert store.get(original.work_order_id) == original


def test_task_contract_changes_conflict_and_plain_create_stays_distinct(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    store.create(contract(tmp_path), request_id="key")
    order = contract(tmp_path)
    changed = replace(order, tasks=(replace(order.tasks[0], max_attempts=7),))
    with pytest.raises(ValueError, match="different WorkOrder contract"):
        store.create(changed, request_id="key")
    assert (
        store.create(contract(tmp_path)).work_order_id
        != store.create(contract(tmp_path)).work_order_id
    )
    with pytest.raises(ValueError, match="request_id"):
        store.create(contract(tmp_path), request_id=" ")


def test_queue_failure_rolls_back_order_receipt_and_events(tmp_path, monkeypatch):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = contract(tmp_path)
    append = store._append_event_tx

    def fail_queue(conn, reference, event_type, **kwargs):
        if event_type == "work.queued":
            raise RuntimeError("failed before queue commit")
        return append(conn, reference, event_type, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(store, "_append_event_tx", fail_queue)
        with pytest.raises(RuntimeError):
            store.create(order, request_id="key", queue=True)
    with pytest.raises(KeyError):
        store.get(order.work_order_id)
    assert store.create(order, request_id="key", queue=True).status == WorkOrderStatus.QUEUED


def test_client_exit_after_commit_can_retry_without_duplicate(tmp_path):
    path = tmp_path / "work.sqlite3"
    order = contract(tmp_path)
    code = """
import json, os, sys
from superqode.workorders import WorkOrder, WorkOrderStore
store = WorkOrderStore(sys.argv[1])
store.create(WorkOrder.from_dict(json.loads(sys.argv[2])), request_id='key', queue=True)
os._exit(17)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(path), json.dumps(order.to_dict())], timeout=20
    )
    assert process.returncode == 17
    store = WorkOrderStore(path)
    retry = store.create(contract(tmp_path), request_id="key", queue=True)
    assert retry.work_order_id == order.work_order_id
    assert [event.type for event in store.events(retry.work_order_id)] == [
        "work.created",
        "work.queued",
    ]


def test_competing_processes_bind_one_request_and_cancelled_work_stays_cancelled(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    code = """
import json, sys
from superqode.workorders import WorkOrder, WorkOrderStore
order = WorkOrder.from_dict(json.loads(sys.argv[2]))
result = WorkOrderStore(sys.argv[1]).create(order, request_id='key', queue=True)
print(result.work_order_id)
"""
    clients = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(store.path), json.dumps(contract(tmp_path).to_dict())],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    identities = []
    for client in clients:
        stdout, stderr = client.communicate(timeout=20)
        assert client.returncode == 0, stderr
        identities.append(stdout.strip())
    assert len(set(identities)) == 1
    identity = identities[0]
    assert [event.type for event in store.events(identity)] == ["work.created", "work.queued"]
    store.cancel(identity, reason="superseded")
    retry = store.create(contract(tmp_path), request_id="key", queue=True)
    assert retry.status == WorkOrderStatus.CANCELLED
    assert [event.type for event in store.events(identity)] == [
        "work.created",
        "work.queued",
        "work.cancelled",
    ]


def test_cli_retry_uses_same_id_and_rejects_changed_budget(tmp_path):
    command = [
        "work",
        "--store",
        str(tmp_path / "work.sqlite3"),
        "create",
        "fix",
        "--repo",
        str(tmp_path),
        "--harness",
        "pipy",
        "--request-id",
        "event-42",
        "--queue",
        "--json",
    ]
    runner = CliRunner()
    first = runner.invoke(cli_main, command)
    second = runner.invoke(cli_main, command)
    assert first.exit_code == second.exit_code == 0, first.output + second.output
    assert json.loads(first.output)["work_order_id"] == json.loads(second.output)["work_order_id"]
    conflict = runner.invoke(cli_main, [*command, "--max-tool-calls", "5"])
    assert conflict.exit_code != 0 and "different WorkOrder contract" in conflict.output
