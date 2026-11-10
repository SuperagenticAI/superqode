"""Recursive agents stay off the Local AI list and never start a worker."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from test_desktop_service import desktop  # noqa: F401

from superqode.desktop_service import recursive
from superqode.desktop_service.local_models import harnesses
from superqode.rlm.root_runtime import runtime_dir


@pytest.fixture
def isolated_rlm(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_RLM_DIR", str(tmp_path / "rlm"))
    recursive._installs.clear()
    yield
    recursive._installs.clear()


def _forbid_popen(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("RLM inspection started a process")

    monkeypatch.setattr("subprocess.Popen", boom)
    monkeypatch.setattr("superqode.rlm.root_runtime.subprocess.Popen", boom)


def _plant(tmp_path: Path, root: Path, *, alive: bool) -> Path:
    session_id = "desk-1"
    directory = runtime_dir(session_id, root)
    directory.mkdir(parents=True)
    manifest = {
        "protocol": "1.0",
        "session_id": session_id,
        "working_directory": str(root.resolve()),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    session = tmp_path / "session.json"
    session.write_text("{}", encoding="utf-8")
    journal = session.with_suffix(".agents.jsonl")
    journal.write_text(
        json.dumps(
            {
                "type": "agent.updated",
                "agent": {
                    "id": "child-1",
                    "status": "running",
                    "parent_id": "root",
                    "prompt": "look here",
                    "usage": {"total_tokens": 12, "cost_usd": 0.25},
                },
            }
        )
        + "\n"
        + json.dumps({"type": "agent.deleted", "agent": {"id": "gone"}})
        + "\n",
        encoding="utf-8",
    )
    (directory / "state.json").write_text(
        json.dumps(
            {
                "pid": os.getpid() if alive else 0,
                "state": "running" if alive else "stopped",
                "heartbeat": time.time() if alive else 0,
                "session_path": str(session),
                "generation": "g1",
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_local_ai_does_not_list_monty_or_docker_templates(desktop):
    service, project, _ = desktop
    ids = {row["id"] for row in harnesses(service, project["id"])}
    assert "rlm" in ids
    assert "rlm-monty" not in ids
    assert "rlm-docker" not in ids
    assert "rlm-hybrid" not in ids


def test_inspect_reads_the_journal_without_starting_a_worker(
    desktop, tmp_path, monkeypatch, isolated_rlm
):
    service, project, root = desktop
    _forbid_popen(monkeypatch)
    _plant(tmp_path, root, alive=False)
    result = service.dispatch("rlm.inspect", {"project": project["id"], "harness": "rlm"})
    assert result["worker_running"] is False
    assert result["worker"] == "stopped"
    assert result["sandbox"] == "host"
    assert result["read_only"] is False
    assert result["a2a"] is False
    assert (result["max_depth"], result["max_children"], result["max_parallel"]) == (
        3,
        8,
        4,
    )
    assert [row["id"] for row in result["children"]] == ["child-1"]
    assert result["usage"]["total_tokens"] == 12
    assert result["usage"]["children"] == 1


def test_command_refuses_a_stopped_worker(desktop, tmp_path, monkeypatch, isolated_rlm):
    service, project, root = desktop
    _forbid_popen(monkeypatch)
    _plant(tmp_path, root, alive=False)
    with pytest.raises(ValueError, match="not running"):
        service.dispatch(
            "rlm.command",
            {
                "project": project["id"],
                "harness": "rlm",
                "command": "goal",
                "argument": "ship",
            },
        )


def test_command_queues_on_a_live_worker_without_starting_one(
    desktop, tmp_path, monkeypatch, isolated_rlm
):
    service, project, root = desktop
    _forbid_popen(monkeypatch)
    directory = _plant(tmp_path, root, alive=True)
    result = service.dispatch(
        "rlm.command",
        {
            "project": project["id"],
            "harness": "rlm",
            "command": "goal",
            "argument": "ship",
        },
    )
    assert result["queued"] is True
    record = json.loads((directory / "commands.jsonl").read_text(encoding="utf-8"))
    assert record["operation"] == "admin"
    assert record["payload"] == {"command": "goal", "argument": "ship"}
    assert not (directory / "controls.jsonl").exists()


def test_monty_commands_are_refused(desktop, monkeypatch, isolated_rlm):
    service, project, _ = desktop
    _forbid_popen(monkeypatch)
    with pytest.raises(ValueError, match="read-only"):
        service.dispatch(
            "rlm.command",
            {
                "project": project["id"],
                "harness": "rlm-monty",
                "command": "cancel",
                "agent": "child-1",
            },
        )


def test_empty_goal_clears_and_install_reuses_one_job(monkeypatch, isolated_rlm):
    assert recursive._argument("goal", {"argument": "  "}) == "off"
    assert recursive._argument("goal", {"argument": "ship"}) == "ship"
    started = threading.Event()
    release = threading.Event()

    def slow(_root, extra):
        assert extra == "monty"
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(recursive, "_monty_importable", lambda: False)
    monkeypatch.setattr("superqode.desktop_service.app_setup.install_extra", slow)

    class Service:
        root = Path("/tmp/superqode-state")

    first = recursive.monty_install(Service())
    assert started.wait(5)
    second = recursive.monty_install(Service())
    assert second["id"] == first["id"]
    assert second["status"] == "running"
    release.set()
    status = {"status": "running"}
    for _ in range(50):
        status = recursive.monty_status({"id": first["id"]})
        if status["status"] != "running":
            break
        time.sleep(0.02)
    assert status["status"] == "completed"
