"""Prepare a reviewable local-to-exo continuation without sending inference."""

import difflib
import hashlib
import json

from superqode.tools.silicon import preview as bounded_preview

from .local_runtimes import checked, validation_digest
from .turn_changes import TERMINAL, summary


def _destination(spec, profile, params):
    model = str(params.get("model") or "")
    if spec.template != "exo" or not checked(profile, model):
        raise ValueError("Run the exo tool check for this model before preparing a handoff")
    return model


def _handoff_digest(profile, project, model):
    content = json.dumps([validation_digest(profile), project, model])
    return hashlib.sha256(content.encode()).hexdigest()


def preview(service, spec, profile, params):
    model = _destination(spec, profile, params)
    project = params["project"]
    root = service.project(project)
    source = str(params.get("job") or "")
    job = service.dispatch("jobs.get", {"id": source})
    request = job.get("request") or {}
    if (
        job["project"] != project
        or job["kind"] != "task"
        or job["status"] not in TERMINAL
        or request.get("provider") != "apple-foundation"
        or request.get("interaction_mode") == "chat"
    ):
        raise ValueError("Select a finished Apple on-device coding turn in this project")
    changes = summary(service, root, source)
    rows = service._all(
        "SELECT payload FROM events WHERE job=? AND "
        "(json_extract(payload,'$.type')='answer' OR "
        "json_extract(payload,'$.data.event') IN ('model_delta','check_result')) "
        "ORDER BY seq DESC LIMIT 150",
        (source,),
    )
    chunks = []
    checks = []
    for item in reversed(rows):
        data = json.loads(item["payload"]).get("data") or {}
        if data.get("event") == "check_result":
            checks.append(data.get("payload") or {})
        else:
            chunks.append(str((data.get("payload") or data).get("text") or ""))
    objective = bounded_preview(str(request.get("prompt") or job.get("title") or ""), 1400)
    response = bounded_preview("".join(chunks).strip(), 900)
    lines = [
        "Continue this coding task using the current workspace. Review the existing changes first.",
        f"Objective: {objective}",
    ]
    if response:
        lines.append(f"Previous model response: {response}")
    for row in checks[-10:]:
        lines.append(f"Observed check: {row.get('name', 'check')} — {row.get('status', 'unknown')}")
    from .checkpoints import manager_for

    task = (
        manager_for(root)._tasks.get(changes.get("checkpoint"))
        if changes.get("available")
        else None
    )
    patch = []
    remaining = min(5000, max(0, spec.context * 2 - 2500))
    for row in changes.get("files", [])[:12]:
        if task is None or not task.finished or remaining <= 0 or row.get("binary"):
            continue
        path = row["path"]
        before = task.before.get(path)
        after = task.after[path]
        text = bounded_preview(
            "".join(
                difflib.unified_diff(
                    ((before.content if before else None) or b"")
                    .decode(errors="replace")
                    .splitlines(True),
                    (after.content or b"").decode(errors="replace").splitlines(True),
                    fromfile="before/" + path,
                    tofile="after/" + path,
                )
            ),
            remaining,
        )
        patch.append(text)
        remaining -= len(text.encode())
    if patch:
        lines.append("Patch from the completed turn:\n" + "\n".join(patch))
    return {
        "prompt": "\n\n".join(lines),
        "model": model,
        "endpoint": spec.endpoint,
        "destination": "On your network",
        "digest": _handoff_digest(profile, project, model),
    }


def start(service, spec, profile, params):
    model = _destination(spec, profile, params)
    project = params["project"]
    if params.get("digest") != _handoff_digest(profile, project, model):
        raise ValueError("The exo destination changed. Review the handoff again")
    prompt = params.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 16000:
        raise ValueError("Enter a handoff preview of up to 16 KB")
    from .local_runtimes import dispatch

    dispatch(
        service, "use", {"id": spec.id, "project": project, "model": model, "harness": "silicon"}
    )
    return service.start(
        project,
        "task",
        {
            "prompt": prompt,
            "harness": "silicon",
            "provider": "local-openai",
            "model": model,
            "interaction_mode": "code",
            "permission_mode": "ask",
            "command_id": params["command_id"],
        },
    )
