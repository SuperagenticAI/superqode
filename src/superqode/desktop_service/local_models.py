"""Native adapters around shared local-AI services and reviewed operation jobs."""

import json
import time

from superqode.local import workbench


def ds4_configuration(service):
    from superqode.local.servers import (
        ServerManager,
        DS4_CHECKOUT,
        DS4_DEFAULT_CTX,
        DS4_DEFAULT_KV_DIR,
        DS4_DEFAULT_KV_DISK_MB,
    )

    binary = ServerManager()._ds4_binary()
    model = DS4_CHECKOUT / "ds4flash.gguf"
    configuration = {
        "binary": str(binary) if binary else "",
        "model": str(model) if model.is_file() else "",
        "context": DS4_DEFAULT_CTX,
        "kv_disk_dir": str(DS4_DEFAULT_KV_DIR),
        "kv_disk_space_mb": DS4_DEFAULT_KV_DISK_MB,
    }
    rows = service._all(
        "SELECT plan FROM local_model_plans WHERE json_extract(plan,'$.engine')='ds4' "
        "AND json_extract(plan,'$.action')='serve' ORDER BY created DESC LIMIT 1"
    )
    if rows:
        saved = json.loads(rows[0]["plan"])
        configuration.update({key: saved[key] for key in configuration if key in saved})
    return configuration


def overview(service):
    from dataclasses import asdict
    from superqode.local.hardware import detect_hardware
    from superqode.local.inventory import inventory_models
    from superqode.local.servers import discover_gguf_models

    return {
        "hardware": asdict(detect_hardware()),
        "engines": servers(service),
        "models": [asdict(model) for model in inventory_models()],
        "gguf_files": discover_gguf_models(),
    }


def servers(service):
    from dataclasses import asdict
    from superqode.local.servers import ServerManager, _pid_alive, _pid_start
    from superqode.local.install import install_plan, NAMES

    registry = service.root / "model-servers"
    manager = ServerManager(registry_dir=registry)
    engines = []
    for engine in workbench.ENGINES:
        if engine == "ds4":
            from pathlib import Path

            config = ds4_configuration(service)
            manager = ServerManager(
                registry_dir=registry,
                ds4_binary=Path(config["binary"]) if config["binary"] else None,
            )
        ready = asdict(manager.precheck(engine))
        handle = manager._load(engine)
        owned = bool(
            handle
            and handle.pid
            and not handle.adopted
            and handle.process_start
            and _pid_start(handle.pid) == handle.process_start
        )
        if (
            handle
            and handle.pid
            and _pid_alive(handle.pid)
            and not ready["running"]
            and time.time() - handle.started_at < 180
        ):
            ready["state"] = "starting"
        engines.append(
            {
                **ready,
                "id": engine,
                "name": "DS4 · DeepSeek V4" if engine == "ds4" else NAMES[engine],
                "can_stop": owned,
                "install": {
                    "automatic": False,
                    "docs_url": "https://github.com/antirez/ds4",
                    "guidance": "Build ds4-server separately, then choose the executable and your downloaded GGUF. No installation or download is automatic.",
                }
                if engine == "ds4"
                else install_plan(engine).to_dict(),
                "cache_control": engine in {"ollama", "llama.cpp"},
            }
        )
    return engines


def prepare(service, params):
    from .hub_access import token

    plan = workbench.prepare(params, service.root / "model-servers", token=token(service))
    digest = workbench.fingerprint(plan)
    service._write(
        "INSERT OR REPLACE INTO local_model_plans VALUES(?,?,?)",
        (digest, json.dumps(plan), time.time()),
    )
    return {**plan, "id": digest, "digest": digest}


def start(service, params):
    rows = service._all("SELECT * FROM local_model_plans WHERE id=?", (params.get("plan"),))
    if not rows or time.time() - rows[0]["created"] > 1800:
        raise ValueError("Review the local operation again; its plan is missing or expired")
    plan = json.loads(rows[0]["plan"])
    if params.get("expected_digest") != workbench.fingerprint(plan):
        raise ValueError("The reviewed local plan changed")
    if plan.get("source") == "hf":
        from superqode.local.storage import cache_directory

        if plan.get("cache_dir") != str(cache_directory()):
            raise ValueError("The model storage location changed. Review the download again.")
    if plan["action"] == "verify" and plan["model"] not in available(plan["engine"])["models"]:
        raise ValueError("The selected model is not advertised by this server")
    with service.lock:
        # Model operations have a separate writer scope. A download need not
        # block editing/coding in unrelated projects.
        if plan["action"] in {"serve", "stop", "install"} and service._all(
            "SELECT id FROM jobs WHERE kind!='local' AND status IN ('running','queued','needs_approval','cancelling')"
        ):
            raise ValueError("Finish or stop agent work before changing inference servers")
        root = service.root / "local-model-workspace"
        root.mkdir(exist_ok=True, mode=0o700)
        service._write(
            "INSERT OR IGNORE INTO projects VALUES(?,?,?)", ("local-model-workspace", str(root), 0)
        )
        return service.start(
            "local-model-workspace",
            "local",
            {"local_plan": plan, "command_id": params.get("command_id")},
        )


def jobs(service, *, checks_only=False):
    rows = service._all(
        "SELECT j.id,j.title,j.status,j.result,j.updated,(SELECT payload FROM events WHERE job=j.id AND json_extract(payload,'$.type')='progress' ORDER BY seq DESC LIMIT 1) AS progress FROM jobs j WHERE kind='local' "
        + ("AND json_extract(request,'$.local_plan.action')='verify' " if checks_only else "")
        + "ORDER BY updated DESC LIMIT 30"
    )
    return [
        {
            **row,
            "result": json.loads(row["result"]) if row["result"] else None,
            "progress": json.loads(row["progress"])["data"] if row["progress"] else {},
        }
        for row in rows
    ]


def harnesses(service, project):
    from superqode.harness.catalog import list_harnesses
    from superqode.harness.backends.registry import backend_capabilities

    rows = []
    for definition in list_harnesses(root=service.project(project)):
        backend = definition.spec.runtime.backend
        supported = (
            backend in {"builtin", "pipy", "rlm", "adk", "openai-agents", "pydanticai"}
            and definition.available
            and backend_capabilities(backend).availability == "available"
        )
        rows.append(
            {
                "id": definition.id,
                "name": definition.display_name,
                "backend": backend,
                "selectable": supported,
                "note": "Accepts a local provider/model route; model tool use still needs testing."
                if supported
                else "Backend-specific local routing needs configuration/verification; not automatically rewired here.",
            }
        )
    return rows


def available(engine):
    import urllib.request
    from superqode.local.servers import SPECS

    if engine not in workbench.ENGINES:
        raise ValueError("Choose a supported local runtime")
    endpoint = f"http://127.0.0.1:{SPECS[engine].default_port}/v1"
    # Fixed loopback endpoints; never inherit a remote host from shell settings.
    with urllib.request.urlopen(endpoint + "/models", timeout=3) as response:
        payload = json.loads(response.read(2_000_000))
    models = [
        row["id"]
        for row in payload.get("data", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str) and 0 < len(row["id"]) <= 4096
    ]
    if engine == "ds4":
        from superqode.providers.local.ds4 import _contradicts_loaded_shape

        models = [
            row["id"]
            for row in payload.get("data", [])
            if isinstance(row, dict)
            and row.get("id") in models
            and not _contradicts_loaded_shape(row["id"], row.get("name"))
        ]
    return {"endpoint": endpoint, "models": models, "provider": workbench.PROVIDERS[engine]}


def use(service, params):
    project = params["project"]
    service.project(project)
    harness = next(
        (
            row
            for row in harnesses(service, project)
            if row["id"] == params.get("harness") and row["selectable"]
        ),
        None,
    )
    if not harness:
        raise ValueError("Choose a native harness with a supported local model route")
    route = available(params["engine"])
    model = params.get("model")
    if model not in route["models"] or any(word in model.lower() for word in ("embed", "rerank")):
        raise ValueError("Choose an advertised coding/chat model from this server")
    with service.lock:
        service._write(
            "INSERT OR REPLACE INTO local_model_bindings VALUES(?,?,?,?,?)",
            (project, harness["id"], route["provider"], model, route["endpoint"]),
        )
        # The native Test model action uses the no-tool harness. Bind that
        # explicit inference check to the same endpoint instead of shell defaults.
        service._write(
            "INSERT OR REPLACE INTO local_model_bindings VALUES(?,?,?,?,?)",
            (project, "no-tool", route["provider"], model, route["endpoint"]),
        )
    return {**route, "model": model, "harness": harness["id"]}


def binding(service, project, harness, provider, model):
    # Keep an explicit local model selection local when changing harnesses or
    # running the no-tool inference test. Agent-owned routes use another provider.
    return service._all(
        "SELECT endpoint FROM local_model_bindings WHERE project=? AND provider=? AND model=? ORDER BY (harness=?) DESC LIMIT 1",
        (project, provider, model, harness),
    )


def clear_binding(service, params):
    service.project(params["project"])
    with service.lock:
        if service._all(
            "SELECT id FROM jobs WHERE project=? AND status IN ('running','queued','needs_approval','cancelling')",
            (params["project"],),
        ):
            raise ValueError("Finish active project work before changing its endpoint binding")
        service._write(
            "DELETE FROM local_model_bindings WHERE project=? AND provider=? AND model=?",
            (params["project"], params["provider"], params["model"]),
        )
    return {"cleared": True}


def compatibility(service, project=None):
    from .connect_workflow import runtime_catalog

    backends = []
    for row in runtime_catalog():
        native = row["backend"] in {"builtin", "pipy", "rlm", "adk", "openai-agents", "pydanticai"}
        backends.append(
            {
                **row,
                "id": row["backend"],
                "local_route": "Native provider/model binding"
                if native
                else "Adapter-specific configuration required",
                "auto_route": native,
                "verification": "Not certified; run an explicit coding task with this harness",
                "endpoints": list(workbench.ENGINES) if native else [],
            }
        )
    return {
        "backends": backends,
        "harnesses": harnesses(service, project) if project else [],
        "checks": [
            row
            for row in jobs(service, checks_only=True)
            if (row.get("result") or {}).get("verification")
        ],
        "note": "Availability is dependency/configuration evidence. Model readiness probes inspect tool-call shapes without executing tools; they do not certify any harness, weights, tool parser or coding quality. ACP agents retain their own model selection and need an agent-specific local configuration adapter.",
    }


def save_storage(service, params):
    from superqode.local import storage

    with service.lock:
        if service._all(
            "SELECT id FROM jobs WHERE kind='local' AND status IN ('running','queued','needs_approval','cancelling')"
        ):
            raise ValueError("Finish or cancel local model operations before changing storage")
        result = storage.save(params.get("hf_cache"))
        # A review displays its exact destination. Changing it invalidates reviews.
        service._write("DELETE FROM local_model_plans WHERE json_extract(plan,'$.source')='hf'")
        return result
