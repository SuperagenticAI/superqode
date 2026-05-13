"""Compact workspace change summaries for clean agent output."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FileChange:
    """One changed file from git status/diff."""

    path: str
    status: str
    additions: Optional[int] = None
    deletions: Optional[int] = None


@dataclass(frozen=True)
class WorkspaceChangeSnapshot:
    """Snapshot of git-visible workspace changes."""

    files: Dict[str, FileChange] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceChangeSummary:
    """Changed files after a harness run."""

    files: List[FileChange]
    diff: str = ""

    @property
    def total_additions(self) -> int:
        return sum(item.additions or 0 for item in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(item.deletions or 0 for item in self.files)

    def to_dict(self) -> dict:
        return {
            "file_count": len(self.files),
            "additions": self.total_additions,
            "deletions": self.total_deletions,
            "files": [
                {
                    "path": item.path,
                    "status": item.status,
                    "additions": item.additions,
                    "deletions": item.deletions,
                }
                for item in self.files
            ],
        }


def capture_workspace_changes(cwd: Path) -> WorkspaceChangeSnapshot:
    """Capture current git-visible changes."""
    status = _git(cwd, ["status", "--porcelain=v1"])
    if status is None:
        return WorkspaceChangeSnapshot()

    numstat = _parse_numstat(_git(cwd, ["diff", "--numstat"]) or "")
    files: Dict[str, FileChange] = {}
    for line in status.splitlines():
        if not line:
            continue
        status_code = line[:2].strip() or "?"
        path = _status_path(line[3:])
        additions, deletions = numstat.get(path, (None, None))
        files[path] = FileChange(
            path=path,
            status=status_code,
            additions=additions,
            deletions=deletions,
        )
    return WorkspaceChangeSnapshot(files=files)


def summarize_workspace_changes(
    cwd: Path,
    before: Optional[WorkspaceChangeSnapshot] = None,
    include_diff: bool = False,
) -> WorkspaceChangeSummary:
    """Return changes that are new or changed since a baseline snapshot."""
    before = before or WorkspaceChangeSnapshot()
    after = capture_workspace_changes(cwd)

    changed = []
    for path, item in after.files.items():
        if before.files.get(path) != item:
            changed.append(item)
    changed.sort(key=lambda item: item.path)

    diff = (
        _git(cwd, ["diff", "--", *[item.path for item in changed]])
        if include_diff and changed
        else ""
    )
    return WorkspaceChangeSummary(files=changed, diff=diff or "")


def render_change_summary(summary: WorkspaceChangeSummary, mode: str = "summary") -> str:
    """Render workspace changes for CLI output."""
    if not summary.files or mode == "none":
        return ""

    total = len(summary.files)
    additions = summary.total_additions
    deletions = summary.total_deletions
    header = f"Changes: {total} file{'s' if total != 1 else ''}"
    if additions or deletions:
        header += f" (+{additions} -{deletions})"

    if mode == "summary":
        return f"{header}. Use `--changes files` or `--changes diff` to inspect details."

    if mode == "files":
        lines = [header]
        for item in summary.files:
            stats = ""
            if item.additions is not None or item.deletions is not None:
                stats = f" (+{item.additions or 0} -{item.deletions or 0})"
            lines.append(f"- {item.status} {item.path}{stats}")
        return "\n".join(lines)

    if mode == "diff":
        if summary.diff.strip():
            return f"{header}\n\n{summary.diff.rstrip()}"
        return header

    return ""


def _git(cwd: Path, args: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_numstat(output: str) -> Dict[str, tuple[Optional[int], Optional[int]]]:
    stats: Dict[str, tuple[Optional[int], Optional[int]]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        additions = _int_or_none(parts[0])
        deletions = _int_or_none(parts[1])
        path = parts[2]
        stats[path] = (additions, deletions)
    return stats


def _int_or_none(value: str) -> Optional[int]:
    try:
        return int(value)
    except ValueError:
        return None


def _status_path(raw_path: str) -> str:
    if " -> " in raw_path:
        return raw_path.rsplit(" -> ", 1)[1].strip('"')
    return raw_path.strip('"')
