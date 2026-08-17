"""Durable record of which capabilities a user has already reached.

Stores milestones so the TUI can reveal one relevant capability at a time and
avoid repeating itself. The file is local and safe to delete; losing it only
means a hint may be shown again.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

#: Milestones the TUI records. Names are stable; they are persisted.
MILESTONES = (
    "connected",  # any successful connection
    "connected_closed_harness",  # Closed key path (Factory droid-key)
    "task_completed",  # the agent finished a run
    "second_session",  # came back to the same repository
    "switched_harness",  # changed harness at least once
    "compared_harnesses",  # changed harness twice, so comparison is meaningful
    "built_harness",  # imported, cloned, or authored a HarnessSpec
    "ran_eval",  # measured a harness
    "used_memory",  # stored an explicit memory
    "explored",  # opened the capability browser
    "toured",  # opened the ownership ladder
    "edited_files",  # the agent changed files on disk
    "ran_shell",  # the agent ran a shell command
    "hit_an_error",  # a run or a check failed
    "used_skill",  # a local skill was loaded into a run
    "used_mcp",  # an MCP server is attached
    "connected_open_harness",  # Open-harness key/local connect succeeded
)


def record_command_used(command: str) -> None:
    """Record that a command root has been run at least once.

    Tracked separately from milestones: milestones record what became
    possible, this records what no longer needs suggesting.
    """
    root = str(command or "").strip().lstrip(":").split()[0:1]
    if not root:
        return
    progress = load_progress()
    if root[0] not in progress.commands_used:
        progress.commands_used.add(root[0])
        save_progress(progress)


def command_used(command: str) -> bool:
    root = str(command or "").strip().lstrip(":").split()[0:1]
    return bool(root) and root[0] in load_progress().commands_used


def clear_progress_cache() -> None:
    """Forget the in-memory copy, so a new state directory is picked up."""
    _CACHE.clear()


def state_dir() -> Path:
    """Return where progress lives, honouring ``SUPERQODE_PROGRESS_DIR``.

    Milestones are per-user, so the default is the home directory. The
    override keeps test runs and automation out of a real user's state.
    """
    override = os.environ.get("SUPERQODE_PROGRESS_DIR", "").strip()
    return Path(override) if override else Path.home() / ".superqode"


def progress_path() -> Path:
    return state_dir() / "progress.json"


#: Pre-milestone marker. Its presence means "this user connected at least once"
#: and is migrated into the milestone set on first read.
def legacy_marker_path() -> Path:
    return state_dir() / ".onboarded"


@dataclass
class Progress:
    """Milestones reached and hints already shown."""

    milestones: set[str] = field(default_factory=set)
    hints_shown: set[str] = field(default_factory=set)
    commands_used: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "milestones": sorted(self.milestones),
            "hints_shown": sorted(self.hints_shown),
            "commands_used": sorted(self.commands_used),
        }


#: Read once per process; milestone checks and hint lookups are frequent.
_CACHE: dict[str, "Progress"] = {}


def load_progress() -> Progress:
    """Return the milestone state, reading from disk at most once per process."""
    cached = _CACHE.get("progress")
    if cached is not None:
        return cached
    progress = _read_progress()
    _CACHE["progress"] = progress
    return progress


def _read_progress() -> Progress:
    """Read the milestone file, migrating the pre-milestone marker if present."""
    path = progress_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Progress(
            milestones=set(raw.get("milestones") or ()),
            hints_shown=set(raw.get("hints_shown") or ()),
            commands_used=set(raw.get("commands_used") or ()),
        )
    except (OSError, ValueError):
        pass

    progress = Progress()
    try:
        if legacy_marker_path().exists():
            progress.milestones.add("connected")
    except OSError:
        pass
    return progress


def save_progress(progress: Progress) -> None:
    """Persist milestones. Never raises: this is a convenience, not state."""
    _CACHE["progress"] = progress
    path = progress_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(progress.to_dict(), indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def record_milestone(name: str) -> Progress:
    """Mark one milestone as reached and return the updated progress."""
    progress = load_progress()
    if name not in progress.milestones:
        progress.milestones.add(name)
        save_progress(progress)
    return progress


def mark_hint_shown(name: str) -> None:
    progress = load_progress()
    if name not in progress.hints_shown:
        progress.hints_shown.add(name)
        save_progress(progress)


@dataclass(frozen=True)
class Hint:
    """One capability reveal, shown at most once per user."""

    id: str
    requires: tuple[str, ...]  # milestones that must all be reached
    blocked_by: tuple[str, ...]  # milestones that make this hint redundant
    command: str
    headline: str
    detail: str


#: Reveal order. Each hint is gated on the milestones that make it relevant.
HINTS: tuple[Hint, ...] = (
    # Edit and shell hints come first: they gate the commands that make a
    # run reviewable and reversible.
    Hint(
        id="diff",
        requires=("edited_files",),
        blocked_by=(),
        command=":diff",
        headline="See exactly what the agent changed",
        detail="Every edit, as a diff, before any of it reaches a commit.",
    ),
    Hint(
        id="undo",
        requires=("edited_files", "hit_an_error"),
        blocked_by=(),
        command=":undo",
        headline="Roll back the last agent edit",
        detail="Files return to what they were. The session keeps its history.",
    ),
    Hint(
        id="trust",
        requires=("ran_shell",),
        blocked_by=(),
        command=":trust",
        headline="Stop approving the same command every time",
        detail="Decide once what this repository may run without asking.",
    ),
    Hint(
        id="sandbox",
        requires=("ran_shell", "hit_an_error"),
        blocked_by=(),
        command=":sandbox",
        headline="Run commands away from your shell",
        detail="An OS sandbox on macOS and Linux, with the network off by default.",
    ),
    Hint(
        id="memory",
        requires=("task_completed",),
        blocked_by=("used_memory",),
        command=":memory remember",
        headline="Keep what this repository taught the agent",
        detail="Facts you store survive every session, harness and agent switch.",
    ),
    Hint(
        id="sessions",
        requires=("second_session",),
        blocked_by=(),
        command=":tree",
        headline="Your sessions branch and resume",
        detail="Every session is durable. Fork one to try a second approach.",
    ),
    Hint(
        id="switch",
        requires=("task_completed", "connected"),
        blocked_by=("switched_harness",),
        command=":harness switch",
        headline="Try another harness on this same session",
        detail="Context is replayed, so comparing agents costs you nothing.",
    ),
    Hint(
        id="eval",
        requires=("compared_harnesses",),
        blocked_by=("ran_eval",),
        command=":eval",
        headline="Stop guessing which harness is better",
        detail="Score them on your repository with tasks, rubrics and gates.",
    ),
    Hint(
        id="optimize",
        requires=("built_harness", "ran_eval"),
        blocked_by=(),
        command=":harness optimize",
        headline="Generate better candidates from recorded evidence",
        detail="Failure mining and held-out evaluation, with promotion and rollback.",
    ),
    Hint(
        id="factory",
        requires=("ran_eval",),
        blocked_by=(),
        command=":work",
        headline="Run verified work across repositories",
        detail="WorkOrders give durable tasks, isolated workers, checks and reviews.",
    ),
    Hint(
        id="skills",
        requires=("task_completed", "edited_files"),
        blocked_by=("used_skill",),
        command=":skills add",
        headline="Write the instruction down once",
        detail="A skill is guidance the agent follows in every later session.",
    ),
    Hint(
        id="mcp",
        requires=("task_completed", "used_memory"),
        blocked_by=("used_mcp",),
        command=":mcp",
        headline="Give the agent tools beyond this repository",
        detail="Databases, browsers, issue trackers and your own internal APIs.",
    ),
    Hint(
        id="benchmark",
        requires=("ran_eval",),
        blocked_by=(),
        command=":benchmark",
        headline="Score this harness against a standard suite",
        detail="Comparable numbers, not just numbers against your own tasks.",
    ),
    Hint(
        id="share",
        requires=("task_completed", "second_session"),
        blocked_by=(),
        command=":share",
        headline="Hand this session to someone else",
        detail="The transcript, the diffs and the harness that produced them.",
    ),
)


def next_hint(progress: Progress | None = None) -> Hint | None:
    """Return the first unseen hint whose milestones are satisfied, or None."""
    state = progress or load_progress()
    for hint in HINTS:
        if hint.id in state.hints_shown:
            continue
        if not set(hint.requires) <= state.milestones:
            continue
        if set(hint.blocked_by) & state.milestones:
            continue
        # Skip commands the user has already run.
        root = hint.command.lstrip(":").split()[0]
        if root in state.commands_used:
            continue
        return hint
    return None


def milestones_reached(names: Iterable[str]) -> bool:
    return set(names) <= load_progress().milestones


__all__ = [
    "HINTS",
    "MILESTONES",
    "Hint",
    "Progress",
    "legacy_marker_path",
    "load_progress",
    "mark_hint_shown",
    "milestones_reached",
    "next_hint",
    "progress_path",
    "record_milestone",
    "save_progress",
    "state_dir",
]
