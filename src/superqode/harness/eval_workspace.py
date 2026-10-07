"""Disposable evaluation fixtures; this is file isolation, not an OS sandbox."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".superqode",
    }
)
MAX_FIXTURE_FILES = 50_000
MAX_FIXTURE_BYTES = 256 * 1024 * 1024

# Repository-local overrides survive cwd changes and would also reach agent
# tools. Refuse them instead of sanitizing only the fixture setup commands.
GIT_REPOSITORY_OVERRIDES = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_OBJECT_DIRECTORY",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_REPLACE_REF_BASE",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_COMMON_DIR",
    }
)


def _require_independent_git_environment() -> None:
    overrides = sorted(GIT_REPOSITORY_OVERRIDES.intersection(os.environ))
    if overrides:
        raise ValueError(
            "Evaluation cannot inherit Git repository overrides: "
            + ", ".join(overrides)
            + ". Clear these variables before running live evaluation."
        )


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    _require_independent_git_environment()
    return subprocess.run(
        ["git", "--no-optional-locks", *arguments],
        cwd=root,
        capture_output=True,
        timeout=60,
        check=False,
    )


@dataclass(frozen=True)
class EvalWorkspaceSnapshot:
    root: Path
    digest: str
    base_commit: str | None
    file_count: int

    def evidence(self) -> dict:
        return {
            "version": 1,
            "isolation": "disposable-file-copy",
            "fixture_digest": self.digest,
            "base_commit": self.base_commit,
            "git_index": "base-commit" if self.base_commit else None,
            "file_count": self.file_count,
        }

    @contextmanager
    def case(self) -> Iterator[Path]:
        _require_independent_git_environment()
        with tempfile.TemporaryDirectory(prefix="superqode-eval-case-") as directory:
            target = Path(directory).resolve() / "workspace"
            _copy_fixture(self.root, target, self.base_commit)
            yield target


def _copy_fixture(source: Path, target: Path, base_commit: str | None) -> None:
    if base_commit:
        _clone_metadata(source, target, base_commit)
    else:
        target.mkdir()
    shutil.copytree(
        source, target, dirs_exist_ok=True, symlinks=True, ignore=shutil.ignore_patterns(".git")
    )


def _clone_metadata(source: Path, target: Path, base_commit: str) -> None:
    result = _git(
        source,
        "clone",
        "--quiet",
        "--local",
        "--no-hardlinks",
        "--no-checkout",
        "--template=",
        str(source),
        str(target),
    )
    if result.returncode:
        raise ValueError("Could not create independent evaluation Git metadata")
    # No source remote: accidental push must not target the developer's repo.
    if _git(target, "remote", "remove", "origin").returncode:
        raise ValueError("Could not detach evaluation repository from its source")
    if _git(target, "update-ref", "HEAD", base_commit).returncode:
        raise ValueError("Could not pin evaluation Git base")
    if _git(target, "read-tree", base_commit).returncode:
        raise ValueError("Could not initialize evaluation Git index")


@contextmanager
def snapshot_eval_workspace(
    source: str | Path,
    *,
    exclude_paths: tuple[Path, ...] = (),
) -> Iterator[EvalWorkspaceSnapshot]:
    """Freeze Git-visible files or a plain tree, retaining project governance.

    Git metadata is cloned without hardlinks or remotes. Dependencies, caches,
    session ledgers and Git-ignored files are omitted. Symlinks must remain
    within the fixture; absolute internal links are rewritten relative to it.
    Explicit policy.yaml is retained even when .superqode is ignored.
    """
    _require_independent_git_environment()
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise ValueError("Evaluation working directory must exist")
    excluded = {
        item.resolve()
        for path in exclude_paths
        for item in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
    }
    try:
        git_files = _git(source, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    except FileNotFoundError:
        git_files = None
    is_git = git_files is not None and git_files.returncode == 0
    if is_git:
        top = _git(source, "rev-parse", "--show-toplevel")
        is_git = top.returncode == 0 and Path(os.fsdecode(top.stdout).strip()).resolve() == source
    base_commit = None
    if is_git:
        head = _git(source, "rev-parse", "--verify", "HEAD")
        if head.returncode:
            raise ValueError("Commit the fixture's initial Git state before evaluating")
        base_commit = head.stdout.decode().strip()
        paths = {Path(os.fsdecode(value)) for value in git_files.stdout.split(b"\0") if value}
    else:
        paths = set()
        for root, directories, files in os.walk(source, followlinks=False):
            relative = Path(root).relative_to(source)
            directories[:] = [name for name in directories if name not in EXCLUDED_DIRECTORIES]
            paths.update(relative / name for name in files)
            paths.update(relative / name for name in directories)
    policy = Path(".superqode/policy.yaml")
    if (source / policy).is_file() or (source / policy).is_symlink():
        paths.add(policy)
    with tempfile.TemporaryDirectory(prefix="superqode-eval-fixture-") as directory:
        frozen = Path(directory).resolve() / "workspace"
        frozen.mkdir()
        digest = hashlib.sha256((base_commit or "no-git").encode())
        count, consumed = 0, 0
        for relative in sorted(paths):
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Evaluation fixture paths must stay within the workspace")
            if relative != policy and set(relative.parts) & EXCLUDED_DIRECTORIES:
                continue
            source_file = source / relative
            if any(source_file == item or item in source_file.parents for item in excluded):
                continue
            if not source_file.exists() and not source_file.is_symlink():
                continue  # Preserve deleted tracked files as deleted.
            if not source_file.is_symlink() and not source_file.resolve().is_relative_to(source):
                raise ValueError(f"Evaluation fixture path escapes: {relative}")
            if count >= MAX_FIXTURE_FILES:
                raise ValueError("Evaluation fixture exceeds 50,000 files")
            target = frozen / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            record = {"path": relative.as_posix()}
            if source_file.is_symlink():
                try:
                    try:
                        resolved = source_file.resolve(strict=True)
                    except FileNotFoundError:
                        resolved = source_file.resolve(strict=False)
                    destination = resolved.relative_to(source)
                except (ValueError, OSError, RuntimeError) as exc:
                    raise ValueError(f"Evaluation symlink escapes or loops: {relative}") from exc
                link = os.path.relpath(frozen / destination, target.parent)
                target.symlink_to(link)
                record["symlink"] = link
            elif source_file.is_file():
                content = hashlib.sha256()
                with source_file.open("rb") as reader, target.open("wb") as writer:
                    while chunk := reader.read(1024 * 1024):
                        consumed += len(chunk)
                        if consumed > MAX_FIXTURE_BYTES:
                            raise ValueError("Evaluation fixture exceeds 256 MiB")
                        writer.write(chunk)
                        content.update(chunk)
                shutil.copymode(source_file, target)
                record.update(mode=target.stat().st_mode & 0o777, sha256=content.hexdigest())
            elif source_file.is_dir() and not is_git:
                target.mkdir(exist_ok=True)
                record["directory"] = True
            else:
                raise ValueError(f"Evaluation fixture contains a non-file entry: {relative}")
            digest.update(json.dumps(record, sort_keys=True).encode() + b"\n")
            count += 1
        if is_git:
            # Clone only metadata into the immutable seed; never modify source.
            seed = Path(directory).resolve() / "git-seed"
            _clone_metadata(source, seed, base_commit)
            shutil.move(str(seed / ".git"), frozen / ".git")
        yield EvalWorkspaceSnapshot(frozen, "sha256:" + digest.hexdigest(), base_commit, count)
