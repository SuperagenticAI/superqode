"""Historical run detail keeps conversation identity outside the recent list."""

import json

from test_desktop_service import desktop  # noqa: F401


def add_run(service, project, identity, parent=None, updated=1):
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            identity,
            project["id"],
            "task",
            "Title " + identity,
            "completed",
            json.dumps({"parent_id": parent} if parent else {}),
            "{}",
            updated,
            updated,
        ),
    )


def test_old_run_detail_resolves_root_without_recent_list(desktop):
    service, project, _ = desktop
    add_run(service, project, "root")
    add_run(service, project, "middle", "root", updated=2)
    add_run(service, project, "last", "middle", updated=3)
    for index in range(101):
        add_run(service, project, f"recent-{index}", updated=10 + index)
    assert "last" not in {row["id"] for row in service.dispatch("jobs.list", {})}
    service._conversation_roots.clear()
    detail = service.dispatch("jobs.get", {"id": "last"})
    assert detail["conversation_id"] == "root"
    assert detail["conversation_title"] == "Title root"
    assert detail["request"]["parent_id"] == "middle"
    assert service.dispatch("jobs.get", {"id": "middle"})["conversation_id"] == "root"


def test_conversation_identity_never_crosses_projects(desktop, tmp_path):
    service, project, _ = desktop
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = service.open_project(str(other_root))
    add_run(service, other, "foreign")
    add_run(service, project, "local", "foreign")
    detail = service.dispatch("jobs.get", {"id": "local"})
    assert detail["conversation_id"] == "local"
    assert detail["project"] == project["id"]


def test_broken_lineage_preserves_independent_identity(desktop):
    service, project, _ = desktop
    add_run(service, project, "orphan", "missing")
    assert service.dispatch("jobs.get", {"id": "orphan"})["conversation_id"] == "orphan"


def test_compaction_keeps_original_conversation_draft_identity(desktop):
    service, project, _ = desktop
    add_run(service, project, "root")
    add_run(service, project, "latest", "root", updated=2)
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "compacted",
            project["id"],
            "compaction",
            "Compact context",
            "completed",
            json.dumps({"source_job": "latest"}),
            "{}",
            3,
            3,
        ),
    )
    result = service.dispatch("jobs.get", {"id": "compacted"})
    assert result["conversation_id"] == "root"
    assert result["conversation_title"] == "Title root"


def test_compaction_cannot_inherit_another_projects_conversation(desktop, tmp_path):
    service, project, _ = desktop
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = service.open_project(str(other_root))
    add_run(service, other, "foreign")
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "compacted",
            project["id"],
            "compaction",
            "Compact context",
            "completed",
            json.dumps({"source_job": "foreign"}),
            "{}",
            3,
            3,
        ),
    )
    assert service.dispatch("jobs.get", {"id": "compacted"})["conversation_id"] == "compacted"
