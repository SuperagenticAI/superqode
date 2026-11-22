"""Encrypted offline runtime checkpoints with same-path, disarmed restoration."""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
from uuid import uuid4
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from superqode import __version__
from superqode.desktop_service.ownership import Lease
from .definition import load_factory
from .maintenance import execution
from .operations import ownership, path, read, write
from .snapshot import canonical, digest, resolve_factory
from .runtime import factory_store

MAGIC = b"SQFACTORY-RUNTIME-1\n"
FORMAT = "superqode.factory-runtime-checkpoint/1"
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 20000
RUNTIME = (
    "factory.yaml",
    "components",
    "harnesses",
    "skills",
    "roles",
    "context",
    "evals",
    "evaluators",
    "factory",
    "workorders",
    "factory-improvements",
    "factory-improvement-fixtures",
    "trials",
    "factory-trials",
    "factory-feedback",
    "factory-campaigns",
    "factory-events",
    "sessions",
)


def _relative(name):
    # Git internals are allowed only in this encrypted offline-image adapter.
    # The normal Factory source path validator continues to reject .git.
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("Checkpoint paths must be canonical project-relative names")
    value = Path(name)
    if value.is_absolute() or ".." in value.parts or value.as_posix() != name or name == ".":
        raise ValueError("Checkpoint paths must stay inside the project")
    return value


def _inside(root, name):
    relative = _relative(name)
    current = Path(root)
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Checkpoint paths cannot follow symbolic links")
    return current


def _hash(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Runtime checkpoint requires a valid standalone Git repository")
    return result.stdout


def _idle(root):
    if not _inside(root, ".git").is_dir():
        raise ValueError(
            "Runtime checkpoint requires its own .git directory, not a linked checkout"
        )
    if _inside(root, ".git/objects/info/alternates").exists():
        raise ValueError("External Git object stores require a separate backup adapter")
    for relative in (".git/index.lock", ".git/HEAD.lock", ".git/shallow.lock"):
        if _inside(root, relative).exists():
            raise ValueError("Finish Git writers before offline maintenance")
    workers = _inside(root, ".superqode/workorders/workers")
    if workers.exists():
        for entry in workers.glob("*.lock"):
            lease = Lease(_inside(root, entry.relative_to(root).as_posix()))
            lease.close()
    db = _inside(root, ".superqode/workorders/store.sqlite3")
    if db.exists():
        store = factory_store(root, read_only=True)
        for order in store.list():
            if order.status.value in {"merging", "checking"} or any(
                t.status.value == "running" for t in order.tasks
            ):
                raise ValueError(
                    "Drain workers and reconcile running delivery before offline maintenance"
                )
            if "factory" not in order.metadata or order.repository != str(root):
                raise ValueError(
                    "Runtime checkpoints require a dedicated project-local Factory store"
                )


def _names(root, *, directories=False):
    names = set()

    def add_tree(relative):
        target = _inside(root, relative)
        if not target.exists():
            return
        if target.is_file() and not directories:
            names.add(relative)
        elif target.is_dir():
            if directories:
                names.add(relative)
            for entry in target.rglob("*"):
                name = entry.relative_to(root).as_posix()
                checked = _inside(root, name)
                if directories and checked.is_dir():
                    names.add(name)
                elif (
                    not directories
                    and checked.is_file()
                    and not name.endswith((".lock", "-wal", "-shm"))
                ):
                    names.add(name)

    add_tree(".git")
    for item in _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(
        b"\0"
    ):
        if item:
            name = item.decode("utf-8")
            _relative(name)
            if not name.startswith(".superqode/") and _inside(root, name).exists():
                add_tree(name)
    for name in RUNTIME:
        add_tree(".superqode/" + name)
    # Deployment files are data; restoring them never installs a supervisor.
    add_tree(".superqode/factory-operations/deployments")
    add_tree(".superqode/factory-operations/retired.json")
    add_tree(".superqode/factory-intake/ledger.json")
    add_tree(".superqode/factory-intake/plans")
    if len(names) > MAX_FILES:
        raise ValueError("Runtime checkpoint exceeds its file count limit")
    return sorted(names)


def _inventory(root, names):
    values = {}
    total = 0
    for name in names:
        source = _inside(root, name)
        metadata = source.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("Checkpoint inputs must be regular, singly linked files")
        total += metadata.st_size
        if total > MAX_BYTES:
            raise ValueError(
                "Runtime checkpoint exceeds 256 MiB; use a larger dedicated backup backend"
            )
        values[name] = {
            "bytes": metadata.st_size,
            "sha256": _hash(read(source, MAX_BYTES)),
            "mode": 0o755 if metadata.st_mode & 0o111 else 0o600,
        }
    return values


def create(root):
    """Capture a stopped instance, including Git objects, queue and worktrees.

    This is a private encrypted backup, not a shareable evidence export. Keys and
    binaries outside this project are deliberately not collected.
    """
    root = Path(root).resolve()
    with ownership(root), execution(root, exclusive=True, require_enabled=False):
        _idle(root)
        snapshot = resolve_factory(load_factory(root=root))
        names = _names(root)
        directories = _names(root, directories=True)
        if len(names) + len(directories) > MAX_FILES:
            raise ValueError("Runtime checkpoint exceeds its entry count limit")
        before = _inventory(root, names)
        identity = "checkpoint_" + uuid4().hex
        stage_parent = path(root, "temporary")
        stage_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(dir=stage_parent) as staging:
            entries = {}
            for name in names:
                source = _inside(root, name)
                raw = read(source, MAX_BYTES)
                if raw.startswith(b"SQLite format 3\x00"):
                    target = Path(staging) / (uuid4().hex + ".sqlite3")
                    with closing(
                        sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
                    ) as incoming:
                        with closing(sqlite3.connect(target)) as outgoing:
                            incoming.backup(outgoing)
                    raw = read(target, MAX_BYTES)
                entries[name] = raw
            if sum(map(len, entries.values())) > MAX_BYTES:
                raise ValueError("Runtime checkpoint exceeds its byte limit")
            if (
                names != _names(root)
                or directories != _names(root, directories=True)
                or before != _inventory(root, names)
            ):
                raise ValueError("Project changed during checkpoint; stop all writers and retry")
            manifest = {
                "format": FORMAT,
                "id": identity,
                "engine_version": __version__,
                "repository": str(root),
                "created": time.time(),
                "commit": _git(root, "rev-parse", "HEAD").decode().strip(),
                "factory_digest": snapshot.digest,
                "entries": {
                    n: {"bytes": len(raw), "sha256": _hash(raw), "mode": before[n]["mode"]}
                    for n, raw in entries.items()
                },
                "directories": directories,
                "restore_mode": "same-path-disarmed",
                "external_credential_stores_included": False,
                "release_authorized": False,
            }
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", canonical(manifest))
                for name, raw in entries.items():
                    archive.writestr("files/" + name, raw)
            key = AESGCM.generate_key(bit_length=256)
            nonce = os.urandom(12)
            payload = MAGIC + nonce + AESGCM(key).encrypt(nonce, buffer.getvalue(), MAGIC)
        key_path = path(root, "backup-keys/" + identity + ".key")
        archive_path = path(root, "backups/" + identity + ".sqfactory-runtime")
        write(key_path, key)
        write(archive_path, payload)
        return {
            "id": identity,
            "path": str(archive_path),
            "sha256": _hash(payload),
            "key_file": str(key_path),
            "key_exported": False,
            "files": len(entries),
            "restore_mode": "same-path-disarmed",
            "release_authorized": False,
            "notice": "Keep the key separately from this private backup. App/OS credential stores and external dependencies are not included.",
        }


def decode(archive_path, key_file, expected):
    from cryptography.exceptions import InvalidTag
    from .handover import _json

    raw = read(Path(archive_path), MAX_BYTES + 16000000)
    key = read(Path(key_file), 32)
    if not expected or _hash(raw) != expected or not raw.startswith(MAGIC) or len(key) != 32:
        raise ValueError("Runtime checkpoint digest, header or key is invalid")
    try:
        offset = len(MAGIC)
        payload = AESGCM(key).decrypt(raw[offset : offset + 12], raw[offset + 12 :], MAGIC)
    except InvalidTag:
        raise ValueError("Runtime checkpoint authentication failed") from None
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        files = archive.infolist()
        if (
            len(files) > MAX_FILES + 1
            or len({f.filename for f in files}) != len(files)
            or any(f.compress_type != zipfile.ZIP_STORED or f.file_size < 0 for f in files)
            or sum(f.file_size for f in files) > MAX_BYTES + 8000000
        ):
            raise ValueError("Runtime checkpoint ZIP inventory is invalid")
        manifest = _json(archive.read("manifest.json"))
        if (
            manifest.get("format") != FORMAT
            or manifest.get("restore_mode") != "same-path-disarmed"
            or manifest.get("release_authorized") is not False
        ):
            raise ValueError("Unsupported runtime checkpoint contract")
        entries = manifest["entries"]
        if not isinstance(entries, dict) or len(entries) > MAX_FILES:
            raise ValueError("Invalid runtime checkpoint index")
        directories = manifest.get("directories", [])
        if (
            not isinstance(directories, list)
            or len(directories) + len(entries) > MAX_FILES
            or any(not isinstance(n, str) for n in directories)
            or len(set(directories)) != len(directories)
        ):
            raise ValueError("Invalid runtime checkpoint directory index")
        directory_names = set(directories)
        for name in [*directories, *entries]:
            relative = _relative(name)
            if name in directory_names and name in entries:
                raise ValueError("Checkpoint directory conflicts with a file")
            if any(
                parent.as_posix() in entries for parent in relative.parents if parent != Path(".")
            ):
                raise ValueError("Checkpoint path has a file as its parent")
        if {f.filename for f in files} != {"manifest.json", *("files/" + n for n in entries)}:
            raise ValueError("Runtime checkpoint contains unindexed files")
        result = {}
        for name, metadata in entries.items():
            if _relative(name).as_posix() != name or metadata.get("mode") not in {0o600, 0o755}:
                raise ValueError("Runtime checkpoint contains unsafe paths or modes")
            content = archive.read("files/" + name)
            if len(content) != metadata["bytes"] or _hash(content) != metadata["sha256"]:
                raise ValueError("Runtime checkpoint indexed bytes changed")
            result[name] = content
        return manifest, result


def restore(archive_path, key_file, *, expected, destination):
    """Claim the original absent path without overwrite; restore while disarmed."""
    manifest, entries = decode(archive_path, key_file, expected)
    target = Path(destination)
    if (
        not target.is_absolute()
        or target != target.resolve()
        or str(target) != manifest["repository"]
        or target.exists()
        or not target.parent.is_dir()
    ):
        raise ValueError("Restore requires the absent original canonical project path")
    if manifest["engine_version"] != __version__:
        raise ValueError("Restore with the pinned engine before rehearsing an upgrade")
    staging = Path(tempfile.mkdtemp(prefix=".factory-restore-", dir=target.parent))
    try:
        for name in manifest.get("directories", []):
            (staging / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, raw in entries.items():
            output = staging / name
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            output.write_bytes(raw)
            output.chmod(manifest["entries"][name]["mode"])
        if resolve_factory(load_factory(root=staging)).digest != manifest["factory_digest"]:
            raise ValueError("Restored Factory does not match its checkpoint")
        marker = {
            "format": FORMAT,
            "checkpoint": manifest["id"],
            "archive_digest": expected,
            "engine_version": __version__,
            "repository": str(target),
            "at": time.time(),
            "execution_enabled": False,
        }
        marker["digest"] = digest(canonical(marker))
        write(staging / ".superqode/factory-operations/recovery-required.json", canonical(marker))
        # mkdir is the no-overwrite commit boundary. An interruption leaves a
        # marked incomplete directory; it can never look like enabled recovery.
        target.mkdir(mode=0o700)
        write(target / ".superqode/factory-operations/recovery-required.json", canonical(marker))
        incomplete = target / ".superqode/factory-operations/restore-incomplete.json"
        write(incomplete, canonical({"checkpoint": manifest["id"], "at": time.time()}))
        for name in manifest.get("directories", []):
            (target / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, raw in entries.items():
            output = target / name
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with output.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            output.chmod(manifest["entries"][name]["mode"])
        if resolve_factory(load_factory(root=target)).digest != manifest["factory_digest"]:
            raise ValueError("Restored Factory changed while writing recovery")
        incomplete.unlink()
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "destination": str(target),
        "checkpoint": manifest["id"],
        "recovery_digest": marker["digest"],
        "execution_enabled": False,
        "release_authorized": False,
    }


def acknowledge(root, expected, *, probe=False):
    """Re-enable only after actual host probes and explicit reconciliation."""
    from .operations import readiness

    root = Path(root).resolve()
    with ownership(root), execution(root, exclusive=True, require_enabled=False):
        marker_path = path(root, "recovery-required.json")
        if path(root, "restore-incomplete.json").exists():
            raise ValueError(
                "An interrupted restore must be inspected and completed before acknowledgement"
            )
        marker = json.loads(read(marker_path, 64000))
        token = marker.pop("digest", "")
        if (
            token != expected
            or digest(canonical(marker)) != expected
            or marker["repository"] != str(root)
        ):
            raise ValueError("Recovery review changed")
        _idle(root)
        if probe is not True:
            raise ValueError(
                "Actual protected host probes are required before re-enabling recovery"
            )
        ready = readiness(root, probe=True, allow_disarmed=True)
        if not ready["worker_ready"]:
            raise ValueError("Recovered host readiness checks did not pass")
        db = _inside(root, ".superqode/workorders/store.sqlite3")
        if db.exists():
            store = factory_store(root)
            with store._transaction() as conn:
                rows = conn.execute(
                    "select status from work_invocations where status in ('intent','uncertain')"
                ).fetchall()
                if rows:
                    raise ValueError("Reconcile uncertain invocations before enabling recovery")
                # Retained signatures remain historical; no old delivery proof is reusable.
                conn.execute("update factory_release_challenges set used=1")
                for order in store.list():
                    if "factory" not in order.metadata:
                        continue
                    metadata = {k: v for k, v in order.metadata.items() if k != "factory_release"}
                    tasks = tuple(
                        replace(
                            t,
                            metadata={k: v for k, v in t.metadata.items() if k != "gate_approval"},
                        )
                        if t.status.value in {"pending", "waiting_for_human", "blocked", "failed"}
                        else t
                        for t in order.tasks
                    )
                    store._save_tx(
                        conn,
                        replace(
                            order,
                            metadata=metadata,
                            tasks=tasks,
                            decision=None
                            if "factory_release" in order.metadata
                            else order.decision,
                        ),
                    )
                    store._append_event_tx(
                        conn,
                        order.work_order_id,
                        "factory.recovered",
                        actor="explicit recovery operator",
                        data={"checkpoint": marker["checkpoint"]},
                    )
        receipt = {
            **marker,
            "digest": expected,
            "acknowledged": time.time(),
            "prior_release_authority_restored": False,
            "host": ready,
        }
        write(path(root, "recoveries/" + marker["checkpoint"] + ".json"), canonical(receipt))
        marker_path.unlink()
        return {
            "execution_enabled": True,
            "release_authorized": False,
            "checkpoint": marker["checkpoint"],
        }
