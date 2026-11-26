"""Run real local-model Factory trials on isolated, deliberately faulty demo projects.

Uses the same desktop jobs, WorkOrders, protected verifier and release protocol as
the app. Gate continuation and signing are automated DEMO operators, not a claim
of human review or Secure Enclave authentication. Never uses a fixture gateway.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import replace
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(data, indent=2, default=str) + "\n")
    temporary.replace(path)


def git(root, *args):
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "core.hooksPath=.git/disabled-hooks",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def probe_baseline(case, storage):
    from superqode.factory.probes import run_python_probe

    results = []
    with tempfile.TemporaryDirectory(dir=storage) as name:
        candidate = Path(name) / "candidate"
        scratch = Path(name) / "scratch"
        candidate.mkdir()
        scratch.mkdir()
        shutil.copy2(ROOT / "examples/factory/demo/app.py", candidate / "app.py")
        for index, row in enumerate(case["probes"]):
            result = run_python_probe(
                ["python", "app.py", case["id"], json.dumps(row["input"])],
                candidate=candidate,
                scratch=scratch,
                stdin="",
                deadline=time.monotonic() + 15,
            )
            expected = json.dumps(row["expected"], sort_keys=True) + "\n"
            results.append(
                {
                    "id": f"case-{index}",
                    "passed": result.get("kind") == "completed"
                    and result.get("returncode") == 0
                    and result.get("stdout") == expected,
                    **result,
                }
            )
    return results


def create_project(case, project, model, public_key, variant):
    import yaml
    from superqode.factory.templates import factory_template
    from superqode.harness.templates import core_template
    from superqode.harness.loader import harness_spec_to_dict

    project.mkdir(parents=True)
    for name in ("app.py", "self_check.py"):
        shutil.copy2(ROOT / "examples/factory/demo" / name, project / name)
    (project / ".gitignore").write_text(".superqode/\n__pycache__/\n")
    config = project / ".superqode"
    (config / "components").mkdir(parents=True)
    (config / "evaluators").mkdir()
    spec = core_template()
    spec = replace(
        spec,
        model_policy=replace(
            spec.model_policy,
            primary=model,
            reasoning="none",
            temperature=0,
            context_window=16384,
            config={**spec.model_policy.config, "max_iterations": 10, "parallel_tools": False},
        ),
        execution_policy=replace(spec.execution_policy, allow_shell=False, allow_network=False),
        agents=(
            replace(
                spec.agents[0],
                tools=("read", "write", "edit"),
                max_iterations=10,
                system_prompt="Work only in this project. Use read to inspect app.py and self_check.py. Use edit or write to apply the requested fix to app.py when assigned implementation. Do not change other files. Shell is unavailable; the controller runs self-checks. Do not claim tests ran unless their results were provided. Return a short evidence report when your assigned task is done.",
            ),
        ),
    )
    (config / "components/demo.yaml").write_text(
        yaml.safe_dump(harness_spec_to_dict(spec), sort_keys=False)
    )
    from superqode.factory.probes import parse_probes

    probe_name = "cli-probes" if case["id"] == "totals" else case["id"]
    probes = parse_probes((ROOT / f"examples/factory/demo/evals/{probe_name}.json").read_text())
    (config / "evaluators/acceptance.json").write_text(json.dumps(probes, indent=2) + "\n")
    definition = factory_template()
    definition["metadata"]["name"] = "demo-" + case["id"]
    definition["inference"]["harnesses"]["coder"] = {
        "path": ".superqode/components/demo.yaml",
        "model": model,
    }
    definition["data_context"]["files"] = {
        "acceptance": {"path": ".superqode/evaluators/acceptance.json", "purpose": "evaluator"}
    }
    definition["improvement"]["checks"]["regression"] = {
        "command": f"python3 self_check.py {case['id']}",
        "files": [],
        "evaluator": "acceptance",
    }
    definition["orchestration"]["stages"][0]["goal"] = (
        "Inspect app.py and self_check.py. Identify the cause of the requested defect and recommend a minimal fix. Do not write any files."
    )
    if variant == "candidate":
        definition["orchestration"]["stages"][0]["goal"] = (
            "Read app.py and self_check.py. Identify the exact faulty branch, recommend the smallest edit, "
            "and list edge cases the implementer should preserve. Distinguish evidence from assumptions. Do not write files."
        )
    definition["orchestration"]["stages"][1]["goal"] = (
        "Read the investigation evidence and app.py, then use edit or write to implement the requested fix in app.py only. Do not merely describe a patch. Preserve self_check.py. The controller runs its self-check after you finish."
    )
    definition["orchestration"]["stages"][2]["goal"] = (
        "Read the implemented app.py and dependency evidence. Check the requested behavior and edge cases by inspection. Do not modify files. Do not claim you ran commands. The controller runs regression tests and protected acceptance probes separately."
    )
    definition["governance"]["budget"] = {
        "max_workers": 1,
        "max_seconds": 1200,
        "max_tool_calls": 70,
        "max_tokens": 60000,
    }
    definition["governance"]["release_authority"] = {
        "method": "p256-signature",
        "keys": {"demo-controller": {"public_key": public_key}},
        "challenge_ttl_seconds": 120,
    }
    (config / "factory.yaml").write_text(yaml.safe_dump(definition, sort_keys=False))
    git(project, "init", "-q")
    git(project, "config", "user.name", "SuperQode Factory Demo")
    git(project, "config", "user.email", "factory-demo@example.invalid")
    git(project, "config", "commit.gpgsign", "false")
    git(project, "config", "core.hooksPath", ".git/disabled-hooks")
    git(project, "add", "app.py", "self_check.py", ".gitignore")
    git(
        project,
        "add",
        "-f",
        ".superqode/factory.yaml",
        ".superqode/components/demo.yaml",
        ".superqode/evaluators/acceptance.json",
    )
    git(project, "commit", "-qm", "Pin faulty demo application and Factory contract")


def job(service, project_id, run, action, record, checkpoint, **extra):
    started = service.dispatch(
        "factory.action.start",
        {
            "project": project_id,
            "run": run,
            "factory_action": action,
            "confirmed": True,
            "command_id": f"demo-{action}-{len(record['jobs'])}",
            **extra,
        },
    )
    entry = {"id": started["id"], "action": action, "status": "running"}
    record["jobs"].append(entry)
    checkpoint()
    deadline = time.monotonic() + 1220
    while True:
        state = service.dispatch("jobs.get", {"id": started["id"]})
        if state["status"] not in {"queued", "running", "needs_approval", "cancelling"}:
            entry.update(status=state["status"], result=state.get("result"))
            checkpoint()
            if state["status"] != "completed":
                raise RuntimeError(f"{action} job {state['status']}: {state.get('result')}")
            return state.get("result") or {}
        if time.monotonic() > deadline:
            service.dispatch("jobs.cancel", {"id": started["id"]})
            raise TimeoutError("Demo job exceeded its wall-time bound")
        time.sleep(0.5)


def run_case(case, directory, model, record, checkpoint, key, variant):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from superqode.desktop_service.service import DesktopService
    from superqode.factory import (
        load_factory,
        resolve_factory,
        compile_factory,
        materialize_snapshot,
        admit_factory,
    )
    from superqode.factory.runtime import factory_store
    from superqode.factory.release import issue_challenge, authorize_release, apply_approved
    from superqode.workorders.usage import usage_from_artifacts

    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).decode()
    project = directory / "projects" / variant / case["id"]
    create_project(case, project, model, public, variant)
    record.update(
        project=str(project),
        model=model,
        baseline_commit=git(project, "rev-parse", "HEAD"),
        phase="baseline-verification",
        application_seed_digest=hashlib.sha256(
            (project / "app.py").read_bytes() + (project / "self_check.py").read_bytes()
        ).hexdigest(),
    )
    checkpoint()
    record["baseline_probes"] = probe_baseline(case, directory / "temporary")
    if any(row.get("kind") != "completed" for row in record["baseline_probes"]):
        raise RuntimeError(
            "Protected baseline probes could not execute under the required OS sandbox"
        )
    if all(row["passed"] for row in record["baseline_probes"]):
        raise RuntimeError("Demo defect was not reproduced before model execution")
    plan = compile_factory(
        resolve_factory(load_factory(root=project)), root=project, goal=case["goal"]
    )
    materialize_snapshot(plan)
    order = admit_factory(plan, request_id="demo-" + case["id"], actor="demo-controller")
    again = admit_factory(plan, request_id="demo-" + case["id"], actor="demo-controller")
    assert order.work_order_id == again.work_order_id
    run = order.work_order_id
    record.update(
        run=run,
        factory_digest=plan.snapshot.digest,
        admission_idempotent=True,
        phase="investigate-and-implement",
    )
    write_json(project / ".superqode/demo-plan.json", plan.to_dict())
    checkpoint()
    state_directory = directory / "desktop-state"
    service = DesktopService(state_directory)
    try:
        identity = service.open_project(str(project))["id"]
        job(service, identity, run, "worker", record, checkpoint)
        store = factory_store(project)
        waiting = store.get(run)
        record["tasks_before_restart"] = [
            {"id": t.task_id, "status": t.status.value, "attempts": t.attempts}
            for t in waiting.tasks
        ]
        write_json(project / ".superqode/demo-order.json", waiting.to_dict())
        if [t.status.value for t in waiting.tasks] != [
            "succeeded",
            "succeeded",
            "waiting_for_human",
        ]:
            raise RuntimeError(
                "Worker did not reach the expected verification gate: " + waiting.error
            )
        workspace = next(
            a
            for a in reversed(waiting.artifacts)
            if a.kind == "workspace" and a.metadata.get("scope") == "work-order"
        )
        integration = Path(workspace.path)
        changed = git(integration, "diff", "--name-only", record["baseline_commit"]).splitlines()
        if changed != ["app.py"]:
            raise RuntimeError("Demo proposal changed unexpected files: " + repr(changed))
        patch = "".join(
            difflib.unified_diff(
                (project / "app.py").read_text().splitlines(True),
                (integration / "app.py").read_text().splitlines(True),
                fromfile="baseline/app.py",
                tofile="candidate/app.py",
            )
        )
        (project / ".superqode/demo-candidate.patch").write_text(patch)
        record.update(
            candidate_patch=str(project / ".superqode/demo-candidate.patch"),
            phase="gate-and-controller-restart",
        )
        checkpoint()
    finally:
        service.close()
    # Reopen persisted controller/store, then exercise hold and explicit demo continuation.
    service = DesktopService(state_directory)
    try:
        identity = service.open_project(str(project))["id"]
        store = factory_store(project)
        reopened = store.get(run)
        token = reopened.tasks[2].metadata["gate_digest"]
        before = [(t.task_id, t.attempts) for t in reopened.tasks]
        for decision in ("hold", "approve"):
            store.decide_gate(
                run,
                "verify",
                expected_digest=token,
                decision=decision,
                actor="automated-demo-controller",
                reason="User-authorized isolated demo protocol exercise; not a human review",
            )
            if decision == "hold":
                held = job(service, identity, run, "worker", record, checkpoint)
                assert held["stats"]["claimed"] == 0
        record["gate_exercise"] = {
            "controller_reopened": True,
            "hold_prevented_execution": True,
            "operator": "automated-demo-controller",
            "human_review": False,
        }
        record["phase"] = "verify-stage"
        checkpoint()
        job(service, identity, run, "worker", record, checkpoint)
        completed = factory_store(project).get(run)
        assert all(t.status.value == "succeeded" for t in completed.tasks)
        assert [(t.task_id, t.attempts) for t in completed.tasks[:2]] == before[:2]
        record.update(no_duplicate_completed_tasks=True, phase="protected-acceptance")
        checkpoint()
        verification = job(service, identity, run, "verify", record, checkpoint)
        write_json(project / ".superqode/demo-verification.json", verification)
        verified = factory_store(project).get(run)
        artifact_id = verified.metadata["factory_verification"]["artifact_id"]
        receipt = next(a for a in verified.artifacts if a.artifact_id == artifact_id)
        record["verification"] = json.loads(receipt.content)
        if (
            verification.get("verification_status") != "passed"
            or record["verification"]["status"] != "passed"
        ):
            raise RuntimeError("Protected acceptance held this candidate")
        record["phase"] = "demo-signed-local-apply"
        checkpoint()
        challenge = issue_challenge(run, root=project, key_id="demo-controller")
        proof = {
            "challenge_id": challenge["challenge"]["id"],
            "signature": base64.b64encode(
                key.sign(base64.b64decode(challenge["message"]), ec.ECDSA(hashes.SHA256()))
            ).decode(),
        }
        approved = authorize_release(run, proof, root=project)
        payload = approved.metadata["factory_release"]["payload"]
        job(
            service,
            identity,
            run,
            "apply",
            record,
            checkpoint,
            candidate_id=payload["candidate_id"],
            candidate_digest=payload["candidate_digest"],
        )
        applied = factory_store(project).get(run)
        before_hash = hashlib.sha256((project / "app.py").read_bytes()).hexdigest()
        again = apply_approved(
            run,
            root=project,
            candidate_id=payload["candidate_id"],
            candidate_digest=payload["candidate_digest"],
        )
        assert (
            again.status.value == "merged"
            and hashlib.sha256((project / "app.py").read_bytes()).hexdigest() == before_hash
        )
        record["release_exercise"] = {
            "signature_verified": True,
            "local_apply": True,
            "repeat_apply_idempotent": True,
            "signer": "ephemeral demo software key",
            "human_authorization_tested": False,
            "secure_enclave_tested": False,
            "production_delivery": False,
        }
        record["usage"] = usage_from_artifacts(applied.artifacts).to_dict()
        record["final_status"] = applied.status.value
        record["tasks"] = [
            {"id": t.task_id, "status": t.status.value, "attempts": t.attempts}
            for t in applied.tasks
        ]
        write_json(project / ".superqode/demo-order.json", applied.to_dict())
        record.update(passed=True, phase="complete")
    finally:
        service.close()
    checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="ollama/qwen3.5:9b")
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=("totals", "active", "ordered"),
        default=["totals", "active", "ordered"],
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Replay cases against baseline and candidate Factory revisions",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Authorize real local model calls and automated DEMO gate/signature exercises",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live to run real local model trials; no synthetic gateway is supported")
    if not args.model.startswith(("ollama/", "lmstudio/")):
        parser.error("This demo runner permits only explicit local model routes")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (
        args.output or ROOT / ".superqode/validation" / ("factory-live-demo-" + stamp)
    ).resolve()
    if not output.is_relative_to(ROOT / ".superqode/validation") or output.exists():
        parser.error("Choose a new output directory inside this repository's .superqode/validation")
    output.mkdir(parents=True)
    (output / "temporary").mkdir()
    os.environ.update(
        SUPERQODE_HOME=str(output / "engine-home"),
        SUPERQODE_STATE_DIR=str(output / "desktop-state"),
        TMPDIR=str(output / "temporary"),
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        PYTHONDONTWRITEBYTECODE="1",
    )
    if args.model.startswith("ollama/"):
        os.environ.update(
            OLLAMA_HOST="http://127.0.0.1:11434", OLLAMA_API_BASE="http://127.0.0.1:11434"
        )
    else:
        os.environ["LMSTUDIO_HOST"] = "http://127.0.0.1:1234/v1"
    suite = json.loads((ROOT / "examples/factory/demo/suite.json").read_text())
    report = {
        "format": "superqode.factory-live-demo-report/1",
        "model": args.model,
        "synthetic_model": False,
        "started": stamp,
        "output": str(output),
        "scope": "Three small Python CLI defects; not whole-Factory reliability or production readiness",
        "cases": [],
        "passed": False,
    }
    destination = output / "report.json"

    def checkpoint():
        write_json(destination, report)

    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(
        ec.SECP256R1()
    )  # In-memory test authority shared by both revisions.
    runs = [
        (variant, case)
        for variant in (("baseline", "candidate") if args.compare else ("baseline",))
        for case in suite["cases"]
    ]
    for variant, case in runs:
        if case["id"] not in args.cases:
            continue
        record = {"id": case["id"], "variant": variant, "passed": False, "jobs": []}
        report["cases"].append(record)
        checkpoint()
        started = time.monotonic()
        print(
            json.dumps(
                {
                    "case": case["id"],
                    "variant": variant,
                    "state": "starting",
                    "report": str(destination),
                }
            ),
            flush=True,
        )
        try:
            run_case(case, output, args.model, record, checkpoint, key, variant)
        except Exception as exc:
            record.update(error=str(exc), phase="held")
            project = Path(record["project"]) if record.get("project") else None
            if project is not None and record.get("run"):
                from superqode.factory.runtime import factory_store
                from superqode.workorders.usage import usage_from_artifacts

                order = factory_store(project).get(record["run"])
                record["usage"] = usage_from_artifacts(order.artifacts).to_dict()
                write_json(project / ".superqode/demo-order.json", order.to_dict())
        record["elapsed_seconds"] = round(time.monotonic() - started, 2)
        checkpoint()
        print(
            json.dumps(
                {
                    "case": case["id"],
                    "variant": variant,
                    "passed": record["passed"],
                    "phase": record["phase"],
                    "error": record.get("error"),
                    "seconds": record["elapsed_seconds"],
                }
            ),
            flush=True,
        )
    report.update(
        passed=len(report["cases"]) == len(set(args.cases)) * (2 if args.compare else 1)
        and all(c["passed"] for c in report["cases"]),
        completed=datetime.now(timezone.utc).isoformat(),
    )
    if args.compare:
        baseline = {c["id"]: c for c in report["cases"] if c["variant"] == "baseline"}
        candidate = {c["id"]: c for c in report["cases"] if c["variant"] == "candidate"}
        regressions = [i for i in baseline if baseline[i]["passed"] and not candidate[i]["passed"]]
        report["comparison"] = {
            "baseline_passed": sum(c["passed"] for c in baseline.values()),
            "candidate_passed": sum(c["passed"] for c in candidate.values()),
            "cases_per_variant": len(baseline),
            "regressions": regressions,
            "matching_application_seeds": all(
                baseline[i].get("application_seed_digest")
                == candidate[i].get("application_seed_digest")
                for i in baseline
            ),
            "factory_change": "Only the investigation stage goal is more explicit; harness, model, permissions, probes and demo authority stay fixed",
            "quality_improvement_demonstrated": not regressions
            and sum(c["passed"] for c in candidate.values())
            > sum(c["passed"] for c in baseline.values()),
            "interpretation": "Descriptive three-case replay, not an optimizer adoption receipt or statistical quality claim",
        }
    checkpoint()
    print(json.dumps({"passed": report["passed"], "report": str(destination)}), flush=True)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
