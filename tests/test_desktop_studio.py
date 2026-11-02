"""Revision ownership and reviewed Harness Studio contracts; no external model calls."""

import json
from pathlib import Path
import time

import pytest
import yaml

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import studio, local_models
from superqode.harness.verification import summary


def review(service, project, slug="my-studio-harness", backend="builtin", route=None):
    draft = service.dispatch("studio.open", {"project": project, "reference": "core"})
    data = yaml.safe_load(draft["yaml"])
    data["runtime"]["backend"] = backend
    return service.dispatch(
        "studio.inspect",
        {
            "project": project,
            "name": slug,
            "yaml": yaml.safe_dump(data),
            "route": route
            or {"source": "provider", "provider": "openai", "model": "fixture-model"},
        },
    )


def save(service, project, inspected, expected="", reason="Initial revision"):
    return service.dispatch(
        "studio.save",
        {
            "project": project,
            "review": inspected["review"],
            "digest": inspected["digest"],
            "expected_file_digest": expected,
            "reason": reason,
        },
    )


def test_inspection_does_not_write_project_or_start_work(desktop):
    service, project, root = desktop
    inspected = review(service, project["id"])
    assert inspected["backend"] == "builtin" and inspected["inspection"]["ok"]
    assert inspected["routes"][0]["model"] == "openai/fixture-model"
    assert not (root / ".superqode").exists()
    assert not service.dispatch("jobs.list", {})


def test_saved_snapshot_is_immutable_and_restoring_preserves_history(desktop):
    service, project, root = desktop
    first = review(service, project["id"])
    saved = save(service, project["id"], first)
    initial = Path(saved["reference"]).read_bytes()
    data = yaml.safe_load(first["yaml"])
    data["description"] = "A second revision"
    second = service.dispatch(
        "studio.inspect",
        {"project": project["id"], "name": first["name"], "yaml": yaml.safe_dump(data)},
    )
    saved_second = save(
        service, project["id"], second, expected=first["digest"], reason="Changed description"
    )
    assert first["digest"] != saved_second["digest"]
    assert Path(saved["reference"]).read_bytes() == initial
    versions = service.dispatch(
        "studio.revisions", {"project": project["id"], "name": first["name"]}
    )
    assert len(versions) == 2 and sum(row["current"] for row in versions) == 1
    restored = service.dispatch(
        "studio.open",
        {"project": project["id"], "name": first["name"], "revision": first["digest"]},
    )
    inspected = service.dispatch(
        "studio.inspect",
        {
            "project": project["id"],
            "name": first["name"],
            "yaml": restored["yaml"],
            "route": restored["route"],
        },
    )
    save(
        service,
        project["id"],
        inspected,
        expected=saved_second["digest"],
        reason="Restore the original definition",
    )
    assert Path(saved["path"]).read_bytes() == initial
    history = (
        (root / ".superqode/harness-studio" / first["name"] / "history.jsonl")
        .read_text()
        .splitlines()
    )
    assert (
        len(history) == 3 and json.loads(history[-1])["reason"] == "Restore the original definition"
    )
    assert not service.dispatch("jobs.list", {})


def test_external_edit_and_stale_review_cannot_overwrite_project_definition(desktop):
    service, project, _ = desktop
    first = review(service, project["id"])
    saved = save(service, project["id"], first)
    second = review(service, project["id"], first["name"])
    Path(saved["path"]).write_text("external edit")
    with pytest.raises(ValueError, match="changed"):
        save(service, project["id"], second, expected=first["digest"])
    assert Path(saved["path"]).read_text() == "external edit"
    with pytest.raises(ValueError, match="changed after"):
        service.dispatch(
            "studio.save",
            {
                "project": project["id"],
                "review": second["review"],
                "digest": "wrong",
                "reason": "No",
            },
        )
    service._write("UPDATE studio_reviews SET created=0")
    with pytest.raises(ValueError, match="expired"):
        save(service, project["id"], second)


@pytest.mark.parametrize("relative", [".superqode/harnesses", ".superqode/harness-studio"])
def test_studio_rejects_storage_symlinks(desktop, tmp_path, relative):
    service, project, root = desktop
    inspected = review(service, project["id"])
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    link = root / relative
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        save(service, project["id"], inspected)
    assert not list(outside.iterdir())


def test_inline_credentials_inheritance_and_recursive_aliases_are_rejected(desktop):
    service, project, _ = desktop
    for text, expected in [
        (
            "name: my-test\nruntime:\n  backend: builtin\n  config:\n    api_key: private-fixture\n",
            "credentials",
        ),
        ("name: my-test\ninherits: ../outside.yaml\n", "resolved preset"),
        ("name: my-test\nmetadata: &loop\n  again: *loop\n", "Recursive"),
    ]:
        with pytest.raises(ValueError, match=expected):
            service.dispatch(
                "studio.inspect", {"project": project["id"], "name": "my-test", "yaml": text}
            )
    assert "private-fixture" not in json.dumps(service._all("SELECT * FROM studio_reviews"))


def test_revision_selection_uses_digest_bound_route_and_survives_catalog_refresh(
    desktop, monkeypatch
):
    service, project, _ = desktop
    monkeypatch.setattr(
        local_models,
        "available",
        lambda engine: {
            "endpoint": "http://127.0.0.1:1234/v1",
            "provider": "lmstudio",
            "models": ["fixture-model"],
        },
    )
    inspected = review(
        service,
        project["id"],
        route={"source": "local", "engine": "lmstudio", "model": "fixture-model"},
    )
    saved = save(service, project["id"], inspected)
    metadata = Path(saved["reference"]).with_suffix(".json")
    data = json.loads(metadata.read_text())
    data["route"] = {"source": "provider", "provider": "remote", "model": "unrelated"}
    metadata.write_text(json.dumps(data))
    selected = service.dispatch(
        "studio.use",
        {"project": project["id"], "name": inspected["name"], "revision": saved["digest"]},
    )
    assert selected["route"]["provider"] == "lmstudio"
    assert selected["route"]["endpoint"] == "http://127.0.0.1:1234/v1"
    assert any(
        row["id"] == saved["reference"]
        for row in service.dispatch("harnesses.list", {"project": project["id"]})
    )
    bindings = local_models.binding(
        service, project["id"], saved["reference"], "lmstudio", "fixture-model"
    )
    assert bindings[0]["endpoint"] == "http://127.0.0.1:1234/v1"
    assert not service.dispatch("jobs.list", {})
    Path(saved["reference"]).write_text("tampered")
    with pytest.raises(ValueError, match="intact"):
        service.dispatch(
            "studio.use",
            {"project": project["id"], "name": inspected["name"], "revision": saved["digest"]},
        )


def test_missing_sdk_does_not_become_verified_or_start_a_job(desktop):
    service, project, _ = desktop
    inspected = review(service, project["id"], backend="adk")
    if inspected["inspection"]["capabilities"]["availability"] == "available":
        pytest.skip("This environment has ADK installed")
    with pytest.raises(ValueError, match="setup"):
        service.dispatch(
            "studio.check.prepare",
            {
                "project": project["id"],
                "review": inspected["review"],
                "digest": inspected["digest"],
            },
        )
    assert not service.dispatch("jobs.list", {})


def test_explicit_provider_revision_clears_stale_local_bindings(desktop):
    service, project, _ = desktop
    inspected = review(service, project["id"])
    saved = save(service, project["id"], inspected)
    for reference in ("core", "no-tool", saved["reference"]):
        service._write(
            "INSERT INTO local_model_bindings VALUES(?,?,?,?,?)",
            (project["id"], reference, "openai", "fixture-model", "http://127.0.0.1:9999/v1"),
        )
    selected = service.dispatch(
        "studio.use",
        {"project": project["id"], "name": inspected["name"], "revision": saved["digest"]},
    )
    assert selected["route"]["source"] == "provider"
    assert not service._all("SELECT * FROM local_model_bindings WHERE project=?", (project["id"],))
    assert not service.dispatch("jobs.list", {})


@pytest.mark.parametrize(
    "policy,check,message",
    [("allow_read", "read", "reads enabled"), ("allow_write", "edit", "disables writes")],
)
def test_restricted_check_respects_source_tool_policy(desktop, policy, check, message):
    service, project, _ = desktop
    draft = service.dispatch("studio.open", {"project": project["id"], "reference": "core"})
    data = yaml.safe_load(draft["yaml"])
    data["execution_policy"][policy] = False
    inspected = service.dispatch(
        "studio.inspect",
        {
            "project": project["id"],
            "name": "restricted-source",
            "yaml": yaml.safe_dump(data),
            "route": {"source": "provider", "provider": "openai", "model": "fixture-model"},
        },
    )
    with pytest.raises(ValueError, match=message):
        service.dispatch(
            "studio.check.prepare",
            {
                "project": project["id"],
                "review": inspected["review"],
                "digest": inspected["digest"],
                "check": check,
            },
        )
    assert not service.dispatch("jobs.list", {})


def test_prepare_freezes_source_and_repeat_budget_without_model_calls(desktop):
    service, project, _ = desktop
    inspected = review(service, project["id"])
    params = {
        "project": project["id"],
        "review": inspected["review"],
        "digest": inspected["digest"],
        "check": "edit",
        "repeats": 3,
    }
    plan = service.dispatch("studio.check.prepare", params)
    assert plan["source_digest"] == inspected["digest"] and plan["repeats"] == 3
    assert plan["spec"]["runtime"]["backend"] == "builtin"
    for invalid in [0, 6, True]:
        with pytest.raises(ValueError):
            service.dispatch("studio.check.prepare", {**params, "repeats": invalid})
    with pytest.raises(ValueError, match="changed"):
        service.dispatch(
            "studio.check.start",
            {"project": project["id"], "plan": plan["plan"], "digest": "wrong"},
        )
    assert not service.dispatch("jobs.list", {})


def test_failed_attempts_and_unknown_usage_remain_in_summary():
    reports = [
        {"status": "passed", "tokens_in": 10, "tokens_out": 5, "cost_usd": 0.01},
        {"status": "error", "tokens_in": None, "tokens_out": None},
    ]
    projected = summary(reports)
    assert projected["attempts"] == 2 and projected["passed"] == 1 and projected["failed"] == 1
    assert projected["pass_rate"] == 0.5
    assert projected["tokens_in"] is None and projected["tokens_in_known_attempts"] == 1
    assert projected["cost_usd"] is None
    assert 0 < projected["wilson_95"][0] < 0.5 < projected["wilson_95"][1] < 1
