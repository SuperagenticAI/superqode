"""Commit and push from the desktop app: path safety, project state, and run ownership."""

import os
import subprocess
import threading
import time

import pytest

from superqode.desktop_service import ship
from superqode.desktop_service.service import DesktopService


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    git(path, "config", "commit.gpgsign", "false")
    return path


@pytest.fixture
def repo(tmp_path):
    root = init_repo(tmp_path / "project")
    (root / "hello.txt").write_text("hello\n")
    git(root, "add", "hello.txt")
    git(root, "commit", "-qm", "init")
    return root


@pytest.fixture
def desktop(tmp_path, repo):
    service = DesktopService(tmp_path / "state")
    project = service.open_project(str(repo))
    yield service, project["id"], repo
    service.close()


@pytest.mark.parametrize(
    "value",
    [
        "../outside.txt",
        ".",
        "./hello.txt",
        "a/../hello.txt",
        "",
        "a//b",
        "sub/",
        "/etc/passwd",
        "~/x",
    ],
)
def test_paths_reject_escapes_and_non_files(repo, value):
    with pytest.raises(ValueError):
        ship._paths(repo, [value])


def test_paths_reject_symlink_escape(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    os.symlink(outside, repo / "link")
    with pytest.raises(ValueError, match="inside the project"):
        ship._paths(repo, ["link/secret.txt"])


def test_paths_reject_private_and_sensitive(repo):
    for value in [
        ".superqode/checkpoints/state.json",
        "a/.superqode/x",
        ".superqode-edit-1",
        ".env",
        ".git/config",
    ]:
        with pytest.raises(ValueError):
            ship._paths(repo, [value])
    assert ship._paths(repo, ["hello.txt"]) == [":(literal)hello.txt"]


def test_status_hides_superqode_state(repo):
    (repo / ".superqode" / "checkpoints").mkdir(parents=True)
    (repo / ".superqode" / "checkpoints" / "state.json").write_text("{}")
    (repo / "hello.txt").write_text("changed\n")
    paths = [f["path"] for f in ship.status(repo)["files"]]
    assert paths == ["hello.txt"]


def test_subdirectory_project_uses_project_relative_paths(tmp_path):
    top = init_repo(tmp_path / "mono")
    sub = top / "apps" / "web"
    sub.mkdir(parents=True)
    (top / "root.txt").write_text("root\n")
    (sub / "page.txt").write_text("page\n")
    (sub / "old.txt").write_text("old\n")
    git(top, "add", ".")
    git(top, "commit", "-qm", "init")
    (sub / "page.txt").write_text("page 2\n")
    (top / "root.txt").write_text("root 2\n")
    git(top, "mv", "apps/web/old.txt", "apps/web/new.txt")
    status = ship.status(sub)
    assert status["repository_prefix"] == "apps/web/"
    files = {f["path"]: f for f in status["files"]}
    assert set(files) == {"page.txt", "new.txt"}
    assert files["new.txt"]["original"] == "old.txt"

    class Idle:
        processes = {}

        def _all(self, query, params=()):
            return []

    result = ship.commit(
        Idle(), sub, {"project": "p", "paths": ["page.txt", "new.txt"], "message": "Sub change"}
    )
    assert result["ok"]
    changed = git(top, "show", "--name-status", "--format=", "HEAD").split("\n")
    assert "M\tapps/web/page.txt" in changed
    assert any(line.startswith("R") and "apps/web/new.txt" in line for line in changed)
    # The file outside the project stays uncommitted.
    assert "root.txt" in git(top, "status", "--porcelain")


def test_commit_refused_while_run_active(desktop):
    service, project, root = desktop
    (root / "hello.txt").write_text("changed\n")
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("job1", project, "task", "Run", "running", "{}", None, time.time(), time.time()),
    )
    with pytest.raises(ValueError, match="active run"):
        service.dispatch(
            "ship.commit", {"project": project, "paths": ["hello.txt"], "message": "x"}
        )


def test_commit_refused_while_worker_holds_project(desktop):
    from superqode.desktop_service.ownership import Lease, project_lease_path

    service, project, root = desktop
    (root / "hello.txt").write_text("changed\n")
    lease = Lease(project_lease_path(service.root, root))
    try:
        with pytest.raises(ValueError, match="owns this project"):
            service.dispatch(
                "ship.commit", {"project": project, "paths": ["hello.txt"], "message": "x"}
            )
    finally:
        lease.close()


def test_run_cannot_start_while_git_action_holds_project(desktop, monkeypatch):
    service, project, root = desktop
    entered, release = threading.Event(), threading.Event()

    def slow_action(svc, path, method, params):
        entered.set()
        release.wait(5)
        return {"ok": True}

    monkeypatch.setattr(ship, "action", slow_action)
    worker = threading.Thread(
        target=service.dispatch, args=("ship.push", {"project": project}), daemon=True
    )
    worker.start()
    assert entered.wait(5)
    try:
        with pytest.raises(ValueError, match="Git commit or push"):
            service.start(project, "task", {"prompt": "hi"})
        with pytest.raises(ValueError, match="Another Git action"):
            service.dispatch(
                "ship.commit", {"project": project, "paths": ["hello.txt"], "message": "x"}
            )
    finally:
        release.set()
        worker.join(5)
    # Released afterwards: the project writer lease can be taken again.
    from superqode.desktop_service.ownership import assert_project_idle

    assert_project_idle(service, project)
    assert project not in service._ship_projects
