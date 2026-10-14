import os
import subprocess
from pathlib import Path

import pytest

from superqode.workspace_evidence import capture_workspace, matching_states, record_check
from superqode.app.task_review import task_review
from superqode.tools.base import ToolResult


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored\n")
    (tmp_path / "source.py").write_text("original")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return tmp_path


def test_content_including_untracked_and_mode_binds_snapshot(repo):
    original = capture_workspace(repo)
    assert original["status"] == "captured"
    assert matching_states(original, capture_workspace(repo))
    path = repo / "source.py"
    before = path.stat()
    path.write_text("changed!")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert not matching_states(original, capture_workspace(repo))
    path.write_text("original")
    assert matching_states(original, capture_workspace(repo))
    (repo / "new.py").write_text("new")
    assert not matching_states(original, capture_workspace(repo))


def test_ignored_files_are_explicitly_outside_scope(repo):
    before = capture_workspace(repo)
    (repo / "ignored").write_text("artifact")
    assert matching_states(before, capture_workspace(repo))
    assert before["scope"] == "git-visible-files-v1"


def test_limits_and_non_git_never_claim_capture(repo, tmp_path):
    assert capture_workspace(repo, max_files=0)["status"] == "unverified"
    assert capture_workspace(repo, max_bytes=1)["status"] == "unverified"
    folder = tmp_path / "non-repo"
    folder.mkdir()
    assert capture_workspace(folder.parent.parent)["status"] == "unverified"


def test_symlinks_do_not_follow_external_targets(repo):
    try:
        (repo / "link").symlink_to("/nonexistent-target")
    except OSError:
        pytest.skip("Symlinks unavailable")
    assert capture_workspace(repo)["status"] == "unverified"


async def test_check_evidence_is_recorded_and_final_changes_invalidate(repo):
    async def run():
        return ToolResult(success=True, output="passed", metadata={"exit_code": 0})

    result = await record_check("pytest -q", repo, run)
    call = {
        "name": "bash",
        "command": "pytest -q",
        "status": "success",
        "metadata": result.metadata,
    }
    summary = {"workspace_state": capture_workspace(repo)}
    assert task_review(summary, [call]).title == "Checks matched final snapshot"
    (repo / "source.py").write_text("later external change")
    summary["workspace_state"] = capture_workspace(repo)
    assert task_review(summary, [call]).title == "Unverified"


async def test_test_that_changes_source_is_not_certified(repo):
    async def run():
        (repo / "source.py").write_text("changed during test")
        return ToolResult(success=True, output="passed", metadata={"exit_code": 0})

    result = await record_check("pytest", repo, run)
    assert not result.metadata["workspace_evidence"]["stable"]


async def test_non_check_does_not_scan_workspace(repo, monkeypatch):
    def no_scan(*args):
        raise AssertionError("Non-check commands must not scan")

    monkeypatch.setattr("superqode.workspace_evidence.capture_workspace", no_scan)

    async def run():
        return ToolResult(success=True, output="ok")

    assert (await record_check("echo ok", repo, run)).success


def test_pipy_protocol_preserves_check_evidence():
    from types import SimpleNamespace
    from superqode.harness.pipy_adapter import translate_event
    from superqode.pipy.tools.base import AgentToolResult

    state = {
        "scope": "git-visible-files-v1",
        "status": "captured",
        "root": "/fixture",
        "sha256": "abc",
    }
    result = AgentToolResult(
        content=[],
        details={"exit_code": 0, "workspace_evidence": {"before": state, "after": state}},
    )
    event = SimpleNamespace(
        type="tool_execution_end",
        tool_name="bash",
        tool_call_id="check",
        result=result,
        is_error=False,
    )
    data = translate_event(event)[0].data
    assert data["exit_code"] == 0
    assert data["workspace_evidence"]["before"] == state


def test_async_outcome_refresh_preserves_identity_and_read_state():
    from superqode.app.outcomes import Outcome, OutcomeStore

    store = OutcomeStore()
    old = store.add(Outcome(title="Checks recorded", summary=""), read=True)
    assert store.replace(old.id, Outcome(title="Checks matched final snapshot", summary=""))
    assert len(store.list()) == 1
    assert store.list()[0].id == old.id
    assert store.unread_count == 0
    assert not store.replace("evicted", old)


async def test_all_distinct_checks_must_match_final_state(repo):
    async def run():
        return ToolResult(success=True, output="passed", metadata={"exit_code": 0})

    first = await record_check("pytest tests/unit", repo, run)
    (repo / "source.py").write_text("new version")
    second = await record_check("pytest tests/integration", repo, run)
    calls = [
        {"name": "bash", "status": "success", "command": command, "metadata": result.metadata}
        for command, result in [("pytest tests/unit", first), ("pytest tests/integration", second)]
    ]
    summary = {"workspace_state": capture_workspace(repo)}
    assert task_review(summary, calls).title == "Unverified"
    rerun = await record_check("pytest tests/unit", repo, run)
    calls.append(
        {
            "name": "bash",
            "status": "success",
            "command": "pytest tests/unit",
            "metadata": rerun.metadata,
        }
    )
    assert task_review(summary, calls).title == "Checks matched final snapshot"
