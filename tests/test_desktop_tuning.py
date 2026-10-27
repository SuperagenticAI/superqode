import json

import pytest

from test_desktop_service import desktop
from test_systemone_tune import CandidateClient, examples
from superqode.desktop_service.tuning import directory, review, run
from superqode.systemone import tune


def prepare(desktop, *, unlabeled=False):
    service, project, root = desktop
    rows = examples()
    if unlabeled:
        for row in rows:
            row["label"] = None
    path = root / "examples.json"
    path.write_text(json.dumps(rows))
    result = service.dispatch(
        "tuning.prepare",
        {"project": project["id"], "data": str(path), "reflection_model": "fake/model"},
    )
    return result


def test_native_prepare_resume_and_project_isolation(desktop):
    service, project, root = desktop
    current = prepare(desktop, unlabeled=True)
    assert current["needs_acquisition"]
    assert current["review"] == []
    assert sum(current["counts"].values()) == 12
    assert service.dispatch("tuning.list", {"project": project["id"]})[0]["id"] == current["id"]
    assert (
        service.dispatch("tuning.get", {"project": project["id"], "id": current["id"]}) == current
    )
    other_root = root.parent / "other"
    other_root.mkdir()
    other = service.open_project(str(other_root))
    assert service.dispatch("tuning.list", {"project": other["id"]}) == []
    with pytest.raises(FileNotFoundError):
        service.dispatch("tuning.get", {"project": other["id"], "id": current["id"]})
    with pytest.raises(ValueError, match="saved"):
        directory(service.root, project["id"], "../../elsewhere")


def test_native_round_acquires_and_labels_shared_tui_examples(desktop):
    service, project, _ = desktop
    current = prepare(desktop, unlabeled=True)
    output = directory(service.root, project["id"], current["id"])
    tune.acquire_review_batch(output, client=CandidateClient())
    current = review(output)
    assert current["review"]
    assert {row["acquired_by"] for row in current["review"]} >= {"uncertain", "audit", "holdout"}
    old_revision = current["revision"]
    for row in current["review"]:
        current = service.dispatch(
            "tuning.label",
            {
                "project": project["id"],
                "id": current["id"],
                "revision": current["revision"],
                "example": row["id"],
                "label": "cheap",
                "rationale": "reviewed",
            },
        )
    assert not current["review"]
    assert not current["needs_acquisition"]
    with pytest.raises(ValueError, match="changed"):
        service.dispatch(
            "tuning.label",
            {
                "project": project["id"],
                "id": current["id"],
                "revision": old_revision,
                "example": "1",
                "label": "cheap",
            },
        )
    assert all(
        row.get("label") for row in tune.load_run(output)["examples"] if row.get("selected_round")
    )


def test_native_start_requires_live_consent_and_completed_labels(desktop):
    service, project, _ = desktop
    current = prepare(desktop, unlabeled=True)
    params = {
        "project": project["id"],
        "id": current["id"],
        "revision": current["revision"],
        "stage": "optimize",
    }
    with pytest.raises(ValueError, match="consent"):
        service.dispatch("tuning.start", params)
    with pytest.raises(ValueError, match="Label"):
        service.dispatch("tuning.start", {**params, "live": True})
    captured = []
    service.start = lambda owner, kind, request: captured.append((owner, kind, request)) or {
        "id": "job"
    }
    service.dispatch("tuning.start", {**params, "live": True, "stage": "acquire"})
    assert captured[0][1] == "tuning"
    assert captured[0][2]["reflection_model"] == "fake/model"
    assert captured[0][2]["project"] == project["id"]


def test_live_writer_lease_blocks_labels_even_after_cancel_status(desktop):
    service, project, _ = desktop
    current = prepare(desktop)
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("writer", project["id"], "tuning", "round", "cancelled", "{}", None, 1, 1),
    )
    service.processes["writer"] = object()
    try:
        with pytest.raises(ValueError, match="Finish"):
            service.dispatch("tuning.decide", {"project": project["id"], "id": current["id"]})
    finally:
        service.processes.clear()


def test_native_worker_runs_staged_optimizer_without_exposing_test_set(desktop):
    from test_systemone_tune import improve

    service, project, root = desktop
    current = prepare(desktop)
    events = []
    run(
        {
            "state_root": str(service.root),
            "project": project["id"],
            "id": current["id"],
            "stage": "optimize",
        },
        lambda kind, data: events.append((kind, data)),
        client=CandidateClient(),
        optimizer=improve,
    )
    result = review(directory(service.root, project["id"], current["id"]))
    assert result["status"] == "completed"
    assert result["report"]["candidate"]["score"] == 1
    assert not result["report"]["eligible"]  # A small pilot is not a verified adoption.
    assert events[-1][0] == "result"
    assert not (root / ".superqode/harness").exists()


def test_native_child_reports_missing_live_credentials_and_preserves_round(desktop, monkeypatch):
    from test_desktop_service import wait_job

    service, project, _ = desktop
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    current = prepare(desktop, unlabeled=True)
    job = service.dispatch(
        "tuning.start",
        {
            "project": project["id"],
            "id": current["id"],
            "revision": current["revision"],
            "live": True,
            "stage": "acquire",
        },
    )
    result = wait_job(service, job["id"])
    assert result["status"] == "failed", result
    assert "TYPESAFE_API_KEY" in json.dumps(result)
    after = service.dispatch("tuning.get", {"project": project["id"], "id": current["id"]})
    assert after["needs_acquisition"]
    assert after["revision"] == current["revision"]


def test_practice_examples_need_no_file_credentials_or_model_calls(desktop, monkeypatch):
    service, project, root = desktop
    before = set(root.iterdir())

    def unexpected(*args, **kwargs):
        raise AssertionError("Practice preparation must not call a model or read a dataset")

    monkeypatch.setattr(tune, "read_examples", unexpected)
    monkeypatch.setattr(tune, "acquire_review_batch", unexpected)
    monkeypatch.setattr(tune, "run_tune", unexpected)
    result = service.dispatch("tuning.prepare", {"project": project["id"], "practice": True})
    assert result["synthetic_practice"]
    assert result["workflow"] == "batch"
    assert result["review"]
    assert not result["needs_acquisition"]
    assert set(root.iterdir()) == before
    assert service.dispatch("experiments.list", {"project": project["id"]}) == []
    row = result["review"][0]
    updated = service.dispatch(
        "tuning.label",
        {
            "project": project["id"],
            "id": result["id"],
            "revision": result["revision"],
            "example": row["id"],
            "label": result["labels"][0],
        },
    )
    assert len(updated["review"]) == len(result["review"]) - 1
    assert service.dispatch("tuning.get", {"project": project["id"], "id": result["id"]})[
        "synthetic_practice"
    ]
    with pytest.raises(ValueError, match="Practice"):
        service.dispatch(
            "tuning.decide",
            {
                "project": project["id"],
                "id": result["id"],
                "revision": updated["revision"],
                "decision": "accept",
            },
        )

    with pytest.raises(ValueError, match="offline only"):
        service.dispatch(
            "tuning.start",
            {
                "project": project["id"],
                "id": result["id"],
                "revision": updated["revision"],
                "stage": "optimize",
                "live": True,
            },
        )
