"""Project context files.

Ported from ``packages/coding-agent/src/core/resource-loader.ts`` of
earendil-works/pi (MIT).

PiPy reads the same project files pi does, so an existing pi or Claude Code
repository needs no changes to work here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import agent_dir

#: Checked in order. Case variants exist because case-insensitive filesystems
#: report whichever name was used at creation.
CONTEXT_FILE_NAMES: tuple[str, ...] = (
    "AGENTS.override.md",
    "AGENTS.md",
    "AGENTS.MD",
    "CLAUDE.md",
    "CLAUDE.MD",
)


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
            content = candidate.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if content.strip():
            return ContextFile(path=str(candidate.resolve()), content=content)
    return None


def load_context_files(cwd: str | Path) -> list[ContextFile]:
    """Load PiPy global rules, then ancestors from root to working directory.

    A local override replaces only that directory's rules. Canonical paths
    prevent a symlinked global directory from loading the same file twice.
    The real pi user directory is never read implicitly.
    """
    root = Path(cwd).expanduser().resolve()
    result: list[ContextFile] = []
    seen: set[str] = set()
    for directory in (agent_dir(), *reversed(root.parents), root):
        found = load_context_file(directory)
        if found is not None and found.path not in seen:
            seen.add(found.path)
            result.append(found)
    return result


def load_system_prompt_files(cwd: str | Path) -> tuple[ContextFile | None, ContextFile | None]:
    """Select one replacement and one append file, project before global.

    Match the existing skill/template precedence: .pi, .superqode/pipy,
    then the PiPy agent directory. These are text resources, never code.
    """
    root = Path(cwd).expanduser().resolve()
    directories = (root / ".pi", root / ".superqode" / "pipy", agent_dir())

    def first(name: str) -> ContextFile | None:
        for directory in directories:
            path = directory / name
            try:
                content = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            if content.strip():
                return ContextFile(str(path.resolve()), content)
        return None

    return first("SYSTEM.md"), first("APPEND_SYSTEM.md")


__all__ = [
    "CONTEXT_FILE_NAMES",
    "ContextFile",
    "load_context_file",
    "load_context_files",
    "load_system_prompt_files",
]
