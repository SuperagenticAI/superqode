"""Project-local operational readiness and explicit, single-order deployment."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import sys
import tempfile
import time
from uuid import uuid4

from superqode import __version__
from .compiler import repository_revision
from .definition import load_factory, project_path
from .snapshot import canonical, digest, resolve_factory

PREFIX = ".superqode/factory-operations"
MAX_FILE = 16_000_000


def path(root, relative):
    return project_path(Path(root).resolve(), PREFIX + "/" + relative)


def read(path, limit=MAX_FILE):
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Operational evidence is missing or exceeds its size limit")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Operational evidence exceeds its size limit")
    return raw


def write(path, raw):
    raw = raw.encode() if isinstance(raw, str) else raw
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def ownership(root):
    from superqode.desktop_service.ownership import Lease

    lease = Lease(path(root, "writer.lock"))
    try:
        yield
    finally:
        lease.close()


_HOST_ACTIONS = {
    "platform": "Run Factory workers on macOS or Linux.",
    "python": "Use Python 3.12 or 3.13 for the Factory worker.",
    "instance-state": "Run `sq factory operations reactivate` after recovery, or recover the instance.",
    "factory": "Fix .superqode/factory.yaml, or run `sq factory init --template fix-and-verify`.",
    "git-baseline": "Commit the application baseline so runs can pin a starting revision.",
    "protected-sandbox": "Install Bubblewrap (Linux) or use macOS so verification can run isolated.",
}


def readiness(
    root,
    *,
    probe=False,
    require_platform="",
    allow_disarmed=False,
    application=False,
    timeout=300,
):
    """No model calls. A structural check alone never certifies a worker host.

    With ``application`` the project's own build, start, health and service
    checks run in a temporary checkout of HEAD. Every finding carries a label:
    configured, execution_tested or quality_evaluated. There is no score.
    """
    from superqode.sandbox.local_sandbox import _backend_for_platform

    root = Path(root).resolve()
    system = platform.system()
    if require_platform not in {"", "Darwin", "Linux"}:
        raise ValueError("Required platform must be Darwin or Linux")
    checks = []

    def check(name, passed, detail):
        checks.append(
            {
                "id": name,
                "passed": bool(passed),
                "detail": detail,
                "label": "configured",
                "action": "" if passed else _HOST_ACTIONS.get(name, ""),
            }
        )

    check(
        "platform",
        system in {"Darwin", "Linux"} and (not require_platform or system == require_platform),
        system,
    )
    check("python", (3, 12) <= sys.version_info[:2] < (3, 14), platform.python_version())
    disarmed = any(path(root, name).exists() for name in ("recovery-required.json", "retired.json"))
    check(
        "instance-state",
        allow_disarmed or not disarmed,
        "Disarmed instance; explicit recovery/reactivation required" if disarmed else "Enabled",
    )
    revision = snapshot_digest = ""
    try:
        snapshot_digest = resolve_factory(load_factory(root=root)).digest
        check("factory", True, snapshot_digest)
    except (ValueError, OSError) as exc:
        check("factory", False, str(exc))
    try:
        revision = repository_revision(root)
        check("git-baseline", True, revision)
    except (ValueError, OSError) as exc:
        check("git-baseline", False, str(exc))
    backend = _backend_for_platform()
    check("protected-sandbox", backend != "none", backend)
    if probe:
        for row in _probe(root):
            row.setdefault("label", "execution_tested")
            row.setdefault(
                "action",
                ""
                if row["passed"]
                else "Protected isolation failed on this host; fix the sandbox before running workers.",
            )
            checks.append(row)
    from .readiness import application_findings

    try:
        findings = application_findings(
            root, execute=application, timeout=timeout, snapshot_digest=snapshot_digest
        )
    except (ValueError, OSError) as exc:
        findings = [
            {
                "id": "application-checks",
                "category": "factory",
                "label": "configured",
                "status": "missing",
                "detail": str(exc),
                "action": "Fix the Factory definition, then check again.",
            }
        ]
    executed = [f for f in findings if f["label"] == "execution_tested"]
    return {
        "format": "superqode.factory-readiness/1",
        "engine_version": __version__,
        "platform": system,
        "snapshot_digest": snapshot_digest,
        "repository_commit": revision,
        "checks": checks,
        "structural_passed": all(c["passed"] for c in checks),
        "probe_executed": probe,
        "worker_ready": probe and all(c["passed"] for c in checks),
        "models_tested": False,
        "release_authorization": False,
        "application": findings,
        "application_executed": application,
        "application_passed": (
            all(f["status"] == "passed" for f in executed) if executed else None
        ),
        "labels": {
            label: sum(f["label"] == label for f in findings)
            for label in ("configured", "execution_tested", "quality_evaluated")
        },
        "actions": [f["action"] for f in [*checks, *findings] if f.get("action")],
    }


def _probe(root):
    from .probes import run_python_probe

    storage = path(root, "temporary")
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    with tempfile.TemporaryDirectory(dir=storage) as folder:
        stage = Path(folder)
        candidate, scratch = stage / "candidate", stage / "scratch"
        candidate.mkdir()
        scratch.mkdir()
        (candidate / "app.py").write_text("print('READY')\n")
        protected = stage / "synthetic-evaluator.txt"
        protected.write_text("synthetic operational isolation check")
        cases = {
            "probe-output": "print('READY')",
            "probe-write-denied": "try:\n open('app.py','w').write('changed')\n print('UNSAFE')\nexcept OSError:\n print('READY')",
            "probe-evaluator-denied": f"try:\n open({str(protected)!r}).read()\n print('UNSAFE')\nexcept OSError:\n print('READY')",
            "probe-network-denied": "import socket\ntry:\n s=socket.socket();s.bind(('127.0.0.1',0));print('UNSAFE')\nexcept OSError:\n print('READY')",
        }
        deadline = time.monotonic() + 30
        for name, code in cases.items():
            result = run_python_probe(
                ["python", "-c", code],
                candidate=candidate,
                scratch=scratch,
                stdin="",
                deadline=deadline,
            )
            passed = (
                result.get("kind") == "completed"
                and result.get("returncode") == 0
                and result.get("stdout") == "READY\n"
            )
            results.append({"id": name, "passed": passed, "evidence": result})
    return results


def _absolute(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
        or ".." in Path(value).parts
        or value == "/"
    ):
        raise ValueError(
            "Deployment paths must be absolute without whitespace, substitutions or traversal"
        )
    return value


def deployment(root, *, target_platform, target_project, python, reference, user="superqode"):
    """Generate an inert service package. Never install, enable or launch it."""
    if target_platform not in {"Darwin", "Linux"}:
        raise ValueError("Choose Darwin or Linux")
    target_project, python = _absolute(target_project), _absolute(python)
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise ValueError("Choose a simple dedicated service user")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", reference):
        raise ValueError("Choose one explicit WorkOrder id")
    root = Path(root).resolve()
    from .runtime import factory_store, validate_factory_order

    order = factory_store(root, read_only=True).get(reference)
    plan = validate_factory_order(order)
    identity = "deploy_" + uuid4().hex
    manifest = {
        "format": "superqode.factory-deployment/1",
        "id": identity,
        "engine_version": __version__,
        "platform": target_platform,
        "project": target_project,
        "python": python,
        "reference": reference,
        "goal": order.goal,
        "execution": "fresh-target-order",
        "user": user,
        "snapshot_digest": plan.snapshot.digest,
        "repository_commit": order.metadata["factory"]["repository_commit"],
        "concurrency": 1,
        "retry": False,
        "max_tasks": 64,
        "once": True,
        "isolation": "worktree",
        "installed": False,
        "release_authorization": False,
    }
    manifest["digest"] = digest(canonical(manifest))
    destination = path(root, "deployments/" + identity)
    manifest_path = target_project + "/" + PREFIX + "/deployments/" + identity + "/manifest.json"
    argv = [python, "-m", "superqode.factory.worker_entry", manifest_path, "--live"]
    with ownership(root):
        destination.mkdir(parents=True, mode=0o700)
        write(destination / "manifest.json", canonical(manifest))
        if target_platform == "Linux":
            # The worker is deliberately one-shot, with no restart/enable section.
            unit = "\n".join(
                [
                    "[Unit]",
                    "Description=SuperQode bounded Factory WorkOrder",
                    "After=network.target",
                    "",
                    "[Service]",
                    "Type=oneshot",
                    "User=" + user,
                    "WorkingDirectory=" + target_project,
                    "ExecStart=" + " ".join(argv),
                    "Restart=no",
                    "UMask=0077",
                    "KillMode=control-group",
                    "TimeoutStopSec=30",
                    "NoNewPrivileges=true",
                    "",
                ]
            )
            write(destination / "worker.service", unit)
        else:
            write(
                destination / "worker.plist",
                plistlib.dumps(
                    {
                        "Label": "dev.superqode.factory." + identity,
                        "ProgramArguments": argv,
                        "WorkingDirectory": target_project,
                        "RunAtLoad": False,
                        "KeepAlive": False,
                        "ProcessType": "Background",
                        "Umask": 0o077,
                    }
                ),
            )
    return {
        **manifest,
        "directory": str(destination),
        "execution_started": False,
        "target_validation": "Run protected readiness probes on the target host before starting",
    }


def run_deployment(manifest_path):
    """Validate on the actual host before handing one order to the existing worker."""
    manifest_path = Path(manifest_path).absolute()
    manifest = json.loads(read(manifest_path, 64_000))
    token = manifest.pop("digest", "")
    if (
        token != digest(canonical(manifest))
        or manifest.get("format") != "superqode.factory-deployment/1"
    ):
        raise ValueError("Deployment manifest changed or is unsupported")
    if (
        manifest.get("engine_version") != __version__
        or manifest.get("platform") != platform.system()
    ):
        raise ValueError("Deployment requires its pinned engine version and actual target platform")
    root = Path(_absolute(manifest["project"])).resolve()
    identity = manifest["id"]
    if not re.fullmatch(r"deploy_[a-f0-9]{32}", identity) or manifest_path != path(
        root, "deployments/" + identity + "/manifest.json"
    ):
        raise ValueError("Deployment manifest must be installed at its pinned project path")
    if Path(manifest["python"]).resolve() != Path(sys.executable).resolve():
        raise ValueError("Use the pinned deployment interpreter")
    from .runtime import factory_store, validate_factory_order, admit_factory
    from .compiler import compile_factory, materialize_snapshot
    from superqode.workorders.worker import WorkOrderWorker, WorkOrderWorkerConfig

    with ownership(root):
        ready = readiness(root, probe=True, require_platform=manifest["platform"])
        if not ready["worker_ready"]:
            raise ValueError("Target protected readiness probes did not pass")
        if (
            ready["snapshot_digest"] != manifest["snapshot_digest"]
            or ready["repository_commit"] != manifest["repository_commit"]
        ):
            raise ValueError("Factory or application baseline changed; generate a new deployment")
        if manifest.get("execution") != "fresh-target-order":
            raise ValueError("Deployment requires fresh target-local work, without queue import")
        # Do not honor edited arbitrary runtime/provider/config switches.
        expected = {
            "concurrency": 1,
            "retry": False,
            "max_tasks": 64,
            "once": True,
            "isolation": "worktree",
        }
        if any(manifest.get(k) != v for k, v in expected.items()):
            raise ValueError("Deployment must retain bounded worker settings")
        store = factory_store(root)
        request_id = "deployment:" + identity
        order = store.find_submission(request_id)
        if order is None:
            snapshot = resolve_factory(load_factory(root=root))
            if snapshot.digest != manifest["snapshot_digest"]:
                raise ValueError("Factory changed during target admission")
            compiled = compile_factory(snapshot, root=root, goal=manifest["goal"])
            materialize_snapshot(compiled)
            order = admit_factory(
                compiled, request_id=request_id, actor="explicit deployment operator"
            )
        plan = validate_factory_order(order, store=store)
        if plan.snapshot.digest != manifest["snapshot_digest"] or order.goal != manifest["goal"]:
            raise ValueError("Deployment receipt differs from its pinned goal or Factory")
        if any(t.status.value == "running" for t in order.tasks) or any(
            r["status"] in {"intent", "uncertain"}
            for r in store.export_evidence(order.work_order_id)["invocations"]
        ):
            raise ValueError("Review running or uncertain prior work before deployment")
        worker = WorkOrderWorker(
            factory_store(root),
            WorkOrderWorkerConfig(worker_id=identity, reference=order.work_order_id, **expected),
        )
        return {
            "stats": asyncio.run(worker.run()).to_dict(),
            "work_order_id": order.work_order_id,
            "source_reference": manifest["reference"],
            "readiness": ready,
            "release_authorization": False,
        }
