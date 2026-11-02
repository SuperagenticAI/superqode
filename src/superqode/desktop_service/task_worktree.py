"""Start a second task in its own Git worktree.

The worktree is created from the current commit, outside the repository, and
nothing is executed there. Uncommitted files stay in the source checkout.
"""

from __future__ import annotations

from pathlib import Path
import re
import time
import uuid

from .ownership import Lease, project_lease_path
from .thread_branches import digest, git, public


def _plan(service, params):
    root = service.project(params["project"])
    top = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root.resolve():
        raise ValueError("Open the Git repository root before isolating a task")
    try:
        head = git(root, "rev-parse", "--verify", "HEAD^{commit}")
    except ValueError:
        raise ValueError("Create the repository's first commit before isolating a task") from None
    identity = str(params.get("fork_id") or uuid.uuid4().hex)
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Review the isolated workspace before creating it")
    title = str(params.get("title") or "Isolated task").strip()
    if not title or len(title) > 120 or any(ord(c) < 32 for c in title):
        raise ValueError("Use a task title of 1 to 120 characters")
    branch = "sq/task-" + identity[:8]
    path = service.root / "worktrees" / identity
    return {
        "fork_id": identity,
        "source_project": params["project"],
        "title": title,
        "branch": branch,
        "base_commit": head,
        "source_path": str(root),
        "path": str(path),
    }


def preview(service, params):
    with service.lock:
        plan = _plan(service, {**params, "fork_id": uuid.uuid4().hex})
        return {**plan, "digest": digest(plan)}


def create(service, params):
    with service.lock:
        identity = str(params.get("fork_id") or "")
        previous = service._all("SELECT * FROM thread_forks WHERE id=?", (identity,))
        if previous:
            row = previous[0]
            if row["source_project"] != params["project"] or row["plan_digest"] != params.get(
                "expected_digest"
            ):
                raise ValueError("The isolated workspace changed. Review it again.")
            if row["state"] != "ready":
                raise ValueError("This workspace needs inspection. Existing files were preserved.")
            return public(row)
        root = service.project(params["project"])
        lease = Lease(project_lease_path(service.root, root))
        try:
            plan = _plan(service, params)
            if digest(plan) != params.get("expected_digest"):
                raise ValueError("The repository changed. Review the isolated workspace again.")
            path = Path(plan["path"])
            if path.exists() or path.is_symlink():
                raise ValueError("This workspace path already exists; it was left untouched")
            path.parent.mkdir(mode=0o700, exist_ok=True)
            if path.parent.is_symlink() or not path.resolve().is_relative_to(service.root):
                raise ValueError(
                    "The managed worktree directory moved. Inspect desktop state first."
                )
            if path.is_relative_to(root):
                raise ValueError(
                    "The desktop state directory must be outside this repository to isolate a task"
                )
            if git(root, "show-ref", "--verify", "refs/heads/" + plan["branch"], check=False) == 0:
                raise ValueError("That branch already exists. Review the workspace again.")
            service._write(
                "INSERT INTO thread_forks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan["fork_id"],
                    plan["source_project"],
                    "",
                    "",
                    "",
                    plan["path"],
                    plan["branch"],
                    plan["base_commit"],
                    plan["title"],
                    "",
                    time.time(),
                    "creating",
                    digest(plan),
                    "",
                ),
            )
            try:
                git(
                    root, "worktree", "add", "-b", plan["branch"], plan["path"], plan["base_commit"]
                )
                project = service.open_project(plan["path"])
                service._write(
                    "UPDATE thread_forks SET project=?,state='ready' WHERE id=?",
                    (project["id"], plan["fork_id"]),
                )
            except Exception as exc:
                service._write(
                    "UPDATE thread_forks SET state='attention',issue=? WHERE id=?",
                    (str(exc)[:2000], plan["fork_id"]),
                )
                raise
            row = service._all("SELECT * FROM thread_forks WHERE id=?", (plan["fork_id"],))[0]
            return public(row)
        finally:
            lease.close()
