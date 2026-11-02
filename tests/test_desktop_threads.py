import json

import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service.service import DesktopService


def task(
    service,
    project,
    identity,
    *,
    parent=None,
    status="completed",
    updated=1,
    title=None,
    harness="core",
    route=None,
):
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            identity,
            project,
            "task",
            title or identity,
            status,
            json.dumps(
                {
                    "parent_id": parent,
                    "prompt": "PRIVATE_PROMPT",
                    "harness": harness,
                    "_desktop_route": route,
                    "model": "research-model",
                }
            ),
            json.dumps({"secret": "PRIVATE_PROVIDER_STATE"}),
            updated,
            updated,
        ),
    )


def test_thread_library_searches_beyond_recent_runs_and_scopes_projects(desktop):
    service, project, root = desktop
    for index in range(115):
        task(
            service, project["id"], f"thread-{index:03}", updated=index, title=f"Experiment {index}"
        )
    other_root = root.parent / "other"
    other_root.mkdir()
    other = service.open_project(str(other_root))
    task(service, other["id"], "foreign", title="Experiment foreign")
    result = service.dispatch("threads.list", {"project": project["id"], "query": "Experiment 0"})
    assert [r["id"] for r in result["items"]] == ["thread-000"]
    assert "PRIVATE" not in json.dumps(result)
    assert service.dispatch("threads.list", {"project": project["id"], "query": "research-model"})[
        "items"
    ]
    with pytest.raises(ValueError, match="not found in this project"):
        service.dispatch(
            "threads.update", {"project": project["id"], "id": "foreign", "pinned": True}
        )


def test_thread_lineage_paging_pin_and_rename_are_durable(desktop):
    service, project, _ = desktop
    task(service, project["id"], "root", title="Initial goal")
    task(service, project["id"], "followup", parent="root", updated=2)
    task(service, project["id"], "other", updated=3)
    service.dispatch(
        "threads.update",
        {
            "project": project["id"],
            "id": "followup",
            "pinned": True,
            "title": "  Routing research  ",
        },
    )
    first = service.dispatch("threads.list", {"project": project["id"], "limit": 1})
    assert first["items"][0]["id"] == "followup"
    assert first["items"][0]["turn_count"] == 2
    assert first["items"][0]["pinned"] is True
    assert first["items"][0]["conversation_title"] == "Routing research"
    second = service.dispatch(
        "threads.list", {"project": project["id"], "limit": 1, "cursor": first["next_cursor"]}
    )
    assert [r["id"] for r in second["items"]] == ["other"]
    assert not second["next_cursor"]
    assert service.dispatch("jobs.get", {"id": "root"})["conversation_title"] == "Routing research"
    assert service._all("SELECT title FROM jobs WHERE id='root'")[0]["title"] == "Initial goal"
    state = service.root
    service.close()
    reopened = DesktopService(state)
    try:
        saved = reopened.dispatch("threads.list", {"project": project["id"], "view": "pinned"})
        assert saved["items"][0]["conversation_title"] == "Routing research"
    finally:
        reopened.close()


def test_archive_is_reversible_and_rejects_any_working_turn(desktop):
    service, project, _ = desktop
    task(service, project["id"], "root", status="running", updated=1)
    task(service, project["id"], "later", parent="root", updated=2)
    params = {"project": project["id"], "id": "later", "archived": True}
    with pytest.raises(ValueError, match="Finish or stop"):
        service.dispatch("threads.update", params)
    working = service.dispatch("threads.list", {"project": project["id"], "view": "working"})
    assert working["items"][0]["id"] == "root"
    service._status("root", "completed")
    service.dispatch("threads.update", params)
    assert not service.dispatch("threads.list", {"project": project["id"]})["items"]
    archived = service.dispatch("threads.list", {"project": project["id"], "view": "archived"})
    assert len(archived["items"]) == 1
    assert all(r["archived"] for r in service.dispatch("jobs.list", {}))
    with pytest.raises(ValueError, match="Restore this archived thread"):
        service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "parent_id": "later",
                "harness": "core",
                "provider": "openai",
                "model": "fixture",
                "prompt": "Continue",
            },
        )
    service.dispatch("threads.update", {**params, "archived": False})
    assert len(service.dispatch("threads.list", {"project": project["id"]})["items"]) == 1
    assert not service.processes


def test_cursor_is_bound_to_project_query_and_filter(desktop):
    service, project, _ = desktop
    task(service, project["id"], "one")
    task(service, project["id"], "two")
    first = service.dispatch("threads.list", {"project": project["id"], "limit": 1})
    for changes in [{"query": "one"}, {"view": "all"}, {"cursor": "malformed"}]:
        with pytest.raises(ValueError, match="Refresh the list"):
            service.dispatch(
                "threads.list",
                {"project": project["id"], "cursor": first["next_cursor"], **changes},
            )


@pytest.mark.parametrize(
    "change",
    [
        {"title": ""},
        {"title": "x" * 201},
        {"title": "line\nbreak"},
        {"pinned": "true"},
        {"archived": 1},
    ],
)
def test_thread_metadata_rejects_invalid_inputs(desktop, change):
    service, project, _ = desktop
    task(service, project["id"], "one")
    with pytest.raises(ValueError):
        service.dispatch("threads.update", {"project": project["id"], "id": "one", **change})


def test_metadata_updates_preserve_independent_fields_and_attention_filter(desktop):
    service, project, _ = desktop
    task(service, project["id"], "one", status="failed")
    params = {"project": project["id"], "id": "one"}
    service.dispatch("threads.update", {**params, "title": "Investigate failure"})
    service.dispatch("threads.update", {**params, "pinned": True})
    rows = service.dispatch("threads.list", {"project": project["id"], "view": "attention"})[
        "items"
    ]
    assert rows[0]["conversation_title"] == "Investigate failure"
    assert rows[0]["pinned"] is True
    assert service.dispatch("threads.list", {"project": project["id"], "query": "%"})["items"] == []


def test_thread_resolution_finds_latest_turn_from_stable_root(desktop):
    service, project, _ = desktop
    task(service, project["id"], "root")
    task(service, project["id"], "next", parent="root", updated=2)
    resolved = service.dispatch("threads.get", {"project": project["id"], "id": "root"})
    assert resolved["id"] == "next"
    assert resolved["conversation_id"] == "root"
    with pytest.raises(ValueError, match="not found"):
        service.dispatch("threads.get", {"project": project["id"], "id": "missing"})


def test_harness_badges_include_full_history_and_survive_restart(desktop):
    service, project, _ = desktop
    task(
        service,
        project["id"],
        "root",
        harness="acp:codex",
        route={"name": "Codex", "agent_id": "codex", "extra_env": {"KEY": "PRIVATE_CREDENTIAL"}},
    )
    parent = "root"
    for index in range(1, 112):
        identity = f"turn-{index:03}"
        harness = (
            "acp:custom-retired" if index == 1 else "acp:claude" if index < 111 else "acp:codex"
        )
        route = (
            {"name": "My research harness"}
            if index == 1
            else {"name": "Claude" if index < 111 else "Codex"}
        )
        task(
            service,
            project["id"],
            identity,
            parent=parent,
            updated=index + 1,
            harness=harness,
            route=route,
        )
        parent = identity
    summaries = service.dispatch("jobs.list", {})
    row = summaries[0]
    expected = ["acp:codex", "acp:custom-retired", "acp:claude"]
    assert [item["id"] for item in row["harnesses_used"]] == expected
    assert [item["icon_key"] for item in row["harnesses_used"]] == [
        "codex",
        "custom-retired",
        "claude",
    ]
    assert row["harnesses_used"][1]["name"] == "My research harness"
    assert "PRIVATE" not in json.dumps(summaries)
    listing = service.dispatch("threads.list", {"project": project["id"]})["items"][0]
    assert listing["harnesses_used"] == row["harnesses_used"]
    for query in ["My research harness", "claude", "custom-retired"]:
        assert (
            service.dispatch("threads.list", {"project": project["id"], "query": query})["items"][
                0
            ]["id"]
            == parent
        )
    assert not service.dispatch("threads.list", {"project": project["id"], "query": "PRIVATE"})[
        "items"
    ]
    assert service.dispatch("jobs.get", {"id": parent})["harnesses_used"] == row["harnesses_used"]
    state = service.root
    service.close()
    reopened = DesktopService(state)
    try:
        assert (
            reopened.dispatch("threads.get", {"project": project["id"], "id": "root"})[
                "harnesses_used"
            ]
            == row["harnesses_used"]
        )
        assert not reopened.processes
    finally:
        reopened.close()
