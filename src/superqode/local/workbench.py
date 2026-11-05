"""Shared local-AI workbench contracts for native UI and terminal clients.

Search and preparation never transfer weights or run installers. Execution uses
an immutable reviewed plan, exact Hub revision/files and existing local services.
"""

from __future__ import annotations

from dataclasses import asdict
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import time

from .hardware import detect_hardware
from .install import install_plan, runtime_executable
from .matrix import estimate_model_memory_gb, memory_fit_phrase, search_models
from .servers import ServerManager, SPECS
from .options import cache_options

ENGINES = ("ollama", "lmstudio", "mlx", "llama.cpp", "ds4")
PROVIDERS = {
    "ollama": "ollama",
    "lmstudio": "lmstudio",
    "mlx": "mlx",
    "llama.cpp": "llamacpp",
    "ds4": "ds4",
}


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def transfer_bytes(repo, revision, files, *, cache_dir=None):
    """Read-only cache lookup, without Hub requests or weight transfers."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return None
    missing = 0
    for row in files:
        if row["bytes"] is None:
            return None
        cached = try_to_load_from_cache(
            repo, row["name"], revision=revision, **({"cache_dir": cache_dir} if cache_dir else {})
        )
        if (
            not isinstance(cached, str)
            or not Path(cached).is_file()
            or Path(cached).stat().st_size != row["bytes"]
        ):
            missing += row["bytes"]
    return missing


def download_disk_free(source, *, cache_dir=None):
    if source == "hf":
        from .storage import cache_directory

        path = Path(cache_dir) if cache_dir else cache_directory()
    else:
        path = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama/models").expanduser()
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def fit(label, *, size_bytes=None):
    hardware = detect_hardware()
    memory = hardware.available_memory_gb
    estimate = size_bytes / 1024**3 if size_bytes else estimate_model_memory_gb(label)
    return {
        "estimate_gb": estimate,
        "memory_gb": memory,
        "verdict": memory_fit_phrase(estimate, memory),
        "likely_fits": bool(estimate and memory and estimate <= memory * 0.6),
        "note": "Weight estimate only; runtime buffers, KV cache, other apps and context need additional memory. This is not a measured compatibility test.",
    }


def search(query, source="recommended", kind="gguf", *, token=None):
    if (
        not isinstance(query, str)
        or len(query) > 160
        or source not in {"recommended", "hf", "lmstudio"}
        or kind not in {"gguf", "mlx"}
    ):
        raise ValueError("Choose a model source/format and a search under 160 characters")
    if source == "recommended":
        rows = []
        hardware = detect_hardware()
        for hit in search_models(query, tier=hardware.tier, inventory=[]):
            for engine, command in hit.commands:
                parts = shlex.split(command)
                if len(parts) == 3 and parts[:2] == ["ollama", "pull"] and _ollama_id(parts[2]):
                    rows.append(
                        {
                            "id": parts[2],
                            "name": hit.name,
                            "source": "ollama",
                            "format": "ollama",
                            "role": hit.role,
                            "engines": ["ollama"],
                            "fit": fit(hit.name),
                            "origin": "Shared TUI recommendation catalog; availability is checked when pulling.",
                        }
                    )
                elif len(parts) >= 3 and parts[:2] == ["hf", "download"]:
                    try:
                        repo = _repo(parts[2])
                    except ValueError:
                        continue
                    lower = repo.lower()
                    artifact = "gguf" if "gguf" in lower else "mlx" if "mlx" in lower else "weights"
                    engines = (
                        ["mlx"]
                        if artifact == "mlx"
                        else ["llama.cpp", "ollama", "lmstudio"]
                        if artifact == "gguf"
                        else []
                    )
                    rows.append(
                        {
                            "id": repo,
                            "name": hit.name,
                            "source": "hf",
                            "format": artifact,
                            "role": hit.role,
                            "engines": engines,
                            "fit": {
                                "estimate_gb": None,
                                "likely_fits": False,
                                "verdict": "Choose an exact artifact to check download size and memory",
                            },
                            "origin": "Shared TUI catalog · Hugging Face. Original weights may need a GGUF or MLX conversion.",
                            "docs_url": "https://huggingface.co/" + repo,
                        }
                    )
                elif parts == ["superqode", "providers", "ds4", "server"]:
                    rows.append(
                        {
                            "id": "ds4:deepseek-v4-flash",
                            "name": hit.name,
                            "source": "ds4",
                            "format": "gguf",
                            "role": hit.role,
                            "engines": ["ds4"],
                            "manual_setup": True,
                            "fit": {
                                "likely_fits": False,
                                "estimate_gb": None,
                                "verdict": "Choose your exact GGUF and inspect its size before starting",
                            },
                            "origin": "DS4 route · requires an existing ds4-server build and compatible DeepSeek GGUF. No automatic download.",
                            "docs_url": "https://github.com/antirez/ds4",
                        }
                    )
        unique = {}
        for row in rows:
            previous = unique.get(row["id"])
            if previous is None or (row["role"] == "main" and previous["role"] != "main"):
                unique[row["id"]] = row
        return list(unique.values())
    from superqode.providers.huggingface.fetch import search_hub

    if source == "lmstudio":
        kind = "gguf"

    return [
        {
            "id": model.id,
            "name": model.id,
            "source": "hf",
            "format": kind,
            "engines": ["mlx"] if kind == "mlx" else ["llama.cpp", "ollama", "lmstudio"],
            "downloads": model.downloads,
            "gated": model.gated,
            "fit": fit(model.id),
            "origin": "Hugging Face catalog"
            + (" · LM Studio-compatible GGUF artifacts" if source == "lmstudio" else ""),
        }
        for model in search_hub(
            query,
            kind="gguf" if source == "lmstudio" else kind,
            limit=24,
            **({"token": token} if token else {}),
        )
    ]


def _ollama_id(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,180}", value)
        and not any(part in {".", ".."} for part in value.split("/"))
    )


def _repo(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}", value
        )
        or ".." in value
    ):
        raise ValueError("Choose a valid Hugging Face publisher/repository")
    return value


def manifest(repo, *, token=None):
    from huggingface_hub import HfApi

    repo = _repo(repo)
    info = HfApi(**({"token": token} if token else {})).model_info(repo, files_metadata=True)
    revision = str(info.sha or "")
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ValueError("The model's immutable revision is unavailable. Retry its metadata.")
    files = []
    for item in info.siblings or []:
        name = item.rfilename
        parts = PurePosixPath(name).parts
        if (
            not parts
            or name.startswith("/")
            or any(part in {".", ".."} for part in parts)
            or not re.fullmatch(r"[A-Za-z0-9_./@+ -]+", name)
        ):
            continue
        size = getattr(item, "size", None)
        files.append({"name": name, "bytes": size if type(size) is int and size >= 0 else None})
    return {"repo": repo, "revision": revision, "files": files, "gated": bool(info.gated)}


def gguf_group(files, selected):
    names = {row["name"] for row in files if row["name"].lower().endswith(".gguf")}
    if selected not in names:
        raise ValueError("Choose an advertised GGUF file")
    split = re.fullmatch(r"(.*)-(\d{5})-of-(\d{5})\.gguf", selected, re.IGNORECASE)
    if not split:
        return [selected]
    count = int(split[3])
    if not 1 <= count <= 128:
        raise ValueError("Unsupported GGUF shard count")
    group = [f"{split[1]}-{index:05d}-of-{count:05d}.gguf" for index in range(1, count + 1)]
    if not all(name in names for name in group):
        raise ValueError("The selected quantization is missing GGUF shards")
    return group


def prepare(params, registry_dir, *, token=None):
    action = params.get("action")
    engine = params.get("engine", "ollama")
    if engine not in ENGINES or action not in {"download", "serve", "stop", "install", "verify"}:
        raise ValueError("Choose a supported local runtime and action")
    if engine == "ds4" and action in {"download", "install"}:
        raise ValueError(
            "Set up ds4-server separately, then choose its executable and downloaded GGUF in Configure & start."
        )
    plan = {"action": action, "engine": engine, "provider": PROVIDERS[engine]}
    manager = ServerManager(registry_dir=Path(registry_dir))
    if action == "verify":
        model = params.get("model")
        if (
            not isinstance(model, str)
            or not 0 < len(model) <= 4096
            or any(ord(c) < 32 for c in model)
        ):
            raise ValueError("Choose a model advertised by this local server")
        check = params.get("check", "readiness")
        if check not in {"readiness", "core-read", "quickstart"}:
            raise ValueError("Choose model readiness probes or the Core read-tool check")
        plan.update(
            model=model,
            endpoint=f"http://127.0.0.1:{SPECS[engine].default_port}/v1",
            check=check,
            title=f"Check local model · {model}",
            command="Run shared local readiness probes (chat, tool-call shapes, patch format and context recall)",
            note="Sends several bounded prompts to the selected server. Tool calls are inspected, not executed; no project files are read or edited. This checks the model endpoint, not a complete harness coding workflow.",
        )
        if check == "core-read":
            plan.update(
                title=f"Core read-tool check · {model}",
                command="Execute a bounded Core read-only profile against generated verification.txt",
                note="Sends up to three model turns and executes the Core read tool in a disposable directory. No project files, writes, shell, MCP or delegation. Checks actual Core tool use, not a full coding task or every harness.",
            )
        if check == "quickstart":
            plan.update(
                title=f"Local coding readiness · {model}",
                command="Probe loaded context and tool-call shapes, then execute Core read on generated data",
                note="Sends bounded local prompts for context recall and tool-call shapes, then up to three Core read-tool turns. No project files are read or edited. Unknown context and model limits are reported rather than assumed.",
            )
    elif action == "install":
        recipe = install_plan(engine)
        if engine == "mlx" and manager.is_running("mlx"):
            raise ValueError("Stop the MLX server before changing its runtime environment")
        if not recipe.steps:
            raise ValueError(recipe.guidance + " " + recipe.docs_url)
        plan.update(
            steps=recipe.steps,
            title=f"Install {recipe.title}",
            guidance=recipe.guidance,
            docs_url=recipe.docs_url,
            command=recipe.command,
        )
    elif action == "download":
        model = params.get("model", "")
        if params.get("source") == "ollama":
            if engine != "ollama" or not _ollama_id(model):
                raise ValueError("Choose a valid Ollama model tag")
            # Remote/cloud tags cannot satisfy an offline/local coding promise.
            if "cloud" in model.lower():
                raise ValueError("Choose downloadable local weights rather than a cloud model")
            plan.update(
                source="ollama",
                model=model,
                title=f"Pull {model}",
                files=[],
                total_bytes=None,
                download_bytes=None,
                fit=fit(model),
                command=shlex.join([runtime_executable("ollama"), "pull", model]),
            )
        else:
            from .storage import cache_directory

            data = manifest(model, **({"token": token} if token else {}))
            cache = str(cache_directory())
            if engine == "mlx":
                from superqode.providers.huggingface.fetch import MLX_ALLOW_PATTERNS

                names = [
                    row["name"]
                    for row in data["files"]
                    if any(fnmatch.fnmatch(row["name"], pattern) for pattern in MLX_ALLOW_PATTERNS)
                    and not row["name"].endswith(".py")
                ]
                if (
                    not any(name.endswith(".safetensors") for name in names)
                    or "config.json" not in names
                ):
                    raise ValueError(
                        "Choose an MLX repository with configuration and safetensors weights"
                    )
                if not (model.startswith("mlx-community/") or params.get("format") == "mlx"):
                    raise ValueError("Choose the MLX format explicitly")
            else:
                names = gguf_group(data["files"], params.get("filename"))
            files = [row for row in data["files"] if row["name"] in names]
            total = (
                sum(row["bytes"] for row in files)
                if all(row["bytes"] is not None for row in files)
                else None
            )
            needed = transfer_bytes(model, data["revision"], files, cache_dir=cache)
            plan.update(
                source="hf",
                cache_dir=cache,
                model=model,
                revision=data["revision"],
                files=files,
                total_bytes=total,
                download_bytes=needed if needed is not None else total,
                transfer_exact=needed is not None,
                gated=data["gated"],
                title=f"Download {model}",
                fit=fit(model + " " + str(params.get("filename") or ""), size_bytes=total),
                command="Download exact reviewed files at revision " + data["revision"],
            )
    elif action == "serve":
        model = str(params.get("model") or "").strip()
        if len(model) > 4096 or model.startswith("-") or any(char in model for char in "\n\r\x00"):
            raise ValueError("Choose a valid local model identifier/path")
        context = params.get("context", 16384)
        cache = params.get("kv_cache", "auto")
        if (
            type(context) is not int
            or not 512 <= context <= 262144
            or cache not in {"auto", "f16", "q8_0", "q4_0"}
        ):
            raise ValueError(
                "Choose a context between 512 and 262144 tokens and a supported KV cache type"
            )
        if engine in {"mlx", "lmstudio", "ds4"} and cache != "auto":
            raise ValueError(
                "This runtime's KV cache is controlled by its own loader; choose Automatic"
            )
        if engine == "llama.cpp" and (
            not Path(model).is_file() or Path(model).suffix.lower() != ".gguf"
        ):
            raise ValueError("Choose an existing GGUF file")
        if engine == "mlx" and not Path(model).is_dir():
            raise ValueError("Download the MLX snapshot first and choose its local directory")
        extra, env = cache_options(engine, cache)
        if engine == "ds4":
            from .servers import DS4_DEFAULT_KV_DIR, DS4_DEFAULT_KV_DISK_MB

            binary = str(params.get("binary") or manager._ds4_binary() or "").strip()
            if not binary or any(ord(c) < 32 for c in binary):
                raise ValueError("Choose an existing ds4-server executable")
            executable = Path(binary).expanduser().resolve()
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise ValueError("Choose an existing ds4-server executable")
            weights = Path(model).expanduser().resolve()
            if not model or not weights.is_file() or weights.suffix.lower() != ".gguf":
                raise ValueError("Choose an existing downloaded DS4 GGUF file")
            raw_directory = params.get("kv_disk_dir", str(DS4_DEFAULT_KV_DIR))
            if (
                not isinstance(raw_directory, str)
                or not raw_directory.strip()
                or len(raw_directory) > 4096
                or any(ord(c) < 32 for c in raw_directory)
            ):
                raise ValueError("Choose a disk-KV cache directory")
            directory = Path(raw_directory).expanduser().resolve()
            if directory.exists() and not directory.is_dir():
                raise ValueError("The disk-KV cache location must be a directory")
            disk_mb = params.get("kv_disk_space_mb", DS4_DEFAULT_KV_DISK_MB)
            if type(disk_mb) is not int or not 512 <= disk_mb <= 1048576:
                raise ValueError("Choose a disk-KV limit between 512 and 1048576 MB")
            model = str(weights)
            manager = ServerManager(registry_dir=Path(registry_dir), ds4_binary=executable)
            extra = ["--kv-disk-dir", str(directory), "--kv-disk-space-mb", str(disk_mb)]
            plan.update(
                binary=str(executable), kv_disk_dir=str(directory), kv_disk_space_mb=disk_mb
            )
        if engine == "lmstudio":
            extra += ["--bind", "127.0.0.1"]
        argv, environment, _ = manager.build_command(
            engine,
            host="127.0.0.1",
            port=SPECS[engine].default_port,
            model=model or None,
            ctx=context,
            extra_args=extra,
        )
        plan.update(
            model=model,
            context=context,
            kv_cache=cache,
            extra_args=extra,
            environment={**environment, **env},
            command=shlex.join(argv),
            title=f"Start {engine}",
            fit=fit(model),
            note="Already-running servers are adopted without changing their settings. MLX ignores requested context; LM Studio applies it at load. No weights are downloaded by server start.",
        )
        if engine == "ds4":
            plan["fit"] = fit(model, size_bytes=Path(model).stat().st_size)
            plan["note"] = (
                "Starts your selected DS4 executable with downloaded weights on 127.0.0.1:8000. Disk-KV cache uses the chosen directory and limit. Existing servers keep their settings; stop them in their owning app before reconfiguring. No build, weight download or inference is started by reviewing this plan."
            )
    else:
        handle = manager._load(engine)
        if not handle or handle.adopted or handle.pid is None or not handle.process_start:
            raise ValueError(
                "This app does not own a stoppable process for this server. Manage it in its owning app or terminal."
            )
        plan.update(
            title=f"Stop app-started {engine}",
            pid=handle.pid,
            started_at=handle.started_at,
            process_start=handle.process_start,
        )
    disk = (
        download_disk_free(
            plan["source"], **({"cache_dir": plan["cache_dir"]} if plan.get("cache_dir") else {})
        )
        if action == "download"
        else shutil.disk_usage(Path.home()).free
    )
    plan.update(disk_free_bytes=disk, created=time.time())
    return plan


def run(plan, registry_dir, emit, *, owner_job=None):
    from superqode.providers.huggingface import fetch

    manager = ServerManager(registry_dir=Path(registry_dir), ds4_binary=plan.get("binary"))
    action, engine = plan["action"], plan["engine"]
    if engine == "ollama":
        os.environ["OLLAMA_HOST"] = "http://127.0.0.1:11434"
        os.environ["OLLAMA_API_BASE"] = "http://127.0.0.1:11434"
    emit("stage", {"message": plan["title"]})
    if action == "verify":
        from .bench import list_endpoint_models
        from .smoke import run_smoke

        if plan["model"] not in list_endpoint_models(plan["endpoint"]):
            raise ValueError(
                "The server no longer advertises this model. Load it and review the check again."
            )
        if plan.get("check") in {"core-read", "quickstart"}:
            import asyncio
            from .coding_check import run as run_coding_check

            readiness = None
            if plan.get("check") == "quickstart":
                emit(
                    "stage",
                    {
                        "message": "Checking loaded context, tool-call shapes and context recall on generated prompts."
                    },
                )
                readiness = run_smoke(
                    engine=engine, endpoint=plan["endpoint"], model=plan["model"], max_tokens=1024
                ).to_dict()
            report = asyncio.run(
                run_coding_check(
                    plan["provider"],
                    plan["model"],
                    plan["endpoint"],
                    Path(registry_dir).parent,
                    emit,
                )
            )
            if readiness is not None:
                from superqode.providers.local.context_probe import probe_base_url

                # A cold Ollama model may report loaded context only after a turn.
                context = asyncio.run(
                    probe_base_url(plan["endpoint"].removesuffix("/v1"), plan["model"])
                )
                if context:
                    readiness["context_window"], readiness["context_source"] = context
                    readiness["warnings"] = [
                        w
                        for w in readiness.get("warnings", [])
                        if not w.startswith("Loaded context window was not detected;")
                    ]
                    readiness["checks"] = [c for c in readiness["checks"] if c["name"] != "context"]
                    readiness["checks"].append(
                        {
                            "name": "context",
                            "ok": True,
                            "detail": f"{context[0]} tokens from {context[1]}",
                        }
                    )
                report["readiness"] = readiness
                if readiness["status"] == "failed":
                    report["status"] = "failed"
        else:
            report = run_smoke(
                engine=engine, endpoint=plan["endpoint"], model=plan["model"], max_tokens=1024
            ).to_dict()
        result = {
            "verification": report,
            "scope": "local-coding-readiness"
            if plan.get("check") == "quickstart"
            else "core-read-tool"
            if plan.get("check") == "core-read"
            else "model-endpoint-readiness",
            "provider": plan["provider"],
            "model": plan["model"],
            "checked_at": time.time(),
            "harness_certified": False,
        }
    elif action == "install":
        for argv in plan["steps"]:
            _command(argv, emit)
        if engine == "mlx":
            from .install import managed_mlx_installed

            if not managed_mlx_installed(refresh=True):
                raise ValueError(
                    "MLX packages could not be imported in the isolated runtime. Inspect setup output and retry."
                )
        result = {"installed": manager.is_installed(engine)}
        if not result["installed"]:
            raise ValueError(
                "Installer exited but the runtime is not available. Refresh setup diagnostics."
            )
    elif action == "stop":
        handle = manager._load(engine)
        if (
            not handle
            or handle.pid != plan["pid"]
            or handle.started_at != plan["started_at"]
            or handle.adopted
            or handle.process_start != plan["process_start"]
        ):
            raise ValueError("Server ownership changed. Review Stop again.")
        if not manager.stop(engine):
            raise ValueError(
                "The owned server is unavailable or its process changed. Refresh before retrying."
            )
        result = {"stopped": True}
    elif action == "serve":
        # Avoid changing process-wide environment in the shared engine: this runs
        # in the isolated, cancellable local-operation worker.
        os.environ.update(plan["environment"])
        was_running = manager.is_running(engine)
        try:
            handle = manager.start(
                engine,
                model=None if engine == "lmstudio" else plan["model"] or None,
                ctx=plan["context"],
                extra_args=plan["extra_args"],
                wait=True,
                timeout=180,
                allow_download=False,
                owner_job=owner_job,
            )
        except Exception:
            current = manager._load(engine)
            if owner_job and current and current.owner_job == owner_job and current.process_start:
                manager.stop(engine)
            raise
        if engine == "lmstudio" and plan["model"]:
            _command(
                [
                    runtime_executable("lms"),
                    "load",
                    plan["model"],
                    "--context-length",
                    str(plan["context"]),
                    "-y",
                ],
                emit,
            )
        result = {
            "server": handle.to_dict(),
            "serve_model": plan["model"],
            "provider": plan["provider"],
            "ready": manager.is_running(engine),
            "notes": handle.notes
            + (["Existing server settings were kept, including KV cache."] if was_running else []),
        }
    elif plan["source"] == "ollama":
        if not manager.is_running("ollama"):
            raise ValueError("Start the Ollama server before pulling weights")
        _pull_ollama(plan["model"], emit)
        result = {"downloaded": True, "serve_model": plan["model"], "provider": "ollama"}
    else:
        storage = {"cache_dir": plan["cache_dir"]} if plan.get("cache_dir") else {}
        needed = transfer_bytes(plan["model"], plan["revision"], plan["files"], **storage)
        if plan.get("transfer_exact") and needed is not None and needed > plan["download_bytes"]:
            raise ValueError("Cached files changed since review. Review the download size again.")
        total = needed if needed is not None else plan["download_bytes"]
        if total and download_disk_free("hf", **storage) < total + 1024**3:
            raise ValueError("Not enough free disk for the reviewed files plus 1 GiB headroom")
        files = [row["name"] for row in plan["files"]]
        emit(
            "stage",
            {
                "message": "Downloading pinned files; Hugging Face reuses completed cache entries on retry."
            },
        )
        paths = []
        if engine == "mlx":
            path = fetch.download_repo(
                plan["model"],
                allow_patterns=files,
                revision=plan["revision"],
                **storage,
                progress_callback=lambda data: emit("progress", data),
            )
            serve_model = str(path)
        else:
            for index, filename in enumerate(files):
                emit("stage", {"message": f"File {index + 1}/{len(files)}: {filename}"})
                paths.append(
                    fetch.download_file(
                        plan["model"],
                        filename,
                        revision=plan["revision"],
                        **storage,
                        progress_callback=lambda data: emit("progress", data),
                    )
                )
            path = paths[0]
            serve_model = str(path)
            if engine == "ollama":
                import asyncio
                from superqode.providers.huggingface.downloader import get_hf_downloader

                serve_model = (
                    "superqode-" + fingerprint([plan["model"], plan["revision"], files])[:12]
                )
                emit("stage", {"message": f"Downloaded to {path}; registering as {serve_model}"})
                if not asyncio.run(get_hf_downloader().register_with_ollama(path, serve_model)):
                    raise ValueError(
                        f"Weights are cached at {path}, but Ollama registration failed. Start Ollama and retry."
                    )
            elif engine == "lmstudio":
                for path in paths:
                    _command(
                        [
                            runtime_executable("lms"),
                            "import",
                            str(path),
                            "--symbolic-link",
                            "--user-repo",
                            plan["model"],
                            "-y",
                        ],
                        emit,
                    )
                serve_model = plan["model"] + "/" + Path(files[0]).name
        result = {
            "downloaded": True,
            "path": str(path),
            "serve_model": serve_model,
            "provider": plan["provider"],
            "revision": plan["revision"],
            "files": files,
        }
    emit("result", result)
    return result


def _command(argv, emit):
    process = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    while raw := os.read(process.stdout.fileno(), 4000):
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw.decode(errors="replace")).replace(
            "\r", "\n"
        )
        emit("output", {"text": text})
    if process.wait():
        raise ValueError("The local operation failed. Inspect its recorded output.")


def _pull_ollama(model, emit):
    from urllib.request import Request, urlopen

    request = Request(
        "http://127.0.0.1:11434/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    success = False
    with urlopen(request, timeout=60) as response:
        while raw := response.readline(65537):
            if len(raw) > 65536:
                raise ValueError("Ollama returned an oversized progress record")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Ollama returned invalid download progress")
            if data.get("error"):
                raise ValueError(str(data["error"])[:1000])
            label = str(data.get("status") or "Downloading")[:200]
            if type(data.get("completed")) is int and type(data.get("total")) is int:
                emit(
                    "progress",
                    {
                        "completed": data["completed"],
                        "total": data["total"],
                        "unit": "B",
                        "label": label,
                    },
                )
            else:
                emit("stage", {"message": label})
            if data.get("status") == "success":
                success = True
    if not success:
        raise ValueError(
            "The Ollama download ended without success. Inspect its status before retrying."
        )
