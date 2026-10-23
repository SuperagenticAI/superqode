"""Review scopes, unsafe paths and task evidence, with disposable Git projects."""

import json
from pathlib import Path
import subprocess

import pytest

from superqode.desktop_service.review import LIMIT, review
from superqode.desktop_service.service import DesktopService


def git(root, *args):
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    (root / "code.py").write_text("original\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "baseline")
    return root


def test_scopes_keep_staged_and_working_content_distinct(project):
    path = project / "code.py"
    path.write_text("staged\n")
    git(project, "add", "code.py")
    path.write_text("working\n")
    assert "+staged" in review(project, {"scope": "staged", "path": "code.py"})["diff"]
    unstaged = review(project, {"scope": "unstaged", "path": "code.py"})["diff"]
    assert "-staged" in unstaged and "+working" in unstaged
    combined = review(project, {"scope": "working", "path": "code.py"})["diff"]
    assert "-original" in combined and "+working" in combined


def test_untracked_binary_sensitive_and_symlink_paths(project, tmp_path):
    (project / "new name.txt").write_text("new content\n")
    (project / "image.bin").write_bytes(b"\0image")
    (project / ".env").write_text("SECRET=fixture")
    internal = project / ".superqode/checkpoints/state.json"
    internal.parent.mkdir(parents=True)
    internal.write_text("private checkpoint data")
    secret = tmp_path / "outside.txt"
    secret.write_text("outside")
    (project / "escape").symlink_to(secret)
    result = review(project, {})
    assert {f["path"] for f in result["files"]} == {"new name.txt", "image.bin"}
    assert result["hidden"] == 3
    assert "+new content" in review(project, {"path": "new name.txt"})["diff"]
    assert review(project, {"path": "image.bin"})["binary"] is True
    for path in [
        "../outside.txt",
        "escape",
        ".env",
        ".git/config",
        ".superqode/checkpoints/state.json",
    ]:
        with pytest.raises(ValueError):
            review(project, {"path": path})


def test_branch_scope_excludes_working_edits(project):
    baseline = git(project, "rev-parse", "HEAD").strip()
    (project / "code.py").write_text("committed\n")
    git(project, "commit", "-qam", "change")
    (project / "code.py").write_text("uncommitted\n")
    patch = review(project, {"scope": "branch", "base": baseline, "path": "code.py"})["diff"]
    assert "+committed" in patch and "uncommitted" not in patch
    with pytest.raises(ValueError):
        review(project, {"scope": "branch", "base": "--output=/tmp/unwanted"})


def test_unborn_repository_shows_staged_and_new_content(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "first.txt").write_text("first\n")
    git(tmp_path, "add", "first.txt")
    (tmp_path / "first.txt").write_text("latest\n")
    assert review(tmp_path, {})["files"][0]["path"] == "first.txt"
    assert "+latest" in review(tmp_path, {"path": "first.txt"})["diff"]
    assert "+first" in review(tmp_path, {"scope": "staged", "path": "first.txt"})["diff"]


def test_file_names_are_literal_and_large_files_are_explicit(project):
    name = "odd\n[abc].txt"
    (project / name).write_text("literal\n")
    assert name in [f["path"] for f in review(project, {})["files"]]
    assert "+literal" in review(project, {"path": name})["diff"]
    (project / "large.txt").write_text("x" * (LIMIT + 1))
    with pytest.raises(ValueError, match="too large"):
        review(project, {"path": "large.txt"})


def test_review_dispatch_and_staging_tracked_deletion(project, tmp_path):
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        (project / "code.py").unlink()
        rows = service.dispatch("git.review", {"project": identity})["files"]
        assert rows == [{"path": "code.py", "staged": False, "exists": False}]
        service.dispatch("git.stage_file", {"project": identity, "path": "code.py"})
        assert "D" in git(project, "diff", "--cached", "--name-status")
    finally:
        service.close()


def test_summary_never_infers_verification_from_agent_success(project, tmp_path):
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "task",
                identity,
                "task",
                "Fix code",
                "completed",
                json.dumps({"harness": "core"}),
                "{}",
                10,
                11,
            ),
        )
        summary = service.dispatch("jobs.summary", {"id": "task"})
        assert summary["status"] == "completed"
        assert summary["checks"] == []
        assert summary["changes_recorded"] is False
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "check",
                identity,
                "check",
                "Project check",
                "failed",
                "{}",
                json.dumps({"exit_code": 1, "command": "false"}),
                12,
                13,
            ),
        )
        assert (
            service.dispatch("jobs.summary", {"id": "task"})["checks"][0]["result"]["exit_code"]
            == 1
        )
    finally:
        service.close()


def test_summary_reports_only_recorded_task_changes(project, tmp_path):
    from superqode.desktop_service.checkpoints import begin_task, finish_task

    (project / "earlier.txt").write_text("preexisting edit\n")
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        capture = begin_task(project, "Task fixture")
        (project / "code.py").write_text("agent change\n")
        checkpoint = finish_task(capture)
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "task",
                identity,
                "task",
                "Fix code",
                "completed",
                '{"harness":"core"}',
                "{}",
                10,
                11,
            ),
        )
        service.append(
            "task", {"type": "checkpoint", "data": {"phase": "sealed", "id": checkpoint}}
        )
        summary = service.dispatch("jobs.summary", {"id": "task"})
        assert summary["changes_recorded"] is True
        assert [item["path"] for item in summary["changes"]] == ["code.py"]
        assert set(summary["changes"][0]) == {"path", "change_type"}
        with pytest.raises(ValueError, match="Sensitive"):
            service.dispatch(
                "git.stage_file", {"project": identity, "path": ".superqode/checkpoints/state.json"}
            )
    finally:
        service.close()


def test_project_actions_are_suggestions_from_declared_scripts(project):
    from superqode.desktop_service.review import project_actions

    (project / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "test": "node test.js",
                    "lint": "eslint .",
                    "arbitrary;command": "bad",
                    "dev": "long-running-server",
                }
            }
        )
    )
    (project / "pnpm-lock.yaml").write_text("")
    assert [row["command"] for row in project_actions(project)] == [
        "pnpm run test",
        "pnpm run lint",
    ]
    (project / "package.json").write_text("[]")
    assert project_actions(project) == []


def test_active_parent_project_blocks_child_mutation_but_not_unrelated_project(project, tmp_path):
    service = DesktopService(tmp_path / "state")
    try:
        parent = service.open_project(str(project))["id"]
        child_path = project / "nested"
        child_path.mkdir()
        (child_path / "file.txt").write_text("child")
        child = service.open_project(str(child_path))["id"]
        unrelated_path = tmp_path / "unrelated"
        unrelated_path.mkdir()
        unrelated = service.open_project(str(unrelated_path))["id"]
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "active",
                parent,
                "task",
                "Working",
                "running",
                "{}",
                None,
                10,
                11,
            ),
        )
        assert service.project_has_writer(child) is True
        assert service.project_has_writer(unrelated) is False
        with pytest.raises(ValueError, match="Finish or stop"):
            service.dispatch("git.stage_file", {"project": child, "path": "file.txt"})
    finally:
        service.close()


def test_commit_refuses_hidden_private_files_in_index(project, tmp_path):
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        internal = project / ".superqode/checkpoints/state.json"
        internal.parent.mkdir(parents=True)
        internal.write_text("private runtime data")
        git(project, "add", ".superqode/checkpoints/state.json")
        with pytest.raises(ValueError, match="Unstage them"):
            service.dispatch(
                "git.commit", {"project": identity, "message": "must not commit private state"}
            )
        assert git(project, "log", "-1", "--format=%s").strip() == "baseline"
    finally:
        service.close()
