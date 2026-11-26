"""Project readiness: does this repository build, start and answer health checks?

Findings are labelled by how much is known about them, never scored:

- ``configured``: declared in the Factory but not executed here.
- ``execution_tested``: the command ran in a temporary checkout and its exit
  status is recorded.
- ``quality_evaluated``: protected verification passed for this check on the
  current Factory revision.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from .definition import load_factory, project_path

APPLICATION_CATEGORIES = ("build", "start", "health", "service")
REQUIRED_CATEGORIES = ("build", "start", "health")
LABELS = ("configured", "execution_tested", "quality_evaluated")
OUTPUT_TAIL = 2000

_ADVICE = {
    "build": "Add a check with category: build, for example the command that compiles or packages the app.",
    "start": "Add a check with category: start whose command starts the app, waits until it is ready and exits 0.",
    "health": "Add a check with category: health whose command calls the app's health endpoint or smoke test.",
}


def _quality_evaluated(root, snapshot_digest):
    """Check names whose protected verification passed on this Factory revision."""
    from .runtime import factory_store
    from superqode.workorders.store import _require_factory_verification

    if not project_path(root, ".superqode/workorders/store.sqlite3").exists():
        return {}
    if _git(root, "status", "--porcelain", "--untracked-files=all").stdout.strip():
        return {}
    current_tree = _git(root, "rev-parse", "HEAD^{tree}").stdout.strip()
    passed = {}
    for order in factory_store(root, read_only=True).list(limit=200):
        factory = order.metadata.get("factory") or {}
        receipt = order.metadata.get("factory_verification") or {}
        if factory.get("snapshot_digest") != snapshot_digest or receipt.get("state") != "passed":
            continue
        if receipt.get("binding", {}).get("candidate_tree") != current_tree:
            continue
        candidate = next(
            (a for a in reversed(order.artifacts) if a.kind == "integration_candidate"), None
        )
        if candidate is None:
            continue
        try:
            _require_factory_verification(order, candidate.artifact_id)
        except ValueError:
            continue
        for name in (receipt.get("binding") or {}).get("evaluators", {}):
            passed.setdefault(name, order.work_order_id)
    return passed


def _git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=check, timeout=120
    )


def _run(command, cwd, timeout):
    from superqode.sandbox.local_sandbox import build_sandboxed_command, sandbox_available

    plan = (
        build_sandboxed_command(command, cwd, mode="workspace-write")
        if sandbox_available()
        else None
    )
    argv = plan.argv if plan is not None and plan.applied else ["/bin/sh", "-c", command]
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        timed_out = True
    return {
        "returncode": None if timed_out else process.returncode,
        "timed_out": timed_out,
        "seconds": round(time.monotonic() - started, 2),
        "output_tail": output.decode("utf-8", "replace")[-OUTPUT_TAIL:],
        "sandbox": plan.backend if plan is not None and plan.applied else "none",
    }


def application_findings(root, *, execute=False, timeout=300, snapshot_digest=""):
    """Actionable findings for the project's own checks. Executes only when asked."""
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 1800:
        raise ValueError("Application check timeout must be between 1 and 1800 seconds")
    root = Path(root).resolve()
    definition = load_factory(root=root)
    if "apiVersion" not in definition.data:
        return [
            {
                "id": "factory-spec",
                "category": "factory",
                "label": "configured",
                "status": "missing",
                "detail": "This project only has a route policy, not a FactorySpec.",
                "action": "Run `sq factory init --template fix-and-verify` to create one.",
            }
        ]
    checks = definition.data["improvement"]["checks"]
    acceptance = set(definition.data["orchestration"]["acceptance_checks"])
    quality = _quality_evaluated(root, snapshot_digest) if snapshot_digest else {}
    findings = []
    selected = [
        (name, check)
        for name, check in checks.items()
        if check.get("category", "test") in APPLICATION_CATEGORIES
    ]
    workspace = None
    head = ""
    if execute and selected:
        head = _git(root, "rev-parse", "HEAD").stdout.strip()
        storage = project_path(root, ".superqode/factory-operations/temporary")
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace = Path(tempfile.mkdtemp(prefix="readiness-", dir=storage))
        _git(root, "worktree", "add", "--detach", "--quiet", str(workspace), head)
    try:
        for name, check in checks.items():
            category = check.get("category", "test")
            row = {
                "id": name,
                "category": category,
                "command": check["command"],
                "acceptance": name in acceptance,
                "label": "configured",
                "status": "not_run",
            }
            if name in quality and not (execute and category in APPLICATION_CATEGORIES):
                row.update(
                    label="quality_evaluated",
                    status="passed",
                    detail=f"Protected verification passed on run {quality[name]} for this exact application tree and Factory revision; environment checks have not been replayed here.",
                    action="",
                )
            elif workspace is not None and category in APPLICATION_CATEGORIES:
                result = _run(check["command"], workspace, timeout)
                passed = result["returncode"] == 0
                row.update(
                    label="execution_tested",
                    status="passed" if passed else "failed",
                    detail=(
                        f"Exited 0 in {result['seconds']}s against HEAD {head[:12]}."
                        if passed
                        else (
                            f"Timed out after {timeout}s."
                            if result["timed_out"]
                            else f"Exited {result['returncode']} after {result['seconds']}s."
                        )
                    ),
                    action=""
                    if passed
                    else (
                        "Make the command exit once the app reports ready, or raise --timeout."
                        if result["timed_out"]
                        else "Run the command locally, fix the failure shown in output_tail, then check again."
                    ),
                    evidence=result,
                )
            elif category in APPLICATION_CATEGORIES:
                row.update(
                    detail="Declared but not executed in this check.",
                    action="Run `sq factory check --application` to execute it in a temporary checkout.",
                )
            else:
                row.update(
                    detail="Runs during Factory runs"
                    + (" and protected verification." if name in acceptance else "."),
                    action=""
                    if check.get("evaluator") or name not in acceptance
                    else "Add protected evaluator probes so this acceptance check can be verified.",
                )
            findings.append(row)
    finally:
        if workspace is not None:
            _git(root, "worktree", "remove", "--force", str(workspace), check=False)
            _git(root, "worktree", "prune", check=False)
    declared = {check.get("category", "test") for check in checks.values()}
    for category in REQUIRED_CATEGORIES:
        if category not in declared:
            findings.append(
                {
                    "id": "missing-" + category,
                    "category": category,
                    "label": "configured",
                    "status": "missing",
                    "detail": f"No {category} check is declared.",
                    "action": _ADVICE[category],
                }
            )
    return findings
