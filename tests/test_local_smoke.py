"""MVP local init/smoke tests."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local import smoke as smoke_mod
from superqode.local.bench import BenchResult
from superqode.local.doctor import DoctorReport
from superqode.local.engines import EngineStatus
from superqode.local.hardware import HardwareProfile
from superqode.local.matrix import ModelCandidate, StackRecommendation
from superqode.local.smoke import render_smoke, run_smoke


class _Manager:
    def __init__(self, rows=None, statuses=None):
        self._rows = rows or []
        self._statuses = statuses or {}

    def list_all(self):
        return self._rows

    def status(self, engine):
        return self._statuses.get(engine, {"running": False})


async def _context(_base, _model):
    return (16384, "/v1/models")


@pytest.fixture(autouse=True)
def _reachable(monkeypatch):
    """Default: treat any endpoint as reachable; tests opt out explicitly."""
    monkeypatch.setattr(smoke_mod, "endpoint_reachable", lambda endpoint: True)


def test_smoke_diagnoses_unreachable_server(monkeypatch):
    monkeypatch.setattr(
        smoke_mod,
        "get_manager",
        lambda: _Manager(rows=[{"engine": "ollama", "running": True, "base_url": "http://x/v1"}]),
    )
    monkeypatch.setattr(smoke_mod, "endpoint_reachable", lambda endpoint: False)

    report = run_smoke()

    assert report.status == "failed"
    assert report.checks[0].name == "server"
    assert report.checks[0].ok is False
    assert "no response" in report.checks[0].detail
    assert "superqode local serve" in report.next_steps[0]


def test_smoke_diagnoses_no_running_server(monkeypatch):
    monkeypatch.setattr(smoke_mod, "get_manager", lambda: _Manager())

    report = run_smoke()

    assert report.status == "failed"
    assert report.checks[0].name == "server"
    assert report.checks[0].ok is False
    assert "superqode local serve" in report.next_steps[0]


def test_smoke_diagnoses_embedding_only_server(monkeypatch):
    monkeypatch.setattr(
        smoke_mod,
        "get_manager",
        lambda: _Manager(rows=[{"engine": "lmstudio", "running": True, "base_url": "http://x/v1"}]),
    )
    monkeypatch.setattr(smoke_mod, "list_endpoint_models", lambda endpoint: ["nomic-embed-text"])

    report = run_smoke()

    assert report.status == "failed"
    assert any("embedding" in check.detail for check in report.checks)
    assert "Load a chat/coding model" in report.next_steps[0]


def test_smoke_ready_report(monkeypatch):
    monkeypatch.setattr(
        smoke_mod,
        "get_manager",
        lambda: _Manager(rows=[{"engine": "ollama", "running": True, "base_url": "http://x/v1"}]),
    )
    monkeypatch.setattr(smoke_mod, "list_endpoint_models", lambda endpoint: ["qwen3-coder"])
    monkeypatch.setattr(smoke_mod, "probe_base_url", _context)
    monkeypatch.setattr(
        smoke_mod,
        "run_agentic_bench",
        lambda *a, **k: BenchResult(
            endpoint="http://x/v1",
            model="qwen3-coder",
            ok=True,
            ttft_s=0.4,
            decode_tps=50.0,
            tool_call_success=True,
            edit_format_success=True,
            shell_call_success=True,
            context_recall_success=True,
            agentic_score=100.0,
            mode="agentic",
        ),
    )

    report = run_smoke(repo_path=".")
    text = render_smoke(report)

    assert report.status == "ready"
    assert report.context_window == 16384
    assert "Local coding harness ready" in text
    assert "read_file_tool" in text


def test_local_smoke_cli_json(monkeypatch):
    monkeypatch.setattr(
        smoke_mod,
        "get_manager",
        lambda: _Manager(rows=[{"engine": "ollama", "running": True, "base_url": "http://x/v1"}]),
    )
    monkeypatch.setattr(smoke_mod, "list_endpoint_models", lambda endpoint: ["qwen3-coder"])
    monkeypatch.setattr(smoke_mod, "probe_base_url", _context)
    monkeypatch.setattr(
        smoke_mod,
        "run_agentic_bench",
        lambda *a, **k: BenchResult(
            endpoint="http://x/v1",
            model="qwen3-coder",
            ok=True,
            ttft_s=0.4,
            decode_tps=50.0,
            tool_call_success=True,
            edit_format_success=True,
            shell_call_success=True,
            context_recall_success=True,
            agentic_score=100.0,
            mode="agentic",
        ),
    )

    result = CliRunner().invoke(local, ["smoke", "--json"])

    assert result.exit_code == 0
    assert '"status": "ready"' in result.output
    assert '"model": "qwen3-coder"' in result.output


def test_local_init_writes_harness(monkeypatch, tmp_path):
    from superqode.local import doctor as doctor_mod

    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="huggingface-cli download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    report = DoctorReport(
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
        matrix_version="test",
    )
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda *a, **k: report)
    target = tmp_path / "superqode.local.yaml"

    result = CliRunner().invoke(
        local,
        ["init", "--repo", str(tmp_path), "--output", str(target), "--skip-smoke"],
    )

    assert result.exit_code == 0
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "primary: mlx/THUDM/GLM-4.5-Air" in text
    assert "pack: glm" in text


def test_local_init_pack_override(monkeypatch, tmp_path):
    from superqode.local import doctor as doctor_mod

    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="hf download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    report = DoctorReport(
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
        matrix_version="test",
    )
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda *a, **k: report)
    target = tmp_path / "superqode.local.yaml"

    result = CliRunner().invoke(
        local,
        [
            "init",
            "--repo",
            str(tmp_path),
            "--output",
            str(target),
            "--skip-smoke",
            "--pack",
            "minimax-m1",
        ],
    )

    assert result.exit_code == 0
    text = target.read_text(encoding="utf-8")
    assert "pack: minimax-m1" in text
    assert "model_pack: minimax-m1" in text
    assert "model_pack_source: user" in text
