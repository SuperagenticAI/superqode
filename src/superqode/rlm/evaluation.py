"""Fresh-workspace coding pilots for native RLM profiles.

Offline mode exercises execution with scripted responses; it cannot establish
model quality or cost savings. Live mode requires an explicit provider/model
and a shared reported-spend threshold. Graders stay outside agent workspaces.
"""

import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

from .budget import BudgetPolicy, RLMBudget, usage_delta
from .coding_session import RLMCodingSession, RLMCodingSessionOptions
from .commands import CommandBroker
from .profile import RLMProfile
from .sandbox import RLMSandboxConfig

PROFILES = {
    "python": RLMProfile(),
    "hybrid": RLMProfile(tool_surface="python-bash"),
    "selective": RLMProfile(observations="selective"),
    "hybrid-selective": RLMProfile(tool_surface="python-bash", observations="selective"),
}


async def grade_case(session, source):
    """Imported agent code must be graded in the selected execution boundary."""
    script = "import sys; sys.path.insert(0, '.');\n" + source
    backend = session.sandbox_backend
    if backend is not None:
        from .kernel_docker import SERVER_MOUNT

        broker_code = (
            "import json,sys; sys.path.insert(0,sys.argv[1]); from commands import CommandBroker; "
            "b=CommandBroker('/workspace','/state/commands.sqlite3'); "
            "j=b.start(['python3','-I','-c',sys.argv[2]],bash=False,timeout=30); "
            "r=j.wait(timeout=35); "
            "print(json.dumps({'returncode':r['returncode'] if r['returncode'] is not None else -1,"
            "'stdout':j.read(size=4000)['text'],'stderr':j.read(stream='stderr',size=4000)['text']}))"
        )
        code, out, err = await backend._docker(
            [
                "docker",
                "exec",
                "--workdir",
                "/workspace",
                backend._require_container(),
                "python3",
                "-I",
                "-c",
                broker_code,
                SERVER_MOUNT,
                script,
            ],
            timeout=45,
        )
        if code:
            raise RuntimeError(err.strip() or "Isolated grader failed")
        return SimpleNamespace(**json.loads(out))
    broker = CommandBroker(session.cwd, session._kernel.commands.path, agent="grader")
    job = await asyncio.to_thread(
        broker.start,
        [sys.executable, "-I", "-c", script],
        bash=False,
        timeout=30,
        request_id="grader-" + uuid4().hex,
    )
    receipt = await asyncio.to_thread(job.wait, timeout=35)
    return SimpleNamespace(
        returncode=receipt["returncode"] if receipt["returncode"] is not None else -1,
        stdout=job.read(size=4000)["text"],
        stderr=job.read(stream="stderr", size=4000)["text"],
    )


def load_cases(path):
    value = json.loads(Path(path).read_text())
    tasks = value.get("tasks", [])
    if not tasks or len({t["id"] for t in tasks}) != len(tasks):
        raise ValueError("Pilot tasks must have unique IDs")
    for task in tasks:
        for name in (*task.get("files", {}), *task.get("smoke_solution", {})):
            p = Path(name)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError("Pilot fixture paths must stay within the workspace")
        if not task.get("prompt") or not task.get("grader"):
            raise ValueError("Each pilot task needs a prompt and an independent grader")
    return tasks


async def run_pilot(
    tasks,
    *,
    output,
    provider="",
    model="",
    live=False,
    max_cost_usd=0,
    max_calls=0,
    repetitions=2,
    profiles=("python", "hybrid", "selective"),
    timeout=180,
    sandbox="host",
):
    if live and (not provider or not model or max_cost_usd <= 0 or max_calls <= 0):
        raise ValueError(
            "Live pilots require provider, model, positive USD threshold and model-call allowance"
        )
    if not 1 <= repetitions <= 20 or sandbox not in {"host", "docker"}:
        raise ValueError("Pilot repetitions must be 1..20 and sandbox host or docker")
    if not profiles or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("Pilot needs profiles and a timeout of 0..3600 seconds")
    for profile in profiles:
        if profile not in PROFILES:
            raise ValueError(f"Unknown pilot profile {profile}")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Pilot output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    policy = BudgetPolicy(max_calls=max_calls, max_cost_usd=max_cost_usd)
    ledger_path = output / "inference.sqlite3"
    ledger = RLMBudget(ledger_path, policy)
    rows = []
    for repetition in range(repetitions):
        for task in tasks:
            order = list(profiles)
            if repetition % 2:
                order.reverse()
            for profile in order:
                if live:
                    total = ledger.snapshot()["total"]
                    if (
                        total["cost_usd"] >= max_cost_usd
                        or total["calls"] >= max_calls
                        or total["unknown_cost_calls"]
                    ):
                        return _write_report(
                            output,
                            rows,
                            ledger.snapshot(),
                            live,
                            provider,
                            model,
                            stopped="Budget threshold or unknown usage",
                        )
                with tempfile.TemporaryDirectory(prefix="superqode-rlm-pilot-") as temporary:
                    root = Path(temporary)
                    for name, body in task.get("files", {}).items():
                        path = root / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(body)
                    source_hash = hashlib.sha256(
                        json.dumps(task["files"], sort_keys=True).encode()
                    ).hexdigest()
                    if live:
                        from superqode.pipy.ai.models import resolve_model

                        selected_model = resolve_model(model, provider=provider)
                        source = None
                    else:
                        from superqode.pipy.ai import FakeStream, text_response, tool_response
                        from superqode.pipy.messages import ToolCall
                        from superqode.pipy.stream import Model

                        selected_model = Model("scripted-smoke", "offline")
                        solution = task.get("smoke_solution")
                        if not solution:
                            raise ValueError("Offline cases need smoke_solution fixture edits")
                        if profile in {"hybrid", "hybrid-selective"}:
                            import shlex

                            script = "from pathlib import Path; " + "; ".join(
                                f"Path({name!r}).parent.mkdir(parents=True, exist_ok=True); Path({name!r}).write_text({body!r})"
                                for name, body in solution.items()
                            )
                            command = (
                                "python3 -c " + shlex.quote(script)
                                if sandbox == "docker"
                                else shlex.quote(sys.executable) + " -c " + shlex.quote(script)
                            )
                            args, tool = {"command": command, "wait": 5}, "bash"
                        else:
                            args = {
                                "code": "\n".join(
                                    f"workspace.write({name!r}, {body!r})"
                                    for name, body in solution.items()
                                )
                            }
                            tool = "python"
                        source = FakeStream(
                            [
                                tool_response(ToolCall(id="edit", name=tool, arguments=args)),
                                text_response("Fixture edited"),
                            ]
                        )
                    session = await RLMCodingSession.create(
                        RLMCodingSessionOptions(
                            cwd=root,
                            session_root=output / "sessions",
                            model=selected_model,
                            stream_fn=source,
                            profile=PROFILES[profile],
                            budget_policy=policy,
                            budget_path=str(ledger_path),
                            sandbox=RLMSandboxConfig.from_config({"sandbox": sandbox}),
                            durable_children=False,
                        )
                    )
                    before = ledger.snapshot()
                    started = time.monotonic()
                    error = ""
                    try:
                        response = await asyncio.wait_for(session.prompt(task["prompt"]), timeout)
                        error = (
                            response.error_message or ""
                            if response.stop_reason in {"error", "aborted"}
                            else ""
                        )
                        pending = await session.command_completion_errors()
                        if pending:
                            error = "; ".join(pending)
                        # Grader source is supplied externally, but imported
                        # model-written code still executes inside the boundary.
                        if error:
                            passed, grading = False, "Grader skipped: unsettled or failed work"
                        else:
                            grade = await grade_case(session, task["grader"])
                            passed = grade.returncode == 0
                            grading = (grade.stdout + grade.stderr)[-4000:]
                    except Exception as exc:
                        passed, grading, error = False, "", str(exc) or type(exc).__name__
                    finally:
                        await session.abort()
                        if session.sandbox_backend is not None:
                            await session.sandbox_backend.close()
                        await session.delegation_manager.close()
                    usage = usage_delta(before, ledger.snapshot())
                    rows.append(
                        {
                            "task": task["id"],
                            "profile": profile,
                            "repetition": repetition + 1,
                            "passed": passed,
                            "error": error,
                            "grader_output": grading,
                            "usage": usage,
                            "wall_seconds": time.monotonic() - started,
                            "source_sha256": source_hash,
                            "task_sha256": hashlib.sha256(
                                json.dumps(task, sort_keys=True).encode()
                            ).hexdigest(),
                            "profile_config": PROFILES[profile].to_dict(),
                            "sandbox": sandbox,
                            "provider": provider if live else "offline",
                            "model": model if live else "scripted-smoke",
                        }
                    )
                    with (output / "attempts.jsonl").open("a") as attempt_file:
                        attempt_file.write(json.dumps(rows[-1]) + "\n")
    return _write_report(output, rows, ledger.snapshot(), live, provider, model)


def _write_report(output, rows, usage, live, provider, model, stopped=""):
    results = {}
    for name in sorted({row["profile"] for row in rows}):
        selected = [row for row in rows if row["profile"] == name]
        passed = sum(row["passed"] for row in selected)
        cost = sum(row["usage"]["total"].get("cost_usd", 0) for row in selected)
        unknown = sum(row["usage"]["total"].get("unknown_cost_calls", 0) for row in selected)
        results[name] = {
            "attempts": len(selected),
            "passed": passed,
            "known_cost_usd": cost,
            "cost_per_accepted_task": cost / passed if passed and not unknown and live else None,
            "unknown_cost_calls": unknown,
            "wall_seconds": sum(row["wall_seconds"] for row in selected),
        }
    report = {
        "mode": "live" if live else "scripted-execution-smoke",
        "provider": provider if live else "offline",
        "model": model if live else "scripted-smoke",
        "profiles": results,
        "usage": usage,
        "stopped": stopped,
        "claim": "Exploratory coding pilot only"
        if live
        else "No model quality or cost-saving claim",
    }
    (output / "scorecard.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--provider", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--max-cost-usd", type=float, default=0)
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--sandbox", choices=["host", "docker"], default="host")
    parser.add_argument(
        "--profiles", nargs="+", choices=list(PROFILES), default=["python", "hybrid", "selective"]
    )
    args = parser.parse_args()
    values = vars(args)
    tasks = load_cases(values.pop("tasks"))
    print(json.dumps(asyncio.run(run_pilot(tasks, **values)), indent=2))


if __name__ == "__main__":
    main()
