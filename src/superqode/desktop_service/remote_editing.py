"""Project-scoped mobile editing, attachments and explicitly reviewed recovery."""

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time

from .remote_access import text
from .remote_project import context_paths, project_path

READS = {"conversations.share": {"project", "id"}, "jobs.export": {"project", "id", "format"}}
WRITES = {
    "files.write": ("edit", {"project", "path", "text", "digest"}),
    "files.create": ("edit", {"project", "path", "text"}),
    "images.upload": ("tasks", {"project", "name", "data"}),
    "images.remove": ("tasks", {"project", "id"}),
    "queue.add": ("queue", {"profile", "prompt", "context_files", "image_ids", "interaction_mode"}),
    **{
        f"queue.{name}": ("queue", {"project", "id", "direction", "revision"})
        for name in ("run", "pause", "move", "remove", "retry")
    },
    **{
        f"checkpoints.{name}": ("restore", {"project", "id", "revision"})
        for name in ("undo", "redo", "restore")
    },
}
METHODS = set(READS) | set(WRITES)


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def image_table(service):
    service._write(
        "CREATE TABLE IF NOT EXISTS companion_images(id TEXT PRIMARY KEY, project TEXT, device TEXT, created REAL)"
    )


def validate_images(service, device, project, identities):
    if not isinstance(identities, list) or len(identities) > 4:
        raise ValueError("Attach up to four images")
    image_table(service)
    for identity in identities:
        if not isinstance(identity, str):
            raise ValueError("Choose an uploaded image")
        if not service._all(
            "SELECT id FROM companion_images WHERE id=? AND project=? AND device=?",
            (identity, project, device["id"]),
        ):
            raise PermissionError("This image is not attached to this device and shared project")
    from .images import resolve_images

    resolve_images(service.root, identities)


def prepare(access, device, method, request, profile, permissions):
    service = access.service
    if method in METHODS and "project" not in request:
        raise ValueError("Choose a shared project")
    if method in {"files.read", "files.write", "files.create"}:
        request["path"] = project_path(request.get("path"))
    if "image_ids" in request:
        validate_images(service, device, request["project"], request["image_ids"])
    if method == "images.upload":
        name = text(request.get("name"), "an image filename", 200)
        if Path(name).name != name or Path(name).suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
        }:
            raise ValueError("Choose a PNG, JPEG, GIF or WebP image")
        data = request.get("data")
        if not isinstance(data, str) or len(data) > 5_592_408:
            raise ValueError("Choose an image no larger than 4 MB")
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise ValueError("The image data is invalid") from exc
        if not raw or len(raw) > 4 * 1024 * 1024:
            raise ValueError("Choose an image no larger than 4 MB")
        from superqode.image_input import load_image

        # Validate before reserving a command. Temporary files are private and removed.
        with tempfile.TemporaryDirectory(prefix="superqode-image-") as folder:
            source = Path(folder) / name
            source.write_bytes(raw)
            load_image(source)
    if method == "queue.run" and "tasks" not in permissions:
        raise PermissionError("Allow coding tasks before starting queued work")
    if method == "queue.add":
        if "tasks" not in permissions or not profile:
            raise PermissionError(
                "Allow coding tasks and share a connection before adding queued work"
            )
        profile = access.validate_profile(profile)
        request.update({k: profile[k] for k in ("harness", "provider", "model")})
        request["prompt"] = text(request.get("prompt"), "a prompt", 32000)
        mode = request.get("interaction_mode", "code")
        if mode not in {"code", "plan", "chat"} or (
            mode == "chat" and (not profile["native"] or profile["provider"].lower() == "agent")
        ):
            raise ValueError("Choose a supported Code, Plan or Chat mode")
        if profile["enforces_controls"]:
            request["permission_mode"] = "ask"
        if "context_files" in request:
            request["context_files"] = context_paths(request["context_files"])


def execute(access, device, method, request, profiles):
    service = access.service
    if method not in METHODS:
        return service.dispatch(method, request)
    if method == "jobs.export":
        from .remote_export import export_run

        return export_run(access, request)
    if method == "images.remove":
        with service.lock:
            validate_images(service, device, request["project"], [request["id"]])
            # Existing recorded jobs own immutable snapshots; do not delete their evidence.
            rows = service._all("SELECT request FROM jobs WHERE project=?", (request["project"],))
            queued = service.dispatch("queue.list", {"project": request["project"]})["items"]
            if any(
                request["id"] in json.loads(row["request"]).get("image_ids", []) for row in rows
            ) or any(request["id"] in row["request"].get("image_ids", []) for row in queued):
                raise ValueError(
                    "This image belongs to a recorded or queued run and cannot be removed"
                )
            for target in (service.root / "images").glob(request["id"] + ".*"):
                target.unlink()
            service._write("DELETE FROM companion_images WHERE id=?", (request["id"],))
            return {"ok": True, "project": request["project"]}
    if method == "images.upload":
        image_table(service)
        existing = service._all(
            "SELECT id FROM companion_images WHERE device=? AND created>?",
            (device["id"], time.time() - 86400),
        )
        if len(existing) >= 100:
            raise ValueError(
                "This device has uploaded 100 images in 24 hours. Try again after the daily limit resets"
            )
        from .images import stage_image

        with tempfile.TemporaryDirectory(prefix="superqode-image-") as folder:
            source = Path(folder) / request["name"]
            source.write_bytes(base64.b64decode(request["data"], validate=True))
            result = stage_image(service.root, str(source))
        service._write(
            "INSERT INTO companion_images VALUES(?,?,?,?)",
            (result["id"], request["project"], device["id"], time.time()),
        )
        return {
            **{k: result[k] for k in ("id", "name", "mime_type", "sha256", "bytes")},
            "project": request["project"],
        }
    if method.startswith("queue.") and method != "queue.add":
        with service.lock:
            current = service.dispatch("queue.list", {"project": request["project"]})
            if request.get("revision") != revision(current):
                raise ValueError("The queue changed. Refresh and review it before trying again")
            if method in {"queue.run", "queue.retry"}:
                # A queue grant never grants unshared routes or Mac-only control overrides.
                for item in current["items"]:
                    if item["state"] != "pending" and not (
                        method == "queue.retry" and item["id"] == request.get("id")
                    ):
                        continue
                    row = item["request"]
                    profile = next(
                        (
                            p
                            for p in profiles
                            if all(p[k] == row.get(k) for k in ("harness", "provider", "model"))
                        ),
                        None,
                    )
                    if (
                        not profile
                        or row.get("acp_options")
                        or row.get("permission_mode", "ask") != "ask"
                    ):
                        raise PermissionError(
                            "The queue includes a Mac-only connection or permission override. Review it on the Mac"
                        )
                    access.validate_profile(profile)
                    if row.get("image_ids"):
                        validate_images(service, device, request["project"], row["image_ids"])
            if method == "queue.move" and request.get("direction") not in {"up", "down"}:
                raise ValueError("Choose Up or Down")
            return service.dispatch(method, request)
    if method.startswith("checkpoints."):
        with service.lock:
            current = service.dispatch("checkpoints.list", {"project": request["project"]})
            if request.get("revision") != revision(current):
                raise ValueError("Checkpoints changed. Refresh and review before restoring files")
            return service.dispatch(method, request)
    try:
        result = service.dispatch(method, request)
    except FileExistsError as exc:
        raise ValueError("This file already exists. Open and review it before editing") from exc
    return {**result, "project": request["project"]} if method == "queue.add" else result
