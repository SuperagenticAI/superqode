"""Reviewed, persistent thread forks in app-managed Git worktrees."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from .conversations import share_context
from .ownership import Lease, project_lease_path


def git(root, *args, check=True):
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(root),
            *args,
        ],
        capture_output=True,
        timeout=30,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and result.returncode:
        raise ValueError(
            result.stderr.decode(errors="replace")[:2000].strip() or "Git operation failed"
        )
    if len(result.stdout) > 2_000_000:
        raise ValueError("Git output is too large to inspect here")
    return result.stdout.decode(errors="replace").strip() if check else result.returncode


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def public(row):
    return {key: value for key, value in row.items() if key != "context"}


def lookup(service, identity):
    rows = service._all("SELECT * FROM thread_forks WHERE id=?", (identity,))
    if not rows:
        raise ValueError("Fork workspace not found")
    return rows[0]


def source_plan(service, params):
    project, identity = params["project"], params["id"]
    root = service.project(project)
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("Open the Git repository root before creating a fork workspace")
    context = share_context(service, identity, project)
    title = str(params.get("title") or "Forked thread").strip()
    branch = str(params.get("branch") or "").strip()
    if not title or len(title) > 120 or any(ord(c) < 32 for c in title):
        raise ValueError("Use a fork title of 1 to 120 characters")
    if (
        not branch
        or len(branch) > 160
        or branch.startswith("-")
        or any(ord(c) < 32 for c in branch)
    ):
        raise ValueError("Enter a valid new Git branch name")
    git(root, "check-ref-format", "--branch", branch)
    try:
        head = git(root, "rev-parse", "--verify", "HEAD^{commit}")
    except ValueError:
        raise ValueError("Create the repository's first commit before forking a worktree") from None
    return {
        "source_project": project,
        "source_run": identity,
        "source_thread": context["source_thread"],
        "title": title,
        "branch": branch,
        "base_commit": head,
        "source_path": str(root),
        "source_dirty": bool(git(root, "status", "--porcelain")),
        "context": context["text"],
        "omitted_messages": context["omitted_messages"],
    }


def preview(service, params):
    with service.lock:
        plan = source_plan(service, params)
        return {**plan, "digest": digest(plan), "fork_id": uuid.uuid4().hex}


def create(service, params):
    with service.lock:
        identity = str(params.get("fork_id") or "")
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Review the fork workspace before creating it")
        previous = service._all("SELECT * FROM thread_forks WHERE id=?", (identity,))
        if previous:
            row = previous[0]
            if (
                row["source_project"] != params["project"]
                or row["source_run"] != params["id"]
                or row["plan_digest"] != params.get("expected_digest")
            ):
                raise ValueError("The fork request changed. Review it again.")
            if row["state"] != "ready":
                raise ValueError(
                    "This creation needs inspection. Existing files were preserved; review the workspace list."
                )
            validate(service, row)
            return public(row)
        root = service.project(params["project"])
        lease = Lease(project_lease_path(service.root, root))
        try:
            plan = source_plan(service, params)
            if digest(plan) != params.get("expected_digest"):
                raise ValueError("Source revision or fork context changed. Review the fork again.")
            if git(root, "show-ref", "--verify", "refs/heads/" + plan["branch"], check=False) == 0:
                raise ValueError("That branch already exists. Choose a new branch name.")
            path = service.root / "worktrees" / identity
            if path.exists() or path.is_symlink():
                raise ValueError("This workspace path already exists; it was left untouched")
            path.parent.mkdir(mode=0o700, exist_ok=True)
            if path.parent.is_symlink() or not path.resolve().is_relative_to(service.root):
                raise ValueError(
                    "The managed worktree directory moved. Inspect desktop state before creating a fork."
                )
            if path.is_relative_to(root):
                raise ValueError(
                    "The desktop state directory must be outside this repository to create isolated worktrees"
                )
            service._write(
                "INSERT INTO thread_forks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    plan["source_project"],
                    plan["source_run"],
                    plan["source_thread"],
                    "",
                    str(path),
                    plan["branch"],
                    plan["base_commit"],
                    plan["title"],
                    plan["context"],
                    time.time(),
                    "creating",
                    digest(plan),
                    "",
                ),
            )
            try:
                git(root, "worktree", "add", "-b", plan["branch"], str(path), plan["base_commit"])
                project = service.open_project(str(path))
                service._write(
                    "UPDATE thread_forks SET project=?,state='ready' WHERE id=?",
                    (project["id"], identity),
                )
            except Exception as exc:
                service._write(
                    "UPDATE thread_forks SET state='attention',issue=? WHERE id=?",
                    (str(exc)[:2000], identity),
                )
                raise
            return public(lookup(service, identity))
        finally:
            lease.close()


def validate(service, row):
    path = Path(row["path"])
    if (
        path.is_symlink()
        or not path.resolve().is_relative_to(service.root)
        or path.resolve() != (service.root / "worktrees" / row["id"]).resolve()
        or not path.is_dir()
    ):
        raise ValueError(
            "The fork workspace moved or is unavailable. Its files have not been changed."
        )
    source = service.project(row["source_project"])
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if (
        Path(common).resolve()
        != Path(git(source, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    ):
        raise ValueError("The fork is no longer attached to its original repository")
    if git(path, "symbolic-ref", "--short", "HEAD") != row["branch"]:
        raise ValueError("The fork's checked-out branch changed. Inspect it before continuing.")
    return path


def reconcile(service):
    """Recover a completed worktree-add without repeating it or deleting anything."""
    for row in service._all("SELECT * FROM thread_forks WHERE state='creating'"):
        try:
            path = validate(service, row)
            project = service.open_project(str(path))
            service._write(
                "UPDATE thread_forks SET project=?,state='ready',issue='' WHERE id=?",
                (project["id"], row["id"]),
            )
        except (ValueError, OSError) as exc:
            service._write(
                "UPDATE thread_forks SET state='attention',issue=? WHERE id=?",
                (str(exc)[:2000], row["id"]),
            )


def list_forks(service, project):
    service.project(project)
    return [
        public(row)
        for row in service._all(
            "SELECT * FROM thread_forks WHERE source_project=? OR project=? ORDER BY created DESC",
            (project, project),
        )
    ]


def merge_plan(service, identity):
    row = lookup(service, identity)
    if row["state"] != "ready":
        raise ValueError("Inspect this fork before reviewing integration")
    path = validate(service, row)
    source = service.project(row["source_project"])
    source_head = git(source, "rev-parse", "HEAD")
    fork_head = git(path, "rev-parse", "HEAD")
    clean = not git(source, "status", "--porcelain") and not git(path, "status", "--porcelain")
    source_branch = git(source, "symbolic-ref", "--short", "HEAD", check=False) == 0
    forward = git(source, "merge-base", "--is-ancestor", source_head, fork_head, check=False) == 0
    reason = (
        "Commit or preserve pending edits in both workspaces before merging."
        if not clean
        else "The source is detached. Check out its intended branch first."
        if not source_branch
        else "The source has diverged. Resolve the integration with Git; no automatic merge is available."
        if not forward
        else "Review the committed branch diff, then explicitly merge into the source."
    )
    plan = {
        "id": identity,
        "source_project": row["source_project"],
        "source_head": source_head,
        "fork_head": fork_head,
        "branch": row["branch"],
        "clean": clean,
        "can_merge": clean and source_branch and forward and source_head != fork_head,
        "message": reason,
    }
    return {**plan, "digest": digest(plan)}


def merge(service, params):
    with service.lock:
        row = lookup(service, params["id"])
        source = service.project(row["source_project"])
        path = validate(service, row)
        leases = []
        try:
            for root in sorted({source, path}):
                leases.append(Lease(project_lease_path(service.root, root)))
            plan = merge_plan(service, row["id"])
            if plan["digest"] != params.get("expected_digest") or not plan["can_merge"]:
                raise ValueError("Merge conditions changed. Review the source and fork again.")
            git(source, "merge", "--ff-only", "--no-edit", plan["fork_head"])
            return {
                "merged": True,
                "commit": plan["fork_head"],
                "source_project": row["source_project"],
            }
        finally:
            for lease in leases:
                lease.close()
