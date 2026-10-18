#!/usr/bin/env python3
"""Local Gemma baseline/refinement calibration; hidden checks stay outside evidence.

Uses existing repository calibration fixtures. No cloud providers are accepted.
Each target starts from the same frozen files and its own workspace. This small
development pilot is not held-out evidence or proof of general quality gains.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

from superqode.harness.refinement import RefinementCoordinator, RefinementRequest
from superqode.harness.refinement.executor import NativeExecutor
from superqode.harness.refinement.store import write_json
from superqode.harness.refinement.workspace import collect_changes, file_manifest, snapshot
from superqode.harness.templates import codegem_template


async def run(args):
    fixtures = Path(__file__).resolve().parents[1] / "tests/fixtures/harness_calibration"
    tasks = json.loads((fixtures / "tasks.json").read_text())["tasks"]
    if args.cases:
        tasks = [task for task in tasks if task["id"] in args.cases]
    args.output.mkdir(parents=True, exist_ok=False)
    verifier = fixtures / "verify.py"
    verifier_digest = hashlib.sha256(verifier.read_bytes()).hexdigest()
    spec = codegem_template()
    spec = replace(
        spec,
        runtime=replace(
            spec.runtime,
            config={
                "tool_mode": args.tool_mode,
                "temperature": 0.2,
                "context_window": 32768,
                "ollama_base_url": "http://127.0.0.1:11434",
                "max_attempts": 1,
            },
        ),
    )
    rows = []
    for task in tasks:
        seed = args.output / task["id"] / "seed"
        shutil.copytree(
            fixtures / task["workspace"], seed, ignore=shutil.ignore_patterns("__pycache__")
        )
        for target in ("baseline", "refinement"):
            output = seed.parent / target
            job = RefinementRequest(
                task=task["prompt"],
                source=seed,
                output=output,
                spec=spec,
                provider=args.provider,
                model=args.model,
                mode=args.mode,
                k=args.k,
                max_wall_seconds=args.max_seconds,
                max_turns=16,
                max_output_tokens=4096,
            )
            print(f"{task['id']} {target}: starting", flush=True)
            started = time.monotonic()
            if target == "baseline":
                workspace = output / "stages/base/workspace"
                snapshot(seed, workspace, file_manifest(seed))
                executor = NativeExecutor()
                try:
                    async with asyncio.timeout(args.max_seconds):
                        response = await executor.run(
                            job, label="base", prompt=job.task, workspace=workspace, overlay=""
                        )
                    result = {
                        "status": "succeeded" if response["status"] == "complete" else "failed",
                        "response": response,
                    }
                except Exception as exc:
                    result = {"status": "failed", "error": str(exc)}
                finally:
                    await executor.cancel()
                write_json(output / "result.json", result)
                changes, patch = collect_changes(seed, workspace)
                (output / "changes.patch").write_text(patch)
            else:
                result = await RefinementCoordinator(job).run()
                workspace = output / "stages" / result.get("chosen_label", "missing") / "workspace"
            if workspace.is_dir():
                grading = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, str(verifier), task["id"], str(workspace)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                grade = {
                    "passed": grading.returncode == 0,
                    "output": grading.stdout,
                    "error": grading.stderr,
                }
            else:
                grade = {"passed": False, "error": "No selected workspace"}
            if hashlib.sha256(verifier.read_bytes()).hexdigest() != verifier_digest:
                raise RuntimeError("External grading source changed")
            row = {
                "task": task["id"],
                "target": target,
                "execution_status": result["status"],
                "task_passed": result["status"] == "succeeded" and grade["passed"],
                "grade": grade,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "usage": result.get("usage", result.get("response", {}).get("usage", {})),
                "artifact_directory": str(output),
            }
            rows.append(row)
            write_json(output / "external-grade.json", row)
            write_json(
                args.output / "results.json",
                {
                    "provider": args.provider,
                    "model": args.model,
                    "tool_mode": args.tool_mode,
                    "temperature": 0.2,
                    "mode": args.mode,
                    "k": args.k,
                    "grading": "external development fixtures, never supplied to editors",
                    "rows": rows,
                },
            )
            print(
                f"{task['id']} {target}: {row['execution_status']}, checks={'passed' if grade['passed'] else 'failed'}, {row['elapsed_seconds']}s",
                flush=True,
            )
    print(
        json.dumps(
            {
                target: {
                    "passed": sum(row["task_passed"] for row in rows if row["target"] == target),
                    "total": sum(row["target"] == target for row in rows),
                }
                for target in ("baseline", "refinement")
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("ollama", "lmstudio", "llamacpp"), default="ollama")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tool-mode", choices=("native", "json", "auto"), default="json")
    parser.add_argument("--mode", choices=("parallel", "sequential"), default="sequential")
    parser.add_argument("--k", type=int, choices=(1, 2), default=1)
    parser.add_argument("--max-seconds", type=float, default=900)
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=(
            "slug-normalization",
            "deep-config-merge",
            "duration-parser",
            "stable-dependency-order",
            "safe-archive-path",
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.expanduser().resolve()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
