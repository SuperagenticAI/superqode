import json

from test_desktop_service import desktop  # noqa: F401
from test_desktop_threads import task
from superqode.desktop_service.service import DesktopService


def test_notification_journal_is_private_deduplicated_and_cursor_bound(desktop):
    service, project, _ = desktop
    task(service, project["id"], "thread", title="PRIVATE task text", status="running")
    baseline = service.dispatch("notifications.poll", {})
    assert baseline["items"] == []
    for request in ["approval-one", "approval-one", "approval-two"]:
        service.pending["thread"] = request
        service._status("thread", "needs_approval")
    result = service.dispatch("notifications.poll", {"after": baseline["cursor"]})
    assert [row["status"] for row in result["items"]] == ["needs_approval", "needs_approval"]
    assert result["attention_count"] == 1
    assert "PRIVATE" not in json.dumps(result)
    assert not service.dispatch("notifications.poll", {"after": result["cursor"]})["items"]
    service._status("thread", "completed")
    service._status("thread", "completed")
    completion = service.dispatch("notifications.poll", {"after": result["cursor"]})
    assert len(completion["items"]) == 1
    assert completion["items"][0]["status"] == "completed"
    assert completion["attention_count"] == 0
    state = service.root
    service.close()
    restored = DesktopService(state)
    try:
        assert not restored.dispatch("notifications.poll", {"after": completion["cursor"]})["items"]
    finally:
        restored.close()


def test_active_jobs_remain_visible_beyond_recent_history_window(desktop):
    service, project, _ = desktop
    task(service, project["id"], "old-worker", status="needs_approval", updated=1)
    for index in range(110):
        task(service, project["id"], f"new-{index}", updated=index + 10)
    assert "old-worker" in {row["id"] for row in service.dispatch("jobs.list", {})}
