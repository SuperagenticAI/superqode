"""Isolated desktop job process using the existing harness and eval engines."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from .redaction import redact, worker_secrets
from .connect_workflow import connection_secrets

SECRETS = list(worker_secrets())
SECRETS.extend(json.loads(os.environ.pop("SUPERQODE_DESKTOP_TOOL_SECRETS", "[]")))
_remote_config = json.loads(os.environ.get("SUPERQODE_DESKTOP_REMOTE", "{}"))

SECRETS.extend(connection_secrets(_remote_config))
del _remote_config
WIRE = sys.stdout
sys.stdout = sys.stderr


def emit(kind: str, data: dict):
    WIRE.write(
        json.dumps({"type": kind, "data": redact(data, SECRETS)}, default=str, ensure_ascii=False)
        + "\n"
    )
    WIRE.flush()


def snapshot_spec(request: dict, output: Path):
    import yaml
    from superqode.harness.catalog import resolve_harness
    from superqode.harness.loader import harness_spec_to_dict

    definition = resolve_harness(request.get("harness") or "core", root=request["cwd"])
    data = harness_spec_to_dict(definition.spec)
    raw = yaml.safe_dump(data, sort_keys=False)
    output.write_text(raw)
    emit(
        "provenance",
        {
            "harness": definition.id,
            "digest": definition.digest,
            "snapshot": str(output),
            "provider": request.get("provider"),
            "model": request.get("model"),
            "live": request.get("live", True),
        },
    )
    return definition.spec


async def task(request, directory):
    from .conversations import with_handoff

    request = with_handoff(request)
    if request.get("interaction_mode") == "chat":
        from .chat import run_chat

        return await run_chat(request, emit)

    connection = request.get("_desktop_connection")
    if connection:
        if connection.get("runtime") == "prime-agent":
            request = {**request, "harness": "prime-agent-python"}
            request.pop("_desktop_connection", None)
        else:
            from .connection_worker import run_connection

            return await run_connection(request, directory, emit, SECRETS)
    if request.get("_desktop_route"):
        from .acp_worker import run_acp

        return await run_acp(request, directory, emit, SECRETS)
    from .images import load_snapshots
    from superqode.harness import FileHarnessStore, init_harness

    spec = snapshot_spec(request, directory / "harness.yaml")
    from superqode.harness.catalog import resolve_harness

    digest = resolve_harness(request.get("harness") or "core", root=request["cwd"]).digest
    if request.get("expected_digest") and request["expected_digest"] != digest:
        raise ValueError(
            "The harness changed since this task. Start a new task to use the new revision."
        )
    spec = replace(
        spec,
        context=replace(
            spec.context, session_storage=str(Path(request["state_root"]) / "native-sessions")
        ),
    )

    # The callback includes terminal run events that are not yielded by stream().
    def event_callback(event):
        data = dict(event.data)
        data.pop("pending_runtime", None)
        emit("harness_event", {"event": event.type, "run_id": event.run_id, "payload": data})

    kernel = await init_harness(
        spec, store=FileHarnessStore(directory / "harness-store"), event_callback=event_callback
    )
    session = await kernel.session(request.get("session_id"))
    from .controls import inbox

    controls = inbox(emit)
    session.observe_runtime(controls.bind)
    async for _ in session.stream(
        request["prompt"],
        provider=request["provider"],
        model=request["model"],
        working_directory=Path(request["cwd"]),
        sandbox_backend=spec.execution_policy.sandbox,
        images=load_snapshots(request),
        metadata={
            "agent_context_window": request.get("context_window") or 0,
            "enable_summarization": request.get("enable_summarization") is True,
        },
    ):
        pass
    while pending := session.pending_approvals():
        request_id = uuid.uuid4().hex
        item = dict(pending[0])
        emit("approval", {"request_id": request_id, "tool": item})
        decision = await asyncio.to_thread(controls.decision, request_id)
        if decision.get("allow") is True:
            response = await session.approve_pending(0, always=False)
        else:
            response = await session.reject_pending(0, message="Denied in SuperQode Desktop")
        if response.content:
            emit("answer", {"text": response.content})
        if response.stopped_reason in {"error", "cancelled"}:
            raise RuntimeError(response.content or f"Harness stopped: {response.stopped_reason}")
    emit(
        "result",
        {
            "session_id": session.session_id,
            "harness": spec.name,
            "harness_digest": digest,
            "native_continuity": spec.runtime.backend == "builtin",
            "artifact_dir": str(directory),
            "status": "completed",
        },
    )


async def evaluate(request, directory):
    from superqode.harness.eval import eval_pack_path, run_harness_eval

    snapshot_spec(request, directory / "harness.yaml")
    tasks = eval_pack_path(request["tasks"])
    specs = [directory / "harness.yaml"]
    from .experiments import candidate_paths

    specs.extend(candidate_paths(request, Path(request["cwd"])))
    emit(
        "stage",
        {
            "message": "Executing evaluation cases"
            if request.get("live")
            else "Validating suite setup; model execution is skipped"
        },
    )
    result = await run_harness_eval(
        spec_paths=specs,
        tasks_path=tasks,
        provider=request.get("provider") or "ollama",
        model=request.get("model") or "",
        working_dir=request["cwd"],
        live=request.get("live") is True,
        eval_split=request.get("split") or "all",
    )
    result["artifact_dir"] = str(directory)
    (directory / "result.json").write_text(
        json.dumps(redact(result, SECRETS), indent=2, default=str)
    )
    emit("result", result)


def optimize(request, directory):
    from superqode.harness.eval import eval_pack_path

    snapshot_spec(request, directory / "harness.yaml")
    tasks = eval_pack_path(request["tasks"])
    method = request.get("method") or "omni"
    if not request.get("live"):
        raise ValueError("Optimization requires explicit permission to make model calls")
    max_evals = int(request.get("max_evals", 4))
    if not 1 <= max_evals <= 100:
        raise ValueError("Evaluation budget must be between 1 and 100")
    cost = float(request.get("max_cost", 1))
    if not 0 < cost <= 100:
        raise ValueError("Token-cost budget must be between 0 and 100 USD")
    if method != "omni":
        raise ValueError("This desktop build supports the staged Omni optimization workflow")
    from superqode.harness.omni import optimize_harness_with_omni

    emit(
        "stage",
        {"message": "Running staged optimization; the live harness will not be overwritten"},
    )
    result = optimize_harness_with_omni(
        spec_path=directory / "harness.yaml",
        tasks_path=tasks,
        output_dir=directory / "optimization",
        provider=request.get("provider") or "ollama",
        model=request.get("model") or "",
        working_dir=request["cwd"],
        max_evals=max_evals,
        max_token_cost=cost,
        reflection_lm=request.get("reflection_model") or "openai/gpt-5.1",
        optimizer_model=request.get("optimizer_model") or "claude-sonnet-4-6",
        max_workers=1,
        live=True,
    )
    data = (
        result.to_dict()
        if hasattr(result, "to_dict")
        else asdict(result)
        if is_dataclass(result)
        else result
    )
    data["staged_sha256"] = hashlib.sha256(Path(data["staged_spec_path"]).read_bytes()).hexdigest()
    (directory / "result.json").write_text(json.dumps(redact(data, SECRETS), indent=2, default=str))
    emit("result", {**data, "artifact_dir": str(directory)})


def check(request, directory):
    from .environment import job_environment

    command = str(request.get("command") or "").strip()
    if not command or len(command) > 4000:
        raise ValueError("Enter a check command")
    emit("stage", {"message": f"Running {command}"})
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=request["cwd"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=job_environment(os.environ, {}, check=True),
    )
    chunks = []
    size = 0
    for line in process.stdout:
        emit("output", {"text": line[:4000]})
        if size < 200_000:
            chunks.append(line[:4000])
            size += len(line[:4000])
    code = process.wait()
    result = {
        "command": command,
        "exit_code": code,
        "output": "".join(chunks),
        "status": "passed" if code == 0 else "failed",
        "artifact_dir": str(directory),
    }
    (directory / "result.json").write_text(json.dumps(redact(result, SECRETS), indent=2))
    emit("result", result)


def main():
    try:
        raw = sys.stdin.readline(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Job request too large")
        request = json.loads(raw)
        directory = Path(request["state_root"]) / "runs" / request["job_id"]
        directory.mkdir(parents=True, mode=0o700)
        os.chdir(request["cwd"])
        remote = request.get("_desktop_connection", {}).get("kind") in {"a2a", "uhp"}
        emit(
            "stage",
            {
                "message": "Sending task directly to the selected remote server"
                if remote
                else "Starting execution on this Mac"
            },
        )
        if request["kind"] == "task":
            capture = None
            if not remote and request.get("interaction_mode") != "chat":
                try:
                    from .checkpoints import begin_task

                    capture = begin_task(request["cwd"], request["prompt"])
                    emit("checkpoint", {"id": capture[2], "phase": "baseline"})
                except (ValueError, OSError) as exc:
                    emit("checkpoint", {"available": False, "reason": str(exc)})
            try:
                asyncio.run(task(request, directory))
            finally:
                if capture:
                    try:
                        from .checkpoints import finish_task

                        emit("checkpoint", {"id": finish_task(capture), "phase": "sealed"})
                    except (ValueError, OSError) as exc:
                        emit("checkpoint", {"available": False, "reason": str(exc)})
        elif request["kind"] == "compaction":
            from .compaction import compact

            asyncio.run(compact(request, emit))
        elif request["kind"] == "evaluation":
            asyncio.run(evaluate(request, directory))
        elif request["kind"] == "tuning":
            from .tuning import run

            run(request, emit)
        elif request["kind"] == "optimization":
            optimize(request, directory)
        elif request["kind"] == "check":
            check(request, directory)
        elif request["kind"] == "tool":
            from .tools import run_tool

            run_tool(request, emit)
        else:
            raise ValueError("Unknown job kind")
    except Exception as exc:
        emit("error", {"message": str(exc), "type": type(exc).__name__})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
