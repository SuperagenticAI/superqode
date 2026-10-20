"""Advanced native forms invoke typed engine commands without a shell or persisted secrets."""

import json
import subprocess
import time

import click
import pytest

from superqode.desktop_service.tools import command_catalog, tool_arguments
from superqode.desktop_service.service import DesktopService


@pytest.fixture
def desktop(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    service = DesktopService(tmp_path / "state")
    opened = service.open_project(str(project))
    yield service, opened["id"], project
    service.close()


def wait(service, identity):
    for _ in range(250):
        result = service.dispatch("jobs.get", {"id": identity})
        if result["status"] not in {"running", "needs_approval"}:
            return result
        time.sleep(0.03)
    pytest.fail(str(result))


def test_catalog_covers_advanced_features_and_budgets_are_not_secrets():
    rows = command_catalog()
    assert {row["category"] for row in rows} >= {
        "work",
        "memory",
        "skills",
        "mcp",
        "harness",
        "skillopt",
        "optimize",
    }
    assert {
        "work create",
        "memory remember",
        "mcp login",
        "harness refine",
        "harness promote stage",
        "harness optimize-omni",
    } <= {row["id"] for row in rows}
    for row in rows:
        for field in row["fields"]:
            if field["name"] in {"max_tokens", "max_token_cost", "max_output_tokens"}:
                assert not field["secret"]


def test_typed_command_validation_rejects_unknown_actions_and_preserves_literal_values():
    text = "a path with spaces; $(touch should-never-exist)"
    assert tool_arguments("memory remember", {"memory remember:text": text})["argv"] == [
        "memory",
        "remember",
        text,
    ]
    with pytest.raises(ValueError):
        tool_arguments("arbitrary shell", {})
    with pytest.raises(ValueError):
        tool_arguments("memory remember", {"invented": "value"})
    with pytest.raises(ValueError):
        tool_arguments("memory search", {})
    with pytest.raises(click.BadParameter):
        tool_arguments(
            "memory search", {"memory search:query": "q", "memory search:limit": "not-a-number"}
        )


def test_memory_workflow_runs_through_real_worker_without_shell_expansion(desktop):
    service, project, root = desktop
    text = "native fixture note with spaces; $(touch should-never-exist)"
    start = service.dispatch(
        "tools.start",
        {
            "project": project,
            "action": "memory remember",
            "values": {"memory remember:text": text},
            "command_id": "remember",
        },
    )
    assert wait(service, start["id"])["status"] == "completed"
    query = service.dispatch(
        "tools.start",
        {
            "project": project,
            "action": "memory search",
            "values": {"memory search:query": "native fixture", "memory search:json_output": True},
            "command_id": "search",
        },
    )
    result = wait(service, query["id"])
    assert result["status"] == "completed", result
    assert "native fixture note" in json.dumps(result["events"])
    assert not (root / "should-never-exist").exists()


def test_secure_form_values_are_redacted_before_job_persistence(desktop, monkeypatch):
    import superqode.main

    @click.group()
    def root():
        pass

    @root.group()
    def memory():
        pass

    @memory.command()
    @click.option("--api-key", required=True)
    def protected(api_key):
        pass

    monkeypatch.setattr(superqode.main, "cli_main", root)
    service, project, _ = desktop
    values = {"memory protected:api_key": "private-native-tool-fixture"}
    plan = service.dispatch("tools.prepare", {"action": "memory protected", "values": values})
    assert "private-native-tool-fixture" not in json.dumps(plan)
    job = service.dispatch(
        "tools.start",
        {
            "project": project,
            "action": "memory protected",
            "values": values,
            "command_id": "private",
        },
    )
    result = wait(service, job["id"])
    assert "private-native-tool-fixture" not in json.dumps(result)
    assert b"private-native-tool-fixture" not in (service.root / "desktop.sqlite").read_bytes()
