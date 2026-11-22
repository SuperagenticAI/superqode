"""Protected artifact verification and conservative SuperGauge evidence emission."""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
from uuid import uuid4

from superqode.gauge import AgentQualityRecord
from superqode.workorders.models import COMPLETED_TASK_STATUSES
from superqode.workorders.integration import (
    capture_integration_candidate,
    IntegrationCandidate,
    work_order_integration_lock,
)
from .definition import project_path, relative_path
from .snapshot import canonical, digest
from .runtime import factory_store, validate_factory_order
from .probes import parse_probes, run_python_probe


def evaluator_contract(plan):
    definition = plan.snapshot.payload["definition"]
    assets = definition["data_context"].get("files", {})
    checks, versions = {}, {}
    for name in definition["orchestration"]["acceptance_checks"]:
        reference = definition["improvement"]["checks"][name].get("evaluator")
        if reference not in assets or assets[reference]["purpose"] != "evaluator":
            raise ValueError(
                f"Check {name} needs a pinned protected evaluator; command-only checks are self-checks"
            )
        path = relative_path(assets[reference]["path"]).as_posix()
        source = plan.snapshot.payload["sources"].get(path)
        if source is None:
            raise ValueError("Protected evaluator is missing from the snapshot")
        checks[name] = parse_probes(source["text"])["cases"]
        versions[name] = {
            "source_digest": source["digest"],
            "manifest_digest": digest(canonical(checks[name])),
        }
    if sum(map(len, checks.values())) > 128:
        raise ValueError("A verification may contain at most 128 protected probes")
    return checks, versions


def _candidate_copy(root, tree, destination, archive, excluded, timeout):
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-rlz", tree],
        capture_output=True,
        timeout=timeout,
        check=True,
    ).stdout
    names, byte_count = {}, 0
    for item in listing.split(b"\0"):
        if not item:
            continue
        metadata, name = item.split(b"\t", 1)
        mode, kind, blob, size = metadata.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError("Verification candidates require regular files without symlinks")
        byte_count += int(size)
        names[name.decode("utf-8")] = (blob.decode(), int(size))
    if len(names) > 10000 or byte_count > 250 * 1024 * 1024:
        raise ValueError("Verification candidate exceeds file or size limits")
    with archive.open("xb") as output:
        subprocess.run(
            ["git", "-C", str(root), "archive", "--format=tar", tree],
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=True,
        )
    if archive.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("Verification candidate archive exceeds 256 MiB")
    hasher = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    total, count, archived = 0, 0, set()
    with tarfile.open(archive) as source:
        for member in source:
            relative = relative_path(member.name)
            if member.isdir():
                continue
            count += 1
            total += member.size
            if count > 10000 or total > 256 * 1024 * 1024:
                raise ValueError("Verification candidate exceeds file or size limits")
            if not member.isfile():
                raise ValueError(
                    "Verification candidates currently require regular files without symlinks"
                )
            archived.add(relative.as_posix())
            expected = names.get(relative.as_posix())
            if expected is None or member.size != expected[1]:
                raise ValueError("Git export attributes changed candidate bytes")
            blob = hashlib.new("sha256" if len(expected[0]) == 64 else "sha1")
            blob.update(f"blob {member.size}\0".encode())
            target = destination / relative
            excluded_file = relative.as_posix() in excluded
            if not excluded_file:
                target.parent.mkdir(parents=True, exist_ok=True)
            with (
                source.extractfile(member) as incoming,
                nullcontext(None) if excluded_file else target.open("xb") as output,
            ):
                while chunk := incoming.read(65536):
                    blob.update(chunk)
                    if output is not None:
                        output.write(chunk)
            if blob.hexdigest() != expected[0]:
                raise ValueError("Git export attributes changed candidate bytes")
            if not excluded_file:
                target.chmod(0o444)
    if archived != set(names):
        raise ValueError(
            "Git export attributes omitted candidate files; verification requires the complete artifact"
        )
    return "sha256:" + hasher.hexdigest()


def verify_factory(reference, *, root=".", timeout=120, actor="verifier"):
    """Evaluate outside agent state; persist missing evidence rather than a false pass."""
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise ValueError("Verification timeout must be between 1 and 300 seconds")
    root = Path(root).resolve()
    store = factory_store(root)
    order = store.get(reference)
    if not order.tasks or any(task.status not in COMPLETED_TASK_STATUSES for task in order.tasks):
        raise ValueError("Factory verification requires completed workflow tasks")
    plan = validate_factory_order(order, store=store)
    if not store.policy_decision(reference, phase="completion").allowed:
        raise ValueError("Factory budget or policy does not permit verification")
    checks, versions = evaluator_contract(plan)
    remaining = order.budget.max_seconds - (time.time() - order.created_at)
    if remaining <= 0:
        raise ValueError("Factory time budget expired before verification")
    timeout = min(timeout, remaining)
    verification_id = "verification_" + uuid4().hex
    with work_order_integration_lock(store, order.work_order_id):
        # Capture and reserve atomically with respect to task integration. Store
        # fencing also prevents two verifiers from publishing competing passes.
        prior = store.get(reference).metadata.get("factory_verification", {})
        if prior.get("state") == "running" and prior.get("expires_at", 0) > time.time():
            raise ValueError("A factory verification is already running")
        candidate = capture_integration_candidate(store, reference, actor=actor)
        if candidate.conflicts:
            raise ValueError("Candidate conflicts must be resolved before verification")
        binding = {
            "factory_digest": plan.snapshot.digest,
            "harness_digest": digest(canonical(plan.snapshot.payload["harnesses"])),
            "candidate_id": candidate.artifact_id,
            "candidate_digest": candidate.digest,
            "candidate_tree": candidate.candidate_tree,
            "baseline_commit": order.metadata["factory"]["repository_commit"],
            "evaluators": versions,
            "cases": [
                {"check": name, "id": row["id"]} for name, rows in checks.items() for row in rows
            ],
        }
        store.begin_factory_verification(
            reference,
            verification_id=verification_id,
            binding=binding,
            timeout=timeout,
            actor=actor,
        )
    report = {
        "format": "superqode.factory-verification/1",
        "id": verification_id,
        "binding": binding,
        "results": [],
        "missing_evidence": [],
        "isolation_applied": False,
        "runtime": {"python": sys.version.split()[0], "libraries": "standard-library-only"},
        "started_at": time.time(),
        "limitations": [
            "Evaluator secrecy during implementation is not established.",
            "This is not release authorization or production certification.",
        ],
    }
    deadline = time.monotonic() + timeout
    try:
        storage = project_path(root, ".superqode/factory/verifications")
        storage.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=verification_id + "-", dir=storage) as temporary:
            stage = Path(temporary)
            copy, scratch = stage / "candidate", stage / "scratch"
            copy.mkdir()
            scratch.mkdir()
            excluded = {
                asset["path"]
                for asset in plan.snapshot.payload["definition"]["data_context"]
                .get("files", {})
                .values()
                if asset["purpose"] == "evaluator"
            }
            report["code_digest"] = _candidate_copy(
                root,
                candidate.candidate_tree,
                copy,
                stage / "candidate.tar",
                excluded,
                max(0.01, deadline - time.monotonic()),
            )
            ready = run_python_probe(
                ["python", "-c", "print('superqode-verifier-ready')"],
                candidate=copy,
                scratch=scratch,
                stdin="",
                deadline=deadline,
            )
            report["sandbox"] = ready.get("backend", "none")
            if (
                ready.get("kind") != "completed"
                or ready.get("returncode") != 0
                or ready.get("stdout") != "superqode-verifier-ready\n"
            ):
                report["missing_evidence"].append(
                    {
                        "kind": "isolation_unavailable",
                        "detail": ready.get("detail")
                        or ready.get("stderr")
                        or "Sandbox readiness probe failed",
                    }
                )
            else:
                report["isolation_applied"] = True
                for check, rows in checks.items():
                    for row in rows:
                        # A distinct scratch directory prevents cross-case state.
                        case_scratch = scratch / f"case-{len(report['results'])}"
                        case_scratch.mkdir()
                        result = run_python_probe(
                            row["argv"],
                            candidate=copy,
                            scratch=case_scratch,
                            stdin=row.get("stdin", ""),
                            deadline=deadline,
                        )
                        passed = (
                            result.get("kind") == "completed"
                            and result.get("returncode") == row.get("returncode", 0)
                            and result.get("stdout") == row["stdout"]
                            and ("stderr" not in row or result.get("stderr") == row["stderr"])
                        )
                        report["results"].append(
                            {
                                "check": check,
                                "id": row["id"],
                                "status": "passed" if passed else "failed",
                                **result,
                            }
                        )
            validate_factory_order(store.get(reference), store=store)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        report["missing_evidence"].append({"kind": "infrastructure_error", "detail": str(exc)})
    report["finished_at"] = time.time()
    try:
        updated = store.finish_factory_verification(
            reference, verification_id=verification_id, report=report, actor=actor
        )
    except ValueError:
        store.add_artifact(
            reference, kind="factory_verification_discarded", content=canonical(report), actor=actor
        )
        raise
    artifact = next(
        a
        for a in updated.artifacts
        if a.artifact_id == updated.metadata["factory_verification"]["artifact_id"]
    )
    record = verification_record(updated, artifact)
    store.add_artifact(
        reference,
        kind="factory_quality_record",
        content=canonical(record),
        digest=digest(canonical(record)),
        metadata={"verification_artifact_id": artifact.artifact_id},
        actor=actor,
    )
    return {
        "work_order": store.get(reference).to_dict(),
        "report": json.loads(artifact.content),
        "record": record,
    }


def verification_record(order, artifact):
    report = json.loads(artifact.content)
    binding = report["binding"]
    record = AgentQualityRecord(
        profile={"id": "sg/coding-agent", "version": "0.1", "tier": "T1"},
        subject={
            "agent": order.metadata["factory"]["name"],
            "harness_digest": binding["harness_digest"],
            "authority": {
                "sandbox": report.get("sandbox", "none"),
                "egress": "deny-by-default",
                "capabilities": ["artifact.read", "probe.execute"],
            },
        },
        task_set={
            "manifest_digest": digest(canonical(binding["evaluators"])),
            "held_in": len(binding["cases"]),
            "held_out": 0,
            "sealed": False,
        },
    )
    if "code_digest" in report:
        record.subject["code_digest"] = report["code_digest"]
    if report["results"]:
        value = sum(row["status"] == "passed" for row in report["results"]) / len(binding["cases"])
        record.add_measure("task.completion", value, n=len(binding["cases"]), split="held-in")
        record.add_gate(
            "task.completion", "pass" if value == 1 else "fail", floor=1, split="held-in"
        )
    record.add_measure(
        "assurance.evidence_complete",
        not report["missing_evidence"] and len(report["results"]) == len(binding["cases"]),
    )
    record.add_gate(
        "safety.isolation", "pass" if report["isolation_applied"] else "fail", source="native"
    )
    record.assurance = {
        "evaluator_independent": False,
        "evidence": {
            "ledger": f".superqode/workorders/store.sqlite3#{order.work_order_id}/{artifact.artifact_id}",
            "format": report["format"],
            "events": 1,
            "replayable": False,
        },
    }
    record.decision = {
        "verdict": "hold",
        "reason": "Application acceptance evidence; release authority remains separate",
    }
    return record.to_dict()


def prepare_verified_candidate(store, reference, *, actor):
    order = store.get(reference)
    plan = validate_factory_order(order, store=store)
    _, expected = evaluator_contract(plan)
    receipt = order.metadata.get("factory_verification", {})
    if receipt.get("state") != "passed" or receipt.get("binding", {}).get("evaluators") != expected:
        raise ValueError(
            "Factory requires passing protected verification before preparing delivery"
        )
    artifact = next(
        (
            a
            for a in order.artifacts
            if a.kind == "integration_candidate"
            and a.artifact_id == receipt["binding"]["candidate_id"]
        ),
        None,
    )
    if artifact is None:
        raise ValueError("Verified factory candidate artifact is missing")
    metadata = artifact.metadata
    store.mark_ready_to_merge(
        reference, candidate_artifact_id=artifact.artifact_id, metadata=metadata, actor=actor
    )
    return IntegrationCandidate(
        artifact_id=artifact.artifact_id,
        patch=artifact.content,
        digest=artifact.digest,
        files=tuple(metadata["files"]),
        conflicts=tuple(metadata["conflicts"]),
        baseline_tree=metadata["baseline_tree"],
        candidate_tree=metadata["candidate_tree"],
        target_tree=metadata["target_tree"],
        expected_tree=metadata["expected_tree"],
    )
