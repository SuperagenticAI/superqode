import json
import subprocess
import sys
import shlex

import pytest

from test_desktop_service import desktop, wait_job  # noqa: F401
from test_desktop_threads import task
from superqode.desktop_service.service import DesktopService
from superqode.desktop_service.ownership import Lease, project_lease_path


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, message):
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        message,
    )


def prepared(desktop):
    service, project, root = desktop
    commit(root, "Initial fixture")
    task(service, project["id"], "source", title="Research source", harness="core")
    service.append("source", {"type": "answer", "data": {"text": "Recorded visible answer"}})
    params = {
        "project": project["id"],
        "id": "source",
        "title": "Alternative approach",
        "branch": "superqode/test-fork",
    }
    plan = service.dispatch("threads.fork.preview", params)
    return service, project, root, params, plan


def create(service, params, plan):
    return service.dispatch(
        "threads.fork.create",
        {**params, "fork_id": plan["fork_id"], "expected_digest": plan["digest"]},
    )


def test_fork_creates_isolated_committed_workspace_without_running_or_copying_edits(desktop):
    service, project, root, params, _ = prepared(desktop)
    (root / "hello.txt").write_text("pending source edit")
    (root / "private-untracked.txt").write_text("not part of the commit")
    plan = service.dispatch("threads.fork.preview", params)
    assert plan["source_dirty"]
    fork = create(service, params, plan)
    from pathlib import Path

    destination = Path(fork["path"])
    assert (destination / "hello.txt").read_text() == "hello"
    assert not (destination / "private-untracked.txt").exists()
    assert (root / "hello.txt").read_text() == "pending source edit"
    assert git(destination, "branch", "--show-current") == params["branch"]
    assert git(destination, "rev-parse", "HEAD") == plan["base_commit"]
    assert not service.processes
    assert len(service.dispatch("jobs.list", {})) == 1
    assert "context" not in fork
    context = service.dispatch("threads.fork.context", {"id": fork["id"]})
    assert "Recorded visible answer" in context["text"]
    assert create(service, params, plan)["id"] == fork["id"]
    assert len(service.dispatch("threads.fork.list", {"project": project["id"]})) == 1
    state = service.root
    service.close()
    restored = DesktopService(state)
    try:
        saved = restored.dispatch("threads.fork.list", {"project": project["id"]})[0]
        assert saved["project"] == fork["project"]
        assert not restored.processes
        assert "context" not in json.dumps(restored.dispatch("jobs.list", {}))
    finally:
        restored.close()


def test_changed_source_revision_or_existing_branch_cannot_create_from_old_preview(desktop):
    service, _, root, params, plan = prepared(desktop)
    (root / "new.txt").write_text("committed after preview")
    git(root, "add", "new.txt")
    commit(root, "Changed source")
    with pytest.raises(ValueError, match="changed"):
        create(service, params, plan)
    assert not service._all("SELECT * FROM thread_forks")
    plan = service.dispatch("threads.fork.preview", params)
    git(root, "branch", params["branch"])
    with pytest.raises(ValueError, match="already exists"):
        create(service, params, plan)


def test_fork_and_merge_respect_writer_ownership_and_reviewed_commits(desktop):
    service, _, root, params, plan = prepared(desktop)
    lease = Lease(project_lease_path(service.root, root))
    try:
        with pytest.raises(ValueError, match="still owns"):
            create(service, params, plan)
    finally:
        lease.close()
    fork = create(service, params, plan)
    from pathlib import Path

    destination = Path(fork["path"])
    (destination / "fork.txt").write_text("new result")
    assert not service.dispatch("threads.fork.merge.plan", {"id": fork["id"]})["can_merge"]
    git(destination, "add", "fork.txt")
    commit(destination, "Fork result")
    merge = service.dispatch("threads.fork.merge.plan", {"id": fork["id"]})
    assert merge["can_merge"]
    with pytest.raises(ValueError, match="conditions changed"):
        service.dispatch("threads.fork.merge", {"id": fork["id"], "expected_digest": "stale"})
    lease = Lease(project_lease_path(service.root, destination))
    try:
        with pytest.raises(ValueError, match="still owns"):
            service.dispatch(
                "threads.fork.merge", {"id": fork["id"], "expected_digest": merge["digest"]}
            )
    finally:
        lease.close()
    result = service.dispatch(
        "threads.fork.merge", {"id": fork["id"], "expected_digest": merge["digest"]}
    )
    assert result["merged"] and (root / "fork.txt").read_text() == "new result"
    assert destination.exists()
    assert git(root, "rev-parse", "HEAD") == merge["fork_head"]


def test_diverged_branches_are_preserved_without_automatic_conflict_resolution(desktop):
    service, _, root, params, plan = prepared(desktop)
    fork = create(service, params, plan)
    from pathlib import Path

    destination = Path(fork["path"])
    for directory, text in [(root, "source"), (destination, "fork")]:
        (directory / "hello.txt").write_text(text)
        git(directory, "add", "hello.txt")
        commit(directory, "Different result")
    merge = service.dispatch("threads.fork.merge.plan", {"id": fork["id"]})
    assert not merge["can_merge"] and "diverged" in merge["message"]
    with pytest.raises(ValueError):
        service.dispatch(
            "threads.fork.merge", {"id": fork["id"], "expected_digest": merge["digest"]}
        )
    assert (root / "hello.txt").read_text() == "source"
    assert (destination / "hello.txt").read_text() == "fork"


def test_replaced_worktree_cannot_be_opened_or_merged(desktop):
    service, _, _, params, plan = prepared(desktop)
    fork = create(service, params, plan)
    from pathlib import Path

    destination = Path(fork["path"])
    git(destination, "checkout", "-b", "unreviewed")
    with pytest.raises(ValueError, match="branch changed"):
        service.dispatch("threads.fork.context", {"id": fork["id"]})


def test_independent_forks_can_run_writers_concurrently_without_touching_source(desktop):
    service, _, root, params, plan = prepared(desktop)
    first = create(service, params, plan)
    other = {**params, "branch": "superqode/second-fork"}
    second = create(service, other, service.dispatch("threads.fork.preview", other))
    command = shlex.join(
        [
            sys.executable,
            "-c",
            "import time; from pathlib import Path; Path('writer-result').write_text('isolated'); time.sleep(0.5)",
        ]
    )
    one = service.dispatch("checks.start", {"project": first["project"], "command": command})
    two = service.dispatch("checks.start", {"project": second["project"], "command": command})
    assert len(service.processes) == 2
    for fork, job in [(first, one), (second, two)]:
        assert wait_job(service, job["id"])["status"] == "completed"
        assert (service.project(fork["project"]) / "writer-result").read_text() == "isolated"
    assert not (root / "writer-result").exists()


def test_crash_reconciliation_adopts_an_existing_fork_without_replaying_creation(desktop):
    service, project, _, params, plan = prepared(desktop)
    fork = create(service, params, plan)
    service._write("UPDATE thread_forks SET state='creating',project='' WHERE id=?", (fork["id"],))
    state = service.root
    service.close()
    restored = DesktopService(state)
    try:
        saved = restored.dispatch("threads.fork.list", {"project": project["id"]})[0]
        assert saved["state"] == "ready" and saved["project"] == fork["project"]
        assert not restored.processes
        assert (
            len(
                git(restored.project(project["id"]), "worktree", "list", "--porcelain").split(
                    "worktree "
                )
            )
            == 3
        )
    finally:
        restored.close()
