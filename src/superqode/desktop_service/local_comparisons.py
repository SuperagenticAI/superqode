"""Reviewed local model/harness comparisons using shared isolated eval trials."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
import shlex
from pathlib import Path
import sys
import time
from uuid import uuid4

from superqode.local import runtimes
from . import local_runtimes

PREFIX = "local-comparison-plan."


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def immutable_identity(artifact):
    for field in ("digest", "revision"):
        value = (artifact or {}).get(field)
        if isinstance(value, str):
            value = value.removeprefix("sha256:")
            if 40 <= len(value) <= 64 and all(c in "0123456789abcdefABCDEF" for c in value):
                return value.lower()
    return None


def identity_changed(before, after):
    if not before or not after:
        return False  # Missing observations are unknown, not evidence of drift.
    old, new = immutable_identity(before), immutable_identity(after)
    if old and new:
        return old != new
    # Generic API sizes may describe changing resident allocations. Only
    # compare stable identity fields that both observations actually report.
    return any(
        before.get(k) is not None and after.get(k) is not None and before[k] != after[k]
        for k in ("key", "digest", "revision", "quantization", "selected_variant")
    )


def starter_suite():
    """Fixed independent verifiers, executed only after native plan review."""
    tasks = []
    examples = (
        (
            "clamp",
            "Create sq_local_trial.py with clamp(value, lower, upper). Return value bounded inclusively by lower and upper; raise ValueError if lower > upper. Do not change other files.",
            "f=m['clamp']; assert f(-2,0,10)==0; assert f(12,0,10)==10; assert f(3,0,10)==3; assert f(0,0,0)==0\ntry: f(1,3,2)\nexcept ValueError: pass\nelse: raise AssertionError('invalid bounds accepted')",
        ),
        (
            "unique_names",
            "Create sq_local_trial.py with unique_names(values). Strip each string, discard blanks, and deduplicate case-insensitively while preserving the first spelling and order. Do not mutate the input. Do not change other files.",
            "f=m['unique_names']; a=[' Alice ','bob','ALICE','',' Bob ','Cara']; assert f(a)==['Alice','bob','Cara']; assert a==[' Alice ','bob','ALICE','',' Bob ','Cara']; assert f([])==[]; assert f(['  ','x',' X '])==['x']",
        ),
    )
    for identity, prompt, checks in examples:
        tasks.append(
            {
                "id": identity,
                "split": "held-out",
                "prompt": prompt,
                "evaluator": {
                    "type": "repository",
                    "require_changes": True,
                    "commands": [
                        {
                            "argv": [
                                sys.executable,
                                "-I",
                                "-B",
                                "-c",
                                "import runpy\nm=runpy.run_path('sq_local_trial.py')\n" + checks,
                            ]
                        }
                    ],
                },
            }
        )
    return {
        "version": 1,
        "metadata": {
            "name": "Local coding comparison v1",
            "note": "Two starter tasks; passing is not production coding certification.",
        },
        "tasks": tasks,
    }


async def _catalog_profiles(service):
    async def probe(profile):
        try:
            spec = runtimes.validate(profile)
            rows = await runtimes.models(spec, local_runtimes.key(service, spec.id))
            return [
                {
                    "provider": "local-openai",
                    "model": row["id"],
                    "runtime": spec.id,
                    "name": spec.name + " · " + row["id"],
                    "context": min(spec.context, row.get("context") or spec.context),
                    "endpoint": spec.endpoint,
                    "runtime_profile": spec.public(),
                    "credential_revision": profile.get("credential_revision", ""),
                }
                for row in rows
                if spec.tools is not False
            ]
        except Exception:
            return []

    groups = await asyncio.gather(*(probe(p) for p in local_runtimes.profiles(service)[:20]))
    return [row for group in groups for row in group]


def catalog(service, project):
    from . import local_models
    from concurrent.futures import ThreadPoolExecutor

    service.project(project)

    def managed(engine):
        try:
            data = local_models.available(engine)
            models = data.get("loaded_models", []) if engine == "lmstudio" else data["models"]
            return [
                {
                    "provider": engine,
                    "model": model,
                    "runtime": engine,
                    "name": engine + " · " + model,
                    "context": 8192,
                    "endpoint": runtimes.loopback_url(data["endpoint"]),
                }
                for model in models
                if not any(s in model.lower() for s in ("embed", "rerank", "cloud"))
            ]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        groups = list(pool.map(managed, ("ollama", "lmstudio")))
    routes = [row for group in groups for row in group] + asyncio.run(_catalog_profiles(service))
    for row in routes:
        row["id"] = fingerprint([row["provider"], row["runtime"], row["model"]])[:24]
    harnesses = [
        r
        for r in local_models.harnesses(service, project)
        if r["selectable"] and r["backend"] in {"builtin", "pipy", "rlm"}
    ]
    return {
        "routes": routes,
        "harnesses": harnesses,
        "note": "Available local endpoints only. Load missing models in their runtime first; discovery makes no generation requests.",
    }


def prepare(service, params):
    import yaml
    from superqode.harness.catalog import resolve_harness
    from superqode.harness.loader import harness_spec_to_dict
    from superqode.local.hardware import detect_hardware
    from .experiments import inspect_suite, reviewed_suite

    root = service.project(params["project"])
    selections = params.get("selections")
    if not isinstance(selections, list) or not 2 <= len(selections) <= 4:
        raise ValueError("Choose a baseline and one to three candidates")
    context = params.get("context", 8192)
    if type(context) is not int or context not in {2048, 4096, 8192, 16384, 32768}:
        raise ValueError("Choose a shared comparison context between 2048 and 32768")
    if type(params.get("warmup", True)) is not bool:
        raise ValueError("Choose whether to run a short warmup")
    available = catalog(service, params["project"])
    selected = []
    for index, row in enumerate(selections):
        if not isinstance(row, dict):
            raise ValueError("Choose a local model and harness for each candidate")
        route = next((r for r in available["routes"] if r["id"] == row.get("route")), None)
        harness = next((r for r in available["harnesses"] if r["id"] == row.get("harness")), None)
        if not route or not harness:
            raise ValueError(
                "A selected model or compatible harness is unavailable; refresh choices"
            )
        definition = resolve_harness(harness["id"], root=root)
        spec = harness_spec_to_dict(definition.spec)
        # Pin an equal request/context budget; harness prompts, tools and
        # orchestration remain the intentional independent variable.
        spec.setdefault("model_policy", {})["context_window"] = context
        spec["model_policy"]["fallbacks"] = []
        spec["model_policy"].setdefault("config", {})["max_iterations"] = 12
        spec.setdefault("runtime", {})["fallback_backends"] = []
        if (
            len(spec.get("agents") or []) > 1
            or any(a.get("model") or a.get("delegates_to") for a in spec.get("agents") or [])
            or (spec.get("workflow") or {}).get("mode", "single") != "single"
        ):
            raise ValueError("Choose a single-agent harness for controlled local model comparisons")
        if context > route["context"]:
            raise ValueError(
                "The shared context exceeds a selected runtime's configured cap; lower it or review that runtime"
            )
        selected.append(
            {
                **route,
                "harness": harness["id"],
                "harness_digest": definition.digest,
                "harness_yaml": yaml.safe_dump(spec, sort_keys=False),
                "label": str(index + 1) + " · " + harness["name"] + " · " + route["name"],
            }
        )
    if len({(r["id"], r["harness"]) for r in selected}) < 2:
        raise ValueError("Choose at least two different model/harness configurations")
    tasks = str(params.get("tasks") or "")
    if tasks:
        options = {"tasks": tasks, "split": "all", "live": True}
        inspection = inspect_suite(root, options)
        content = reviewed_suite(root, {**options, "tasks_hash": inspection["tasks_hash"]})
    else:
        content = yaml.safe_dump(starter_suite(), sort_keys=False)
        inspection = {
            "tasks_hash": "sha256:" + hashlib.sha256(content.encode()).hexdigest(),
            "task_count": 2,
            "warnings": ["Two starter tasks measure a narrow slice of coding behavior."],
            "repository_checks": [
                {
                    "id": t["id"],
                    "commands": [shlex.join(c["argv"]) for c in t["evaluator"]["commands"]],
                }
                for t in starter_suite()["tasks"]
            ],
        }
    suite = yaml.safe_load(content)
    if suite.get("variants"):
        raise ValueError(
            "Choose harnesses explicitly in this comparison; remove suite-level variants"
        )
    if any(
        (t.get("evaluator") or {}).get("type") not in {"repository", "contains", "decision"}
        for t in suite["tasks"]
    ):
        raise ValueError(
            "Use independent repository, contains or decision graders for local comparisons"
        )
    plan = {
        "id": uuid4().hex,
        "project": params["project"],
        "routes": selected,
        "context": context,
        "max_tokens": min(2048, context // 4),
        "warmup": params.get("warmup", True),
        "suite_content": content,
        "inspection": inspection,
        "hardware": asdict(detect_hardware()),
        "created": time.time(),
        "note": "Trials use independent project copies, not an OS sandbox. Verifiers execute code with your user permissions. Cache state and runtime identity are recorded when reported; missing observations remain unknown.",
    }
    plan["digest"] = fingerprint(plan)
    service._write("INSERT INTO settings VALUES(?,?)", (PREFIX + plan["id"], json.dumps(plan)))
    return public(plan)


def public(plan):
    return {
        **{k: v for k, v in plan.items() if k != "suite_content"},
        "routes": [
            {k: v for k, v in r.items() if k not in {"harness_yaml", "credential_revision"}}
            for r in plan["routes"]
        ],
    }


def start(service, params):
    rows = service._all(
        "SELECT value FROM settings WHERE key=?", (PREFIX + str(params.get("plan")),)
    )
    if not rows:
        raise ValueError("Review the local comparison before running it")
    plan = json.loads(rows[0]["value"])
    if fingerprint({k: v for k, v in plan.items() if k != "digest"}) != plan["digest"]:
        raise ValueError("The stored comparison changed; prepare and review it again")
    if (
        plan["project"] != params.get("project")
        or params.get("expected_digest") != plan["digest"]
        or params.get("execute") is not True
    ):
        raise ValueError("Review and explicitly start this comparison with its current digest")
    if time.time() - plan["created"] > 86400:
        raise ValueError("This comparison review expired; prepare it again")
    for route in plan["routes"]:
        if route["provider"] == "local-openai":
            current = local_runtimes.read(service, route["runtime"])
            if (
                runtimes.validate(current).public() != route["runtime_profile"]
                or current.get("credential_revision", "") != route["credential_revision"]
            ):
                raise ValueError(
                    "Runtime settings or credentials changed; review the comparison again"
                )
    return service.start(
        plan["project"],
        "local-comparison",
        {"comparison_plan": plan, "command_id": params.get("command_id") or uuid4().hex},
    )


def environment(service, plan):
    keys = {
        r["runtime"]: local_runtimes.key(service, r["runtime"]) or ""
        for r in plan["routes"]
        if r["provider"] == "local-openai"
    }
    return {"SUPERQODE_LOCAL_COMPARISON_KEYS": json.dumps(keys)}, [k for k in keys.values() if k]


@contextmanager
def route_environment(route, context, keys):
    updates = {
        "SUPERQODE_LOCAL_COMPARISON_TRACE": "",
        "SUPERQODE_LOCAL_CONTEXT_CONTRACT": json.dumps(
            {
                "provider": route["provider"],
                "model": route["model"],
                "context": context,
                "max_tokens": min(2048, context // 4),
            }
        ),
        "SUPERQODE_UTILITY_PROVIDER": "",
        "LOCAL_RUNTIME_API_KEY": "",
    }
    if route["provider"] == "local-openai":
        spec = {
            **route["runtime_profile"],
            "context": min(context, route["runtime_profile"]["context"]),
        }
        updates.update(
            SUPERQODE_LOCAL_RUNTIME=json.dumps(spec),
            LOCAL_RUNTIME_API_KEY=keys.get(route["runtime"], ""),
        )
    elif route["provider"] == "ollama":
        updates.update(
            OLLAMA_API_BASE=route["endpoint"].removesuffix("/v1"),
            OLLAMA_HOST=route["endpoint"].removesuffix("/v1"),
        )
    else:
        updates["LMSTUDIO_HOST"] = route["endpoint"]
    previous = {k: os.environ.get(k) for k in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


async def observe_identity(route, key):
    """Read reported identity/version/context. No invented revision or cache hit."""
    import httpx

    root = route["endpoint"].removesuffix("/v1")
    paths = (
        ["/api/tags", "/api/ps", "/api/version"]
        if route["provider"] == "ollama"
        else ["/api/v1/models", "/v1/models"]
    )
    if route["provider"] == "local-openai":
        paths = ["/models"]
        root = route["endpoint"]
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=3,
        headers={"Authorization": "Bearer " + key} if key else {},
    ) as client:

        async def get(path):
            try:
                response = await client.get(root + path)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        payloads = await asyncio.gather(*(get(p) for p in paths))
    result = {
        "model": route["model"],
        "artifact": None,
        "runtime_version": None,
        "loaded_context": None,
        "residency": None,
    }
    for path, payload in zip(paths, payloads):
        if isinstance(payload.get("version"), str):
            result["runtime_version"] = payload["version"][:200]
        for row in payload.get("models", payload.get("data", [])):
            if not isinstance(row, dict):
                continue
            loaded = next(
                (i for i in row.get("loaded_instances", []) if i.get("id") == route["model"]), None
            )
            if (
                route["model"]
                not in (row.get("id"), row.get("name"), row.get("model"), row.get("key"))
                and loaded is None
            ):
                continue
            artifact = {
                k: row[k]
                for k in (
                    "id",
                    "key",
                    "digest",
                    "revision",
                    "quantization",
                    "size_bytes",
                    "size",
                    "details",
                    "selected_variant",
                )
                if row.get(k) is not None
            }
            if artifact and path != "/api/ps":
                result["artifact"] = {**(result["artifact"] or {}), **artifact}
            config = (loaded or {}).get("config") or row
            context = config.get("context_length") or config.get("context_window")
            if type(context) is int and context >= 512:
                result["loaded_context"] = context
            if row.get("size_vram") is not None:
                result["residency"] = {"vram_bytes": row["size_vram"], "reported_by": "server"}
    return result


async def run(request, directory, emit, secrets):
    import yaml
    from superqode.harness.eval import run_harness_eval, load_eval_tasks
    from superqode.harness.eval_workspace import EvaluationWorkspace
    from superqode.providers.gateway import LiteLLMGateway, Message
    from .evaluation_review import evaluation_comparison

    plan = request["comparison_plan"]
    keys = json.loads(os.environ.pop("SUPERQODE_LOCAL_COMPARISON_KEYS", "{}"))
    secrets.extend(k for k in keys.values() if k)
    tasks = directory / "comparison-tasks.yaml"
    tasks.write_text(plan["suite_content"])
    task_file = load_eval_tasks(tasks)
    variants = []
    started = time.monotonic()
    with EvaluationWorkspace(request["cwd"], exclude_paths=(directory,)) as snapshot:
        for index, route in enumerate(plan["routes"]):
            emit(
                "stage",
                {
                    "message": "Comparing " + route["label"],
                    "candidate": index + 1,
                    "total": len(plan["routes"]),
                },
            )
            spec = directory / f"candidate-{index}.yaml"
            spec.write_text(route["harness_yaml"])
            before = {
                "artifact": None,
                "runtime_version": None,
                "loaded_context": None,
                "residency": None,
            }
            after = dict(before)
            warmup = None
            tick = time.monotonic()
            with route_environment(route, plan["context"], keys):
                key = keys.get(route["runtime"], "")
                try:
                    async with asyncio.timeout(300):
                        before = await observe_identity(route, key)
                        if before["loaded_context"] and before["loaded_context"] < plan["context"]:
                            raise ValueError(
                                "The server loaded less context than the shared request cap. Lower the comparison context or reload the model explicitly."
                            )
                        if plan["warmup"]:
                            warm_tick = time.monotonic()
                            await LiteLLMGateway().chat_completion(
                                [Message("user", "Reply with exactly: ok")],
                                provider=route["provider"],
                                model=route["model"],
                                max_tokens=8,
                            )
                            warmup = time.monotonic() - warm_tick
                        os.environ["SUPERQODE_LOCAL_COMPARISON_TRACE"] = (
                            request["job_id"] + ":" + str(index)
                        )
                        result = await run_harness_eval(
                            spec_paths=[spec],
                            tasks_path=tasks,
                            provider=route["provider"],
                            model=route["model"],
                            working_dir=request["cwd"],
                            live=True,
                            workspace_snapshot=snapshot,
                        )
                        after = await observe_identity(route, key)
                    variant = result["variants"][0]
                except Exception as exc:
                    variant = {
                        "status": "error",
                        "score": 0,
                        "passed": 0,
                        "failed": 0,
                        "errors": len(task_file["tasks"]),
                        "duration_seconds": time.monotonic() - tick,
                        "tasks": [
                            {
                                "id": task["id"],
                                "split": task["split"],
                                "status": "error",
                                "score": 0,
                                "reason": "Candidate did not complete: "
                                + (str(exc)[:600] or type(exc).__name__),
                                "evaluation": {
                                    "evaluator": "execution",
                                    "status": "error",
                                    "reason": "Candidate execution failed",
                                },
                            }
                            for task in task_file["tasks"]
                        ],
                    }
            variant["harness"] = route["label"]
            from superqode.local.execution import comparison_records

            variant["model_requests"] = comparison_records(request["job_id"] + ":" + str(index))
            variant["local_configuration"] = {
                "provider": route["provider"],
                "model": route["model"],
                "runtime": route["runtime"],
                "harness": route["harness"],
                "harness_digest": route["harness_digest"],
                "effective_harness_sha256": hashlib.sha256(
                    route["harness_yaml"].encode()
                ).hexdigest(),
                "endpoint": route["endpoint"],
                "requested_context": plan["context"],
                "max_tokens": plan["max_tokens"],
                "before": before,
                "after": after,
                "identity_changed": identity_changed(before["artifact"], after["artifact"])
                or bool(
                    before["runtime_version"]
                    and after["runtime_version"]
                    and before["runtime_version"] != after["runtime_version"]
                ),
                "identity_verified": bool(
                    immutable_identity(before["artifact"])
                    and immutable_identity(before["artifact"])
                    == immutable_identity(after["artifact"])
                ),
                "warmup_seconds": warmup,
                "cache_policy": "short warmup request"
                if plan["warmup"]
                else "as found; uncontrolled",
                "cache_reset": False,
            }
            variants.append(variant)
            emit(
                "progress",
                {
                    "message": "Finished " + route["label"],
                    "completed": len(variants),
                    "total": len(plan["routes"]),
                },
            )
        result = {
            "live": True,
            "status": "completed",
            "baseline": variants[0]["harness"],
            "variants": variants,
            "task_count": len(task_file["tasks"]),
            "tasks_hash": task_file["tasks_hash"],
            "hardware": plan["hardware"],
            "workspace": {"mode": "isolated-copy", "snapshot_sha256": snapshot.digest},
            "duration_seconds": time.monotonic() - started,
            "artifact_dir": str(directory),
            "note": plan["note"],
        }
    result["comparison"] = evaluation_comparison(result)
    # Identity changes invalidate quality comparisons, even if tests passed.
    if any(v["local_configuration"]["identity_changed"] for v in variants):
        result["comparison"] = {
            "available": False,
            "message": "A model artifact changed during execution; rerun with stable model artifacts.",
        }
    from .redaction import redact

    result = redact(result, secrets)
    (directory / "result.json").write_text(json.dumps(result, indent=2))
    emit("result", result)
