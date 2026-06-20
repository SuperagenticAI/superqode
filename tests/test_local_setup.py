from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local.doctor import DoctorReport
from superqode.local.engines import EngineStatus
from superqode.local.guardrails import LocalGuardrails
from superqode.local.hardware import HardwareProfile
from superqode.local.matrix import ModelCandidate, ModelSearchHit, StackRecommendation
from superqode.local.repo import RepoProfile
from superqode.local.setup import LocalSetupGuide, render_local_setup_guide


def _guide() -> LocalSetupGuide:
    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="hf download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    report = DoctorReport(
        hardware=HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
        engines={"mlx-lm": EngineStatus(engine="mlx-lm", installed=True, running=False)},
        inventory=[],
        recommendation=StackRecommendation(
            tier_id="apple_64",
            description="test",
            engine="mlx-lm",
            engine_ranked=["mlx-lm"],
            models=[candidate],
        ),
        repo=RepoProfile(
            root="/tmp/project",
            code_file_count=12,
            estimated_tokens=42000,
            recommended_context_tokens=65536,
            recommended_model_size="medium",
        ),
        guardrails=LocalGuardrails(
            hardware_tier="apple_64",
            max_worker_concurrency=2,
            recommended_context_cap=65536,
            memory_headroom_gb=12,
            battery_mode="normal",
        ),
    )
    hit = ModelSearchHit(
        name="GLM-4.5-Air",
        role="main",
        sources=["models.dev/labs/zhipuai"],
        packs=["glm"],
        tiers=["apple_64"],
        commands=[("MLX", "hf download THUDM/GLM-4.5-Air")],
        downloaded_as=None,
        fits=True,
        est_memory_gb=24.0,
    )
    return LocalSetupGuide(query="glm", repo="/tmp/project", report=report, hits=[hit])


def test_render_local_setup_guide_is_tui_first_and_non_mutating():
    text = render_local_setup_guide(_guide(), tui_first=True)

    assert "This is a guide only" in text
    assert "TUI  : :local search glm" in text
    assert "TUI  : :local serve mlx --model THUDM/GLM-4.5-Air --ctx 65536" in text
    assert "TUI  : :local build --repo /tmp/project --model THUDM/GLM-4.5-Air --pack glm" in text
    assert "Do not rely on anyone else's harness as-is" in text
    assert "does not download a model or start a server" in text


def test_local_setup_cli(monkeypatch):
    import superqode.local.setup as setup_mod

    monkeypatch.setattr(setup_mod, "build_local_setup_guide", lambda *a, **k: _guide())

    result = CliRunner().invoke(local, ["setup", "glm", "--repo", "/tmp/project"])

    assert result.exit_code == 0
    assert "SuperQode Local Model Setup" in result.output
    assert ":local setup" not in result.output
    assert ":local serve mlx" in result.output


def test_local_setup_cli_json(monkeypatch):
    import json

    import superqode.local.setup as setup_mod

    monkeypatch.setattr(setup_mod, "build_local_setup_guide", lambda *a, **k: _guide())

    result = CliRunner().invoke(local, ["setup", "glm", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["query"] == "glm"
    assert payload["engine"] == "mlx-lm"
    assert payload["context_cap"] == 65536
