"""Frozen source snapshots and reviewable changes, without modifying the source."""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from .models import relpath
from .store import digest, job_lock, read_json, verify_digest, verify_manifest, write_json

EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".superqode",
    ".aws",
    ".ssh",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024


def source_files(root: Path):
    """Respect Git ignores where available, with additional credential exclusions."""
    try:
        if not (root / ".git").exists():
            raise ValueError("snapshot is not its own Git root")
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
            capture_output=True,
            timeout=10,
        )
        if proc.returncode == 0:
            candidates = [root / os.fsdecode(name) for name in proc.stdout.split(b"\0") if name]
        else:
            raise ValueError("not a git checkout")
    except (ValueError, OSError, subprocess.TimeoutExpired):
        candidates = []
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [
                name
                for name in dirs
                if name not in EXCLUDED and not (Path(directory) / name).is_symlink()
            ]
            candidates.extend(Path(directory) / name for name in files)
    total = 0
    for path in sorted(set(candidates)):
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if (
            path.name == ".env"
            or path.name.startswith(".env.")
            or path.suffix in {".pem", ".key", ".pyc"}
        ):
            continue
        if path.is_symlink() or any(
            (root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts))
        ):
            raise ValueError(f"Refinement source contains a symlink: {relative}")
        if not path.exists():
            continue
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Refinement only snapshots regular files: {relative}")
        if info.st_size > MAX_FILE:
            raise ValueError(f"Source file exceeds the 2 MiB snapshot limit: {relative}")
        total += info.st_size
        if total > MAX_TOTAL:
            raise ValueError("Source snapshot exceeds 32 MiB; select a smaller source directory")
        yield path, relative.as_posix()


def file_manifest(root: Path):
    return {
        name: {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mode": stat.S_IMODE(path.stat().st_mode),
        }
        for path, name in source_files(root)
    }


def snapshot(source: Path, destination: Path, expected: dict):
    destination.mkdir(parents=True, exist_ok=False)
    for name in expected:
        src, dst = source / name, destination / name
        if src.is_symlink() or not src.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Source changed while snapshotting: {name}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    if file_manifest(destination) != expected or file_manifest(source) != expected:
        raise ValueError("Source changed during snapshot; start a new refinement")


def collect_changes(base: Path, workspace: Path):
    before, after = file_manifest(base), file_manifest(workspace)
    changes, diff = [], []
    for name in sorted(before.keys() | after.keys()):
        if before.get(name) == after.get(name):
            continue
        changes.append({"path": name, "before": before.get(name), "after": after.get(name)})
        left = (base / name).read_bytes() if name in before else b""
        right = (workspace / name).read_bytes() if name in after else b""
        try:
            diff.extend(
                difflib.unified_diff(
                    left.decode().splitlines(keepends=True),
                    right.decode().splitlines(keepends=True),
                    fromfile="a/" + name,
                    tofile="b/" + name,
                )
            )
        except UnicodeDecodeError:
            diff.append(f"Binary file changed: {name}\n")
        if before.get(name, {}).get("mode") != after.get(name, {}).get("mode"):
            diff.append(f"File mode changed: {name}\n")
    return changes, "".join(diff)


def apply_refinement(root: str | Path):
    """Apply an inspected, checked candidate only to its unchanged original source."""
    root = Path(root).resolve()
    with job_lock(root):
        return _apply_refinement(root)


def _replace_file(target, body, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".refinement-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _apply_refinement(root):
    manifest, result = read_json(root / "manifest.json"), read_json(root / "result.json")
    verify_manifest(manifest)
    verify_digest(result, "result_digest", "refinement result")
    if result.get("manifest_identity") != manifest["identity"]:
        raise ValueError("Selected result belongs to a different experiment")
    if result.get("status") != "succeeded" or result.get("validation") != "passed":
        raise ValueError("Application requires a successful candidate with passing explicit checks")
    source, base = Path(manifest["source"]), root / "source"
    if (
        file_manifest(source) != manifest["source_files"]
        or file_manifest(base) != manifest["source_files"]
    ):
        raise ValueError("Source changed after refinement; review/reconcile before applying")
    label = relpath(result["chosen_label"])
    if len(Path(label).parts) != 1:
        raise ValueError("Invalid selected stage")
    stage = root / "stages" / label
    record = read_json(stage / "record.json")
    verify_digest(record, "record_digest", "stage record")
    if (
        record["record_digest"] != result["selected_record_digest"]
        or record["state"] != "complete"
        or not record["ok"]
        or record["editor"]
        or not record["checks"]
        or any(check["status"] != "passed" for check in record["checks"])
        or [check.get("argv") for check in record["checks"]] != manifest["checks"]
    ):
        raise ValueError("Selected stage does not match the validated result")
    workspace = stage / "workspace"
    if digest(file_manifest(workspace)) != record["workspace_digest"]:
        raise ValueError("Candidate changed after validation")
    changes, _ = collect_changes(base, workspace)
    if digest(changes) != result["changes_digest"]:
        raise ValueError("Candidate changes no longer match the selected result")
    # Validate all paths and parent components before the first mutation.
    for change in changes:
        relpath(change["path"])
        if not (source / change["path"]).resolve().is_relative_to(source.resolve()):
            raise ValueError("Destination escapes source")
    # Stage bytes before touching the source; restore completed writes on failure.
    before = {
        item["path"]: (base / item["path"]).read_bytes() if item["before"] else None
        for item in changes
    }
    after = {
        item["path"]: (workspace / item["path"]).read_bytes() if item["after"] else None
        for item in changes
    }
    applied = []
    try:
        for change in changes:
            target = source / change["path"]
            if change["after"] is None:
                target.unlink()
            else:
                _replace_file(target, after[change["path"]], change["after"]["mode"])
            applied.append(change)
    except BaseException:
        for change in reversed(applied):
            target = source / change["path"]
            if change["before"] is None:
                target.unlink(missing_ok=True)
            else:
                _replace_file(target, before[change["path"]], change["before"]["mode"])
        raise
    receipt = {
        "status": "applied",
        "files": [item["path"] for item in changes],
        "source": str(source),
        "result_digest": result["result_digest"],
    }
    write_json(root / "application.json", receipt)
    return receipt
