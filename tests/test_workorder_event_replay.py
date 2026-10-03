"""Lifecycle evidence can be paged and resumed without skipping a backlog."""

import json

import pytest
from click.testing import CliRunner

from superqode.main import cli_main
from superqode.workorders import WorkOrder, WorkOrderStore, WorkOrderTask


def create(store, identity):
    return store.create(
        WorkOrder(
            work_order_id=identity,
            goal="work",
            repository=".",
            tasks=(WorkOrderTask(task_id="task", title="Task", goal="work"),),
        ),
        queue=True,
    )


def test_cursor_pages_across_restart_and_interleaved_orders(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    create(store, "first")
    create(store, "other")
    store.claim_next_task(reference="first", worker_id="worker")
    store.complete_task("first", "task", worker_id="worker")
    expected = store.events("first")
    assert all(event.sequence > 0 for event in expected)
    first_page = store.events("first", after_sequence=0, limit=2)
    assert first_page == expected[:2]
    reopened = WorkOrderStore(store.path)
    second_page = reopened.events("first", after_sequence=first_page[-1].sequence, limit=2)
    remaining = reopened.events("first", after_sequence=second_page[-1].sequence)
    assert first_page + second_page + remaining == expected
    assert reopened.events("first", after_sequence=expected[-1].sequence) == []
    assert reopened.events("first", limit=2) == expected[-2:]
    assert reopened.events("first", after_sequence=0, limit=0) == []
    assert expected[2].sequence > expected[1].sequence + 1


@pytest.mark.parametrize("cursor", [-1, True, 1.5, "1"])
def test_invalid_cursors_fail(tmp_path, cursor):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    create(store, "work")
    with pytest.raises(ValueError, match="nonnegative integer"):
        store.events("work", after_sequence=cursor)


def test_cli_json_exposes_cursor_for_next_page(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    create(store, "work")
    command = ["work", "--store", str(store.path), "events", "work", "--json", "--limit", "1"]
    first = CliRunner().invoke(cli_main, [*command, "--after-sequence", "0"])
    assert first.exit_code == 0, first.output
    page = json.loads(first.output)
    second = CliRunner().invoke(cli_main, [*command, "--after-sequence", str(page[-1]["sequence"])])
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)[0]["type"] == "work.queued"
