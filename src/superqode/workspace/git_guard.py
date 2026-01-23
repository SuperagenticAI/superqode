"""
Git Guard - Prevents Git Operations During QE Sessions.

Ensures the immutable repo guarantee by blocking all git operations
that could permanently alter the repository state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set, Tuple


class GitOperationType(Enum):
    """Types of git operations."""

    READ = "read"  # Safe: status, log, diff, show, branch -l
    WRITE = "write"  # Blocked: add, commit, push, merge, rebase
    DESTRUCTIVE = "destructive"  # Blocked: reset --hard, clean -f, checkout -f


class GitOperationBlocked(Exception):
    """Raised when a blocked git operation is attempted."""

    def __init__(self, command: str, reason: str, suggestion: str = ""):
        self.command = command
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(f"Git operation blocked: {reason}")


@dataclass
class GitCommandAnalysis:
    """Analysis of a git command."""

    command: str
    operation_type: GitOperationType
    is_blocked: bool
    reason: str
    suggestion: str = ""


class GitGuard:
    """
    Guards against git operations that would violate the immutable repo guarantee.

    Rules:
    - ❌ No commits
    - ❌ No pushes
    - ❌ No branching/merging/rebasing
    - ❌ No checkout that overwrites changes
    - ❌ No reset that loses changes
    - ❌ No clean that removes files
    - ✅ Read operations allowed (status, log, diff, show)

    Usage:
        guard = GitGuard()

        # Check before executing
        if guard.is_blocked("git commit -m 'test'"):
            raise guard.analyze("git commit -m 'test'").reason

        # Or use the wrapper
        guard.check_command("git push origin main")  # Raises GitOperationBlocked
    """

    # Git commands that are always safe (read-only)
    SAFE_COMMANDS: Set[str] = {
        "status",
        "log",
        "diff",
        "show",
        "branch",
        "tag",
        "ls-files",
        "ls-tree",
        "cat-file",
        "rev-parse",
        "describe",
        "name-rev",
        "shortlog",
        "whatchanged",
        "blame",
        "annotate",
        "grep",
        "log",
        "reflog",
        "remote",
        "config",
        "help",
        "version",
    }

    # Git commands that are blocked (write operations)
    BLOCKED_COMMANDS: Set[str] = {
        "commit",
        "push",
        "pull",
        "fetch",
        "merge",
        "rebase",
        "cherry-pick",
        "revert",
        "reset",
        "checkout",
        "switch",
        "restore",
        "add",
        "rm",
        "mv",
        "clean",
        "stash",
        "tag",
        "branch",
        "remote",
        "submodule",
        "subtree",
        "init",
        "clone",
        "gc",
        "prune",
        "fsck",
        "reflog",
    }

    # Patterns for safe variants of normally blocked commands
    SAFE_PATTERNS: List[Tuple[str, re.Pattern]] = [
        # git branch -l, --list, -a, -r (listing only)
        ("branch", re.compile(r"branch\s+(-[lar]+|--list|--all|--remotes)(\s|$)")),
        # git remote -v, show, get-url (listing only)
        ("remote", re.compile(r"remote\s+(-v|--verbose|show|get-url)(\s|$)")),
        # git tag -l, --list (listing only)
        ("tag", re.compile(r"tag\s+(-l|--list)(\s|$)")),
        # git stash list, show (reading only)
        ("stash", re.compile(r"stash\s+(list|show)(\s|$)")),
        # git config --get, --list (reading only)
        ("config", re.compile(r"config\s+(--get|--list|-l)(\s|$)")),
        # git diff (always safe)
        ("diff", re.compile(r"diff(\s|$)")),
        # git log (always safe)
        ("log", re.compile(r"log(\s|$)")),
        # git status (always safe)
        ("status", re.compile(r"status(\s|$)")),
        # git show (always safe)
        ("show", re.compile(r"show(\s|$)")),
    ]

    # Human-readable reasons for blocking
    BLOCK_REASONS = {
        "commit": "Commits would permanently alter the repository history",
        "push": "Push would send changes to remote repository",
        "pull": "Pull could introduce external changes during QE session",
        "fetch": "Fetch is unnecessary during ephemeral QE session",
        "merge": "Merge would alter branch history",
        "rebase": "Rebase would rewrite commit history",
        "cherry-pick": "Cherry-pick would create new commits",
        "revert": "Revert would create new commits",
        "reset": "Reset could lose tracked changes",
        "checkout": "Checkout could overwrite working changes",
        "switch": "Branch switching is not allowed during QE",
        "restore": "Restore could overwrite working changes",
        "add": "Staging changes is not needed in ephemeral workspace",
        "rm": "Git rm would stage deletions",
        "mv": "Git mv would stage renames",
        "clean": "Git clean could remove untracked files",
        "stash": "Stashing is not needed in ephemeral workspace",
        "tag": "Creating tags is not allowed during QE",
        "branch": "Creating/deleting branches is not allowed during QE",
        "init": "Repository initialization is not allowed",
        "clone": "Cloning is not allowed during QE session",
    }

    SUGGESTIONS = {
        "commit": "Changes are automatically tracked and reverted. Use QIR to document findings.",
        "push": "All findings are saved to .superqode/qe-artifacts/ for review.",
        "add": "File tracking is automatic in ephemeral workspace.",
        "checkout": "File modifications are tracked and will be reverted automatically.",
        "reset": "Use 'superqode revert' to manually revert specific changes.",
        "clean": "Ephemeral files are cleaned up automatically after QE session.",
        "stash": "All changes are ephemeral - no need to stash.",
        "branch": "QE runs in ephemeral mode - no branch needed.",
    }

    def __init__(self, enabled: bool = True):
        """
        Initialize the Git Guard.

        Args:
            enabled: If False, guard is disabled (all operations allowed).
        """
        self.enabled = enabled
        self._blocked_attempts: List[GitCommandAnalysis] = []

    def is_git_command(self, command: str) -> bool:
        """Check if a command is a git command."""
        cmd = command.strip().lower()
        return cmd.startswith("git ") or cmd == "git"

    def extract_git_subcommand(self, command: str) -> Optional[str]:
        """Extract the git subcommand from a full command."""
        parts = command.strip().split()
        if len(parts) < 2:
            return None
        if parts[0].lower() != "git":
            return None
        return parts[1].lower()

    def is_safe_variant(self, command: str, subcommand: str) -> bool:
        """Check if this is a safe variant of a normally blocked command."""
        # Remove 'git ' prefix for pattern matching
        cmd_without_git = (
            command.strip()[4:].strip() if command.strip().lower().startswith("git ") else command
        )

        for pattern_cmd, pattern in self.SAFE_PATTERNS:
            if subcommand == pattern_cmd and pattern.search(cmd_without_git):
                return True
        return False

    def analyze(self, command: str) -> GitCommandAnalysis:
        """
        Analyze a git command and determine if it should be blocked.

        Returns detailed analysis including reason and suggestion.
        """
        if not self.is_git_command(command):
            return GitCommandAnalysis(
                command=command,
                operation_type=GitOperationType.READ,
                is_blocked=False,
                reason="Not a git command",
            )

        subcommand = self.extract_git_subcommand(command)

        if not subcommand:
            return GitCommandAnalysis(
                command=command,
                operation_type=GitOperationType.READ,
                is_blocked=False,
                reason="Bare git command",
            )

        # Check if it's a known safe command
        if subcommand in self.SAFE_COMMANDS:
            return GitCommandAnalysis(
                command=command,
                operation_type=GitOperationType.READ,
                is_blocked=False,
                reason=f"'{subcommand}' is a read-only operation",
            )

        # Check if it's a safe variant of a blocked command
        if subcommand in self.BLOCKED_COMMANDS and self.is_safe_variant(command, subcommand):
            return GitCommandAnalysis(
                command=command,
                operation_type=GitOperationType.READ,
                is_blocked=False,
                reason=f"'{subcommand}' in read-only mode",
            )

        # Check if it's a blocked command
        if subcommand in self.BLOCKED_COMMANDS:
            reason = self.BLOCK_REASONS.get(
                subcommand, f"'{subcommand}' could modify repository state"
            )
            suggestion = self.SUGGESTIONS.get(subcommand, "")

            # Determine operation type
            if subcommand in {"reset", "clean", "checkout"}:
                op_type = GitOperationType.DESTRUCTIVE
            else:
                op_type = GitOperationType.WRITE

            return GitCommandAnalysis(
                command=command,
                operation_type=op_type,
                is_blocked=True,
                reason=reason,
                suggestion=suggestion,
            )

        # Unknown git command - block by default for safety
        return GitCommandAnalysis(
            command=command,
            operation_type=GitOperationType.WRITE,
            is_blocked=True,
            reason=f"Unknown git subcommand '{subcommand}' - blocked for safety",
            suggestion="Only read operations (status, log, diff, show) are allowed during QE.",
        )

    def is_blocked(self, command: str) -> bool:
        """Quick check if a command is blocked."""
        if not self.enabled:
            return False
        if not self.is_git_command(command):
            return False
        return self.analyze(command).is_blocked

    def check_command(self, command: str) -> None:
        """
        Check a command and raise GitOperationBlocked if blocked.

        Use this as a guard before executing commands.
        """
        if not self.enabled:
            return

        analysis = self.analyze(command)

        if analysis.is_blocked:
            self._blocked_attempts.append(analysis)
            raise GitOperationBlocked(
                command=command,
                reason=analysis.reason,
                suggestion=analysis.suggestion,
            )

    def get_blocked_attempts(self) -> List[GitCommandAnalysis]:
        """Get list of all blocked command attempts."""
        return self._blocked_attempts.copy()

    def clear_blocked_attempts(self) -> None:
        """Clear the blocked attempts log."""
        self._blocked_attempts.clear()

    def format_block_message(self, analysis: GitCommandAnalysis) -> str:
        """Format a user-friendly block message."""
        lines = [
            "🛡️  Git Operation Blocked",
            "━" * 40,
            f"Command: {analysis.command}",
            f"Reason: {analysis.reason}",
        ]

        if analysis.suggestion:
            lines.append(f"💡 Tip: {analysis.suggestion}")

        lines.extend(
            [
                "",
                "SuperQode runs in ephemeral mode - all changes are",
                "automatically tracked and reverted after QE completes.",
                "Findings are preserved in .superqode/qe-artifacts/",
            ]
        )

        return "\n".join(lines)


# Singleton instance for easy access
_default_guard: Optional[GitGuard] = None


def get_git_guard() -> GitGuard:
    """Get the default Git Guard instance."""
    global _default_guard
    if _default_guard is None:
        _default_guard = GitGuard()
    return _default_guard


def set_git_guard(guard: GitGuard) -> None:
    """Set the default Git Guard instance."""
    global _default_guard
    _default_guard = guard


def check_git_command(command: str) -> None:
    """Convenience function to check a command against the default guard."""
    get_git_guard().check_command(command)
