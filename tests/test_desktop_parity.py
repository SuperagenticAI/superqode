"""Native image, checkpoint and live-control paths use actual shared engines."""

import base64
import json
import subprocess
import time

import pytest

from test_desktop_service import desktop, desktop_acp_route, drive_acp  # noqa: F401
from superqode.desktop_service.images import resolve_images, load_snapshots

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aU1QAAAAASUVORK5CYII="
)


def test_image_snapshots_and_real_acp_transport(desktop_acp_route, tmp_path):
    (service, project, _), route = desktop_acp_route
    source = tmp_path / "outside-project.png"
    source.write_bytes(PNG)
    staged = service.dispatch("images.stage", {"path": str(source)})
    source.write_bytes(b"changed source")
    snapshots = resolve_images(service.root, [staged["id"]])
    assert base64.b64decode(load_snapshots({"image_snapshots": snapshots})[0].data) == PNG
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": route["id"],
            "prompt": "image",
            "image_ids": [staged["id"]],
            "image_snapshots": [{"path": "/etc/passwd"}],
        },
    )
    result = drive_acp(service, job["id"])
    assert result["status"] == "completed", result
    assert "Image parts received: 1" in json.dumps(result["events"])
    assert base64.b64encode(PNG).decode() not in json.dumps(result["request"])
    for ids in [["../escape"], [{}], [staged["id"]] * 5]:
        with pytest.raises(ValueError):
            resolve_images(service.root, ids)
    with open(staged["path"], "wb") as output:
        output.write(PNG + b"changed")
    with pytest.raises(ValueError, match="changed"):
        load_snapshots({"image_snapshots": snapshots})


def test_native_task_checkpoint_restores_without_overwriting_later_edits(desktop_acp_route):
    (service, project, root), route = desktop_acp_route
    staged_before = subprocess.check_output(["git", "-C", str(root), "diff", "--cached"])
    job = service.dispatch(
        "tasks.start", {"project": project["id"], "harness": route["id"], "prompt": "write code"}
    )
    result = drive_acp(service, job["id"])
    assert result["status"] == "completed", result
    items = service.dispatch("checkpoints.list", {"project": project["id"]})["items"]
    assert items and any(change["path"] == "main.py" for change in items[-1]["changes"])
    target = root / "main.py"
    generated = target.read_text()
    target.write_text("my later edit")
    with pytest.raises(ValueError, match="changed"):
        service.dispatch("checkpoints.undo", {"project": project["id"]})
    assert target.read_text() == "my later edit"
    target.write_text(generated)
    service.dispatch("checkpoints.undo", {"project": project["id"]})
    assert not target.exists()
    service.dispatch("checkpoints.redo", {"project": project["id"]})
    assert target.read_text() == generated
    assert subprocess.check_output(["git", "-C", str(root), "diff", "--cached"]) == staged_before


def test_real_vendor_live_steering_is_acknowledged(desktop, monkeypatch, tmp_path):
    import sys
    from test_runtime_codex_cli import SERVER

    service, project, _ = desktop
    executable = tmp_path / "codex-steering-fixture"
    executable.write_text(
        "#!"
        + sys.executable
        + "\nimport sys\nif 'generate-json-schema' in sys.argv: sys.exit(1)\nif '--version' in sys.argv: print('codex 0.160.0'); sys.exit(0)\n"
        + SERVER
    )
    executable.chmod(0o700)
    monkeypatch.setenv("SUPERQODE_CODEX_BIN", str(executable))
    monkeypatch.delenv("SUPERQODE_CODEX_SERVER", raising=False)
    job = service.dispatch(
        "tasks.start",
        {"project": project["id"], "harness": "connection:codex", "prompt": "wait", "model": ""},
    )
    identity = job["id"]
    for _ in range(200):
        result = service.dispatch("jobs.get", {"id": identity})
        if "hello " in json.dumps(result["events"]):
            break
        time.sleep(0.025)
    sent = service.dispatch("jobs.steer", {"id": identity, "text": "Focus on the tests"})
    result = drive_acp(service, identity)
    assert result["status"] == "completed", result
    assert any(
        event["type"] == "steering"
        and event["data"]["accepted"]
        and event["data"]["request_id"] == sent["request_id"]
        for event in result["events"]
    )
    assert "steered" in json.dumps(result["events"])


def test_workorder_board_is_read_only_and_uses_shared_cockpit(desktop):
    from superqode.workorders.models import WorkOrder, WorkOrderTask
    from superqode.workorders.store import WorkOrderStore

    service, project, root = desktop
    params = {"project": project["id"]}
    assert service.dispatch("workorders.snapshot", params) == {"items": []}
    assert not (root / ".superqode/workorders").exists()
    store = WorkOrderStore(root / ".superqode/workorders/store.sqlite3")
    store.create(
        WorkOrder(
            work_order_id="native-board",
            goal="Build a native workflow",
            repository=str(root),
            tasks=(WorkOrderTask(task_id="code", title="Implement", goal="Write code"),),
        )
    )
    result = service.dispatch("workorders.snapshot", params)
    assert result["items"][0]["work_order_id"] == "native-board"
    assert result["items"][0]["tasks"][0]["title"] == "Implement"
    assert {"workers", "usage", "gates", "budget"} <= result["items"][0].keys()


def test_unsealed_checkpoint_cannot_adopt_and_undo_later_user_edits(desktop):
    from superqode.desktop_service.checkpoints import begin_task

    service, project, root = desktop
    begin_task(root, "Interrupted before after-state")
    (root / "hello.txt").write_text("later user edit")
    state = service.dispatch("checkpoints.list", {"project": project["id"]})
    assert state["items"][-1]["sealed"] is False
    assert state["items"][-1]["changes"] == []
    assert state["can_undo"] is False
    with pytest.raises(ValueError, match="sealed"):
        service.dispatch("checkpoints.undo", {"project": project["id"]})
    assert (root / "hello.txt").read_text() == "later user edit"
