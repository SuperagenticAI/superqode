"""Mobile project workflows preserve the desktop's scope and revision checks."""

import json
import subprocess

import pytest

from test_desktop_companion import companion, pair  # noqa: F401
from test_desktop_service import desktop  # noqa: F401


def test_new_project_views_refuse_unshared_or_missing_projects(companion):
    service, _, root, profile, access = companion
    _, device = pair(access, profile)
    outside = root.parent / "other-project"
    outside.mkdir()
    other = service.open_project(str(outside))
    for method in [
        "review.list",
        "review.diff",
        "review.feedback",
        "queue.list",
        "workorders.snapshot",
        "checkpoints.list",
        "checkpoints.diff",
    ]:
        with pytest.raises(PermissionError, match="not shared"):
            access.rpc(device, method, {"project": other["id"]})
        with pytest.raises(ValueError, match="Choose a shared project"):
            access.rpc(device, method, {})


def test_reference_context_is_explicit_project_text_not_harness_configuration(companion):
    service, _, root, profile, access = companion
    _, device = pair(access, profile, ["read"])
    result = access.rpc(
        device,
        "context.preview",
        {"profile": profile["id"], "prompt": "Review this", "context_files": ["hello.txt"]},
    )
    assert "hello" in result["prompt"]
    assert result["files"][0]["path"] == "hello.txt"
    assert "harness" not in result
    assert service._all("SELECT id FROM jobs") == []
    (root / "escape").symlink_to(root.parent / "outside-secret")
    (root.parent / "outside-secret").write_text("not for this device")
    (root / "large.txt").write_text("x" * 64001)
    (root / "binary.txt").write_bytes(b"\x00binary")
    for paths in [
        ["../outside-secret"],
        [str(root / "hello.txt")],
        [".env"],
        [".aws/config"],
        ["escape"],
        ["large.txt"],
        ["binary.txt"],
        ["hello.txt"] * 11,
    ]:
        with pytest.raises(ValueError):
            access.rpc(
                device,
                "context.preview",
                {"profile": profile["id"], "prompt": "Review", "context_files": paths},
            )
    with pytest.raises(ValueError, match="Code or Plan"):
        access.rpc(
            device,
            "context.preview",
            {
                "profile": profile["id"],
                "prompt": "Review",
                "context_files": ["hello.txt"],
                "interaction_mode": "chat",
            },
        )


def test_bad_attachments_are_rejected_before_command_reservation(companion):
    service, _, _, profile, access = companion
    _, device = pair(access, profile)
    with pytest.raises(ValueError):
        access.rpc(
            device,
            "tasks.start",
            {"profile": profile["id"], "prompt": "Read", "context_files": ["../secret"]},
            "invalid-context",
        )
    assert not service._all("SELECT * FROM companion_commands WHERE key=?", ("invalid-context",))


def test_queue_projection_does_not_expose_agent_configuration(companion):
    service, project, _, profile, access = companion
    _, device = pair(access, profile, ["read"])
    service.dispatch(
        "queue.add",
        {
            "project": project["id"],
            "prompt": "x" * 3000,
            "harness": "core",
            "provider": "ollama",
            "model": "fixture",
            "acp_options": {"opaque_secret": "do-not-send"},
        },
    )
    result = access.rpc(device, "queue.list", {"project": project["id"]})
    assert result["running"] is False
    assert len(result["items"][0]["request"]["prompt"]) == 2000
    assert result["items"][0]["prompt_truncated"] is True
    assert "do-not-send" not in json.dumps(result)
    with pytest.raises(PermissionError):
        access.rpc(device, "queue.run", {"project": project["id"]}, "no-generic-queue-execution")


def test_workorder_projection_excludes_worker_configuration_and_raw_artifacts(
    companion, monkeypatch
):
    service, project, _, profile, access = companion
    _, device = pair(access, profile, ["read"])
    original = service.dispatch

    def dispatch(method, params):
        if method == "workorders.snapshot":
            return {
                "items": [
                    {
                        "work_order_id": "order",
                        "goal": "Build safely",
                        "status": "running",
                        "repository": "/private/other",
                        "tasks": [
                            {
                                "task_id": "task",
                                "status": "running",
                                "worker_id": "worker",
                                "lease_remaining_seconds": 10,
                            }
                        ],
                        "workers": [
                            {
                                "worker_id": "worker",
                                "responsive": True,
                                "config": {"secret": "worker-secret"},
                                "active": ["private-session"],
                            }
                        ],
                        "events": [{"payload": "raw-secret"}],
                        "gates": {"check_results": 1, "last_check_passed": True},
                    }
                ]
            }
        return original(method, params)

    monkeypatch.setattr(service, "dispatch", dispatch)
    result = access.rpc(device, "workorders.snapshot", {"project": project["id"]})
    row = result["items"][0]
    assert row["tasks"][0]["lease_remaining_seconds"] == 10
    assert row["workers"][0]["responsive"] is True
    assert row["gates"]["last_check_passed"] is True
    for secret in ["worker-secret", "raw-secret", "private-session", "/private/other"]:
        assert secret not in json.dumps(result)


def test_checkpoint_projection_hides_sensitive_content_and_accepts_checkpoint_ids(
    companion, monkeypatch
):
    service, project, _, profile, access = companion
    _, device = pair(access, profile, ["read"])
    original = service.dispatch
    calls = []

    def dispatch(method, params):
        if method == "checkpoints.list":
            return {
                "items": [
                    {
                        "id": "checkpoint-only",
                        "name": "Task",
                        "sealed": True,
                        "changes": [
                            {
                                "path": "hello.txt",
                                "change_type": "modified",
                                "old_content": "hidden-before",
                                "new_content": "hidden-after",
                            },
                            {"path": ".env", "old_content": "private-key"},
                        ],
                    }
                ]
            }
        if method == "checkpoints.diff":
            calls.append(params)
            return {"diff": "-before\n+after\n"}
        return original(method, params)

    monkeypatch.setattr(service, "dispatch", dispatch)
    result = access.rpc(device, "checkpoints.list", {"project": project["id"]})
    assert result["items"][0]["changes"] == [{"path": "hello.txt", "change_type": "modified"}]
    assert "hidden-before" not in json.dumps(result) and "private-key" not in json.dumps(result)
    assert access.rpc(
        device,
        "checkpoints.diff",
        {"project": project["id"], "id": "checkpoint-only", "path": "hello.txt"},
    )["diff"]
    assert calls[0]["id"] == "checkpoint-only"
    with pytest.raises(ValueError, match="non-sensitive"):
        access.rpc(
            device,
            "checkpoints.diff",
            {"project": project["id"], "id": "checkpoint-only", "path": ".env"},
        )


def test_revision_bound_review_feedback_and_opt_in_staging(companion):
    service, project, root, profile, access = companion
    _, reader = pair(access, profile, ["read"])
    (root / "hello.txt").write_text("new content\n")
    listing = access.rpc(reader, "review.list", {"project": project["id"], "scope": "uncommitted"})
    file = next(item for item in listing["files"] if item["layer"] == "unstaged")
    params = {"project": project["id"], "scope": "uncommitted", "file_id": file["id"]}
    document = access.rpc(reader, "review.diff", params)
    params["snapshot_id"] = document["snapshot_id"]
    index_before = subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage"])
    feedback = access.rpc(
        reader,
        "review.feedback",
        {**params, "hunk_id": 0, "start": 0, "end": 0, "comment": "Keep this revision in mind"},
    )
    assert document["snapshot_id"] in feedback["text"]
    assert subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage"]) == index_before
    assert service._all("SELECT id FROM jobs") == []
    with pytest.raises(PermissionError):
        access.rpc(reader, "review.stage", params, "not-approved")
    _, reviewer = pair(access, profile, ["read", "review"])
    (root / "hello.txt").write_text("changed again\n")
    with pytest.raises(ValueError, match="revision changed"):
        access.rpc(reviewer, "review.stage", params, "stale-review")
    assert subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage"]) == index_before
    document = access.rpc(
        reader, "review.diff", {k: v for k, v in params.items() if k != "snapshot_id"}
    )
    params["snapshot_id"] = document["snapshot_id"]
    assert access.rpc(reviewer, "review.stage", params, "reviewed-stage") == {"ok": True}
    assert (
        subprocess.check_output(["git", "-C", str(root), "show", ":hello.txt"])
        == b"changed again\n"
    )
    assert (root / "hello.txt").read_text() == "changed again\n"


def test_turn_changes_projection_filters_sensitive_paths_and_enforces_project_scope(
    companion, monkeypatch
):
    service, project, root, profile, access = companion
    _, device = pair(access, profile, ["read"])
    outside = root.parent / "other-turn-project"
    outside.mkdir()
    other = service.open_project(str(outside))
    service._write(
        "INSERT INTO jobs(id,project,kind,title,status,request,result,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
        ("job-shared", project["id"], "task", "Shared", "completed", "{}", "{}", 1.0, 2.0),
    )
    service._write(
        "INSERT INTO jobs(id,project,kind,title,status,request,result,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
        ("job-other", other["id"], "task", "Other", "completed", "{}", "{}", 1.0, 2.0),
    )
    with pytest.raises(PermissionError, match="not in a shared project"):
        access.rpc(device, "turns.changes", {"project": project["id"], "job": "job-other"})

    original = service.dispatch

    def dispatch(method, params):
        if method == "turns.changes":
            return {
                "available": True,
                "checkpoint": "cp-1",
                "live": False,
                "running": False,
                "file_count": 2,
                "added": 4,
                "removed": 1,
                "can_restore": True,
                "later_turns": 0,
                "conflicts": ["Sources/App.swift", ".env"],
                "files": [
                    {
                        "path": "Sources/App.swift",
                        "change": "modified",
                        "added": 4,
                        "removed": 1,
                        "binary": False,
                    },
                    {
                        "path": ".env",
                        "change": "modified",
                        "added": 1,
                        "removed": 0,
                        "binary": False,
                    },
                ],
            }
        return original(method, params)

    monkeypatch.setattr(service, "dispatch", dispatch)
    result = access.rpc(device, "turns.changes", {"project": project["id"], "job": "job-shared"})
    assert result["available"] is True
    assert result["file_count"] == 1
    assert result["excluded_count"] == 1
    assert [row["path"] for row in result["files"]] == ["Sources/App.swift"]
    assert result["conflicts"] == ["Sources/App.swift"]
    assert ".env" not in json.dumps(result)


def test_factory_inspection_is_bounded_and_gates_require_approve_permission(companion, monkeypatch):
    service, project, _, profile, access = companion
    _, reader = pair(access, profile, ["read"])
    _, approver = pair(access, profile, ["read", "approve"])
    original = service.dispatch
    gate_calls = []

    def dispatch(method, params):
        if method == "factory.list":
            return {
                "revisions": [{"digest": "rev-1", "intact": True}],
                "runs": [
                    {
                        "id": "wo-1",
                        "goal": "Ship safely",
                        "status": "needs_review",
                        "factory_digest": "snap-1",
                        "repository": "/private/repo",
                    }
                ],
            }
        if method == "factory.run.inspect":
            return {
                "work_order": {
                    "work_order_id": "wo-1",
                    "goal": "Ship safely",
                    "status": "needs_review",
                    "repository": "/private/repo",
                    "metadata": {
                        "factory": {"snapshot_digest": "snap-1", "secret_env": "hidden"},
                        "factory_verification": {
                            "state": "passed",
                            "sandbox": "docker",
                            "isolation_applied": True,
                        },
                    },
                    "tasks": [
                        {
                            "task_id": "stage-review",
                            "title": "Human review",
                            "role": "reviewer",
                            "status": "blocked",
                            "metadata": {
                                "human_gate": True,
                                "gate_digest": "gate-123",
                                "factory_stage": "review",
                                "worker_secret": "hidden-task",
                            },
                        }
                    ],
                },
                "evidence": [
                    {
                        "id": "art-1",
                        "kind": "factory_quality_record",
                        "task_id": "verify",
                        "content": json.dumps({"decision": {"verdict": "ship"}}),
                        "truncated": False,
                    }
                ],
                "candidate_diff": "+ok\n",
                "diff_truncated": False,
                "candidate_id": "cand-1",
                "candidate_digest": "dig-1",
                "cockpit": {
                    "status": "needs_review",
                    "elapsed_seconds": 12.5,
                    "workers": [{"secret": "no"}],
                },
            }
        if method == "factory.evidence.trace":
            return {
                "format": "superqode.factory-trace/2",
                "run": "wo-1",
                "snapshot_digest": "snap-1",
                "verification_bound_to_current": True,
                "missing_evidence": [],
                "summary": {
                    "checks": {"passed": 2, "failed": 0, "blocked": 0, "never_ran": 0},
                    "requirements": {},
                },
                "application_checks": [
                    {
                        "check": "unit",
                        "category": "test",
                        "status": "passed",
                        "reason": "All passed",
                        "cases": ["c1"],
                        "failed_cases": [],
                    }
                ],
                "requirements": [],
                "release_authorized": False,
            }
        if method == "factory.gate":
            gate_calls.append(params)
            return {"id": params["run"], "status": "running"}
        return original(method, params)

    monkeypatch.setattr(service, "dispatch", dispatch)
    listed = access.rpc(reader, "factory.list", {"project": project["id"]})
    assert listed["revision_count"] == 1
    assert listed["runs"][0]["id"] == "wo-1"
    assert "/private/repo" not in json.dumps(listed)

    inspected = access.rpc(reader, "factory.run.inspect", {"project": project["id"], "run": "wo-1"})
    assert inspected["work_order"]["tasks"][0]["metadata"]["gate_digest"] == "gate-123"
    for leaked in ["/private/repo", "hidden", "hidden-task", "secret"]:
        assert leaked not in json.dumps(inspected)

    traced = access.rpc(reader, "factory.evidence.trace", {"project": project["id"], "run": "wo-1"})
    assert traced["summary"]["checks"]["passed"] == 2

    gate_params = {
        "project": project["id"],
        "run": "wo-1",
        "stage": "stage-review",
        "gate_digest": "gate-123",
        "decision": "approve",
        "reason": "Looks good",
    }
    with pytest.raises(PermissionError):
        access.rpc(reader, "factory.gate", gate_params, "gate-no-perm")
    with pytest.raises(ValueError, match="approve or hold"):
        access.rpc(approver, "factory.gate", {**gate_params, "decision": "release"}, "gate-bad")
    assert access.rpc(approver, "factory.gate", gate_params, "gate-ok") == {
        "id": "wo-1",
        "status": "running",
    }
    assert gate_calls[0]["decision"] == "approve"
    with pytest.raises(PermissionError, match="not available"):
        access.rpc(
            approver,
            "factory.release.authorize",
            {"project": project["id"], "run": "wo-1"},
            "no-release",
        )
