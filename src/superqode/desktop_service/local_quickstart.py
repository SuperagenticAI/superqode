"""Project-scoped, resumable local setup using the reviewed workbench jobs."""

import hashlib
import json

from . import local_models


def _key(project):
    return "local-quickstart:" + project


def _read(service, project):
    rows = service._all("SELECT value FROM settings WHERE key=?", (_key(project),))
    return json.loads(rows[0]["value"]) if rows else {}


def _save(service, project, state):
    service._write(
        "INSERT OR REPLACE INTO settings VALUES(?,?)", (_key(project), json.dumps(state))
    )


def catalog(service, project):
    from superqode.local.hardware import detect_hardware

    service.project(project)
    hardware = detect_hardware()
    engines = local_models.servers(service)
    choices = {}

    def add(engine, model, name, detail, installed):
        if any(word in model.lower() for word in ("embed", "rerank", "cloud")):
            return
        identity = hashlib.sha256((engine + "\n" + model).encode()).hexdigest()[:24]
        choices[identity] = dict(
            id=identity, engine=engine, model=model, name=name, detail=detail, installed=installed
        )

    for engine in engines:
        if engine["running"]:
            try:
                for model in local_models.available(engine["id"])["models"]:
                    add(engine["id"], model, model, "Already available · " + engine["name"], True)
            except (OSError, ValueError):
                pass
    # Keep the first setup small. These are starting choices, not quality claims.
    memory = hardware.available_memory_gb
    if memory and memory >= 8:
        suggestions = [("qwen3.5:2b", "Qwen · smaller download", "Start with a small local model.")]
        if memory >= 16:
            suggestions += [
                ("qwen3.5:9b", "Qwen · more capable", "Needs more memory than the smaller Qwen."),
                ("gemma4:e4b", "Gemma · alternative", "Google's open model family."),
            ]
        for model, name, detail in suggestions:
            identity = hashlib.sha256(("ollama\n" + model).encode()).hexdigest()[:24]
            if identity not in choices:
                add(
                    "ollama",
                    model,
                    name,
                    detail + " Download size is reported during transfer.",
                    False,
                )
    saved = _read(service, project)
    previous = saved.get("selection")
    if previous and previous["id"] not in choices:
        choices[previous["id"]] = {
            **previous,
            "installed": False,
            "detail": "Previous setup · check its server and recorded progress.",
        }
    return {
        "choices": sorted(choices.values(), key=lambda row: not row["installed"]),
        "selected": saved.get("choice", ""),
        "memory_gb": memory,
        "note": "Starting suggestions, not measured coding-quality guarantees. Context and other apps also need memory.",
    }


def prepare(service, params):
    project, choice_id = params["project"], params["choice"]
    with service.lock:
        state = _read(service, project)
        original = dict(state)
        job = service._all("SELECT * FROM jobs WHERE id=?", (state.get("job", ""),))
        if job and job[0]["status"] in {"running", "queued", "needs_approval", "cancelling"}:
            if state.get("choice") != choice_id:
                raise ValueError("Finish or cancel the current setup before choosing another model")
            return {"step": "working", "job": job[0]["id"]}
        if state.get("choice") == choice_id and job:
            row = job[0]
            result = json.loads(row["result"]) if row["result"] else {}
            passed = (result.get("verification") or {}).get("status") == "passed"
            if row["status"] != "completed" or (state.get("step") == "verify" and not passed):
                if not params.get("retry"):
                    return {
                        "step": "retry",
                        "job": row["id"],
                        "message": "Setup stopped. Review its output, then retry. Completed downloads are reused.",
                    }
                state = {"choice": choice_id}
            elif state.get("step") == "verify":
                state["verified"] = True
        else:
            state = {"choice": choice_id}

    def finish(result):
        with service.lock:
            if _read(service, project) != original:
                raise ValueError("Setup changed. Check its progress again.")
            _save(
                service,
                project,
                {**state, "selection": choice, "plan": (result.get("plan") or {}).get("id")},
            )
        return result

    choice = next(
        (row for row in catalog(service, project)["choices"] if row["id"] == choice_id), None
    )
    if not choice:
        raise ValueError("Refresh model choices; this model is no longer available here")
    engine, model = choice["engine"], choice["model"]
    status = next(row for row in local_models.servers(service) if row["id"] == engine)
    options = {"engine": engine, "model": model}
    if not status["installed"] and not status["running"]:
        if not status["install"]["automatic"]:
            return finish(
                {
                    "step": "manual",
                    "url": status["install"]["docs_url"],
                    "message": "Install "
                    + status["name"]
                    + " using its official installer, then check again. Your model choice is kept.",
                }
            )
        step = "install"
    elif not status["running"]:
        # Reuse existing model-specific configuration for single-model engines.
        if engine != "ollama":
            raise ValueError("Start this model from Advanced setup, then check again")
        step = "serve"
        options["context"] = 8192
    elif model not in local_models.available(engine)["models"]:
        if engine != "ollama":
            raise ValueError("Load the selected model in its server, then check again")
        step = "download"
        options["source"] = "ollama"
    elif state.get("verified"):
        return finish({"step": "ready", "engine": engine, "model": model})
    else:
        step = "verify"
        options["check"] = "core-read"
    plan = local_models.prepare(service, {**options, "action": step})
    return finish({"step": step, "plan": plan, "engine": engine, "model": model})


def start(service, params):
    project = params["project"]
    service.project(project)
    with service.lock:
        state = _read(service, project)
        if state.get("choice") != params["choice"]:
            raise ValueError("Review the selected model again")
        if state.get("job"):
            row = service._all("SELECT status FROM jobs WHERE id=?", (state["job"],))
            if row and row[0]["status"] in {"running", "queued", "needs_approval", "cancelling"}:
                return {"id": state["job"]}
        plans = service._all("SELECT plan FROM local_model_plans WHERE id=?", (params["plan"],))
        if not plans:
            raise ValueError("Review this step again")
        plan = json.loads(plans[0]["plan"])
        if state.get("plan") != params["plan"]:
            raise ValueError("Review the current setup step again")
        choice_id = params["choice"]
        result = local_models.start(service, params)
        _save(
            service,
            project,
            {
                "choice": choice_id,
                "selection": state["selection"],
                "step": plan["action"],
                "job": result["id"],
            },
        )
        return result
