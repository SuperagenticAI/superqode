"""Explicit companion API; never forward arbitrary desktop management calls."""

from __future__ import annotations

import json
from pathlib import Path
import time

from .remote_access import digest, text

READS = {
    "threads.list": {"project", "query", "view", "limit", "cursor"},
    "threads.get": {"project", "id"},
    "jobs.get": {"id", "after"},
    "conversations.get": {"id", "before"},
    "git.status": {"project"},
    "files.list": {"project"},
    "files.read": {"project", "path"},
    "evals.inspect": {"profile", "tasks", "split"},
    "experiments.list": {"project"},
}
WRITES = {
    "tasks.start": ("tasks", {"profile", "prompt", "parent_id", "interaction_mode"}),
    "evaluations.start": ("evaluate", {"profile", "tasks", "tasks_hash", "live", "split"}),
    "optimizations.start": (
        "optimize",
        {"profile", "tasks", "tasks_hash", "live", "max_evals", "max_cost"},
    ),
    "jobs.approve": ("approve", {"id", "request_id", "allow"}),
    "jobs.cancel": ("cancel", {"id"}),
    "jobs.steer": ("steer", {"id", "text"}),
}


def available_profiles(access, device):
    return [
        {
            **{
                k: p[k]
                for k in ("id", "name", "project", "harness", "provider", "model", "local_only")
            },
            "evaluation": p["evaluation"],
            "optimization": bool(
                p["native"]
                and not p["local_only"]
                and p["reflection_model"]
                and p["optimizer_model"]
            ),
            "enforces_controls": p["enforces_controls"],
            "permission_note": "Ask before edits and commands"
            if p["enforces_controls"]
            else "This agent manages its own permissions on the Mac",
        }
        for p in access.profiles(device)
    ]


def dispatch(access, device, method, params, key):
    service = access.service
    profiles = access.profiles(device)
    projects = {p["project"] for p in profiles}
    permissions = set(json.loads(device["permissions"]))
    if "read" not in permissions:
        raise PermissionError("This device does not have read access")
    if method == "companion.catalog":
        return {
            "protocol": 1,
            "device": {"id": device["id"], "name": device["name"], "expires": device["expires"]},
            "permissions": sorted(permissions),
            "profiles": available_profiles(access, device),
            "suites": [
                {k: p[k] for k in ("id", "name", "description", "tasks")}
                for p in service.dispatch("evals.packs", {})
            ],
            "features": {
                "tasks": True,
                "evaluations": True,
                "optimization": "Staged candidates only; adoption stays on the Mac",
                "files": "Read only",
                "terminal": False,
                "provider_setup": "On the Mac",
                "push_notifications": False,
            },
        }
    if method == "projects.list":
        return [
            {"id": p["id"], "name": p["name"]}
            for p in service.dispatch(method, {})
            if p["id"] in projects
        ]
    if method == "jobs.list":
        return [j for j in service.dispatch(method, {}) if j["project"] in projects]
    if method not in READS and method not in WRITES:
        raise PermissionError("This action is not available through the companion API")
    allowed = READS.get(method) if method in READS else WRITES[method][1]
    if not isinstance(params, dict) or set(params) - allowed:
        raise ValueError("Unsupported parameters for this companion action")
    request = dict(params)
    permission = WRITES[method][0] if method in WRITES else "read"
    if permission not in permissions:
        raise PermissionError("Allow this action in the Mac's device pairing permissions first")
    job = None
    profile = None
    if "profile" in request:
        profile = next((p for p in profiles if p["id"] == request.pop("profile")), None)
        if not profile:
            raise PermissionError("This connection was removed or is not shared with this device")
        request["project"] = profile["project"]
    if "project" in request and request["project"] not in projects:
        raise PermissionError("This project is not shared with this device")
    if "id" in request:
        identity = text(request["id"], "a job ID")
        found = service._all("SELECT project FROM jobs WHERE id=?", (identity,))
        if not found or found[0]["project"] not in projects:
            raise PermissionError("This run is not in a shared project")
        if "project" in request and request["project"] != found[0]["project"]:
            raise PermissionError("This run belongs to another project")
        job = identity
    if method == "files.read":
        relative = text(request.get("path"), "a project file path", 1000)
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Choose a relative path inside the shared project")
    if method.startswith("eval") or method == "optimizations.start":
        if not profile or not profile["evaluation"]:
            raise ValueError("Choose a native evaluation-capable connection shared by the Mac")
        suites = {p["id"] for p in service.dispatch("evals.packs", {})}
        if request.get("tasks") not in suites:
            raise ValueError("Choose a bundled suite; custom verifier setup stays on the Mac")
        if request.get("live") is True and not request.get("tasks_hash"):
            raise ValueError(
                "Review the suite and its verifier commands before starting a live run"
            )
    if method in WRITES:
        key = text(key, "an idempotency key", 128)
        signature = digest(json.dumps([method, params], sort_keys=True, separators=(",", ":")))
        previous = service._all(
            "SELECT signature,result FROM companion_commands WHERE device=? AND key=?",
            (device["id"], key),
        )
        if previous:
            if previous[0]["signature"] != signature:
                raise ValueError("This request ID was already used for another action")
            if previous[0]["result"] is None:
                raise ValueError(
                    "The earlier request has an uncertain outcome. Refresh activity before sending another request."
                )
            return json.loads(previous[0]["result"])
        if method.endswith(".start"):
            if not profile:
                raise ValueError("Choose a connection shared by the Mac")
            # Revalidate the route and local endpoint at execution time, not just pairing.
            profile = access.validate_profile(profile)
            request.update({k: profile[k] for k in ("harness", "provider", "model")})
            request.update(
                command_id=f"companion:{device['id']}:{key}",
                remote_origin={"device": device["id"], "name": device["name"]},
            )
            if method == "tasks.start":
                request["prompt"] = text(request.get("prompt"), "a prompt", 32000)
                mode = request.get("interaction_mode", "code")
                if mode not in {"code", "chat", "plan"}:
                    raise ValueError("Choose Code, Plan or Chat")
                if profile["enforces_controls"]:
                    request["permission_mode"] = "ask"
                if request.get("parent_id"):
                    parent = service._all(
                        "SELECT project FROM jobs WHERE id=?", (request["parent_id"],)
                    )
                    if not parent or parent[0]["project"] != profile["project"]:
                        raise PermissionError("Continue a conversation in the same shared project")
            elif method == "optimizations.start":
                if profile["local_only"]:
                    raise ValueError(
                        "Local-only optimization is not enabled: the optimizer needs separately verified local reflection and optimization routes"
                    )
                if not profile["reflection_model"] or not profile["optimizer_model"]:
                    raise ValueError(
                        "Configure the reflection and optimization models on the Mac first"
                    )
                request.update(
                    reflection_model=profile["reflection_model"],
                    optimizer_model=profile["optimizer_model"],
                    method="omni",
                )
                count, cost = request.get("max_evals", 4), request.get("max_cost", 1)
                if (
                    type(count) is not int
                    or not 1 <= count <= 20
                    or type(cost) not in {int, float}
                    or not 0 < cost <= 10
                ):
                    raise ValueError("Use 1 to 20 evaluations and a positive cost budget up to $10")
        # Reserve before execution: a crash must not replay a tool decision or command.
        service._write(
            "INSERT INTO companion_commands VALUES(?,?,?,NULL,?)",
            (device["id"], key, signature, time.time()),
        )
    try:
        result = service.dispatch(method, request)
    except BaseException:
        if method in WRITES:
            access._audit(device["id"], method + ":failed", request.get("project", ""), job or "")
        raise
    if method == "jobs.get":
        result["pending_request_id"] = service.pending.get(job)
        result["pending_approval"] = None
        if result["pending_request_id"]:
            pending = service._all(
                "SELECT payload FROM events WHERE job=? AND json_extract(payload,'$.type')='approval' ORDER BY seq DESC LIMIT 1",
                (job,),
            )
            if pending:
                approval = json.loads(pending[0]["payload"]).get("data", {})
                if approval.get("request_id") == result["pending_request_id"]:
                    result["pending_approval"] = approval
        capabilities = service._all(
            "SELECT payload FROM events WHERE job=? AND json_extract(payload,'$.type')='control_capabilities' ORDER BY seq DESC LIMIT 1",
            (job,),
        )
        result["control_capabilities"] = (
            json.loads(capabilities[0]["payload"]).get("data", {}) if capabilities else {}
        )
        result["remote_origin"] = result["request"].get("remote_origin")
        # Do not send worker internals, snapshots or arbitrary recorded request fields.
        result["request"] = {
            k: v
            for k, v in result["request"].items()
            if k
            in {
                "prompt",
                "provider",
                "model",
                "harness",
                "parent_id",
                "interaction_mode",
                "remote_origin",
            }
        }
    if method in WRITES:
        safe = access.clean(result)
        service._write(
            "UPDATE companion_commands SET result=? WHERE device=? AND key=?",
            (json.dumps(safe, default=str), device["id"], key),
        )
        access._audit(
            device["id"],
            method,
            request.get("project", ""),
            (result.get("id", "") if isinstance(result, dict) else "") or job or "",
        )
    return result
