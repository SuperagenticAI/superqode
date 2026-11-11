"""Native runtime profiles, session-only keys and reviewed readiness checks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import time
from uuid import uuid4

from superqode.local import runtimes

PREFIX = "local-runtime."


def read(service, identity):
    rows = service._all("SELECT value FROM settings WHERE key=?", (PREFIX + identity,))
    if not rows:
        raise ValueError("Choose a saved runtime in Local AI")
    return json.loads(rows[0]["value"])


def digest(spec):
    return hashlib.sha256(json.dumps(spec.public(), sort_keys=True).encode()).hexdigest()


def save(service, profile):
    with service.lock:
        service._write(
            "INSERT OR REPLACE INTO settings VALUES(?,?)",
            (PREFIX + profile["id"], json.dumps(profile)),
        )


def profiles(service):
    rows = service._all("SELECT value FROM settings WHERE key LIKE ? ORDER BY key", (PREFIX + "%",))
    return [
        {
            **json.loads(row["value"]),
            "key_configured": bool(service.runtime_keys.get(json.loads(row["value"])["id"])),
        }
        for row in rows
    ]


def key(service, identity):
    return service.runtime_keys.get(identity)


def validation_digest(profile):
    return hashlib.sha256(
        (digest(runtimes.validate(profile)) + str(profile.get("credential_revision", ""))).encode()
    ).hexdigest()


def checked(profile, model):
    spec = runtimes.validate(profile)
    result = profile.get("checks", {}).get(model) or {}
    return (
        result.get("digest") == validation_digest(profile)
        and result.get("tool_call_success") is True
    )


def dispatch(service, action, params):
    if action == "catalog":
        return {
            "templates": [spec.public() for spec in runtimes.TEMPLATES],
            "profiles": profiles(service),
        }
    if action == "harnesses":
        from .local_models import harnesses

        return [
            row
            for row in harnesses(service, params["project"])
            if row["backend"] in {"builtin", "pipy", "rlm"}
        ]
    if action == "save":
        spec = runtimes.validate(params)
        try:
            previous = read(service, spec.id)
        except ValueError:
            previous = {}
        record = {
            **spec.public(),
            "checks": previous.get("checks", {})
            if previous and digest(runtimes.validate(previous)) == digest(spec)
            else {},
        }
        record["credential_revision"] = previous.get("credential_revision", "")
        record["remember_key"] = params.get("remember_key") is True
        for field in ("last_check_job", "last_operation_job"):
            if previous.get(field):
                record[field] = previous[field]
        save(service, record)
        return record
    identity = str(params.get("id") or "")
    if action == "key":
        read(service, identity)
        value = params.get("key")
        if value is not None and (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 16000
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Enter a local API key without control characters, or remove it")
        with service.lock:
            if value is None:
                service.runtime_keys.pop(identity, None)
            else:
                service.runtime_keys[identity] = value.strip()
            record = read(service, identity)
            if params.get("restore") is not True or record.get("remember_key") is not True:
                record["checks"] = {}
                record["credential_revision"] = uuid4().hex
            save(service, record)
        return {"configured": value is not None}
    if action == "delete":
        with service.lock:
            service._write(
                "DELETE FROM local_model_bindings WHERE provider='local-openai' AND EXISTS "
                "(SELECT 1 FROM local_runtime_bindings r WHERE r.runtime=? "
                "AND r.project=local_model_bindings.project "
                "AND r.harness=local_model_bindings.harness AND r.model=local_model_bindings.model)",
                (identity,),
            )
            service._write("DELETE FROM settings WHERE key=?", (PREFIX + identity,))
            service._write("DELETE FROM local_runtime_bindings WHERE runtime=?", (identity,))
            service.runtime_keys.pop(identity, None)
        return {"ok": True}
    profile = read(service, identity)
    spec = runtimes.validate(profile)
    if action == "setup.plan":
        from superqode.local.runtime_setup import plan

        return plan(profile)
    if action == "setup.start":
        from superqode.local.runtime_setup import plan

        reviewed = plan(profile)
        if not reviewed["automatic"]:
            raise ValueError(reviewed["guidance"])
        if params.get("expected_digest") != reviewed["digest"]:
            raise ValueError("Runtime installation plan changed; review it again")
        job = service.start(
            str(params.get("project") or ""),
            "local-runtime",
            {
                "runtime_setup": reviewed,
                "command_id": params.get("command_id") or uuid4().hex,
            },
        )
        with service.lock:
            current = read(service, identity)
            current["last_operation_job"] = job["id"]
            save(service, current)
        return job
    if action == "probe":
        try:
            models = asyncio.run(runtimes.models(spec, key(service, identity)))
        except ValueError:
            raise
        except Exception:
            raise ValueError(
                "Local server did not answer. Start it with the vendor guide, verify the port, then retry."
            ) from None
        return {"models": models, "endpoint": spec.endpoint, "runtime": spec.id}
    if action in {"test", "warm"}:
        project = str(params.get("project") or "")
        service.project(project)
        model = str(params.get("model") or "")
        if not model or len(model) > 4096:
            raise ValueError("Choose a model advertised by this server")
        job = service.start(
            project,
            "local-runtime",
            {
                "provider": "local-openai",
                "model": model,
                "harness": "no-tool",
                "runtime_profile": profile,
                "runtime_digest": validation_digest(profile),
                "runtime_action": "warm" if action == "warm" else "tool-check",
                "command_id": params.get("command_id") or uuid4().hex,
            },
        )
        with service.lock:
            current = read(service, identity)
            current["last_operation_job"] = job["id"]
            if action == "test":
                current["last_check_job"] = job["id"]
            save(service, current)
        return job
    if action == "use":
        project = str(params.get("project") or "")
        service.project(project)
        model = str(params.get("model") or "")
        harness = params.get("harness") or "no-tool"
        if not any(
            row["id"] == model for row in asyncio.run(runtimes.models(spec, key(service, identity)))
        ):
            raise ValueError("Choose a model currently advertised by this local server")
        if harness != "no-tool":
            from .local_models import harnesses

            if not checked(profile, model):
                raise ValueError("Run the read-only tool check before choosing a coding harness")
            if not any(
                row["id"] == harness
                and row["selectable"]
                and row["backend"] in {"builtin", "pipy", "rlm"}
                for row in harnesses(service, project)
            ):
                raise ValueError("Choose a compatible local coding harness")
        with service.lock:
            service.db.execute(
                "CREATE TABLE IF NOT EXISTS local_runtime_bindings(project TEXT,harness TEXT,model TEXT,runtime TEXT,digest TEXT,PRIMARY KEY(project,harness,model))"
            )
            for selected in {harness, "no-tool"}:
                service._write(
                    "INSERT OR REPLACE INTO local_model_bindings VALUES(?,?,?,?,?)",
                    (project, selected, "local-openai", model, spec.endpoint),
                )
                service._write(
                    "INSERT OR REPLACE INTO local_runtime_bindings VALUES(?,?,?,?,?)",
                    (project, selected, model, spec.id, digest(spec)),
                )
        return {
            "provider": "local-openai",
            "model": model,
            "harness": harness,
            "endpoint": spec.endpoint,
            "runtime": spec.id,
        }
    raise ValueError("Unknown local runtime action")


async def verify(profile, model, token):
    """Inspect generated-data tool calls without executing tools or reading a repo."""
    from superqode.providers.gateway.base import Message, ToolDefinition
    from superqode.local.execution import LocalTurn

    spec = runtimes.validate(profile)
    if not any(row["id"] == model for row in await runtimes.models(spec, token)):
        raise ValueError("Refresh the server models and choose an advertised model")
    if spec.tools is False:
        raise ValueError(
            "This runtime is marked chat-only. Change its declared capability before checking tools."
        )
    schema = ToolDefinition(
        "read_probe",
        "Read a generated fixture",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )
    started = time.monotonic()
    calls = []
    async with LocalTurn("local-openai", model) as turn:
        async for chunk in runtimes.stream(
            spec,
            [
                Message(
                    "user",
                    "Call read_probe with path exactly generated-fixture.txt. Do not answer in prose.",
                )
            ],
            model,
            key=token,
            tools=[schema],
            max_tokens=128,
        ):
            calls.extend(chunk.tool_calls or [])
            turn.observe(
                text=bool(chunk.content),
                thinking=bool(chunk.thinking_content),
                terminal=bool(chunk.finish_reason),
                usage=chunk.usage,
            )
    valid = False
    for call in calls:
        function = call.get("function") or {}
        args = function.get("arguments") or {}
        args = json.loads(args) if isinstance(args, str) else args
        valid = valid or (
            function.get("name") == "read_probe" and args == {"path": "generated-fixture.txt"}
        )
    result = {
        "tool_call_success": valid,
        "digest": validation_digest(profile),
        "duration_s": time.monotonic() - started,
        "checked": time.time(),
        "scope": "generated-data shape check; no tools executed or project files accessed",
    }
    return result


def accept_result(service, result):
    identity = result.get("runtime")
    profile = read(service, identity)
    check = result.get("verification") or {}
    if check.get("digest") != validation_digest(profile):
        raise ValueError("Runtime settings or key changed during this check; retry it")
    profile.setdefault("checks", {})[result["model"]] = check
    save(service, profile)


async def worker(request, emit):
    import os

    if request.get("runtime_setup"):
        from superqode.local.runtime_setup import run

        run(request["runtime_setup"], emit)
        return

    profile = request["runtime_profile"]
    if request.get("runtime_action") == "warm":
        from superqode.providers.gateway.base import Message
        from superqode.local.execution import LocalTurn

        spec = runtimes.validate(profile)
        if not any(
            row["id"] == request["model"]
            for row in await runtimes.models(spec, os.environ.get("LOCAL_RUNTIME_API_KEY"))
        ):
            raise ValueError("Warmup requires a model currently advertised by this local server")
        async with LocalTurn("local-openai", request["model"]) as turn:
            async for chunk in runtimes.stream(
                runtimes.validate(profile),
                [Message("user", "Reply with exactly: ok")],
                request["model"],
                key=os.environ.get("LOCAL_RUNTIME_API_KEY"),
                max_tokens=8,
            ):
                turn.observe(
                    text=bool(chunk.content), terminal=bool(chunk.finish_reason), usage=chunk.usage
                )
        emit(
            "result",
            {
                "status": "completed",
                "runtime": profile["id"],
                "model": request["model"],
                "message": "Warmup completed. The server controls how long weights and caches remain resident.",
            },
        )
        return
    result = await verify(profile, request["model"], os.environ.get("LOCAL_RUNTIME_API_KEY"))
    emit(
        "result",
        {
            "status": "completed",
            "runtime": profile["id"],
            "model": request["model"],
            "verification": result,
        },
    )


def environment(service, project, harness, model):
    rows = service._all(
        "SELECT * FROM local_runtime_bindings WHERE project=? AND model=? ORDER BY (harness=?) DESC LIMIT 1",
        (project, model, harness),
    )
    if not rows:
        raise ValueError("Reconnect this model using its saved local runtime")
    binding = rows[0]
    profile = read(service, binding["runtime"])
    spec = runtimes.validate(profile)
    if binding["digest"] != digest(spec):
        raise ValueError(
            "Runtime configuration changed. Reconnect the model before starting a new task."
        )
    if harness != "no-tool" and not checked(profile, model):
        raise ValueError("Run the read-only tool check again before coding with this runtime")
    spec = replace(spec, tools=False if harness == "no-tool" else True)
    return {
        "SUPERQODE_LOCAL_RUNTIME": json.dumps(spec.public()),
        "SUPERQODE_LOCAL_ENDPOINT": spec.endpoint,
        "LOCAL_RUNTIME_API_KEY": key(service, spec.id) or "",
    }
