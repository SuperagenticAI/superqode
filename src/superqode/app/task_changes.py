"""Bounded, read-only task baselines and guarded per-file restoration."""

from __future__ import annotations

import difflib
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class FileState:
    content: bytes | None
    mode: int = 0o644


class TaskChanges:
    """Compare against the pre-task working tree without touching Git's index.

    Clean tracked files use their original index blobs. Dirty and untracked
    files are copied before execution. Unavailable baselines never permit undo.
    """

    FILE_LIMIT = 2_000_000
    MEMORY_LIMIT = 32_000_000

    def __init__(self, cwd: Path):
        self.id = uuid4().hex[:12]
        self.cwd = cwd.resolve()
        self.root = self.cwd
        self.index: dict[str, tuple[str, int]] = {}
        self.before: dict[str, FileState | None] = {}
        self.after: dict[str, FileState] = {}
        self.diffs: dict[str, dict] = {}
        self.undone: set[str] = set()
        self.preexisting: set[str] = set()
        self.used = 0
        self.available = False
        self.finished = False

    def _git(self, *args: str) -> bytes:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(self.root), *args],
            capture_output=True,
            timeout=10,
            check=True,
        )
        return result.stdout

    def _path(self, name: str) -> Path:
        if any(character in name for character in "\n\r\t\0"):
            raise ValueError("This file name cannot be represented safely in task review.")
        path = self.root / name
        # Never follow symlinks (including parent directory links) for undo.
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(self.root):
            raise ValueError("File is outside the task workspace or is a symbolic link.")
        return path

    def _read(self, name: str) -> FileState:
        path = self._path(name)
        if not path.exists():
            return FileState(None)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > self.FILE_LIMIT:
            raise ValueError("File is too large or is not a regular file.")
        return FileState(path.read_bytes(), stat.S_IMODE(info.st_mode))

    def _changed_paths(self) -> set[str]:
        paths = set(self._git("diff", "--name-only", "-z").decode().split("\0"))
        paths.update(
            self._git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
        )
        return paths - {""}

    def capture(self) -> TaskChanges:
        try:
            self.root = Path(self._git("rev-parse", "--show-toplevel").decode().strip()).resolve()
            for row in self._git("ls-files", "--stage", "-z").decode().split("\0"):
                if not row:
                    continue
                meta, name = row.split("\t", 1)
                mode, oid, stage = meta.split()
                if stage != "0" or mode not in {"100644", "100755"}:
                    self.before[name] = None
                else:
                    self.index[name] = (oid, int(mode, 8) & 0o777)
            dirty = self._changed_paths()
            content_overrides = set()
            for row in self._git("ls-files", "--eol", "-z").decode().split("\0"):
                if not row:
                    continue
                metadata, name = row.split("\t", 1)
                endings = metadata.split()
                if len(endings) >= 2 and endings[0][2:] != endings[1][2:]:
                    content_overrides.add(name)
            # Staged content is already represented by the original index blob.
            staged = set(
                self._git("diff", "--cached", "--name-only", "-z").decode().split("\0")
            ) - {""}
            self.preexisting = dirty | staged
            for name in dirty | content_overrides:
                try:
                    state = self._read(name)
                    size = len(state.content or b"")
                    if self.used + size > self.MEMORY_LIMIT:
                        raise ValueError("Task baseline memory limit reached.")
                    self.before[name] = state
                    self.used += size
                except (OSError, ValueError):
                    self.before[name] = None
            self.available = True
        except (OSError, ValueError, subprocess.SubprocessError):
            self.available = False
        return self

    def _baseline(self, name: str) -> FileState | None:
        if name in self.before:
            return self.before[name]
        if name not in self.index:
            ignored = subprocess.run(
                [
                    "git",
                    "--no-optional-locks",
                    "-C",
                    str(self.root),
                    "check-ignore",
                    "-q",
                    "--",
                    name,
                ],
                capture_output=True,
                timeout=10,
            )
            # Ignored files were not enumerated at capture time. Their prior
            # existence is unknown, so never treat them as task-created files.
            return FileState(None) if ignored.returncode == 1 else None
        oid, mode = self.index[name]
        if int(self._git("cat-file", "-s", oid)) > self.FILE_LIMIT:
            return None
        return FileState(self._git("cat-file", "blob", oid), mode)

    def finish(self, reported: list[str]) -> dict[str, dict]:
        if self.finished:
            return self.diffs
        self.finished = True
        if not self.available:
            return {}
        try:
            names = self._changed_paths() | self.preexisting
            names.update(self._git("diff", "--cached", "--name-only", "-z").decode().split("\0"))
            reported_names = set()
            for name in reported:
                path = Path(name)
                path = path if path.is_absolute() else self.cwd / path
                if path.absolute().is_relative_to(self.root):
                    relative = str(path.absolute().relative_to(self.root))
                    names.add(relative)
                    reported_names.add(relative)
            for name in sorted(names - {""}):
                try:
                    before, after = self._baseline(name), self._read(name)
                    if before is None:
                        if name in reported_names:
                            self._unavailable_diff(name)
                        continue
                    if before == after:
                        continue
                    size = len(before.content or b"") + len(after.content or b"")
                    if self.used + size > self.MEMORY_LIMIT:
                        self._unavailable_diff(name)
                        continue
                    self.before[name], self.after[name] = before, after
                    self.used += size
                    old, new = before.content or b"", after.content or b""
                    binary = b"\0" in old or b"\0" in new
                    patch = (
                        "\n".join(
                            difflib.unified_diff(
                                old.decode("utf-8", errors="replace").splitlines(),
                                new.decode("utf-8", errors="replace").splitlines(),
                                fromfile=f"a/{name}" if before.content is not None else "/dev/null",
                                tofile=f"b/{name}" if after.content is not None else "/dev/null",
                                lineterm="",
                            )
                        )
                        if not binary
                        else "Binary content changed."
                    )
                    if before.mode != after.mode:
                        patch = f"old mode {before.mode:o}\nnew mode {after.mode:o}\n" + patch
                    patch = f"diff --git a/{name} b/{name}\n" + patch
                    self.diffs[name] = {
                        "diff_text": patch,
                        "additions": sum(
                            s.startswith("+") and not s.startswith("+++")
                            for s in patch.splitlines()
                        ),
                        "deletions": sum(
                            s.startswith("-") and not s.startswith("---")
                            for s in patch.splitlines()
                        ),
                        "preexisting": name in self.preexisting,
                    }
                except (OSError, ValueError, subprocess.SubprocessError):
                    if name in reported_names or name not in self.preexisting:
                        self._unavailable_diff(name)
                    continue
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return self.diffs

    def _unavailable_diff(self, name: str) -> None:
        self.diffs[name] = {
            "diff_text": f"diff --git a/{name} b/{name}\nTask baseline or preview unavailable. Use :diff to inspect the working tree.",
            "additions": 0,
            "deletions": 0,
            "preexisting": name in self.preexisting,
        }

    def undo(self, name: str) -> str:
        """Restore one file only if it still matches the recorded task result."""
        if name not in self.after:
            raise ValueError("No restorable task change for this file.")
        if self._read(name) != self.after[name]:
            raise ValueError("File changed since this task. Review the newer edits before undoing.")
        path, before = self._path(name), self.before[name]
        if before is None:
            raise ValueError("No baseline is available for this file.")
        if before.content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".superqode-undo-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(before.content)
                os.chmod(temporary, before.mode)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        del self.after[name]
        self.undone.add(name)
        return f"Undid task changes in {name}."
