"""WorkOrder input identities and workspace verification, without a new runtime."""

from __future__ import annotations

import os
import hashlib
import json
import subprocess
from pathlib import Path
from superqode.execution_recovery import (
    RecoveryScope,
    input_fingerprint,
    recoverable_call,
    recovery_scope,
)


def workspace_fingerprint(root: Path, *, exclude_paths: tuple[Path, ...] = ()) -> str:
    """Hash Git-visible files (including untracked), or a bounded plain tree.

    Ignored files and SuperQode's own ledgers are excluded. This detects drift;
    it is not a backup or proof that the execution environment is identical.
    """
    root = root.resolve()
    proc = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=root,
        capture_output=True,
        timeout=15,
    )
    if proc.returncode == 0:
        paths = [Path(os.fsdecode(p)) for p in proc.stdout.split(b"\0") if p]
        head = (
            subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, timeout=15)
            .stdout.decode()
            .strip()
        )
    else:
        paths = [p.relative_to(root) for p in root.rglob("*") if p.is_file() or p.is_symlink()]
        head = "no-git"
    excluded = {".git", ".superqode", ".venv", "__pycache__", ".pytest_cache"}
    digest = hashlib.sha256(head.encode())
    consumed = 0
    excluded_files = {
        p.resolve()
        for path in exclude_paths
        for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
    }
    for index, path in enumerate(sorted(set(paths))):
        if set(path.parts) & excluded:
            continue
        if index > 50_000 or consumed > 256 * 1024 * 1024:
            raise ValueError(
                "Workspace is too large for recovery verification; reconciliation required"
            )
        file = root / path
        if file.resolve() in excluded_files:
            continue
        record = {"path": os.fsdecode(path)}
        if file.is_symlink():
            record["symlink"] = os.readlink(file)
        elif file.is_file():
            record["mode"] = file.stat().st_mode & 0o777
            content = hashlib.sha256()
            with file.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    consumed += len(chunk)
                    if consumed > 256 * 1024 * 1024:
                        raise ValueError("Workspace recovery hashing exceeded 256 MiB")
                    content.update(chunk)
            record["content_sha256"] = content.hexdigest()
        else:
            record["missing"] = True
        digest.update(json.dumps(record, sort_keys=True, ensure_ascii=True).encode() + b"\n")
    return digest.hexdigest()
