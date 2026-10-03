"""Addressable predecessor findings with deterministic source validity checks."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sqlite3
from dataclasses import replace
from pathlib import Path

from superqode.harness.context_artifacts import ContextArtifactStore


def evidence_config(order):
    value = order.metadata.get("evidence_reuse")
    return {"enabled": True} if value is True else dict(value) if isinstance(value, dict) else {}


def source_manifest(root: Path, *, max_files=2000, max_bytes=20_000_000, env_names=()):
    """Bounded tracked/untracked inventory, including deletion and new-file inputs.

    No model-selected paths are presumed to form a complete dependency set.
    Non-Git repositories or incomplete inventories explicitly remain unknown.
    """
    root = root.resolve()
    manifest = {
        "version": 1,
        "complete": False,
        "sources": {},
        "revision": "",
        "repository_identity": "",
        "environment": "",
    }
    try:

        def git(*args):
            return subprocess.run(
                ["git", "-C", str(root), *args], check=True, capture_output=True, timeout=10
            ).stdout

        manifest["revision"] = git("rev-parse", "HEAD").decode().strip()
        common = git("rev-parse", "--git-common-dir").decode().strip()
        manifest["repository_identity"] = str((root / common).resolve())
        names = sorted(
            set(git("ls-files", "-co", "--exclude-standard", "-z").decode().split("\0")) - {""}
        )
        names = [
            name
            for name in names
            if not name.startswith(
                (
                    ".superqode/workorders/",
                    ".superqode/sessions/",
                    ".superqode/context/",
                    ".pi/sessions/",
                    ".sessions/",
                )
            )
        ]
        if len(names) > max_files:
            return manifest
        total = 0
        for name in names:
            path = root / name
            if not path.resolve().is_relative_to(root):
                return manifest
            if not path.is_file():
                manifest["sources"][name] = "missing"
                continue
            stamp = path.stat()
            size = stamp.st_size
            total += size
            if total > max_bytes:
                return manifest
            with path.open("rb") as stream:
                data = stream.read(size + 1)
            after = path.stat()
            # Reading can change atime; only content identity/change signals
            # determine whether the observation was stable.
            stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
            if len(data) != size or any(
                getattr(after, field) != getattr(stamp, field) for field in stable_fields
            ):
                return manifest
            manifest["sources"][name] = hashlib.sha256(data).hexdigest()
        env = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "variables": {
                name: hashlib.sha256(os.environ.get(name, "").encode()).hexdigest()
                for name in env_names
            },
        }
        manifest["environment"] = hashlib.sha256(
            json.dumps(env, sort_keys=True).encode()
        ).hexdigest()
        manifest["env_names"] = list(env_names)
        manifest["complete"] = True
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        pass
    return manifest


def evidence_validity(manifest, root: Path):
    if (
        not isinstance(manifest, dict)
        or not manifest.get("complete")
        or manifest.get("version") != 1
    ):
        return {"freshness": "unknown", "reason": "incomplete_source_manifest"}
    current = source_manifest(root, env_names=manifest.get("env_names", ()))
    if not current["complete"]:
        return {"freshness": "unknown", "reason": "current_sources_unavailable"}
    for field in ("repository_identity", "sources", "environment"):
        if current[field] != manifest.get(field):
            return {"freshness": "stale", "reason": f"changed_{field}"}
    return {"freshness": "current", "reason": "source_and_environment_hashes_match"}


def publish_evidence(store, order, task, content, workspace: Path, *, actor="", supporting=()):
    config = evidence_config(order)
    if config.get("enabled") is not True:
        return None
    manifest = source_manifest(workspace, env_names=config.get("env_names", ()))
    artifacts = ContextArtifactStore(config.get("store_path"))
    receipts = []
    for source in list(supporting)[:32]:
        if not isinstance(source, dict) or not isinstance(source.get("reference"), str):
            continue
        try:
            observation = artifacts.describe(order.work_order_id, source["reference"])
        except (OSError, ValueError, LookupError, PermissionError, sqlite3.Error):
            continue
        if (
            observation.metadata.get("task_id") != task.task_id
            or observation.metadata.get("verification") != "observed_output"
        ):
            continue
        receipts.append(
            {
                "reference": observation.reference,
                "digest": observation.digest,
                "tool": observation.metadata.get("tool", ""),
            }
        )
    current_order = store.get(order.work_order_id)
    parents = {}
    for dependency in task.dependencies:
        matches = [
            a for a in current_order.artifacts if a.kind == "evidence" and a.task_id == dependency
        ]
        if matches:
            parents[dependency] = matches[-1].artifact_id
    snapshot_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    identity = f"{task.task_id}:{task.attempts}:{hashlib.sha256(content.encode()).hexdigest()}:{snapshot_hash}"
    record = artifacts.put(
        order.work_order_id,
        identity,
        content,
        metadata={
            "tool": "read_context_chunk",
            "arguments": {},
            "manifest": manifest,
            "verification": "reported",
            "task_id": task.task_id,
        },
    )
    return store.add_artifact(
        order.work_order_id,
        kind="evidence",
        task_id=task.task_id,
        digest=record.digest,
        metadata={
            "schema_version": 1,
            "reference": record.reference,
            "manifest": manifest,
            "verification": "reported",
            "parents": parents,
            "supporting": receipts,
        },
        actor=actor,
    )


def artifact_validity(artifact, order, root, seen=frozenset()):
    if artifact.artifact_id in seen:
        return {"freshness": "unknown", "reason": "cyclic_evidence"}
    result = evidence_validity(artifact.metadata.get("manifest"), root)
    if result["freshness"] != "current":
        return result
    producer = next((t for t in order.tasks if t.task_id == artifact.task_id), None)
    if producer is None:
        return {"freshness": "unknown", "reason": "producer_unavailable"}
    parents = artifact.metadata.get("parents", {})
    for dependency in producer.dependencies:
        matches = [a for a in order.artifacts if a.kind == "evidence" and a.task_id == dependency]
        if not matches or dependency not in parents:
            return {"freshness": "unknown", "reason": "incomplete_evidence_dependencies"}
        if matches[-1].artifact_id != parents[dependency]:
            return {"freshness": "stale", "reason": "changed_predecessor_evidence"}
        parent_result = artifact_validity(matches[-1], order, root, seen | {artifact.artifact_id})
        if parent_result["freshness"] != "current":
            return {
                "freshness": parent_result["freshness"],
                "reason": "invalid_predecessor_evidence",
            }
    return result


def dependency_catalog(order, task, workspace: Path):
    result = []
    for dependency in task.dependencies:
        matches = [a for a in order.artifacts if a.kind == "evidence" and a.task_id == dependency]
        if matches:
            artifact = matches[-1]
            result.append(
                {
                    "task_id": dependency,
                    "artifact_id": artifact.artifact_id,
                    "reference": artifact.metadata.get("reference"),
                    "verification": artifact.metadata.get("verification", "reported"),
                    **artifact_validity(artifact, order, workspace),
                }
            )
            sources = artifact.metadata.get("supporting", ())
            for source in sources[:32] if isinstance(sources, (list, tuple)) else ():
                if not isinstance(source, dict) or not isinstance(source.get("reference"), str):
                    continue
                result.append(
                    {
                        "task_id": dependency,
                        "artifact_id": artifact.artifact_id,
                        "reference": source["reference"],
                        "tool": source.get("tool", ""),
                        "verification": "observed_output",
                        "freshness": "unknown",
                        "reason": "historical_tool_output_requires_source_validation",
                    }
                )
    return result


def collect_supporting_evidence(order, task, events, *, invocation_namespace=""):
    """Freeze bounded tool observations with actual call identity and arguments.

    An observed output is a receipt of bytes, not verification of a claim or
    proof that its external inputs are still current.
    """
    config = evidence_config(order)
    if config.get("enabled") is not True:
        return []
    from superqode.systemone.state import redact_evidence

    try:
        artifacts = ContextArtifactStore(config.get("store_path"))
    except (OSError, ValueError, sqlite3.Error):
        return []
    calls, supporting = {}, []
    for event in events:
        data = event.data
        if event.type == "tool_call" and data.get("tool_call_id"):
            calls[data["tool_call_id"]] = data.get("args", data.get("arguments", {}))
        if event.type != "tool_result" or len(supporting) >= 32:
            continue
        meta = data.get("metadata") or {}
        call_id = data.get("tool_call_id", meta.get("invocation_id", ""))
        arguments = meta.get("source_arguments", calls.get(call_id))
        if (
            not call_id
            or not isinstance(arguments, dict)
            or not isinstance(data.get("output"), str)
        ):
            continue
        output = data["output"]
        tool = str(data.get("tool_name") or "")
        try:
            identity = f"observation:{task.task_id}:{task.attempts}:{invocation_namespace}:{call_id}:{hashlib.sha256(output.encode()).hexdigest()}"
            record = artifacts.put(
                order.work_order_id,
                identity,
                output,
                metadata={
                    "tool": tool,
                    "arguments": arguments,
                    "success": data.get("success") is True,
                    "verification": "observed_output",
                    "task_id": task.task_id,
                },
            )
            supporting.append(
                redact_evidence(
                    {
                        "reference": record.reference,
                        "tool": tool,
                        "arguments": arguments,
                        "digest": record.digest,
                    }
                )
            )
        except (OSError, ValueError, PermissionError, sqlite3.Error):
            continue  # Missing observations remain unavailable, never replayed.
    return supporting


def read_workorder_evidence(
    scope, reference: str, root: Path, *, offset=0, limit=4000, permission_manager=None
):
    """Trusted active worker scope, restricted to explicitly assigned predecessors."""
    if scope is None:
        raise LookupError("No active WorkOrder evidence scope")
    order = scope.store.get(scope.work_order_id)
    task = next(t for t in order.tasks if t.task_id == scope.task_id)
    catalog = dependency_catalog(order, task, root)
    item = next((v for v in catalog if v["reference"] == reference), None)
    if item is None:
        raise LookupError("Reference is not assigned dependency evidence")
    store = ContextArtifactStore(evidence_config(order).get("store_path"))
    if permission_manager is not None:
        from superqode.harness.context_artifacts import originating_tool
        from superqode.tools.permissions import Permission

        record = store.describe(order.work_order_id, reference)
        if (
            permission_manager.check_permission(
                originating_tool(record.metadata), record.metadata.get("arguments", {})
            )
            == Permission.DENY
        ):
            raise PermissionError("Originating resource permission revoked")
    page = store.read_page(order.work_order_id, reference, offset=offset, limit=limit)
    return replace(
        page,
        text=f"[WorkOrder evidence: {item['freshness']}; verification: {item['verification']}; {item['reason']}]\n{page.text}",
    )
