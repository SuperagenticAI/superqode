from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from superqode.commands.local import local
from superqode.harness.loader import load_harness_spec
from superqode.local.airplane import collect_health, doctor_airplane, prepare_airplane


def _repo(tmp_path: Path, name: str = "repo") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "app.py").write_text("def sentinel_airplane():\n    return 1\n", encoding="utf-8")
    return root


def test_prepare_writes_no_network_harness_and_manifest(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "work")
    ref = _repo(tmp_path, "ref")
    monkeypatch.setattr("superqode.local.airplane._semantic_available", lambda: (True, "ok"))

    report = prepare_airplane(
        repo_path=repo,
        refs=[ref],
        output_path=repo / "airplane.yaml",
        model="ollama/qwen3:8b",
        force=True,
    )

    harness = Path(report.harness_path)
    manifest = Path(report.manifest_path)
    assert harness.exists()
    assert manifest.exists()
    assert str(ref) in manifest.read_text(encoding="utf-8")
    assert Path(report.index_path).exists()
    assert report.indexed_files >= 2

    spec = load_harness_spec(harness)
    assert spec.execution_policy.allow_network is False
    assert "network" in spec.execution_policy.blocked_categories
    assert spec.execution_policy.config["airplane_mode"] is True
    assert spec.execution_policy.config["search_roots"] == [str(ref.resolve())]
    assert spec.agents[0].tools
    assert "local_code_search" in spec.agents[0].tools
    assert "semantic_search" in spec.agents[0].tools
    assert spec.metadata["airplane_mode"] is True


def test_prepare_refuses_to_overwrite_without_force(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    target = repo / "airplane.yaml"
    target.write_text("exists", encoding="utf-8")
    monkeypatch.setattr("superqode.local.airplane._semantic_available", lambda: (True, "ok"))

    try:
        prepare_airplane(repo_path=repo, output_path=target)
    except FileExistsError as exc:
        assert "already exists" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FileExistsError")


def test_doctor_reports_search_roots_and_model_suggestions(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "work")
    ref = _repo(tmp_path, "ref")
    monkeypatch.setattr("superqode.local.airplane._semantic_available", lambda: (False, "missing"))

    report = doctor_airplane(repo_path=repo, refs=[ref])
    assert report.repo == str(repo.resolve())
    assert str(ref.resolve()) in report.refs
    assert any(check.name == "semantic_search" and not check.ok for check in report.checks)
    assert isinstance(report.model_suggestions, list)


def test_collect_health_is_best_effort():
    health = collect_health()
    payload = health.to_dict()
    assert "warnings" in payload
    assert isinstance(payload["warnings"], list)


def test_airplane_cli_prepare_and_json(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "work")
    ref = _repo(tmp_path, "ref")
    monkeypatch.setattr("superqode.local.airplane._semantic_available", lambda: (True, "ok"))

    result = CliRunner().invoke(
        local,
        [
            "airplane",
            "prepare",
            "--repo",
            str(repo),
            "--ref",
            str(ref),
            "--output",
            "airplane.yaml",
            "--model",
            "ollama/qwen3:8b",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["harness_path"].endswith("airplane.yaml")
    assert payload["refs"] == [str(ref.resolve())]


def test_airplane_cli_models_json():
    result = CliRunner().invoke(local, ["airplane", "models", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
