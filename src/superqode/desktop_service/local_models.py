"""Native adapters around shared local-AI services and reviewed operation jobs."""

import json
import threading
import time
import uuid

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

    def inspect(engine):
        manager = ServerManager(registry_dir=registry)
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
        return {
            **ready,
            "id": engine,
            "name": "DS4 · DeepSeek V4" if engine == "ds4" else NAMES[engine],
            "can_stop": owned
            or bool(engine == "lmstudio" and ready["running"] and handle and not handle.adopted),
            "install": {
                "automatic": False,
                "docs_url": "https://github.com/antirez/ds4",
                "guidance": "Build ds4-server separately, then choose the executable and your downloaded GGUF. No installation or download is automatic.",
            }
            if engine == "ds4"
            else install_plan(engine).to_dict(),
            "cache_control": engine in {"ollama", "llama.cpp"},
        }

    # These checks are independent. A slow or unavailable engine must not add
    # another serial timeout before the developer can see the engines in use.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(workbench.ENGINES)) as pool:
        return list(pool.map(inspect, workbench.ENGINES))


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
        if plan["action"] in {"serve", "stop", "unload", "load", "install"} and service._all(
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


# Backends that run an Ollama or LM Studio model themselves. ACP attachments
# are intentionally absent: those agents own their own model setup.
_LOCAL_MODEL_BACKENDS = {
    "builtin",
    "pipy",
    "rlm",
    "adk",
    "openai-agents",
    "pydanticai",
    "codegem",
    "strands",
    "deepagents",
    "deepseek-harness",
    "tau",
    "rlm-code",
}
# Missing backends the app can install. The value is the pyproject extra, or
# "strands" for that harness's separate runtime.
_INSTALLABLE = {
    "adk": "adk",
    "openai-agents": "openai-agents",
    "pydanticai": "pydanticai",
    "deepagents": "deepagents",
    "deepseek-harness": "deepseek-harness",
    "tau": "tau",
    "rlm-code": "rlm-code",
    "strands": "strands",
}
_install_lock = threading.Lock()
_installs: dict[str, dict] = {}
_install_ids: dict[str, str] = {}


def harnesses(service, project):
    from superqode.harness.catalog import list_harnesses
    from superqode.harness.backends.registry import backend_capabilities

    rows = []
    for definition in list_harnesses(root=service.project(project)):
        if definition.id == "no-tool" or definition.source == "built-in-template":
            continue
        if definition.category == "model-preset":
            continue
        backend = definition.spec.runtime.backend
        if backend not in _LOCAL_MODEL_BACKENDS:
            continue
        supported = (
            definition.available and backend_capabilities(backend).availability == "available"
        )
        extra = "" if supported else _INSTALLABLE.get(backend, "")
        if not supported and not extra:
            continue
        rows.append(
            {
                "id": definition.id,
                "name": definition.display_name,
                "description": definition.description,
                "backend": backend,
                "group": "superqode",
                "selectable": supported,
                "install_extra": extra,
                "note": (
                    "Runs this model on your Mac."
                    if supported
                    else "One install, then it can use a model on this Mac."
                ),
            }
        )
    return rows


def install(service, params):
    """Start a background install for a harness whose package is missing."""
    project = params["project"]
    harness_id = str(params.get("harness") or "")
    row = next((item for item in harnesses(service, project) if item["id"] == harness_id), None)
    if row is None:
        raise ValueError("Choose a harness that can use a local model")
    if row["selectable"]:
        return {"status": "completed", "harness": harness_id}
    if not row["install_extra"]:
        raise ValueError("This harness cannot be installed from the app")
    with _install_lock:
        current = _installs.get(harness_id)
        if current and current["status"] == "running":
            return {"id": current["id"], "status": "running", "harness": harness_id}
        job_id = uuid.uuid4().hex
        _installs[harness_id] = {
            "id": job_id,
            "status": "running",
            "harness": harness_id,
            "progress": f"Installing {row['name']} and checking that it loads…",
            "error": "",
        }
        _install_ids[job_id] = harness_id
    thread = threading.Thread(
        target=_run_install,
        args=(service, harness_id, job_id, row["install_extra"]),
        daemon=True,
    )
    thread.start()
    return {"id": job_id, "status": "running", "harness": harness_id}


def install_status(service, params):
    job_id = str(params.get("id") or "")
    with _install_lock:
        harness_id = _install_ids.get(job_id)
        if harness_id is None or harness_id not in _installs:
            raise ValueError("That install is no longer running")
        return dict(_installs[harness_id])


_warm_lock = threading.Lock()
_warms: dict[str, dict] = {}


def warm(service, params):
    """Preload a connected local model so the first prompt does not pay load time."""
    endpoint = _loopback_endpoint(params.get("endpoint"))
    model = str(params.get("model") or "").strip()
    if not model or len(model) > 4096:
        raise ValueError("Choose a local model")
    engine = str(params.get("engine") or "")
    job_id = uuid.uuid4().hex
    with _warm_lock:
        _warms[job_id] = {
            "id": job_id,
            "status": "running",
            "progress": "Warming the model…",
            "error": "",
        }
    threading.Thread(
        target=_run_warm,
        args=(job_id, endpoint, model, engine),
        daemon=True,
    ).start()
    return {"id": job_id, "status": "running"}


def warm_status(service, params):
    job_id = str(params.get("id") or "")
    with _warm_lock:
        row = _warms.get(job_id)
        if row is None:
            raise ValueError("That warmup is no longer running")
        return dict(row)


def _run_warm(job_id, endpoint, model, engine):
    try:
        from superqode.local.bench import run_bench

        extra = {"think": False} if engine == "ollama" else None
        result = run_bench(
            endpoint,
            model,
            prompt="Reply with exactly: ok",
            max_tokens=8,
            extra=extra,
        )
        if not result.ok:
            raise RuntimeError(result.error or "The model did not respond.")
    except Exception as exc:
        message = str(exc).strip() or "The model did not finish warming up."
        _finish_warm(job_id, "failed", message[-500:])
        return
    _finish_warm(job_id, "completed", "")


def _finish_warm(job_id, status, error):
    with _warm_lock:
        row = _warms.get(job_id)
        if row is None:
            return
        row["status"] = status
        row["error"] = error
        row["progress"] = "" if status != "running" else row["progress"]


def _loopback_endpoint(value) -> str:
    import urllib.parse

    endpoint = str(value or "").strip()
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Warmup only runs against a local model")
    if parsed.port is None:
        raise ValueError("Choose a local model endpoint")
    return endpoint.rstrip("/")


def _run_install(service, harness_id, job_id, extra):
    try:
        if extra == "strands":
            _install_strands(service)
        elif extra:
            from .app_setup import install_extra

            install_extra(service.root, extra)
        else:
            raise ValueError("This harness cannot be installed from the app")
    except Exception as exc:
        _finish_install(harness_id, job_id, "failed", _plain_install_error(exc))
        return
    _finish_install(harness_id, job_id, "completed", "")


def _install_strands(service):
    import subprocess

    from superqode.harness.strands_setup import setup_runtime

    from .app_setup import ensure_uv

    ensure_uv(service.root / "bin")
    try:
        setup_runtime(install=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(_plain_install_error(exc)) from exc
    from superqode.harness.backends.strands import strands_installation_status

    ready, issue = strands_installation_status()
    if not ready:
        raise RuntimeError(issue or "Strands installed, but it does not load.")


def _finish_install(harness_id, job_id, status, error):
    with _install_lock:
        current = _installs.get(harness_id)
        if not current or current["id"] != job_id:
            return
        current["status"] = status
        current["error"] = error
        current["progress"] = ""


def _plain_install_error(exc) -> str:
    text = str(exc).strip() or "The install did not finish."
    for phrase in (
        "Install uv first, then run `superqode harness strands setup`.",
        "Run `superqode harness strands setup`, then `superqode harness strands doctor`.",
        "Strands runtime not found. Run `superqode harness strands setup`.",
    ):
        text = text.replace(phrase, "The install did not finish.")
    return text[-500:]


def installed(service):
    """Chat models already installed for Ollama or LM Studio, plus engine status."""
    from superqode.local.inventory import installed_chat_models

    status = {row["id"]: row for row in servers(service)}
    models = []
    for row in installed_chat_models():
        engine = status.get(row["engine"], {})
        models.append(
            {
                **{key: value for key, value in row.items() if key != "metadata"},
                "server_running": bool(engine.get("running")),
                "server_installed": bool(engine.get("installed") or engine.get("running")),
            }
        )
    return {
        "models": models,
        "engines": [status[name] for name in ("ollama", "lmstudio") if name in status],
    }


def available(engine):
    import urllib.request
    from superqode.local.servers import SPECS

    if engine not in workbench.ENGINES:
        raise ValueError("Choose a supported local runtime")
    endpoint = f"http://127.0.0.1:{SPECS[engine].default_port}/v1"
    if engine == "lmstudio":
        from superqode.local.inventory import lmstudio_advertised_models

        rows = lmstudio_advertised_models()
        return {
            "endpoint": endpoint,
            "models": [r["model"] for r in rows],
            "loaded_models": [r["model"] for r in rows if r.get("loaded")],
            "metadata": [r.get("metadata", {}) for r in rows],
            "provider": "lmstudio",
        }
    if engine == "ollama":
        from superqode.local.inventory import _chat_model, ollama_advertised_models

        # /api/tags is the installed library the terminal lists. /v1/models can
        # be empty or unavailable while those models are still on disk.
        listed = ollama_advertised_models()
        library = [row["model"] for row in listed]
        loaded = [row["model"] for row in listed if row.get("loaded")]
        openai_ids = []
        try:
            with urllib.request.urlopen(endpoint + "/models", timeout=3) as response:
                payload = json.loads(response.read(2_000_000))
            openai_ids = [
                row["id"]
                for row in payload.get("data", [])
                if isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and _chat_model(row["id"])
            ]
        except (OSError, ValueError, json.JSONDecodeError):
            if not library:
                raise
        models = list(dict.fromkeys([*library, *openai_ids]))
        return {
            "endpoint": endpoint,
            "models": models,
            "loaded_models": loaded,
            "provider": "ollama",
        }
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
    if str(params.get("harness") or "").startswith("attach:"):
        raise ValueError("Choose a harness that runs the local model itself")
    harness = next(
        (
            row
            for row in harnesses(service, project)
            if row["id"] == params.get("harness") and row["selectable"]
        ),
        None,
    )
    if not harness:
        raise ValueError("Choose a harness that can use this local model")
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
