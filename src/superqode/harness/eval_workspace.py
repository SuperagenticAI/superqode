"""Independent fixture copies for evaluation trials, not an OS sandbox."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

EXCLUDED = {
    ".git",
    ".superqode",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 50_000


def file_manifest(root: Path) -> dict:
    """Bounded content/mode inventory without following symbolic links."""
    rows = {}
    consumed = 0
    pending = [root]
    while pending:
        for path in sorted(pending.pop().iterdir()):
            if path.name in EXCLUDED:
                continue
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                rows[relative] = {"link": os.readlink(path)}
            elif stat.S_ISDIR(info.st_mode):
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                consumed += info.st_size
                if consumed > MAX_BYTES:
                    raise ValueError(
                        "Evaluation fixture exceeds 256 MiB; use a smaller disposable fixture"
                    )
                rows[relative] = {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "mode": stat.S_IMODE(info.st_mode),
                }
            else:
                raise ValueError(f"Evaluation fixtures cannot contain special files: {relative}")
            if len(rows) > MAX_FILES:
                raise ValueError(
                    "Evaluation fixture exceeds 50,000 files; use a smaller disposable fixture"
                )
    return rows


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def changed_files(before: dict, after: dict) -> list[str]:
    return sorted(
        name for name in before.keys() | after.keys() if before.get(name) != after.get(name)
    )


class EvaluationWorkspace:
    """Capture one input before any trials; never write into the source project."""

    def __init__(self, root, *, exclude_paths=()):
        self.source = Path(root).resolve(strict=True)
        self.excluded_files = {
            Path(str(p) + suffix).resolve()
            for p in exclude_paths
            for suffix in ("", "-wal", "-shm")
        }
        self.temporary = None

    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="superqode-eval-")
        try:
            self.root = Path(self.temporary.name)
            self.snapshot = self.root / "fixture"
            self.snapshot.mkdir()
            try:
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
                    cwd=self.source,
                    capture_output=True,
                    timeout=15,
                )
            except FileNotFoundError:
                proc = None
            if proc is not None and proc.returncode == 0:
                self.git_fixture = True
                paths = sorted({Path(os.fsdecode(p)) for p in proc.stdout.split(b"\0") if p})
            else:
                self.git_fixture = False
                # Enumerate plain fixtures without traversing linked directories.
                paths = [Path(name) for name in file_manifest(self.source)]
            consumed = 0
            for index, relative in enumerate(paths):
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Evaluation fixture contains a path outside its root")
                if set(relative.parts) & EXCLUDED:
                    continue
                source = self.source / relative
                if any(source.resolve().is_relative_to(p) for p in self.excluded_files):
                    continue
                if not source.resolve().is_relative_to(self.source):
                    raise ValueError(f"Evaluation fixture link leaves the project: {relative}")
                try:
                    info = source.lstat()
                except FileNotFoundError:
                    continue  # Tracked deletions are part of the input state.
                consumed += info.st_size
                if index >= MAX_FILES or consumed > MAX_BYTES:
                    raise ValueError(
                        "Evaluation fixture is too large; use at most 50,000 files and 256 MiB"
                    )
                target = self.snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if stat.S_ISLNK(info.st_mode):
                    link = os.path.relpath(source.resolve(), source.parent)
                    target.symlink_to(link)
                elif stat.S_ISREG(info.st_mode):
                    shutil.copy2(source, target)
                else:
                    raise ValueError(
                        f"Evaluation fixture contains a submodule or special file: {relative}"
                    )
            self.manifest = file_manifest(self.snapshot)
            self.digest = manifest_digest(self.manifest)
            return self
        except BaseException:
            self.temporary.cleanup()
            raise

    def __exit__(self, *args):
        self.temporary.cleanup()

    @contextmanager
    def trial(self):
        with tempfile.TemporaryDirectory(prefix="trial-", dir=self.root) as directory:
            root = Path(directory) / "project"
            shutil.copytree(self.snapshot, root, symlinks=True)
            if self.git_fixture:
                # A separate repository supports Git-aware agents without linking
                # source metadata, hooks, signing settings or worktree branches.
                environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
                environment.update(
                    GIT_CONFIG_NOSYSTEM="1",
                    GIT_CONFIG_GLOBAL=os.devnull,
                    GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
                    GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
                )
                prefix = [
                    "git",
                    "-c",
                    "core.hooksPath=" + os.devnull,
                    "-c",
                    "user.name=SuperQode Evaluation",
                    "-c",
                    "user.email=evaluation@localhost",
                ]
                for command in (
                    ["init", "--quiet", "--template="],
                    ["add", "--all"],
                    [
                        "commit",
                        "--quiet",
                        "--allow-empty",
                        "--no-gpg-sign",
                        "-m",
                        "Evaluation fixture",
                    ],
                ):
                    subprocess.run(
                        [*prefix, *command],
                        cwd=root,
                        env=environment,
                        check=True,
                        capture_output=True,
                        timeout=15,
                    )
            yield root

    def evidence(self, trial: Path) -> dict:
        changes = changed_files(self.manifest, file_manifest(trial))
        return {
            "mode": "isolated-copy",
            "snapshot_sha256": self.digest,
            "changed_files": changes[:1000],
            "changes_truncated": len(changes) > 1000,
            "source_untouched_by_runner": True,
            "note": "Independent fixture copy for each trial; this is not an OS sandbox. Git metadata, ignored files and dependency caches are excluded.",
        }
