"""Advanced, project-scoped harness launches. No newcomer or global config writes."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from types import MappingProxyType
import urllib.request

from superqode.local.context_contract import choose_contract, memory_fit, requested_context
from superqode.local.hardware import detect_hardware
from superqode.local.model_metadata import read_metadata

PREFIX = "local-harness:"
ENDPOINTS = {
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
}
HARNESSES = {
    "superqode": ("SuperQode harness", "", ""),
    "opencode": (
        "OpenCode (ACP, version 1.19.5+)",
        "opencode",
        "https://github.com/anomalyco/opencode/releases/tag/v1.19.5",
    ),
    "goose": (
        "Goose (ACP, version 1.58.0+)",
        "goose",
        "https://github.com/aaif-goose/goose/releases/tag/v1.58.0",
    ),
}


# Documented local-model support AND a reviewed launch adapter are both required.
# A generic ACP descriptor, installed binary or saved profile never grants access.
# See docs/integrations/local-harness-support.md for the full evidence audit.
DOCUMENTED_LOCAL_SUPPORT = MappingProxyType(
    {
        "superqode": ("https://github.com/SuperagenticAI/superqode/blob/main/README.md",),
        "opencode": (
            "https://github.com/anomalyco/opencode/blob/v1.19.5/packages/web/src/content/docs/providers.mdx",
            "https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/acp.ts",
            "https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/config/config.ts",
        ),
        "goose": (
            "https://github.com/aaif-goose/goose/blob/v1.58.0/documentation/docs/getting-started/providers.md",
            "https://github.com/aaif-goose/goose/blob/v1.58.0/documentation/docs/guides/environment-variables.md",
            "https://github.com/aaif-goose/goose/blob/v1.58.0/crates/goose/src/providers/ollama_def.rs",
            "https://github.com/aaif-goose/goose/blob/v1.58.0/crates/goose-providers/src/declarative/definitions/lmstudio.json",
        ),
    }
)
VISIBLE_STATUSES = frozenset({"Configured", "Not installed"})
# Reviewed stable release floors, not claims about the vendors' oldest support.
ADAPTER_VERSION_FLOORS = MappingProxyType({"opencode": (1, 19, 5), "goose": (1, 58, 0)})


def _allowed(identity):
    return identity in DOCUMENTED_LOCAL_SUPPORT and identity in HARNESSES


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _get(url):
    # Fixed loopback endpoints only, with no proxy, redirect, auth or caller URL.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=2) as response:
        value = json.loads(response.read(4_000_000))
        if not isinstance(value, dict):
            raise ValueError("The local server returned an invalid response")
        return value


def installed_harness(identity):
    if not _allowed(identity):
        raise ValueError("This harness is not supported by the Advanced local launcher")
    name, binary, url = HARNESSES[identity]
    path = shutil.which(binary) if binary else "builtin"
    status = "Configured" if path else "Not installed"
    reason, version = "", ""
    if identity in ADAPTER_VERSION_FLOORS and path:
        try:
            result = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=3, check=False
            )
            version = result.stdout.strip()[:120]
            parsed = re.fullmatch(rf"(?:{identity}(?:\s+version)?\s+)?(\d+)\.(\d+)\.(\d+)", version)
            floor = ADAPTER_VERSION_FLOORS[identity]
            detected = tuple(map(int, parsed.groups())) if parsed else ()
            if result.returncode or not detected or detected[0] != floor[0] or detected < floor:
                status = "Unavailable"
                minimum = ".".join(map(str, floor))
                reason = f"This adapter requires a stable {name} build at least {minimum}."
        except (OSError, subprocess.TimeoutExpired):
            status = "Unavailable"
            reason = f"Could not verify this {name} version."
    return dict(
        id=identity,
        name=name,
        binary=path or "",
        status=status,
        reason=reason,
        install_url=url,
        version=version,
        local_support="documented",
        source_urls=list(DOCUMENTED_LOCAL_SUPPORT[identity]),
    )


def running_models(engine):
    if engine not in ENDPOINTS:
        raise ValueError("Choose Ollama or LM Studio")
    base = ENDPOINTS[engine].removesuffix("/v1")
    if engine == "ollama":
        entries = _get(base + "/api/ps").get("models", [])
        return [
            dict(
                model=row.get("name") or row.get("model"),
                actual_context=row.get("context_length"),
                metadata={},
            )
            for row in entries
            if isinstance(row, dict) and (row.get("name") or row.get("model"))
        ]
    entries = _get(base + "/api/v1/models").get("models", [])
    rows = []
    for row in entries:
        if not isinstance(row, dict) or row.get("type") == "embedding":
            continue
        for instance in row.get("loaded_instances") or []:
            # Requests must name the actual loaded identifier, not an unloaded catalog alias.
            if not isinstance(instance, dict):
                continue
            model = instance.get("id")
            if model:
                rows.append(
                    dict(
                        model=model,
                        artifact=row.get("key", model),
                        actual_context=(instance.get("config") or {}).get("context_length"),
                        metadata=row,
                    )
                )
    return rows


def model_contract(engine, row):
    model = row["model"]
    actual = row.get("actual_context")
    if type(actual) is not int or not 512 <= actual <= 2_000_000:
        raise ValueError(
            "The server did not report a loaded context. Reload with an explicit context first."
        )
    hardware = detect_hardware()
    artifact = row.get("artifact", model)
    metadata = {**read_metadata(engine, artifact), **row.get("metadata", {})}
    size = metadata.get("size_bytes") or metadata.get("size")
    weights = size / 1024**3 if type(size) in {int, float} and size > 0 else None
    contract = choose_contract(
        artifact,
        hardware,
        provider=engine,
        context=min(actual, requested_context(engine, artifact)),
        metadata=metadata,
        weights_gb=weights,
        kv_cache="f16",
    )
    # A running model already allocates its loaded KV window. Do not rate it
    # against a smaller request budget or assume a quantized cache was enabled.
    fit = memory_fit(
        artifact,
        hardware.available_memory_gb,
        actual,
        metadata=metadata,
        weights_gb=weights,
        kv_cache="f16",
        apple=hardware.is_apple_silicon,
    )
    return {
        **asdict(contract),
        "fit": fit,
        "actual_context": actual,
        "requested_context": requested_context(engine, artifact),
    }


def generate_config(identity, engine, model, contract):
    """Pure generators, never shell strings or changes to user configuration files."""
    if not _allowed(identity):
        raise ValueError("This harness has no documented and wired local adapter")
    endpoint = ENDPOINTS[engine]
    context, output = contract["context"], contract["max_tokens"]
    if identity == "superqode":
        return {
            "env": {
                "OLLAMA_HOST" if engine == "ollama" else "LMSTUDIO_HOST": endpoint.removesuffix(
                    "/v1"
                )
                if engine == "ollama"
                else endpoint
            },
            "model": model,
            "tools": "native",
            "argv": [],
        }
    if identity == "opencode":
        selected = "sq-local/" + model
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": selected,
            "small_model": selected,
            "enabled_providers": ["sq-local"],
            "autoupdate": False,
            "share": "disabled",
            "permission": "ask",
            "provider": {
                "sq-local": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "SuperQode local",
                    "options": {"baseURL": endpoint, "apiKey": "local-only"},
                    "models": {
                        model: {
                            "name": model,
                            "tool_call": True,
                            "limit": {"context": context, "output": output},
                        }
                    },
                }
            },
        }
        return {
            "env": {
                "OPENCODE_CONFIG_CONTENT": json.dumps(config),
                "OPENCODE_DISABLE_AUTOUPDATE": "true",
                "OPENCODE_DISABLE_MODELS_FETCH": "true",
            },
            "model": selected,
            "tools": "native; permissions ask",
            "argv": ["acp"],
        }
    if identity == "goose":
        # Use the official local providers, not an OpenAI-model-name heuristic.
        # Ollama applies num_ctx/num_predict; LM Studio uses its chat endpoint
        # and its provider-specific max_tokens mapping in upstream Goose.
        return {
            "env": {
                "GOOSE_PROVIDER": engine,
                "GOOSE_MODEL": model,
                "OLLAMA_HOST" if engine == "ollama" else "LMSTUDIO_HOST": endpoint.removesuffix(
                    "/v1"
                ),
                **({"GOOSE_INPUT_LIMIT": str(context)} if engine == "ollama" else {}),
                "GOOSE_CONTEXT_LIMIT": str(context),
                "GOOSE_MAX_TOKENS": str(output),
                "GOOSE_SUBAGENT_PROVIDER": engine,
                "GOOSE_SUBAGENT_MODEL": model,
                "GOOSE_MODE": "approve",
                "GOOSE_TOOLSHIM": "false",
                "GOOSE_DISABLE_SESSION_NAMING": "true",
                "GOOSE_TELEMETRY_ENABLED": "false",
            },
            "model": model,
            "tools": "native; approve mode; no tool shim",
            "argv": ["acp"],
        }
    raise ValueError("This harness has no documented and wired local adapter")


def preflight(service, params):
    project, identity = params["project"], params["harness"]
    root = service.project(project)
    harness = installed_harness(identity)
    engine, model = params["engine"], params["model"]
    if (
        engine not in ENDPOINTS
        or not isinstance(model, str)
        or not model
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,511}", model)
    ):
        raise ValueError("Choose a running Ollama or LM Studio model")
    result = {
        "harness": identity,
        "engine": engine,
        "model": model,
        "endpoint": ENDPOINTS[engine],
        "status": harness["status"],
        "reason": harness["reason"],
        "install_url": harness["install_url"],
        "ready": False,
    }
    if harness["status"] != "Configured":
        return result
    try:
        row = next((r for r in running_models(engine) if r["model"] == model), None)
        if row is None:
            raise ValueError("This model is not loaded. Load it in Local AI, then refresh.")
        # Verify that this exact identifier is advertised by the compatible API.
        offered = _get(ENDPOINTS[engine] + "/models").get("data", [])
        if model not in {r.get("id") for r in offered if isinstance(r, dict)}:
            raise ValueError("The loaded identifier is not available on the OpenAI-compatible API.")
        contract = model_contract(engine, row)
        if contract["fit"]["rating"] != "Fits":
            result["contract"] = contract
            raise ValueError("Choose a model and loaded context marked Fits before launching.")
        config = generate_config(identity, engine, model, contract)
        if identity == "goose":
            # Isolate config migrations, extensions, permissions and session data
            # from the user's global Goose directory. JSON is valid YAML.
            scope = _digest(
                [
                    "native-local-v1",
                    project,
                    engine,
                    model,
                    contract["context"],
                    contract["max_tokens"],
                ]
            )
            private_root = service.root / "local-harnesses" / scope / "goose"
            config["env"]["GOOSE_PATH_ROOT"] = str(private_root)
            config["files"] = {
                str(private_root / "config" / "config.yaml"): json.dumps(
                    {
                        "active_provider": engine,
                        "providers": {
                            engine: {"enabled": True, "configured": True, "model": model}
                        },
                        "GOOSE_MODE": "approve",
                        "GOOSE_TOOLSHIM": False,
                        "extensions": {
                            "developer": {
                                "type": "builtin",
                                "name": "developer",
                                "bundled": True,
                                "enabled": True,
                                "timeout": 300,
                            }
                        },
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            }
        from superqode.harness.catalog import resolve_harness

        core_digest = resolve_harness("core", root=root).digest if identity == "superqode" else ""
        # Store only request budgets and fit rating in the revision. Device load
        # and incidental API metadata must not invalidate native continuation.
        revision = {
            "harness": identity,
            "engine": engine,
            "model": model,
            "config": config,
            "context": contract["context"],
            "max_tokens": contract["max_tokens"],
            "core_digest": core_digest,
            "binary": harness["binary"],
            "version": harness["version"],
        }
        return {
            **result,
            "ready": True,
            "contract": contract,
            "config": config,
            "binary": harness["binary"],
            "digest": _digest(revision),
            "note": "Configured is not a tool-quality test. External tools and extensions can access the network.",
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {**result, "status": "Preflight blocked", "reason": str(exc)}


def catalog(service, project):
    service.project(project)
    rows, issues = [], []
    for engine in ENDPOINTS:
        try:
            for row in running_models(engine):
                rows.append({"id": _digest([engine, row["model"]])[:24], "engine": engine, **row})
        except (OSError, ValueError, TypeError) as exc:
            issues.append(engine + ": " + str(exc))
    return {
        "harnesses": [
            row
            for identity in DOCUMENTED_LOCAL_SUPPORT
            if _allowed(identity)
            for row in [installed_harness(identity)]
            if row["status"] in VISIBLE_STATUSES
        ],
        "models": rows,
        "issues": issues,
    }


def _profile(service, project, reference):
    rows = service._all("SELECT value FROM settings WHERE key=?", (reference,))
    profile = json.loads(rows[0]["value"]) if rows else {}
    if profile.get("project") != project:
        raise ValueError("Configure this local harness from Advanced in this project first")
    return profile


def launch(service, params):
    # Reuse the normal task command idempotency boundary, including retry after
    # a lost RPC response. No second profile or agent is created on retry.
    command = str(params.get("command_id") or "")
    if not command or len(command) > 128:
        raise ValueError("A launch command id is required")
    with service.lock:
        for row in service._all(
            "SELECT id,request FROM jobs WHERE project=?", (params["project"],)
        ):
            if json.loads(row["request"]).get("command_id") == command:
                return {"id": row["id"]}
        plan = preflight(service, params)
        if not plan["ready"]:
            raise ValueError(plan["reason"] or plan["status"])
        if params.get("digest") != plan["digest"]:
            raise ValueError("Local configuration changed. Review the preflight again.")
        prompt = str(params.get("prompt") or "").strip()
        if not prompt or len(prompt) > 100_000:
            raise ValueError(
                "Write a first message of up to 100,000 characters before starting the thread"
            )
        reference = PREFIX + _digest([params["project"], plan["digest"]])[:32]
        service._write(
            "INSERT OR IGNORE INTO settings VALUES(?,?)",
            (
                reference,
                json.dumps(
                    {
                        "project": params["project"],
                        "harness": params["harness"],
                        "engine": params["engine"],
                        "model": params["model"],
                        "digest": plan["digest"],
                    }
                ),
            ),
        )
        return service.start(
            params["project"],
            "task",
            {
                "harness": reference,
                "prompt": prompt,
                "command_id": command,
                "interaction_mode": "code",
            },
        )


def apply_route(service, project, params):
    """Rebuild trusted launch data every turn. Ignore client env, argv and model overrides."""
    profile = _profile(service, project, params["harness"])
    plan = preflight(service, profile)
    if not plan["ready"] or plan.get("digest") != profile["digest"]:
        raise ValueError(
            plan.get("reason") or "Local configuration changed. Start again from Advanced."
        )
    params["_local_harness"] = plan
    params["context_window"] = plan["contract"]["context"]
    params["max_tokens"] = plan["contract"]["max_tokens"]
    params["model"] = plan["config"]["model"]
    params.pop("acp_options", None)
    if profile["harness"] == "superqode":
        params["provider"] = profile["engine"]
        params["_thread_harness"] = {"name": "SuperQode local", "runtime": "builtin"}
    else:
        argv = [plan["binary"], *plan["config"]["argv"]]
        params["provider"] = "agent"
        params["_desktop_route"] = {
            "id": params["harness"],
            "name": HARNESSES[profile["harness"]][0],
            "command": shlex.join(argv),
            "command_argv": argv,
            "extra_env": plan["config"]["env"],
            "digest": plan["digest"],
            "auth": "local; no app credentials",
            "subscription_vendor": None,
        }


def selections(service, project):
    result, installed = [], {}
    for row in service._all("SELECT key,value FROM settings WHERE key LIKE ?", (PREFIX + "%",)):
        profile = json.loads(row["value"])
        if profile.get("project") != project:
            continue
        identity = profile.get("harness")
        if not _allowed(identity):
            continue
        if identity not in installed:
            installed[identity] = installed_harness(identity)
        harness = installed[identity]
        if harness["status"] not in VISIBLE_STATUSES:
            continue
        core = identity == "superqode"
        result.append(
            {
                "id": row["key"],
                "name": HARNESSES[identity][0] + " · " + profile["model"],
                "description": "Advanced local thread configuration",
                "runtime": "builtin" if core else "ACP",
                "available": harness["status"] == "Configured",
                "issue": harness["reason"],
                "digest": profile["digest"],
                "path": None,
                "desktop_kind": "" if core else "acp",
                "enforces_session_controls": core,
                "local_provider": profile["engine"] if core else "agent",
                "local_model": profile["model"]
                if identity != "opencode"
                else "sq-local/" + profile["model"],
            }
        )
    return result


def worker_environment(base, plan):
    """No inherited provider keys, routing overrides or alternate-model settings."""
    from .environment import job_environment

    clean = job_environment(base, {}, allowed=())
    for key in list(clean):
        if key.startswith(("GOOSE_", "OPENAI_", "OLLAMA_", "LMSTUDIO_", "OPENCODE_")):
            clean.pop(key)
    clean.pop("SUPERQODE_LOCAL_CONTEXT_CONTRACT", None)
    clean.update(plan["config"]["env"])
    if plan["harness"] == "superqode":
        clean["SUPERQODE_LOCAL_CONTEXT_CONTRACT"] = json.dumps(
            {
                "provider": plan["engine"],
                "model": plan["model"],
                "context": plan["contract"]["context"],
                "max_tokens": plan["contract"]["max_tokens"],
            }
        )
    clean["NO_PROXY"] = clean["no_proxy"] = "127.0.0.1,localhost"
    return clean


def materialize_worker_files(plan, state_root):
    """Create reviewed private config only on explicit task launch, never overwrite."""
    root = Path(state_root).resolve()
    base = root / "local-harnesses"
    for name, content in plan["config"].get("files", {}).items():
        target = Path(name)
        if not target.is_absolute() or not target.is_relative_to(base):
            raise ValueError(
                "Generated harness configuration must stay in private application storage"
            )
        relative = target.relative_to(base)
        if ".." in relative.parts:
            raise ValueError("Generated harness configuration cannot leave private storage")
        directory = root
        for part in ("local-harnesses", *relative.parts[:-1]):
            directory /= part
            if directory.is_symlink():
                raise ValueError("Generated harness configuration cannot use a symlink")
            directory.mkdir(mode=0o700, exist_ok=True)
        if target.is_symlink() or not target.resolve().is_relative_to(base):
            raise ValueError("Generated harness configuration cannot use a symlink")
        if target.exists():
            if not target.is_file() or target.stat().st_nlink != 1:
                raise ValueError("Private harness configuration is not a single-link regular file")
            # Goose may reserialize YAML and add ordinary preferences. Keep the
            # owned provider, model and extension selection unchanged, without
            # overwriting either those preferences or approval/session data.
            import yaml

            expected = json.loads(content)
            actual = yaml.safe_load(target.read_text())
            if not isinstance(actual, dict) or any(
                actual.get(key) != expected[key] for key in expected
            ):
                raise ValueError(
                    "Private harness configuration changed. Review it before starting again."
                )
            continue
        with target.open("x", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(content)
