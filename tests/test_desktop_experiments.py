import json
from pathlib import Path

import pytest

from test_desktop_service import desktop, wait_job
from superqode.desktop_service.experiments import candidate_paths


def suite(root):
    path = root / "tasks.yaml"
    path.write_text(
        "tasks:\n  - id: train\n    prompt: Say ready\n    expect_contains: ready\n    split: held-in\n  - id: gate\n    prompt: Say ready\n    expect_contains: ready\n    split: held-out\n"
    )
    return path


def test_preflight_reports_split_counts_and_quality_without_running(desktop):
    service, project, root = desktop
    path = suite(root)
    result = service.dispatch(
        "evals.inspect", {"project": project["id"], "tasks": str(path), "split": "held-out"}
    )
    assert result["task_count"] == 1
    assert result["optimization_ready"] is True
    assert result["tasks_hash"].startswith("sha256:")
    assert not service.dispatch("experiments.list", {"project": project["id"]})
    path.write_text(path.read_text().replace("    expect_contains: ready\n", ""))
    result = service.dispatch("evals.inspect", {"project": project["id"], "tasks": str(path)})
    assert not result["optimization_ready"]
    assert result["smoke_task_ids"] == ["train", "gate"]


def test_split_and_multiple_candidates_reach_real_setup_worker(desktop):
    service, project, root = desktop
    from superqode.harness.loader import harness_spec_to_dict
    from superqode.harness.templates import no_tool_template
    import yaml

    for index in range(2):
        (root / f"candidate{index}.yaml").write_text(
            yaml.safe_dump(harness_spec_to_dict(no_tool_template()))
        )
    job = service.dispatch(
        "evaluations.start",
        {
            "project": project["id"],
            "harness": "core",
            "provider": "ollama",
            "model": "unused",
            "tasks": str(suite(root)),
            "split": "held-out",
            "live": False,
            "variants": ["candidate0.yaml", "candidate1.yaml"],
        },
    )
    completed = wait_job(service, job["id"])
    assert completed["status"] == "completed", completed
    result = completed["result"]
    assert result["split"] == "held-out"
    assert len(result["variants"]) == 3
    assert all(v["skipped"] == 1 for v in result["variants"])
    assert all(v["tasks"][0]["id"] == "gate" for v in result["variants"])


def test_history_is_project_scoped_and_separate_from_latest_coding_runs(desktop):
    service, project, root = desktop
    other_root = root.parent / "other"
    other_root.mkdir()
    other = service.open_project(str(other_root))
    for index in range(110):
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (str(index), project["id"], "task", "coding", "completed", "{}", None, index, index),
        )
    for identity, owner in [("experiment", project["id"]), ("foreign", other["id"])]:
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (identity, owner, "evaluation", "suite", "completed", "{}", None, 0, 0),
        )
    assert [
        row["id"] for row in service.dispatch("experiments.list", {"project": project["id"]})
    ] == ["experiment"]


def test_candidate_limit_is_enforced_before_reading_files(tmp_path):
    with pytest.raises(ValueError, match="eight"):
        candidate_paths({"variants": ["missing"] * 9}, tmp_path)


def test_preflight_exposes_candidates_declared_inside_suite(desktop):
    service, project, root = desktop
    path = suite(root)
    (root / "extra.yaml").write_text("name: extra\n")
    path.write_text(path.read_text() + "variants:\n  - spec: extra.yaml\n")
    result = service.dispatch("evals.inspect", {"project": project["id"], "tasks": str(path)})
    assert result["candidate_count"] == 1
    assert any("additional candidate" in warning for warning in result["warnings"])
