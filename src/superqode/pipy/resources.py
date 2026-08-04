"""Project context files.

Ported from ``packages/coding-agent/src/core/resource-loader.ts`` of
earendil-works/pi (MIT).

PiPy reads the same project files pi does, so an existing pi or Claude Code
repository needs no changes to work here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Checked in order. Case variants exist because case-insensitive filesystems
#: report whichever name was used at creation.
CONTEXT_FILE_NAMES: tuple[str, ...] = ("AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD")


@dataclass(frozen=True, slots=True)
class ContextFile:
    path: str
    content: str


def load_context_file(directory: str | Path) -> ContextFile | None:
    """Load the first context file present in one directory.

    pi stops at the first candidate rather than merging them. A repository with
    both ``AGENTS.md`` and ``CLAUDE.md`` usually has one shadowing the other, so
    loading both would send near-duplicate instructions to the model. It also
    sidesteps case-insensitive filesystems, where ``AGENTS.md`` and
    ``AGENTS.MD`` are the same file under two names.
    """
    root = Path(directory).expanduser().resolve()
    for name in CONTEXT_FILE_NAMES:
        candidate = root / name
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if content.strip():
            return ContextFile(path=str(candidate), content=content)
    return None


def load_context_files(cwd: str | Path) -> list[ContextFile]:
    """Load project instruction files for a working directory."""
    found = load_context_file(cwd)
    return [found] if found is not None else []


__all__ = ["CONTEXT_FILE_NAMES", "ContextFile", "load_context_file", "load_context_files"]
