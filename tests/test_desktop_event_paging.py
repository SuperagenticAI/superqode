"""Run history remains pageable after completion and while the final page arrives."""

import json

import pytest

from test_desktop_service import desktop  # noqa: F401


def add_run(service, project, identity, status):
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (identity, project["id"], "task", identity, status, "{}", None, 1, 1),
    )


def add_events(service, identity, count):
    with service.lock:
        service.db.executemany(
            "INSERT INTO events(job,payload) VALUES(?,?)",
            [
                (identity, json.dumps({"type": "answer", "data": {"text": str(index)}}))
                for index in range(count)
            ],
        )
        service.db.commit()


@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled", "interrupted"])
@pytest.mark.parametrize("count", [0, 499, 500, 501, 1507])
def test_history_drains_without_gaps_or_duplicates_after_terminal_status(desktop, status, count):
    service, project, _ = desktop
    add_run(service, project, "history", status)
    add_events(service, "history", count)
    cursor, received = 0, []
    for _ in range(5):
        page = service.dispatch("jobs.get", {"id": "history", "after": cursor})
        assert page["status"] == status
        assert len(page["events"]) <= 500
        received.extend(page["events"])
        next_cursor = page["next_sequence"]
        assert next_cursor == (received[-1]["sequence"] if received else cursor)
        if not page["has_more_events"]:
            break
        assert next_cursor > cursor
        cursor = next_cursor
    else:
        pytest.fail("History cursor did not reach the final page")
    assert len(received) == count
    assert len({row["sequence"] for row in received}) == count
    assert [row["data"]["text"] for row in received] == list(map(str, range(count)))


def test_interleaved_runs_and_completion_with_unread_activity(desktop):
    service, project, _ = desktop
    add_run(service, project, "selected", "running")
    add_run(service, project, "other", "completed")
    add_events(service, "other", 50)
    add_events(service, "selected", 500)
    first = service.dispatch("jobs.get", {"id": "selected"})
    assert first["has_more_events"] is False  # Exactly one full page is not an extra page.
    assert first["next_sequence"] == 550

    add_events(service, "other", 20)
    add_events(service, "selected", 1)
    service._write("UPDATE jobs SET status='completed' WHERE id='selected'")
    final = service.dispatch("jobs.get", {"id": "selected", "after": first["next_sequence"]})
    assert final["status"] == "completed"
    assert [row["sequence"] for row in final["events"]] == [571]
    assert final["next_sequence"] == 571
    assert final["has_more_events"] is False
    empty = service.dispatch("jobs.get", {"id": "selected", "after": 571})
    assert empty["events"] == []
    assert empty["next_sequence"] == 571
    assert empty["has_more_events"] is False


def test_cancellation_keeps_polling_until_the_writer_has_drained(desktop):
    service, project, _ = desktop
    add_run(service, project, "cancelled", "cancelled")
    # A cancellation status is visible before the watcher has consumed stdout.
    service.processes["cancelled"] = object()
    try:
        waiting = service.dispatch("jobs.get", {"id": "cancelled"})
        assert waiting["events"] == []
        assert waiting["has_more_events"] is False
        assert waiting["event_stream_open"] is True
        add_events(service, "cancelled", 1)
    finally:
        with service.lock:
            service.processes.pop("cancelled")
    drained = service.dispatch("jobs.get", {"id": "cancelled"})
    assert len(drained["events"]) == 1
    assert drained["event_stream_open"] is False
