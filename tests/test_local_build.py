"""Static local harness builder flow."""

from __future__ import annotations

from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local import build as build_mod
from superqode.local.build import build_local_harness, render_local_build_report
from superqode.local.doctor import DoctorReport
from superqode.local.engines import EngineStatus
from superqode.local.hardware import HardwareProfile
from superqode.local.matrix import ModelCandidate, StackRecommendation


def _doctor_report() -> DoctorReport:
    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="hf download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    return DoctorReport(
        hardware=HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
        engines={"mlx-lm": EngineStatus(engine="mlx-lm", installed=True, running=True)},
        inventory=[],
        recommendation=StackRecommendation(
            tier_id="apple_64",
            description="test",
            engine="mlx-lm",
            engine_ranked=["mlx-lm"],
            models=[candidate],
        ),
    )


def test_build_local_harness_writes_selected_model_and_pack(monkeypatch, tmp_path):
    monkeypatch.setattr(build_mod, "run_doctor", lambda *a, **k: _doctor_report())
    (tmp_path / "AGENTS.md").write_text("Local rules.\n", encoding="utf-8")

    report = build_local_harness(
        repo_path=tmp_path,
        model="MiniMaxAI/MiniMax-M1",
        endpoint="http://localhost:8000/v1",
        pack="minimax-m1",
        output="superqode.local.yaml",
        force=True,
    )

    target = tmp_path / "superqode.local.yaml"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "primary: openai_compatible/MiniMaxAI/MiniMax-M1" in text
    assert "pack: minimax-m1" in text
    assert report.harness_written is True
    assert report.pack == "minimax-m1"
    assert "Final live checks" in render_local_build_report(report)


def test_build_local_harness_dry_run_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(build_mod, "run_doctor", lambda *a, **k: _doctor_report())

    report = build_local_harness(
        repo_path=tmp_path,
        model="unknown-model",
        output="superqode.local.yaml",
        dry_run=True,
    )

    assert report.harness_written is False
    assert not (tmp_path / "superqode.local.yaml").exists()
    assert report.pack == "unknown-model"
    assert report.pack_draft is not None


def test_local_build_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(build_mod, "run_doctor", lambda *a, **k: _doctor_report())

    result = CliRunner().invoke(
        local,
        [
            "build",
            "--repo",
            str(tmp_path),
            "--model",
            "MiniMaxAI/MiniMax-M1",
            "--pack",
            "minimax-m1",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert "SuperQode local harness builder" in result.output
    assert (tmp_path / "superqode.local.yaml").exists()
