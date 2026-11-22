"""Factory source commits preserve the private-state boundary and unrelated Git work."""
# ruff: noqa: F811

import os
import time

import pytest

from test_factory_definition import project, git, rewrite, EXAMPLE  # noqa: F401
from superqode.factory.versioning import (
    inspect_sources,
    commit_sources,
    selected_review,
    source_path,
)
from superqode.desktop_service.service import DesktopService


@pytest.fixture
def versioned(project):
    git(project, "config", "commit.gpgsign", "false")
    return project


def review_commit(root, message="Version Factory sources"):
    review = inspect_sources(root)
    paths = [row["path"] for row in review["files"] if row["changed"]]
    return commit_sources(root, review, paths, message)


def test_ignored_definition_can_be_reviewed_without_staging_runtime_or_unrelated_files(versioned):
    root = versioned
    private = root / ".superqode/workorders/private.json"
    private.parent.mkdir(parents=True)
    private.write_text('{"password":"private-fixture"}')
    (root / "app.py").write_text("print('a separate staged change')\n")
    git(root, "add", "app.py")
    index_before = git(root, "ls-files", "--stage")
    review = inspect_sources(root)
    assert [row["path"] for row in review["files"]] == [".superqode/factory.yaml"]
    assert review["files"][0]["status"] == "new"
    assert "apiVersion" in review["files"][0]["diff"]
    assert git(root, "ls-files", "--stage") == index_before
    result = commit_sources(root, review, [".superqode/factory.yaml"], "Version Factory")
    assert result["index_updated"] and not result["pushed"]
    assert (
        git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        == ".superqode/factory.yaml"
    )
    assert git(root, "diff", "--cached", "--name-only") == "app.py"
    assert git(root, "show", "HEAD:app.py") == "answer = 42"
    assert not git(root, "ls-files", ".superqode/workorders")
    assert inspect_sources(root)["files"][0]["status"] == "unchanged"


def test_source_review_requires_all_new_dependencies_and_the_changed_definition(versioned):
    root = versioned
    context = root / ".superqode/context/rules.md"
    context.parent.mkdir(parents=True)
    context.write_text("Use concise error messages.\n")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(
            rules={"path": ".superqode/context/rules.md", "purpose": "context"}
        ),
    )
    review = inspect_sources(root)
    with pytest.raises(ValueError, match="new declared"):
        selected_review(review, [".superqode/factory.yaml"])
    with pytest.raises(ValueError, match="changed Factory definition"):
        selected_review(review, [".superqode/context/rules.md"])
    result = review_commit(root)
    assert set(result["paths"]) == {".superqode/factory.yaml", ".superqode/context/rules.md"}


@pytest.mark.parametrize("change", ["disk", "head", "branch"])
def test_changed_sources_or_git_state_cannot_use_stale_review(versioned, change):
    root = versioned
    review = inspect_sources(root)
    if change == "disk":
        (root / ".superqode/factory.yaml").write_text(
            (root / ".superqode/factory.yaml").read_text() + "\n"
        )
    elif change == "head":
        git(root, "commit", "--allow-empty", "-qm", "Later commit")
    else:
        git(root, "switch", "-qc", "later-branch")
    before = git(root, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="changed after review"):
        commit_sources(root, review, [".superqode/factory.yaml"], "Stale")
    assert git(root, "rev-parse", "HEAD") == before


def test_removed_declared_component_is_reviewed_and_deleted_from_git(versioned):
    root = versioned
    (root / ".superqode/context").mkdir()
    (root / ".superqode/context/old.md").write_text("Old instructions\n")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(
            old={"path": ".superqode/context/old.md", "purpose": "context"}
        ),
    )
    review_commit(root)
    (root / ".superqode/context/old.md").unlink()
    rewrite(root, lambda d: d["data_context"]["files"].pop("old"))
    review = inspect_sources(root)
    deleted = next(row for row in review["files"] if row["path"].endswith("old.md"))
    assert deleted["status"] == "deleted" and "-Old instructions" in deleted["diff"]
    review_commit(root, "Remove old context")
    assert not git(root, "ls-files", ".superqode/context/old.md")


def test_removed_reference_does_not_delete_a_component_that_still_exists(versioned):
    root = versioned
    (root / "rules.md").write_text("Instructions\n")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(
            rules={"path": "rules.md", "purpose": "context"}
        ),
    )
    review_commit(root)
    rewrite(root, lambda d: d["data_context"]["files"].pop("rules"))
    review_commit(root)
    assert git(root, "ls-files", "rules.md") == "rules.md"


@pytest.mark.parametrize(
    "path",
    [
        ".superqode/workorders/x.json",
        ".superqode/factory/snapshots/x.yaml",
        ".superqode/factory-studio/revisions/x.yaml",
        ".superqode/sessions/x.yaml",
        ".env",
        "docs/.env.local",
        ".ssh/id_rsa",
        "a/.superqode/context/x",
        ".superqode-edit-1",
        ".superqode/components/token.key",
        "../x",
    ],
)
def test_runtime_and_sensitive_paths_cannot_be_source_control_exemptions(versioned, path):
    with pytest.raises(ValueError):
        source_path(versioned, path)


def test_declared_runtime_and_inline_credentials_never_produce_a_review(versioned):
    root = versioned
    private = root / ".superqode/sessions/context.md"
    private.parent.mkdir(parents=True)
    private.write_text("Private session fixture")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(
            private={"path": ".superqode/sessions/context.md", "purpose": "context"}
        ),
    )
    with pytest.raises(ValueError, match="Runtime state"):
        inspect_sources(root)
    rewrite(root, lambda d: d["data_context"]["files"].clear())
    (root / "config.yaml").write_text("api_key: fixture-secret\n")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(
            config={"path": "config.yaml", "purpose": "context"}
        ),
    )
    with pytest.raises(ValueError, match="credentials"):
        inspect_sources(root)


def test_unreviewed_paths_and_modified_review_are_refused(versioned):
    root = versioned
    review = inspect_sources(root)
    with pytest.raises(ValueError, match="complete reviewed diff"):
        selected_review(review, ["app.py"])
    review["files"][0]["path"] = "app.py"
    with pytest.raises(ValueError, match="invalid"):
        commit_sources(root, review, ["app.py"], "Forged")


def test_external_git_filters_are_not_run_for_source_review(versioned):
    root = versioned
    (root / ".gitattributes").write_text(".superqode/factory.yaml filter=external\n")
    git(root, "config", "filter.external.clean", "false")
    with pytest.raises(ValueError, match="external Git filter"):
        inspect_sources(root)


def test_source_commit_in_monorepo_stays_in_selected_project(tmp_path):
    top = tmp_path / "mono"
    top.mkdir()
    git(top, "init", "-q")
    git(top, "config", "user.name", "Test")
    git(top, "config", "user.email", "test@example.invalid")
    git(top, "config", "commit.gpgsign", "false")
    (top / "outside.txt").write_text("Unrelated\n")
    git(top, "add", "outside.txt")
    git(top, "commit", "-qm", "Baseline")
    root = top / "apps/project"
    (root / ".superqode").mkdir(parents=True)
    (root / ".superqode/factory.yaml").write_text(EXAMPLE.read_text())
    (top / "outside.txt").write_text("Separate staged work\n")
    git(top, "add", "outside.txt")
    result = review_commit(root)
    assert result["paths"] == [".superqode/factory.yaml"]
    assert git(top, "show", "HEAD:apps/project/.superqode/factory.yaml").startswith("apiVersion")
    assert git(top, "diff", "--cached", "--name-only") == "outside.txt"
    assert git(top, "show", "HEAD:outside.txt") == "Unrelated"
    assert inspect_sources(root)["files"][0]["status"] == "unchanged"
    # Removal uses the same project prefix as insertion, without touching siblings.
    (root / "context.md").write_text("Context\n")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(
            context={"path": "context.md", "purpose": "context"}
        ),
    )
    review_commit(root, "Add monorepo context")
    (root / "context.md").unlink()
    rewrite(root, lambda d: d["data_context"]["files"].clear())
    review_commit(root, "Remove monorepo context")
    assert not git(top, "ls-files", "apps/project/context.md")
    assert git(top, "diff", "--cached", "--name-only") == "outside.txt"


def test_source_commit_runs_through_durable_factory_job(versioned, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(versioned))["id"]
        reviewed = service.dispatch("factory.source.inspect", {"project": identity})
        params = {
            "project": identity,
            "factory_action": "source-commit",
            "confirmed": True,
            "source_review": reviewed["review"],
            "source_digest": reviewed["digest"],
            "paths": [".superqode/factory.yaml"],
            "message": "Version Factory from app",
            "command_id": "once",
        }
        started = service.dispatch("factory.action.start", params)
        assert service.dispatch("factory.action.start", params)["id"] == started["id"]
        for _ in range(200):
            job = service.dispatch("jobs.get", {"id": started["id"]})
            if job["status"] not in {"running", "queued", "needs_approval", "cancelling"}:
                break
            time.sleep(0.05)
        assert job["status"] == "completed", job
        assert job["result"]["paths"] == [".superqode/factory.yaml"]
        assert not job["result"]["pushed"]
        assert git(versioned, "log", "-1", "--format=%s") == "Version Factory from app"
        # Retrying the same command acknowledges the existing job, never a new commit.
        assert service.dispatch("factory.action.start", params)["id"] == started["id"]
    finally:
        service.close()


def test_named_pipe_component_is_rejected_without_opening_it(versioned):
    root = versioned
    os.mkfifo(root / "pipe.md")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(pipe={"path": "pipe.md", "purpose": "context"}),
    )
    with pytest.raises(ValueError, match="regular files"):
        inspect_sources(root)


def test_hard_linked_source_is_rejected(versioned):
    root = versioned
    (root / "rules.md").write_text("Instructions\n")
    os.link(root / "rules.md", root / "copy.md")
    rewrite(
        root,
        lambda d: d["data_context"]["files"].update(
            rules={"path": "rules.md", "purpose": "context"}
        ),
    )
    with pytest.raises(ValueError, match="hard links"):
        inspect_sources(root)


def test_source_commit_plan_is_server_reviewed_and_credential_free(
    versioned, tmp_path, monkeypatch
):
    from superqode.desktop_service.factory_studio import validate_request

    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(versioned))["id"]
        review = service.dispatch("factory.source.inspect", {"project": identity})
        params = {
            "project": identity,
            "factory_action": "source-commit",
            "confirmed": True,
            "source_review": review["review"],
            "source_digest": review["digest"],
            "source_plan": {"files": [{"path": ".env"}]},
            "harness": "evil",
            "provider": "anthropic",
            "paths": [".superqode/factory.yaml"],
            "message": "Version sources",
            "factory_providers": ["anthropic"],
        }
        safe = validate_request(versioned, params, service=service)
        assert safe["source_plan"]["digest"] == review["digest"]
        assert safe["factory_providers"] == [] and safe["provider"] == ""
        assert "harness" not in safe
        service._write("UPDATE factory_source_reviews SET created=0")
        with pytest.raises(ValueError, match="expired"):
            validate_request(versioned, params, service=service)
    finally:
        service.close()


def test_source_commit_is_blocked_while_project_has_active_work(versioned, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(versioned))["id"]
        reviewed = service.dispatch("factory.source.inspect", {"project": identity})
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "active",
                identity,
                "task",
                "Running",
                "running",
                "{}",
                None,
                time.time(),
                time.time(),
            ),
        )
        with pytest.raises(ValueError, match="active project run"):
            service.dispatch(
                "factory.action.start",
                {
                    "project": identity,
                    "factory_action": "source-commit",
                    "confirmed": True,
                    "source_review": reviewed["review"],
                    "source_digest": reviewed["digest"],
                    "paths": [".superqode/factory.yaml"],
                    "message": "Must not start",
                },
            )
        assert not git(versioned, "ls-files", ".superqode/factory.yaml")
    finally:
        service.close()


def test_concurrent_git_writer_cannot_be_overwritten_by_prepared_source_commit(
    versioned, monkeypatch
):
    from superqode.factory import versioning

    root = versioned
    reviewed = inspect_sources(root)
    original = versioning._git
    later = []

    def competing_writer(path, *args, **kwargs):
        if args and args[0] == "update-ref":
            original(root, "commit", "--allow-empty", "-qm", "A concurrent Git writer")
            later.append(git(root, "rev-parse", "HEAD"))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(versioning, "_git", competing_writer)
    with pytest.raises(ValueError, match="no Factory commit was published"):
        commit_sources(root, reviewed, [".superqode/factory.yaml"], "Must not overwrite")
    assert git(root, "rev-parse", "HEAD") == later[0]
    assert git(root, "log", "-1", "--format=%s") == "A concurrent Git writer"
    assert not git(root, "ls-files", ".superqode/factory.yaml")
    assert git(root, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_configured_git_hook_can_stop_source_commit_without_mutating_branch_or_index(versioned):
    root = versioned
    hooks = root / ".hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'Fixture hook stopped commit' >&2\nexit 1\n")
    hook.chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))
    before = git(root, "rev-parse", "HEAD")
    index = git(root, "ls-files", "--stage")
    review = inspect_sources(root)
    with pytest.raises(ValueError, match="hook stopped"):
        commit_sources(root, review, [".superqode/factory.yaml"], "Hook test")
    assert git(root, "rev-parse", "HEAD") == before
    assert git(root, "ls-files", "--stage") == index
    assert git(root, "worktree", "list", "--porcelain").count("worktree ") == 1
