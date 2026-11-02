import json

import pytest

from test_desktop_service import desktop  # noqa: F401
from test_desktop_threads import task


def test_activity_lists_priority_threads_across_projects_without_private_payloads(desktop):
    service, project, root = desktop
    other = root.parent / "another-project"
    other.mkdir()
    second = service.open_project(str(other))
    task(service, project["id"], "older-active", status="needs_approval", updated=1)
    for index in range(110):
        task(service, second["id"], f"done-{index}", updated=index + 10)
    task(service, second["id"], "worker", status="running", updated=3)
    result = service.dispatch("activity.list", {})
    assert result["items"][0]["id"] == "older-active"
    assert result["counts"]["working"] == 1
    assert result["counts"]["attention"] == 1
    assert result["counts"]["done"] == 110
    assert "PRIVATE" not in json.dumps(result)
    assert {row["project"] for row in result["items"]} == {project["id"], second["id"]}
    page = service.dispatch("activity.list", {"cursor": result["next_cursor"]})
    assert not {row["id"] for row in result["items"]}.intersection(
        row["id"] for row in page["items"]
    )
    with pytest.raises(ValueError, match="Refresh activity"):
        service.dispatch("activity.list", {"cursor": result["next_cursor"], "view": "working"})
    scoped = service.dispatch("activity.list", {"project": project["id"]})
    assert [row["id"] for row in scoped["items"]] == ["older-active"]


def test_activity_groups_full_lineage_and_filters_archived_threads(desktop):
    service, project, _ = desktop
    task(service, project["id"], "root", updated=1)
    task(service, project["id"], "latest", parent="root", updated=2, status="failed")
    rows = service.dispatch("activity.list", {"view": "attention"})["items"]
    assert len(rows) == 1 and rows[0]["id"] == "latest"
    assert service.dispatch("activity.list", {"query": "nonexistent"})["counts"]["all"] == 0
    service.dispatch("threads.update", {"project": project["id"], "id": "latest", "archived": True})
    assert not service.dispatch("activity.list", {})["items"]
