"""Reviewed handoffs of a finished coding turn to another inference target.

A target kind is an adapter with ``targets``, ``preview`` and ``start``. Target ids
are ``"<kind>:<id>"``. Only exo clusters are offered today; another kind plugs in by
adding an adapter to ``ADAPTERS``. Nothing is sent until the user reviews the
preview and chooses Send.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
from urllib.parse import urlsplit

from superqode.local import runtimes
from superqode.tools.silicon import preview as bounded_preview

from . import local_runtimes
from .turn_changes import TERMINAL, summary

LIVE = ("running", "needs_approval", "queued", "cancelling")
FALLBACK_HARNESS = "core"


def _harnesses(service, project):
    from .local_models import harnesses

    return [
        row
        for row in harnesses(service, project)
        if row["selectable"] and row["backend"] in {"builtin", "pipy", "rlm"}
    ]


def source(service, project, job):
    """Whether this turn can be handed off, and the harness the new run will use."""
    service.project(project)
    blocked = {"ready": False, "job": job, "harness": "", "harness_name": ""}
    if not job:
        return {**blocked, "reason": "Select a finished coding turn in this conversation first."}
    try:
        row = service.dispatch("jobs.get", {"id": job})
    except (KeyError, ValueError):
        return {**blocked, "reason": "This turn is no longer available."}
    request = row.get("request") or {}
    if row.get("project") != project:
        return {**blocked, "reason": "This turn belongs to another project. Open that project."}
    if row.get("kind") != "task":
        return {**blocked, "reason": "Select a coding turn. Checks and setup runs cannot be sent."}
    if row.get("status") not in TERMINAL:
        return {**blocked, "reason": "Wait for this turn to finish, then send it."}
    if request.get("interaction_mode") == "chat":
        return {**blocked, "reason": "This is a chat turn. Send a finished coding turn instead."}
    if service._all(
        "SELECT id FROM jobs WHERE project=? AND status IN (?,?,?,?)", (project, *LIVE)
    ):
        return {**blocked, "reason": "Finish the current run in this project first."}
    rows = _harnesses(service, project)
    wanted = str(request.get("harness") or "")
    chosen = next((r for r in rows if r["id"] == wanted), None) or next(
        (r for r in rows if r["id"] == FALLBACK_HARNESS), None
    )
    if chosen is None:
        return {**blocked, "reason": "No local coding harness is available in this project."}
    return {
        "ready": True,
        "reason": "",
        "job": job,
        "harness": chosen["id"],
        "harness_name": chosen.get("name") or chosen["id"],
        "kept_harness": chosen["id"] == wanted,
        "source_harness": wanted,
    }


def turn_prompt(service, project, job, budget):
    """The editable objective, response excerpt, checks and patch from a finished turn."""
    root = service.project(project)
    row = service.dispatch("jobs.get", {"id": job})
    request = row.get("request") or {}
    changes = summary(service, root, job)
    events = service._all(
        "SELECT payload FROM events WHERE job=? AND "
        "(json_extract(payload,'$.type')='answer' OR "
        "json_extract(payload,'$.data.event') IN ('model_delta','check_result')) "
        "ORDER BY seq DESC LIMIT 150",
        (job,),
    )
    chunks = []
    checks = []
    for item in reversed(events):
        data = json.loads(item["payload"]).get("data") or {}
        if data.get("event") == "check_result":
            checks.append(data.get("payload") or {})
        else:
            chunks.append(str((data.get("payload") or data).get("text") or ""))
    objective = bounded_preview(str(request.get("prompt") or row.get("title") or ""), 1400)
    response = bounded_preview("".join(chunks).strip(), 900)
    lines = [
        "Continue this coding task using the current workspace. Review the existing changes first.",
        f"Objective: {objective}",
    ]
    if response:
        lines.append(f"Previous model response: {response}")
    for check in checks[-10:]:
        lines.append(
            f"Observed check: {check.get('name', 'check')} ({check.get('status', 'unknown')})"
        )
    from .checkpoints import manager_for

    task = (
        manager_for(root)._tasks.get(changes.get("checkpoint"))
        if changes.get("available")
        else None
    )
    patch = []
    remaining = budget
    for item in changes.get("files", [])[:12]:
        if task is None or not task.finished or remaining <= 0 or item.get("binary"):
            continue
        path = item["path"]
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
    return "\n\n".join(lines)


def _digest(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


class ExoTargets:
    """A saved exo cluster profile. Inference runs on your network; tools stay on this Mac."""

    kind = "exo"

    def _profiles(self, service):
        return [row for row in local_runtimes.profiles(service) if row.get("template") == "exo"][:8]

    def _profile(self, service, identity):
        profile = local_runtimes.read(service, identity)
        spec = runtimes.validate(profile)
        if spec.template != "exo":
            raise ValueError("Choose a saved exo cluster profile")
        return profile, spec

    async def _probe(self, service, profile):
        spec = runtimes.validate(profile)
        try:
            catalog = await runtimes.model_catalog(spec, local_runtimes.key(service, spec.id))
        except ValueError as exc:
            return spec, [], str(exc)
        except Exception:
            return spec, [], "exo did not answer. Start exo on this Mac, then try again."
        if catalog["cluster_error"]:
            return spec, [], catalog["cluster_error"]
        return spec, catalog["models"], ""

    def _row(self, profile, spec, running, error):
        url = urlsplit(spec.endpoint)
        checked = [m for m in running if local_runtimes.checked(profile, m["id"])]
        reason = error
        if not reason and not running:
            reason = "No model is running in exo. Start one in Local AI → exo cluster."
        elif not reason and not checked:
            reason = "Run the tool check for a running model in Local AI → exo cluster."
        return {
            "id": f"{self.kind}:{spec.id}",
            "kind": self.kind,
            "title": f"{spec.name} ({url.netloc})",
            "detail": "On your network. Tools and file changes stay on this Mac.",
            "endpoint": spec.endpoint,
            "available": not reason,
            "reason": reason,
            "models": [
                {"id": m["id"], "title": m["id"], "context": m.get("context")} for m in checked
            ],
        }

    def targets(self, service):
        profiles = self._profiles(service)

        async def probe_all():
            return await asyncio.gather(*(self._probe(service, p) for p in profiles))

        results = asyncio.run(probe_all()) if profiles else []
        return [
            self._row(profile, spec, running, error)
            for profile, (spec, running, error) in zip(profiles, results)
        ]

    def _ready(self, service, identity, model):
        profile, spec = self._profile(service, identity)
        _, running, error = asyncio.run(self._probe(service, profile))
        row = self._row(profile, spec, running, error)
        if not row["available"]:
            raise ValueError(row["reason"])
        models = [m["id"] for m in row["models"]]
        model = model or models[0]
        if model not in models:
            raise ValueError("Choose a running exo model that passed the tool check")
        return profile, spec, row, model

    def preview(self, service, identity, params, origin):
        profile, spec, row, model = self._ready(service, identity, params.get("model"))
        budget = min(5000, max(0, spec.context * 2 - 2500))
        return {
            "target": row["id"],
            "title": row["title"],
            "detail": row["detail"],
            "endpoint": spec.endpoint,
            "destination": "On your network",
            "models": row["models"],
            "model": model,
            "prompt": turn_prompt(service, params["project"], origin["job"], budget),
            "digest": _digest(
                local_runtimes.validation_digest(profile),
                params["project"],
                origin["job"],
                origin["harness"],
            ),
        }

    def start(self, service, identity, params, origin):
        profile, spec, _row, model = self._ready(service, identity, params.get("model"))
        project = params["project"]
        expected = _digest(
            local_runtimes.validation_digest(profile), project, origin["job"], origin["harness"]
        )
        if params.get("digest") != expected:
            raise ValueError("The destination or turn changed. Review the handoff again")
        local_runtimes.dispatch(
            service,
            "use",
            {"id": spec.id, "project": project, "model": model, "harness": origin["harness"]},
        )
        return service.start(
            project,
            "task",
            {
                "prompt": params["prompt"],
                "harness": origin["harness"],
                "provider": "local-openai",
                "model": model,
                "interaction_mode": "code",
                "permission_mode": "ask",
                "command_id": params["command_id"],
            },
        )


ADAPTERS = {adapter.kind: adapter for adapter in (ExoTargets(),)}


def _adapter(target):
    kind, _, identity = str(target or "").partition(":")
    if kind not in ADAPTERS or not identity:
        raise ValueError("Choose a handoff target from the Send to menu")
    return ADAPTERS[kind], identity


def _origin(service, params):
    origin = source(service, str(params.get("project") or ""), str(params.get("job") or ""))
    if not origin["ready"]:
        raise ValueError(origin["reason"])
    return origin


def dispatch(service, action, params):
    if action == "targets":
        project = str(params.get("project") or "")
        origin = source(service, project, str(params.get("job") or ""))
        rows = [row for adapter in ADAPTERS.values() for row in adapter.targets(service)]
        return {"source": origin, "targets": rows}
    if action == "preview":
        origin = _origin(service, params)
        adapter, identity = _adapter(params.get("target"))
        return {
            **adapter.preview(service, identity, params, origin),
            "harness": origin["harness"],
            "harness_name": origin["harness_name"],
            "kept_harness": origin["kept_harness"],
        }
    if action == "start":
        prompt = params.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 16000:
            raise ValueError("Enter a handoff preview of up to 16 KB")
        if not params.get("command_id"):
            raise ValueError("Missing command id for this handoff")
        origin = _origin(service, params)
        adapter, identity = _adapter(params.get("target"))
        return adapter.start(service, identity, params, origin)
    raise ValueError("Unknown handoff action")
