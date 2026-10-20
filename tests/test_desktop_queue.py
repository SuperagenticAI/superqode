"""Queue persistence, ordering and explicit execution boundaries."""

import time

import pytest

from superqode.desktop_service.service import DesktopService
from test_desktop_service import desktop, desktop_acp_route, drive_acp  # noqa: F401


def queue_wait(service, project, state):
    for _ in range(200):
        result = service.dispatch("queue.list", {"project": project})
        if result["items"] and result["items"][-1]["state"] == state:
            return result
        time.sleep(0.02)
    pytest.fail(str(result))


def test_queue_runs_in_order_and_persists_without_automatic_replay(desktop_acp_route):
    (service, project, root), route = desktop_acp_route
    params = {"project": project["id"], "harness": route["id"], "prompt": "write code"}
    first = service.dispatch("queue.add", params)["id"]
    second = service.dispatch("queue.add", {**params, "prompt": "terminal"})["id"]
    assert not service.processes
    service.dispatch("queue.move", {"project": project["id"], "id": second, "direction": "up"})
    assert service.dispatch("queue.list", params)["items"][0]["id"] == second
    started = service.dispatch("queue.run", params)
    job = started["items"][0]["job"]
    assert job
    drive_acp(service, job)
    for _ in range(200):
        items = service.dispatch("queue.list", params)["items"]
        if items[1]["job"]:
            break
        time.sleep(0.02)
    drive_acp(service, items[1]["job"])
    result = queue_wait(service, project["id"], "completed")
    assert {item["state"] for item in result["items"]} == {"completed"}
    assert (root / "main.py").exists()
    # A retry creates a fresh command identity, never silently reuses the old run.
    previous_job = result["items"][1]["job"]
    service.dispatch("queue.retry", {"project": project["id"], "id": first})
    assert not service.dispatch("queue.list", params)["running"]
    rerun = service.dispatch("queue.run", params)
    fresh = rerun["items"][1]["job"]
    assert fresh != previous_job
    drive_acp(service, fresh)
    queue_wait(service, project["id"], "completed")
    service.dispatch("queue.add", params)
    service.close()
    restored = DesktopService(service.root)
    try:
        assert not restored.dispatch("queue.list", params)["running"]
        assert restored.dispatch("queue.list", params)["items"][-1]["state"] == "pending"
        assert not restored.processes
    finally:
        restored.close()


def test_queue_setup_failure_pauses_and_keeps_remaining_tasks(desktop):
    service, project, _ = desktop
    params = {
        "project": project["id"],
        "prompt": "task",
        "harness": "unknown-profile-no-such-harness",
    }
    service.dispatch("queue.add", params)
    service.dispatch("queue.add", params)
    result = service.dispatch("queue.run", params)
    assert not result["running"]
    assert [item["state"] for item in result["items"]] == ["failed", "pending"]
    assert not service.processes


def test_pause_leaves_following_task_pending(desktop_acp_route):
    (service, project, _), route = desktop_acp_route
    params = {"project": project["id"], "harness": route["id"], "prompt": "write code"}
    service.dispatch("queue.add", params)
    service.dispatch("queue.add", params)
    running = service.dispatch("queue.run", params)
    service.dispatch("queue.pause", params)
    drive_acp(service, running["items"][0]["job"])
    for _ in range(100):
        result = service.dispatch("queue.list", params)
        if result["items"][0]["state"] == "completed":
            break
        time.sleep(0.02)
    assert not result["running"]
    assert result["items"][1]["state"] == "pending"
    assert not result["items"][1]["job"]
