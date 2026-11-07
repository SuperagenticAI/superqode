"""Mobile editing uses exact revisions, device-owned attachments and explicit grants."""

import json

import httpx
import pytest

from test_desktop_companion import companion, pair, PRINCIPAL, ORIGIN  # noqa: F401
from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service.remote_http import application

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aU1QAAAAASUVORK5CYII="


def test_file_edits_require_new_grant_exact_revision_and_shared_path(companion):
    service, project, root, profile, access = companion
    _, reader = pair(access, profile, ["read", "tasks"])
    with pytest.raises(PermissionError):
        access.rpc(
            reader,
            "files.write",
            {"project": project["id"], "path": "hello.txt", "text": "wrong", "digest": "wrong"},
            "denied",
        )
    _, writer = pair(access, profile, ["read", "edit"])
    before = access.rpc(writer, "files.read", {"project": project["id"], "path": "hello.txt"})
    payload = {
        "project": project["id"],
        "path": "hello.txt",
        "text": "first mobile edit",
        "digest": before["digest"],
    }
    saved = access.rpc(writer, "files.write", payload, "edit-1")
    assert (root / "hello.txt").read_text() == payload["text"]
    assert access.rpc(writer, "files.write", payload, "edit-1") == saved
    (root / "hello.txt").write_text("external edit")
    with pytest.raises(ValueError, match="changed"):
        access.rpc(writer, "files.write", payload, "stale")
    assert (root / "hello.txt").read_text() == "external edit"
    with pytest.raises(ValueError):
        access.rpc(
            writer,
            "files.create",
            {"project": project["id"], "path": ".superqode/checkpoints/raw", "text": "bad"},
            "hidden",
        )
    result = access.rpc(
        writer,
        "files.create",
        {"project": project["id"], "path": "Sources/模型.py", "text": "print('local')"},
        "create",
    )
    assert result["digest"]
    with pytest.raises(ValueError, match="already exists"):
        access.rpc(
            writer,
            "files.create",
            {"project": project["id"], "path": "Sources/模型.py", "text": "overwrite"},
            "duplicate",
        )
    assert not service._all("SELECT id FROM jobs")


def test_uploaded_images_are_idempotent_private_and_bound_to_device_and_project(companion):
    service, project, _, profile, access = companion
    _, phone = pair(access, profile, ["read", "tasks"])
    payload = {"project": project["id"], "name": "screenshot.png", "data": PNG}
    image = access.rpc(phone, "images.upload", payload, "photo-1")
    assert image["bytes"] > 0 and "path" not in image
    assert access.rpc(phone, "images.upload", payload, "photo-1") == image
    assert len(service._all("SELECT * FROM companion_images")) == 1
    _, other = pair(access, profile, ["read", "tasks"])
    for method, values in [
        ("tasks.start", {"profile": profile["id"], "prompt": "review", "image_ids": [image["id"]]}),
        ("images.remove", {"project": project["id"], "id": image["id"]}),
    ]:
        with pytest.raises(PermissionError, match="device"):
            access.rpc(other, method, values, method)
    with pytest.raises(ValueError):
        access.rpc(phone, "images.upload", {**payload, "name": "../escape.png"}, "escape")
    with pytest.raises(ValueError):
        access.rpc(phone, "images.upload", {**payload, "data": "not base64"}, "invalid")
    assert access.rpc(
        phone, "images.remove", {"project": project["id"], "id": image["id"]}, "remove"
    )["ok"]
    assert not list((service.root / "images").glob(image["id"] + ".*"))
    assert access.rpc(
        phone, "images.remove", {"project": project["id"], "id": image["id"]}, "remove"
    )["ok"]


def test_queue_edits_refuse_stale_revision_and_cannot_start_unshared_routes(companion):
    service, project, _, profile, access = companion
    _, phone = pair(access, profile, ["read", "tasks", "queue"])
    old = access.rpc(phone, "queue.list", {"project": project["id"]})
    entry = access.rpc(
        phone, "queue.add", {"profile": profile["id"], "prompt": "A scoped queued task"}, "enqueue"
    )
    request = service.task_queues.list(project["id"])["items"][0]["request"]
    assert request["permission_mode"] == "ask"
    assert request["model"] == profile["model"]
    with pytest.raises(ValueError, match="queue changed"):
        access.rpc(
            phone,
            "queue.remove",
            {"project": project["id"], "id": entry["id"], "revision": old["revision"]},
            "stale-remove",
        )
    current = access.rpc(phone, "queue.list", {"project": project["id"]})
    access.rpc(
        phone,
        "queue.remove",
        {"project": project["id"], "id": entry["id"], "revision": current["revision"]},
        "remove",
    )
    assert not service.task_queues.list(project["id"])["items"]
    service.dispatch(
        "queue.add",
        {
            "project": project["id"],
            "prompt": "Mac-only route",
            "harness": "core",
            "provider": "openai",
            "model": "unshared",
        },
    )
    current = access.rpc(phone, "queue.list", {"project": project["id"]})
    with pytest.raises(PermissionError, match="Mac-only"):
        access.rpc(
            phone, "queue.run", {"project": project["id"], "revision": current["revision"]}, "run"
        )
    assert not service._all("SELECT id FROM jobs")
    _, no_tasks = pair(access, profile, ["read", "queue"])
    with pytest.raises(PermissionError, match="coding tasks"):
        access.rpc(
            no_tasks,
            "queue.run",
            {"project": project["id"], "revision": current["revision"]},
            "no-tasks",
        )


@pytest.mark.asyncio
async def test_attachment_endpoints_keep_auth_and_reject_other_methods(companion):
    _, project, _, profile, access = companion
    token, _ = pair(access, profile, ["read", "tasks"])
    headers = {
        "Host": ORIGIN.removeprefix("https://"),
        "Tailscale-User-Login": PRINCIPAL,
        "Authorization": "Bearer " + token,
        "Idempotency-Key": "http-image",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application(access), client=("127.0.0.1", 1234)),
        base_url=ORIGIN,
        headers=headers,
    ) as client:
        good = await client.post(
            "/v1/images",
            json={
                "method": "images.upload",
                "params": {"project": project["id"], "name": "image.png", "data": PNG},
            },
        )
        assert good.status_code == 200, good.text
        refused = await client.post("/v1/images", json={"method": "tools.start", "params": {}})
        assert refused.status_code == 400
        refused = await client.post("/v1/files", json={"method": "tasks.start", "params": {}})
        assert refused.status_code == 400
        invalid = await client.post(
            "/v1/images",
            json={"method": "images.upload", "params": {}},
            headers={"Authorization": "Bearer unknown"},
        )
        assert invalid.status_code == 403
        assert "path" not in json.dumps(good.json())


def test_checkpoint_controls_preserve_later_edits_and_git_index(companion):
    import subprocess
    from superqode.desktop_service.checkpoints import begin_task, finish_task

    service, project, root, profile, access = companion
    _, phone = pair(access, profile, ["read", "restore"])
    before = (root / "hello.txt").read_text()
    index = subprocess.check_output(["git", "-C", str(root), "diff", "--cached"])
    capture = begin_task(root, "Mobile checkpoint fixture")
    (root / "hello.txt").write_text("agent edit")
    finish_task(capture)
    state = access.rpc(phone, "checkpoints.list", {"project": project["id"]})
    assert state["can_undo"]
    (root / "hello.txt").write_text("later human edit")
    with pytest.raises(ValueError, match="changed"):
        access.rpc(
            phone,
            "checkpoints.undo",
            {"project": project["id"], "revision": state["revision"]},
            "refuse-later-edit",
        )
    assert (root / "hello.txt").read_text() == "later human edit"
    (root / "hello.txt").write_text("agent edit")
    access.rpc(
        phone, "checkpoints.undo", {"project": project["id"], "revision": state["revision"]}, "undo"
    )
    assert (root / "hello.txt").read_text() == before
    current = access.rpc(phone, "checkpoints.list", {"project": project["id"]})
    assert current["can_redo"]
    with pytest.raises(ValueError, match="Checkpoints changed"):
        access.rpc(
            phone,
            "checkpoints.redo",
            {"project": project["id"], "revision": state["revision"]},
            "stale-redo",
        )
    access.rpc(
        phone,
        "checkpoints.redo",
        {"project": project["id"], "revision": current["revision"]},
        "redo",
    )
    assert (root / "hello.txt").read_text() == "agent edit"
    assert subprocess.check_output(["git", "-C", str(root), "diff", "--cached"]) == index


def test_portable_exports_include_visible_answers_without_worker_internals(companion):
    from test_desktop_session_identity import add_run

    service, project, _, profile, access = companion
    _, phone = pair(access, profile, ["read"])
    add_run(service, project, "export-run")
    service._write(
        "UPDATE jobs SET result=? WHERE id=?",
        (
            json.dumps(
                {"summary": "visible summary", "private_reasoning": "PRIVATE_WORKER_REASONING"}
            ),
            "export-run",
        ),
    )
    for format in ["markdown", "json", "html"]:
        result = access.rpc(
            phone, "jobs.export", {"project": project["id"], "id": "export-run", "format": format}
        )
        assert "PRIVATE_WORKER_REASONING" not in result["content"]
        assert result["content"]
        if format == "json":
            assert json.loads(result["content"])["id"] == "export-run"
    with pytest.raises(ValueError, match="Markdown"):
        access.rpc(
            phone, "jobs.export", {"project": project["id"], "id": "export-run", "format": "shell"}
        )
