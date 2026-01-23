"""
Git Worktree Manager - Isolated testing environments using git worktrees.

Inspired by EveryCode's git_worktree.rs implementation.

Benefits over file snapshots:
- Git handles all the complexity
- Preserves build caches (target/, node_modules/, __pycache__/)
- Can test specific commits
- Multiple worktrees for parallel QE
- Native git integration

Usage:
    manager = GitWorktreeManager(project_root)

    # Create QE worktree
    worktree = await manager.create_qe_worktree(
        session_id="qe-20260108",
        base_ref="HEAD",
        copy_uncommitted=True,
    )

    # Run QE in worktree...

    # Cleanup
    await manager.remove_worktree(worktree)
"""

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Information about a QE worktree."""

    path: Path
    session_id: str
    base_ref: str
    base_commit: str
    created_at: datetime
    repo_root: Path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "session_id": self.session_id,
            "base_ref": self.base_ref,
            "base_commit": self.base_commit,
            "created_at": self.created_at.isoformat(),
            "repo_root": str(self.repo_root),
        }


class GitWorktreeManager:
    """
    Manage git worktrees for QE sessions.

    Creates isolated worktrees for QE analysis while:
    - Preserving build caches for faster test runs
    - Supporting multiple parallel QE sessions
    - Enabling testing of specific commits
    """

    # Global worktree location
    WORKTREE_ROOT = Path.home() / ".superqode" / "working"
    SESSION_REGISTRY = Path.home() / ".superqode" / "working" / "_sessions"

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self._git_root: Optional[Path] = None
        self._repo_name: Optional[str] = None

    @property
    def git_root(self) -> Path:
        """Get the git repository root."""
        if self._git_root is None:
            self._git_root = self._find_git_root()
        return self._git_root

    @property
    def repo_name(self) -> str:
        """Get a unique name for this repository."""
        if self._repo_name is None:
            # Use repo directory name + hash of path for uniqueness
            name = self.git_root.name
            path_hash = hashlib.md5(str(self.git_root).encode()).hexdigest()[:8]
            self._repo_name = f"{name}-{path_hash}"
        return self._repo_name

    @property
    def worktree_base(self) -> Path:
        """Base directory for this repo's worktrees."""
        return self.WORKTREE_ROOT / self.repo_name / "qe"

    def _find_git_root(self) -> Path:
        """Find the git repository root."""
        current = self.project_root
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent

        # Not a git repo - use project root
        logger.warning(f"Not a git repository: {self.project_root}")
        return self.project_root

    async def _run_git(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
        check: bool = True,
    ) -> asyncio.subprocess.Process:
        """Run a git command."""
        cwd = cwd or self.git_root

        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if check and process.returncode != 0:
            error_msg = stderr.decode().strip()
            raise RuntimeError(f"Git command failed: git {' '.join(args)}\n{error_msg}")

        return process

    async def _get_git_output(self, args: List[str], cwd: Optional[Path] = None) -> str:
        """Run git command and return stdout."""
        cwd = cwd or self.git_root

        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _ = await process.communicate()
        return stdout.decode().strip()

    async def is_git_repo(self) -> bool:
        """Check if project is a git repository."""
        try:
            await self._run_git(["rev-parse", "--git-dir"])
            return True
        except RuntimeError:
            return False

    async def get_current_head(self) -> str:
        """Get the current HEAD commit."""
        return await self._get_git_output(["rev-parse", "HEAD"])

    async def create_qe_worktree(
        self,
        session_id: str,
        base_ref: str = "HEAD",
        copy_uncommitted: bool = True,
        keep_gitignored: bool = True,
    ) -> WorktreeInfo:
        """
        Create an isolated worktree for a QE session.

        Args:
            session_id: Unique session identifier
            base_ref: Git ref to base the worktree on (commit, branch, tag)
            copy_uncommitted: Whether to copy uncommitted changes
            keep_gitignored: Whether to preserve gitignored files (caches)

        Returns:
            WorktreeInfo with worktree details
        """
        if not await self.is_git_repo():
            raise RuntimeError("Not a git repository - cannot create worktree")

        # Ensure base directory exists
        self.worktree_base.mkdir(parents=True, exist_ok=True)

        worktree_path = self.worktree_base / session_id

        # Resolve the base commit
        base_commit = await self._get_git_output(["rev-parse", base_ref])

        # Check if worktree already exists
        if worktree_path.exists():
            logger.info(f"Reusing existing worktree: {worktree_path}")
            # Reset to base commit
            await self._reset_worktree(worktree_path, base_commit, keep_gitignored)
        else:
            # Create new detached worktree
            await self._create_worktree(worktree_path, base_commit)

        # Copy uncommitted changes if requested
        if copy_uncommitted:
            await self._copy_uncommitted_changes(worktree_path)

        # Create worktree info
        info = WorktreeInfo(
            path=worktree_path,
            session_id=session_id,
            base_ref=base_ref,
            base_commit=base_commit,
            created_at=datetime.now(),
            repo_root=self.git_root,
        )

        # Register worktree
        await self._register_worktree(info)

        logger.info(f"Created QE worktree: {worktree_path} @ {base_commit[:8]}")

        return info

    async def _create_worktree(self, worktree_path: Path, commit: str) -> None:
        """Create a new detached worktree."""
        try:
            await self._run_git(
                [
                    "worktree",
                    "add",
                    "--detach",
                    str(worktree_path),
                    commit,
                ]
            )
        except RuntimeError as e:
            error_str = str(e)

            # Handle "already registered" error
            if "already registered" in error_str or "already used by" in error_str:
                logger.info("Pruning stale worktrees...")
                await self._run_git(["worktree", "prune"])

                # Retry
                await self._run_git(
                    [
                        "worktree",
                        "add",
                        "--detach",
                        str(worktree_path),
                        commit,
                    ]
                )
            else:
                raise

    async def _reset_worktree(
        self,
        worktree_path: Path,
        commit: str,
        keep_gitignored: bool,
    ) -> None:
        """Reset existing worktree to a specific commit."""
        # Hard reset to commit
        await self._run_git(["reset", "--hard", commit], cwd=worktree_path)

        # Clean tracked files
        clean_args = ["clean", "-fd"]
        if not keep_gitignored:
            clean_args.append("-x")  # Also remove gitignored files

        await self._run_git(clean_args, cwd=worktree_path)

    async def _copy_uncommitted_changes(self, worktree_path: Path) -> int:
        """
        Copy uncommitted (modified + untracked) files to worktree.

        Returns:
            Number of files copied
        """
        # List modified and untracked files
        output = await self._get_git_output(["ls-files", "-om", "--exclude-standard", "-z"])

        copied = 0
        for file_path in output.split("\0"):
            if not file_path or file_path.startswith(".git/"):
                continue

            src = self.git_root / file_path
            dest = worktree_path / file_path

            if not src.exists() or not src.is_file():
                continue

            # Create parent directories
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Copy file
            shutil.copy2(src, dest)
            copied += 1

        # Also handle deletions - remove files in worktree that were deleted locally
        deleted_output = await self._get_git_output(["ls-files", "-d", "-z"])

        for file_path in deleted_output.split("\0"):
            if not file_path or file_path.startswith(".git/"):
                continue

            target = worktree_path / file_path
            if target.exists():
                target.unlink()
                copied += 1

        logger.debug(f"Copied {copied} uncommitted files to worktree")
        return copied

    async def remove_worktree(self, worktree: WorktreeInfo, force: bool = False) -> None:
        """Remove a QE worktree."""
        if not worktree.path.exists():
            logger.debug(f"Worktree already removed: {worktree.path}")
            return

        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree.path))

        try:
            await self._run_git(args)
        except RuntimeError as e:
            if force:
                # Force remove directory manually
                shutil.rmtree(worktree.path, ignore_errors=True)
            else:
                raise

        # Unregister
        await self._unregister_worktree(worktree.session_id)

        logger.info(f"Removed worktree: {worktree.path}")

    async def list_worktrees(self) -> List[WorktreeInfo]:
        """List all QE worktrees for this repository."""
        worktrees = []

        registry_file = self.SESSION_REGISTRY / f"{self.repo_name}.json"
        if not registry_file.exists():
            return worktrees

        try:
            data = json.loads(registry_file.read_text())
            for entry in data.get("worktrees", []):
                worktrees.append(
                    WorktreeInfo(
                        path=Path(entry["path"]),
                        session_id=entry["session_id"],
                        base_ref=entry["base_ref"],
                        base_commit=entry["base_commit"],
                        created_at=datetime.fromisoformat(entry["created_at"]),
                        repo_root=Path(entry["repo_root"]),
                    )
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to read worktree registry: {e}")

        return worktrees

    async def cleanup_stale_worktrees(self, max_age_hours: int = 24) -> int:
        """Remove worktrees older than max_age_hours."""
        removed = 0
        now = datetime.now()

        for worktree in await self.list_worktrees():
            age = now - worktree.created_at
            if age.total_seconds() > max_age_hours * 3600:
                await self.remove_worktree(worktree, force=True)
                removed += 1

        return removed

    async def _register_worktree(self, info: WorktreeInfo) -> None:
        """Register worktree in session registry."""
        self.SESSION_REGISTRY.mkdir(parents=True, exist_ok=True)
        registry_file = self.SESSION_REGISTRY / f"{self.repo_name}.json"

        data = {"worktrees": []}
        if registry_file.exists():
            try:
                data = json.loads(registry_file.read_text())
            except json.JSONDecodeError:
                pass

        # Add or update entry
        data["worktrees"] = [
            w for w in data.get("worktrees", []) if w.get("session_id") != info.session_id
        ]
        data["worktrees"].append(info.to_dict())

        registry_file.write_text(json.dumps(data, indent=2))

    async def _unregister_worktree(self, session_id: str) -> None:
        """Remove worktree from session registry."""
        registry_file = self.SESSION_REGISTRY / f"{self.repo_name}.json"

        if not registry_file.exists():
            return

        try:
            data = json.loads(registry_file.read_text())
            data["worktrees"] = [
                w for w in data.get("worktrees", []) if w.get("session_id") != session_id
            ]
            registry_file.write_text(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            pass


async def prepare_qe_worktree(
    project_root: Path,
    session_id: str,
    base_ref: str = "HEAD",
) -> WorktreeInfo:
    """
    Convenience function to prepare a QE worktree.

    Creates or reuses a worktree pinned to base_ref with uncommitted changes.
    """
    manager = GitWorktreeManager(project_root)
    return await manager.create_qe_worktree(
        session_id=session_id,
        base_ref=base_ref,
        copy_uncommitted=True,
        keep_gitignored=True,
    )
