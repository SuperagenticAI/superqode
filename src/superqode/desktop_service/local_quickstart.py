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

    if project:
        service.project(project)
    hardware = detect_hardware()
    engines = local_models.servers(service)
    choices = {}
    from dataclasses import asdict
    from superqode.local.context_contract import choose_contract
    from superqode.local.guardrails import build_guardrails

    def add(
        engine, model, name, detail, installed, *, preset="running", context=None, metadata=None
    ):
        if engine not in {e["id"] for e in engines} or engine not in {"ollama", "lmstudio"}:
            return
        if any(word in model.lower() for word in ("embed", "rerank", "cloud")):
            return
        identity = hashlib.sha256((engine + "\n" + model).encode()).hexdigest()[:24]
        if identity in choices and not installed:
            return
        weights = (metadata or {}).get("size_bytes")
        contract = choose_contract(
            model,
            hardware,
            provider=engine,
            context=context,
            weights_gb=weights / 1024**3 if weights else None,
            metadata=metadata,
        )
        choices[identity] = dict(
            id=identity,
            engine=engine,
            model=model,
            name=name,
            detail=detail,
            installed=installed,
            preset=preset,
            suggested_context=contract.context,
            max_tokens=contract.max_tokens,
            kv_cache=contract.kv_cache,
            fit=contract.fit,
            metadata=metadata,
        )

    for engine in engines:
        if engine["running"]:
            try:
                available = local_models.available(engine["id"])
                for model in available["models"]:
                    metadata = next(
                        (m for m in available.get("metadata", []) if m.get("key") == model), None
                    )
                    add(
                        engine["id"],
                        model,
                        model,
                        "Already available · " + engine["name"],
                        True,
                        metadata=metadata,
                    )
            except (OSError, ValueError):
                pass
    try:
        from superqode.local.inventory import installed_chat_models

        for row in installed_chat_models():
            label = "Ollama" if row["engine"] == "ollama" else "LM Studio"
            add(
                row["engine"],
                row["model"],
                row.get("name") or row["model"],
                "Already installed on this Mac · " + label,
                True,
                metadata=row.get("metadata"),
            )
    except (OSError, ValueError):
        pass
    memory = hardware.available_memory_gb
    from superqode.local.starter_registry import suggestions

    for row in suggestions(hardware):
        engine, model = row["engine"], row["model"]
        name = "Ollama" if engine == "ollama" else "LM Studio"
        detail = (
            "Tested in a local five-task run for this engine and Mac memory tier."
            if row["status"] == "tested"
            else "Catalog-verified suggestion, not a measured quality guarantee."
        )
        add(
            engine,
            model,
            name + " · " + model,
            detail,
            False,
            preset="suggested",
            context=row["context"],
        )
        identity = hashlib.sha256((engine + "\n" + model).encode()).hexdigest()[:24]
        if identity in choices:
            choices[identity]["evaluation_status"] = row["status"]
    from superqode.local.presets import setup_presets

    presets = setup_presets(list(choices.values()), hardware)
    preset_ids = {p["choice"]["id"] for p in presets if p["choice"]}
    saved = _read(service, project) if project else {}
    previous = saved.get("selection")
    if previous and previous["id"] not in choices and previous["id"] not in preset_ids:
        choices[previous["id"]] = {
            **{key: value for key, value in previous.items() if key != "evaluation_status"},
            "installed": False,
            "preset": "previous",
            "detail": "Previous setup · check its server and recorded progress.",
        }
    return {
        "choices": sorted(choices.values(), key=lambda row: not row["installed"]),
        "setup_presets": presets,
        "capacity": _capacity(hardware),
        "starter": _starter(choices.values(), presets),
        "selected": saved.get("choice", ""),
        "memory_gb": memory,
        "hardware": asdict(hardware),
        "engines": [e for e in engines if e["id"] in {"ollama", "lmstudio"}],
        "other_engines": [e for e in engines if e["id"] not in {"ollama", "lmstudio"}],
        "guardrails": build_guardrails(hardware).to_dict(),
        "note": "Starting suggestions, not measured coding-quality guarantees. Context and other apps also need memory.",
    }


def _capacity(hardware):
    """A plain estimate of the model size this Mac runs comfortably.

    It mirrors the fit budget in ``context_contract``: about 70% of unified
    memory on Apple silicon (85% elsewhere), keeping 10% spare plus headroom,
    buffers and a modest context. It is guidance, not a measurement.
    """
    memory = hardware.available_memory_gb
    if not memory:
        return {
            "memory_gb": None,
            "comfortable_gb": None,
            "summary": "Memory was not reported. Start with a small model marked Fits.",
        }
    budget = float(memory) * (0.70 if hardware.is_apple_silicon else 0.85)
    headroom = max(1.0, float(memory) * 0.03)
    comfortable = max(0, int(budget * 0.90 - headroom - 1.5))
    summary = (
        f"Comfortable with models up to about {comfortable} GB."
        if comfortable >= 2
        else "Memory is limited. Small models work best on this Mac."
    )
    return {"memory_gb": memory, "comfortable_gb": comfortable, "summary": summary}


def _starter(choices, presets):
    """One suggested starter for this memory tier, preferring the Balanced preset."""
    balanced = next((p["choice"] for p in presets if p["id"] == "balanced" and p["choice"]), None)
    if balanced:
        return balanced
    fitting = [
        row
        for row in choices
        if row.get("preset") == "suggested" and (row.get("fit") or {}).get("rating") == "Fits"
    ]
    return fitting[0] if fitting else None


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
                        "verification": result.get("verification", {}),
                    }
                state = {"choice": choice_id}
            elif state.get("step") == "verify":
                verification = result.get("verification") or {}
                # Older Core-only checks must run the new readiness checks too.
                state["verified"] = (verification.get("readiness") or {}).get("status") in {
                    "ready",
                    "warning",
                }
                state["verification"] = verification
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

    available = catalog(service, project)
    options = available["choices"] + [
        p["choice"] for p in available["setup_presets"] if p["choice"]
    ]
    choice = next((row for row in options if row["id"] == choice_id), None)
    if not choice:
        raise ValueError("Refresh model choices; this model is no longer available here")
    if choice.get("setup_preset"):
        from superqode.local.context_contract import choose_contract
        from superqode.local.hardware import detect_hardware

        current = choose_contract(
            choice["model"],
            detect_hardware(),
            provider=choice["engine"],
            context=choice["suggested_context"],
            metadata=choice.get("metadata"),
            weights_gb=(choice.get("fit") or {}).get("weights_gb"),
        )
        if current.fit["rating"] != "Fits" or current.context != choice["suggested_context"]:
            raise ValueError(
                "This preset no longer fits its reviewed context. Refresh and choose a fitting setup preset."
            )
    engine, model = choice["engine"], choice["model"]
    status = next(row for row in local_models.servers(service) if row["id"] == engine)
    options = {"engine": engine, "model": model, "context": choice.get("suggested_context") or 8192}
    # LM Studio's installed desktop app does not necessarily bootstrap lms.
    # Offer the consented official headless installer when the CLI is missing.
    if engine == "lmstudio" and not status["running"]:
        from superqode.local.install import runtime_executable
        import shutil

        if not shutil.which(runtime_executable("lms")):
            status = {**status, "installed": False}
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
        if engine not in {"ollama", "lmstudio"}:
            raise ValueError("Start this model from Advanced setup, then check again")
        step = "serve"
        options["context"] = choice.get("suggested_context") or 8192
        if engine == "lmstudio":
            options["model"] = ""
    else:
        available = local_models.available(engine)
        runtime_model = model
        if engine == "lmstudio" and model not in available["models"]:
            # Catalog aliases resolve to the exact downloaded artifact key.
            needle = model.split("/")[-1].lower()
            matches = [m for m in available["models"] if needle in m.lower()]
            if len(matches) == 1:
                runtime_model = matches[0]
            elif len(matches) > 1:
                raise ValueError(
                    "Multiple artifacts match. Choose the downloaded model explicitly."
                )
        model = runtime_model
        options["model"] = model
        if model not in available["models"]:
            # An installed library or on-disk model is never a download.
            if choice.get("installed"):
                if engine == "lmstudio":
                    step = "load"
                    options["context"] = choice.get("suggested_context") or 8192
                else:
                    return finish(
                        {
                            "step": "manual",
                            "engine": engine,
                            "model": model,
                            "message": "This model is already installed. Start Ollama if it is stopped, then choose the model again. SuperQode will not download it.",
                        }
                    )
            else:
                step = "download"
                options["source"] = engine
        elif engine == "lmstudio" and model not in available.get("loaded_models", []):
            step = "load"
            options["context"] = choice.get("suggested_context") or 8192
        elif state.get("verified"):
            return finish(
                {
                    "step": "ready",
                    "engine": engine,
                    "model": model,
                    "verification": state.get("verification", {}),
                }
            )
        else:
            step = "verify"
            options["check"] = "quickstart"
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
        from superqode.local.context_contract import ContextContract, choose_contract, save_contract

        selection = state["selection"]
        result = local_models.start(service, params)
        contract = (
            ContextContract(**plan["contract"])
            if plan.get("contract")
            else choose_contract(
                selection["model"],
                provider=selection["engine"],
                context=selection.get("suggested_context"),
                metadata=selection.get("metadata"),
                weights_gb=(selection.get("fit") or {}).get("weights_gb"),
            )
        )
        save_contract(selection["engine"], plan.get("model") or selection["model"], contract)
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
