import json

import pytest

from test_desktop_service import desktop  # noqa: F401


def add_turn(service, project, identity, parent=None, status="completed", prompt=None):
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            identity,
            project,
            "task",
            identity,
            status,
            json.dumps(
                {"prompt": prompt or identity, "parent_id": parent, "image_ids": ["private-image"]}
            ),
            json.dumps({"session_id": "private-session"}),
            1,
            1,
        ),
    )
    service.append(identity, {"type": "answer", "data": {"text": "visible answer " + identity}})
    service.append(
        identity,
        {
            "type": "harness_event",
            "data": {"event": "thinking", "payload": {"text": "PRIVATE_REASONING"}},
        },
    )


def test_share_is_scoped_visible_and_read_only(desktop):
    service, project, root = desktop
    add_turn(service, project["id"], "first")
    add_turn(service, project["id"], "second", "first")
    before = service.dispatch("jobs.list", {})
    result = service.dispatch("conversations.share", {"project": project["id"], "id": "second"})
    assert result["source_thread"] == "first"
    assert result["omitted_messages"] == 0
    assert "visible answer first" in result["text"]
    assert "visible answer second" in result["text"]
    for private in ["PRIVATE_REASONING", "private-image", "private-session"]:
        assert private not in result["text"]
    assert service.dispatch("jobs.list", {}) == before
    assert not service.processes
    other = root.parent / "other"
    other.mkdir()
    other_project = service.open_project(str(other))
    with pytest.raises(ValueError, match="selected project"):
        service.dispatch("conversations.share", {"project": other_project["id"], "id": "second"})


def test_share_bounds_complete_messages_and_rejects_active_source(desktop):
    service, project, _ = desktop
    add_turn(service, project["id"], "large", prompt="x" * 60_000)
    add_turn(service, project["id"], "recent", "large")
    result = service.dispatch("conversations.share", {"project": project["id"], "id": "recent"})
    assert result["omitted_messages"] == 1
    assert "visible answer recent" in result["text"]
    assert len(result["text"].encode()) < 50_000
    add_turn(service, project["id"], "busy", "recent", "running")
    with pytest.raises(ValueError, match="finished thread"):
        service.dispatch("conversations.share", {"project": project["id"], "id": "busy"})


@pytest.mark.parametrize("backend", ["adk", "pydanticai"])
def test_runtime_discovery_and_draft_without_execution(desktop, backend):
    import yaml

    service, project, _ = desktop
    runtimes = service.dispatch("connect.runtimes", {})
    assert any(row["backend"] == backend and "availability" in row for row in runtimes)
    result = service.dispatch(
        "connect.harness.draft", {"project": project["id"], "backend": backend}
    )
    data = yaml.safe_load(result["yaml"])
    assert data["runtime"]["backend"] == backend
    saved = service.dispatch(
        "connect.harness.save",
        {"project": project["id"], "name": "custom-" + backend, "yaml": result["yaml"]},
    )
    assert saved["id"] == "custom-" + backend
    assert service.dispatch("jobs.list", {}) == []


def test_catalog_includes_both_registries_and_documents_every_runtime(desktop):
    from pathlib import Path
    import re

    from superqode.harness.backends.registry import known_harness_backend_names
    from superqode.runtime.registry import known_runtime_names

    service, _, _ = desktop
    direct = set(known_runtime_names())
    harness = set(known_harness_backend_names())
    rows = service.dispatch("connect.runtimes", {})
    assert {row["backend"] for row in rows} == direct | harness
    assert len(rows) == len(direct | harness)
    for row in rows:
        assert row["agent_runtime"] == (row["backend"] in direct)
        assert row["harness_backend"] == (row["backend"] in harness)
        assert row["display_name"]
    by_id = {row["backend"]: row for row in rows}
    for name in {
        "antigravity-sdk",
        "antigravity-cli",
        "antigravity-managed",
        "devin-cli",
        "muse",
        "copilot-cli",
        "grok-cli",
    }:
        assert by_id[name]["agent_runtime"]
        assert not by_id[name]["harness_backend"]
    assert by_id["systemone"]["supports_decision"]
    assert not by_id["systemone"]["supports_coding"]
    assert by_id["strands"]["harness_backend"]
    inventory = (Path(__file__).parents[1] / "docs/integrations/runtimes-harnesses.md").read_text()
    documented = set(re.findall(r"^\| [^|]+ \| `([^`]+)` \|", inventory, re.MULTILINE))
    assert documented == direct | harness
    assert service.dispatch("jobs.list", {}) == []
