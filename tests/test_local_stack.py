"""Tests for the local stack: hardware, engines, inventory, matrix, doctor,
bench, model policy packs, and utility-model routing.

Everything external (subprocess, HTTP, filesystem caches) is mocked; no test
touches a real engine or model.
"""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import replace

import pytest

from superqode.local.bench import BenchResult, render_bench, run_agentic_bench, run_bench
from superqode.local.engines import EngineStatus, _parse_semver, detect_ollama
from superqode.local.guardrails import PowerState, build_guardrails, render_guardrails
from superqode.local.hardware import HardwareProfile, NvidiaGpu
from superqode.local.inventory import LocalModel, list_ollama_models
from superqode.local.matrix import load_matrix, recommend
from superqode.local.optimize import (
    optimization_harness_yaml,
    recommend_roles,
    render_optimization,
)
from superqode.local.packs import detect_pack, get_pack, load_packs
from superqode.local.repo import analyze_repository, render_repo_profile
from superqode.harness.loader import load_harness_spec, save_harness_spec
from superqode.harness.model_policy import resolve_harness_model_policy
from superqode.harness.spec import ModelPolicySpec
from superqode.harness.templates import get_harness_template


# ---------------------------------------------------------------- hardware


def _apple(mem: int, gen: int = 4, macos: str = "26.1") -> HardwareProfile:
    return HardwareProfile(
        platform="darwin",
        is_apple_silicon=True,
        chip=f"Apple M{gen} Max",
        apple_generation=gen,
        unified_memory_gb=mem,
        macos_version=macos,
    )


@pytest.mark.parametrize(
    "mem,expected",
    [(128, "apple_128"), (96, "apple_128"), (64, "apple_64"), (36, "apple_32"), (16, "apple_16")],
)
def test_apple_tiers(mem, expected):
    assert _apple(mem).tier == expected


@pytest.mark.parametrize(
    "vram,expected", [(80.0, "nvidia_48"), (24.0, "nvidia_24"), (12.0, "nvidia_16")]
)
def test_nvidia_tiers(vram, expected):
    profile = HardwareProfile(platform="linux", nvidia_gpus=[NvidiaGpu("GPU", vram)])
    assert profile.tier == expected


def test_cpu_tier():
    assert HardwareProfile(platform="linux", cpu_only=True).tier == "cpu"


def test_local_guardrails_reduce_limits_on_battery(monkeypatch):
    monkeypatch.setattr(
        "superqode.local.guardrails.detect_power_state",
        lambda: PowerState(on_battery=True, source="test", detail="battery power"),
    )
    monkeypatch.setattr(
        "superqode.local.guardrails.detect_load_state",
        lambda: type("Load", (), {"load_1m": 0.1, "cpu_count": 8, "normalized_1m": 0.01})(),
    )

    guardrails = build_guardrails(_apple(128))

    assert guardrails.max_worker_concurrency == 1
    assert guardrails.recommended_context_cap == 32768
    assert guardrails.battery_mode == "conservative"
    assert guardrails.warnings
    assert "Local Runtime Guardrails" in render_guardrails(guardrails)


def test_local_guardrails_use_repo_context_cap(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("print('x')\n" * 1000, encoding="utf-8")
    repo = analyze_repository(tmp_path)
    monkeypatch.setattr(
        "superqode.local.guardrails.detect_power_state",
        lambda: PowerState(on_battery=False, source="test", detail="AC power"),
    )
    monkeypatch.setattr(
        "superqode.local.guardrails.detect_load_state",
        lambda: type("Load", (), {"load_1m": 0.1, "cpu_count": 8, "normalized_1m": 0.01})(),
    )

    guardrails = build_guardrails(_apple(128), repo_profile=repo)

    assert guardrails.recommended_context_cap == repo.recommended_context_tokens
    assert guardrails.max_worker_concurrency >= 1


# ----------------------------------------------------------------- engines


def test_parse_semver():
    assert _parse_semver("ollama version is 0.30.3") == (0, 30, 3)
    assert _parse_semver("0.19") == (0, 19, 0)
    assert _parse_semver("garbage") == (0, 0, 0)


def test_ollama_mlx_notes(monkeypatch):
    monkeypatch.setattr("superqode.local.engines.shutil.which", lambda _: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        "superqode.local.engines._cli_version", lambda _: "ollama version is 0.19.2"
    )
    monkeypatch.setattr("superqode.local.engines._http_json", lambda _: None)

    big = detect_ollama(unified_memory_gb=64, apple_silicon=True)
    assert any("MLX runtime available" in n for n in big.notes)

    small = detect_ollama(unified_memory_gb=16, apple_silicon=True)
    assert any("more than 32GB" in n for n in small.notes)

    monkeypatch.setattr(
        "superqode.local.engines._cli_version", lambda _: "ollama version is 0.18.0"
    )
    old = detect_ollama(unified_memory_gb=64, apple_silicon=True)
    assert any("Update to Ollama 0.19+" in n for n in old.notes)


def test_ollama_running_without_cli(monkeypatch):
    monkeypatch.setattr("superqode.local.engines.shutil.which", lambda _: None)
    monkeypatch.setattr("superqode.local.engines._http_json", lambda _: {"version": "0.30.0"})
    status = detect_ollama()
    assert status.running and status.installed and status.version == "0.30.0"


# --------------------------------------------------------------- inventory


def test_ollama_inventory(monkeypatch):
    def fake_models(path):
        if path == "/api/ps":
            return [{"model": "gemma4:12b"}]
        return [
            {"model": "gemma4:12b", "size": 8 * 1024**3},
            {"model": "qwen3-coder:30b-a3b", "size": 18 * 1024**3},
        ]

    monkeypatch.setattr("superqode.local.inventory._ollama_models", fake_models)
    models = list_ollama_models()
    assert [m.model_id for m in models] == ["ollama:gemma4:12b", "ollama:qwen3-coder:30b-a3b"]
    assert models[0].loaded and not models[1].loaded
    assert models[0].size_gb == 8.0
    assert models[1].bare_id == "qwen3-coder:30b-a3b"


# ------------------------------------------------------------------ matrix


def test_matrix_ships_all_tiers():
    matrix = load_matrix()
    ids = {t["id"] for t in matrix["tiers"]}
    assert ids >= {
        "apple_16",
        "apple_32",
        "apple_64",
        "apple_128",
        "nvidia_16",
        "nvidia_24",
        "nvidia_48",
        "cpu",
    }


def test_matrix_recommendations_have_trusted_sources():
    trusted = {
        "models.dev/labs/alibaba",
        "models.dev/labs/deepseek",
        "models.dev/labs/google",
        "models.dev/labs/mistral",
        "models.dev/labs/zhipuai",
        "mlx-community",
        "lmstudio-community",
    }
    matrix = load_matrix()

    for tier in matrix["tiers"]:
        for model in tier.get("models", []):
            source = model.get("source", "")
            assert source in trusted, f"{tier['id']}::{model.get('name')} has untrusted source"


def test_recommend_prefers_installed_engine_and_downloaded_model():
    engines = {
        "mlx-lm": EngineStatus(engine="mlx-lm", installed=False),
        "ollama": EngineStatus(engine="ollama", installed=True, running=True),
        "ds4": EngineStatus(engine="ds4", installed=False),
        "lmstudio": EngineStatus(engine="lmstudio", installed=False),
    }
    inventory = [LocalModel(model_id="hf:org/gemma-4-31b-it-4bit-mlx", source="hf")]
    rec = recommend(_apple(128), engines, inventory)
    assert rec.tier_id == "apple_128"
    assert rec.engine == "ollama"
    assert "mlx-lm" in rec.engines_missing
    best = rec.best_model
    assert best is not None and best.downloaded is not None
    assert best.downloaded.model_id == "hf:org/gemma-4-31b-it-4bit-mlx"


def test_recommend_neural_accelerator_note():
    rec = recommend(_apple(128, gen=5, macos="26.2"), {}, [])
    assert any("Neural Accelerators" in n for n in rec.notes)


def test_user_matrix_override(monkeypatch, tmp_path):
    override = tmp_path / "stack_matrix.yaml"
    override.write_text(
        "tiers:\n  - id: apple_128\n    description: mine\n    engines: [ollama]\n    models: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("superqode.local.matrix.USER_MATRIX", override)
    matrix = load_matrix()
    tier = next(t for t in matrix["tiers"] if t["id"] == "apple_128")
    assert tier["description"] == "mine"
    # Other tiers survive the merge.
    assert any(t["id"] == "cpu" for t in matrix["tiers"])


# ------------------------------------------------------------------ doctor


def _fake_report(monkeypatch, inventory=None):
    from superqode.local import doctor as doctor_mod

    monkeypatch.setattr(doctor_mod, "detect_hardware", lambda: _apple(128))
    monkeypatch.setattr(
        doctor_mod,
        "detect_engines",
        lambda **kw: {
            "mlx-lm": EngineStatus(engine="mlx-lm", installed=True, version="0.30.0"),
            "ollama": EngineStatus(engine="ollama", installed=True, running=True),
            "ds4": EngineStatus(engine="ds4"),
            "lmstudio": EngineStatus(engine="lmstudio"),
        },
    )
    monkeypatch.setattr(doctor_mod, "inventory_models", lambda: inventory or [])
    monkeypatch.setattr(doctor_mod, "_detect_apple_fm", lambda profile: False)
    return doctor_mod.run_doctor()


def test_doctor_render(monkeypatch):
    from superqode.local.doctor import render_report

    report = _fake_report(
        monkeypatch,
        inventory=[
            LocalModel(model_id="hf:org/gemma-4-31b-it-4bit-mlx", source="hf", size_gb=32.2)
        ],
    )
    text = render_report(report)
    assert "SuperQode Local Stack Doctor" in text
    assert "apple_128" in text
    assert "downloaded (hf:org/gemma-4-31b-it-4bit-mlx" in text
    assert "Verdict" in text


def test_doctor_generates_loadable_harness(monkeypatch, tmp_path):
    from superqode.local.doctor import generate_harness_yaml

    report = _fake_report(
        monkeypatch,
        inventory=[LocalModel(model_id="hf:org/gemma-4-31b-it-4bit-mlx", source="hf")],
    )
    path = tmp_path / "h.yaml"
    path.write_text(generate_harness_yaml(report), encoding="utf-8")
    spec = load_harness_spec(path)
    # An HF cache model must route to the mlx provider, not ollama.
    assert spec.model_policy.primary == "mlx/org/gemma-4-31b-it-4bit-mlx"
    assert spec.model_policy.pack == "gemma4"


def test_doctor_harness_pull_fallback(monkeypatch):
    from superqode.local.doctor import generate_harness_yaml

    report = _fake_report(monkeypatch, inventory=[])
    text = generate_harness_yaml(report)
    # Nothing downloaded: derive the model from the pull command.
    assert "primary: mlx/THUDM/GLM-4.5-Air" in text
    assert "pack: glm" in text


def test_repository_profile_recommends_context_and_workflow(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for index in range(220):
        (src / f"mod_{index}.py").write_text("def f():\n    return 1\n" * 80, encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("x" * 500_000, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    profile = analyze_repository(tmp_path)

    assert profile.code_file_count == 220
    assert profile.config_file_count == 1
    assert profile.languages["Python"] == 220
    assert profile.recommended_context_tokens >= 32768
    assert profile.workflow_shape in {"fix-and-verify", "plan-implement-review"}
    assert profile.recommended_model_size in {"medium", "medium-large", "large"}
    text = render_repo_profile(profile)
    assert "Repository profile" in text
    assert "Python 220" in text


def test_doctor_generates_repo_aware_harness(monkeypatch, tmp_path):
    from superqode.local.doctor import generate_harness_yaml

    (tmp_path / "app.py").write_text("print('hello')\n" * 5000, encoding="utf-8")
    report = _fake_report(
        monkeypatch,
        inventory=[LocalModel(model_id="hf:org/gemma-4-31b-it-4bit-mlx", source="hf")],
    )
    report.repo = analyze_repository(tmp_path)
    report.guardrails = build_guardrails(report.hardware, repo_profile=report.repo)

    text = generate_harness_yaml(report)
    path = tmp_path / "repo-aware.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_harness_spec(path)

    assert "workflow:" in text
    assert "context_window:" in text
    assert "repo_model_size:" in text
    assert "repo_context_tokens:" in text
    assert "local_guardrails:" in text
    assert "guardrail_context_cap:" in text
    assert loaded.model_policy.context_window == report.repo.recommended_context_tokens


# ------------------------------------------------------------------- bench


class _FakeStream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _sse(*events: dict) -> _FakeStream:
    lines = [b"data: " + json.dumps(e).encode() + b"\n" for e in events]
    lines.append(b"data: [DONE]\n")
    return _FakeStream(b"".join(lines))


def test_run_bench_parses_stream(monkeypatch):
    chunks = [{"choices": [{"delta": {"content": "tok"}}]} for _ in range(20)]
    monkeypatch.setattr("superqode.local.bench.urlopen", lambda req, timeout=None: _sse(*chunks))
    result = run_bench("http://localhost:9999/v1", "test-model", max_tokens=32)
    assert result.ok
    assert result.completion_tokens == 20
    assert result.ttft_s is not None and result.total_s is not None


def test_run_agentic_bench_scores_control_probes(monkeypatch):
    def fake_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        messages = payload["messages"]
        prompt = messages[-1]["content"]
        if "Read this function" in prompt:
            return _sse(*[{"choices": [{"delta": {"content": "tok"}}]} for _ in range(4)])
        if "read_file with path" in prompt:
            return _sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path": "pyproject.toml"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        if "unified diff" in prompt:
            return _sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "content": "--- a/x.py\n+++ b/x.py\n@@\n-    return 1\n+    return 2\n"
                            }
                        }
                    ]
                }
            )
        if "bash with command" in prompt:
            return _sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "content": (
                                    '<tool_call>{"name": "bash", "arguments": '
                                    '{"command": "pytest -q"}}</tool_call>'
                                )
                            }
                        }
                    ]
                }
            )
        if "Final important token" in prompt:
            return _sse({"choices": [{"delta": {"content": "SUPERQODE_SENTINEL_4f9c8b2a"}}]})
        raise AssertionError(prompt)

    monkeypatch.setattr("superqode.local.bench.urlopen", fake_urlopen)
    result = run_agentic_bench("http://localhost:9999/v1", "test-model")
    assert result.ok
    assert result.mode == "agentic"
    assert result.agentic_score == 100.0
    assert result.tool_call_success is True
    assert result.edit_format_success is True
    assert result.shell_call_success is True
    assert result.context_recall_success is True

    text = render_bench([result])
    assert "score" in text
    assert "100%" in text


def test_run_bench_empty_stream(monkeypatch):
    monkeypatch.setattr("superqode.local.bench.urlopen", lambda req, timeout=None: _sse())
    result = run_bench("http://localhost:9999/v1", "test-model")
    assert not result.ok
    assert "no content" in result.error


def test_run_bench_connection_error(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("superqode.local.bench.urlopen", boom)
    result = run_bench("http://localhost:9999/v1", "test-model")
    assert not result.ok and "connection refused" in result.error


def test_render_bench():
    text = render_bench(
        [
            BenchResult(
                endpoint="e", model="good", ok=True, ttft_s=0.4, decode_tps=42.0, total_s=3.1
            ),
            BenchResult(endpoint="e", model="bad", error="boom"),
        ]
    )
    assert "42.0 tok/s" in text
    assert "failed: boom" in text


# --------------------------------------------------------------- optimizer


def test_recommend_roles_picks_agentic_and_fast_models_by_role():
    accurate = BenchResult(
        endpoint="http://e/v1",
        model="coder",
        ok=True,
        ttft_s=1.0,
        decode_tps=30.0,
        mode="agentic",
        tool_call_success=True,
        edit_format_success=True,
        shell_call_success=True,
        context_recall_success=True,
        agentic_score=100.0,
    )
    fast = BenchResult(
        endpoint="http://e/v1",
        model="tiny",
        ok=True,
        ttft_s=0.1,
        decode_tps=80.0,
        mode="agentic",
        tool_call_success=False,
        edit_format_success=False,
        shell_call_success=False,
        context_recall_success=True,
        agentic_score=25.0,
    )

    report = recommend_roles([accurate, fast])

    by_role = {item.role: item for item in report.recommendations}
    assert by_role["implementer"].model == "coder"
    assert by_role["planner"].model == "coder"
    assert by_role["utility"].model == "tiny"
    text = render_optimization(report)
    assert "SuperQode local optimizer" in text
    assert "implementer" in text


def test_recommend_roles_uses_repo_profile_for_context_heavy_roles(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for index in range(650):
        (src / f"m{index}.py").write_text("x = 1\n", encoding="utf-8")
    repo_profile = analyze_repository(tmp_path)
    fast_weak_context = BenchResult(
        endpoint="http://e/v1",
        model="tiny",
        ok=True,
        ttft_s=0.1,
        decode_tps=90.0,
        mode="agentic",
        tool_call_success=True,
        edit_format_success=True,
        shell_call_success=True,
        context_recall_success=False,
        agentic_score=75.0,
    )
    slower_coder = BenchResult(
        endpoint="http://e/v1",
        model="qwen-coder",
        ok=True,
        ttft_s=1.0,
        decode_tps=30.0,
        mode="agentic",
        tool_call_success=True,
        edit_format_success=True,
        shell_call_success=True,
        context_recall_success=True,
        agentic_score=100.0,
    )

    report = recommend_roles(
        [fast_weak_context, slower_coder],
        roles=("planner", "utility"),
        repo_profile=repo_profile,
    )

    by_role = {item.role: item for item in report.recommendations}
    assert by_role["planner"].model == "qwen-coder"
    assert by_role["utility"].model == "tiny"
    assert report.repo_profile is repo_profile
    assert any("Repo-aware scoring" in note for note in report.notes)
    assert "repo" in by_role["planner"].reason


def test_optimization_harness_yaml_contains_role_routing():
    result = BenchResult(
        endpoint="http://localhost:11434/v1",
        model="qwen3-coder:30b",
        ok=True,
        ttft_s=0.4,
        decode_tps=40.0,
        mode="agentic",
        agentic_score=100.0,
        tool_call_success=True,
        edit_format_success=True,
        shell_call_success=True,
        context_recall_success=True,
    )
    report = recommend_roles([result], roles=("planner", "implementer"))

    text = optimization_harness_yaml(report, name="local-team")

    assert "name: local-team" in text
    assert "mode: chain" in text
    assert "id: planner" in text
    assert "model: qwen3-coder:30b" in text
    assert "endpoint: http://localhost:11434/v1" in text


def test_optimization_harness_yaml_contains_repo_context(tmp_path):
    (tmp_path / "app.py").write_text("print('x')\n" * 2000, encoding="utf-8")
    result = BenchResult(
        endpoint="http://localhost:11434/v1",
        model="qwen-coder",
        ok=True,
        ttft_s=0.4,
        decode_tps=40.0,
        mode="agentic",
        agentic_score=100.0,
        tool_call_success=True,
        edit_format_success=True,
        shell_call_success=True,
        context_recall_success=True,
    )
    report = recommend_roles([result], roles=("planner",), repo_profile=analyze_repository(tmp_path))

    text = optimization_harness_yaml(report, name="repo-routed")

    assert "context_window:" in text
    assert "repo_model_size:" in text
    assert "repo_context_tokens:" in text


# ------------------------------------------------------------------- packs


def test_shipped_packs_load():
    packs = load_packs()
    assert {"gemma4", "qwen3", "qwen-coder", "ds4", "devstral", "gpt-oss", "glm"} <= set(packs)


def test_detect_pack_longest_match_wins():
    assert detect_pack("ollama qwen3-coder-next").name == "qwen-coder"
    assert detect_pack("ollama qwen3.6:35b-a3b").name == "qwen3"
    assert detect_pack("zhipuai glm-4.5-air").name == "glm"
    assert detect_pack("gpt-4o-mini") is None


def test_user_pack_override(monkeypatch, tmp_path):
    (tmp_path / "gemma4.yaml").write_text(
        "name: gemma4\ndescription: custom\nmatch: [gemma]\npolicy:\n  temperature: 0.9\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("superqode.local.packs.USER_PACKS_DIR", tmp_path)
    pack = get_pack("gemma4")
    assert pack is not None and pack.description == "custom"
    assert pack.policy["temperature"] == 0.9


def test_pack_applies_to_resolved_policy():
    spec = get_harness_template("coding")
    policy = resolve_harness_model_policy(spec, provider="ollama", model="qwen3-coder-next")
    assert policy.temperature == 0.1
    assert policy.session_history_limit == 16


def test_explicit_pack_reference():
    spec = replace(
        get_harness_template("coding"),
        model_policy=ModelPolicySpec(primary="mlx/some-model", pack="qwen-coder"),
    )
    policy = resolve_harness_model_policy(spec)
    assert policy.temperature == 0.1


def test_spec_scalars_beat_pack():
    spec = replace(
        get_harness_template("coding"),
        model_policy=ModelPolicySpec(primary="ollama/qwen3-coder", temperature=0.7),
    )
    policy = resolve_harness_model_policy(spec)
    assert policy.temperature == 0.7


def test_config_beats_pack():
    spec = replace(
        get_harness_template("coding"),
        model_policy=ModelPolicySpec(
            primary="ollama/qwen3-coder", config={"session_history_limit": 5}
        ),
    )
    policy = resolve_harness_model_policy(spec)
    assert policy.session_history_limit == 5


def test_pack_field_round_trips(tmp_path):
    spec = replace(
        get_harness_template("coding"),
        name="packed",
        model_policy=ModelPolicySpec(primary="ollama/gemma4:12b", pack="gemma4"),
    )
    path = save_harness_spec(spec, tmp_path / "packed.yaml")
    loaded = load_harness_spec(path)
    assert loaded.model_policy.pack == "gemma4"


# ---------------------------------------------------------- utility model


def test_utility_route_parsing(monkeypatch):
    from superqode.agent.utility_model import utility_route

    monkeypatch.setenv("SUPERQODE_UTILITY_PROVIDER", "apple-fm")
    assert utility_route() == ("apple-fm", "")
    monkeypatch.setenv("SUPERQODE_UTILITY_PROVIDER", "ollama/gemma4:e4b")
    assert utility_route() == ("ollama", "gemma4:e4b")
    monkeypatch.delenv("SUPERQODE_UTILITY_PROVIDER")
    assert utility_route() is None


def test_utility_completion_routes_to_override(monkeypatch):
    from superqode.agent.utility_model import utility_completion

    calls = []

    class _Response:
        content = "answer"

    class _Gateway:
        async def chat_completion(self, **kwargs):
            calls.append((kwargs["provider"], kwargs["model"]))
            return _Response()

    monkeypatch.setenv("SUPERQODE_UTILITY_PROVIDER", "ollama/tiny")
    out = asyncio.run(utility_completion(_Gateway(), "anthropic", "big", "sys", "user"))
    assert out == "answer"
    assert calls == [("ollama", "tiny")]


def test_utility_completion_falls_back_when_apple_fm_missing(monkeypatch):
    from superqode.agent.utility_model import utility_completion

    class _Response:
        content = "session-answer"

    class _Gateway:
        async def chat_completion(self, **kwargs):
            return _Response()

    monkeypatch.setenv("SUPERQODE_UTILITY_PROVIDER", "apple-fm")
    monkeypatch.setattr("superqode.providers.apple_fm.apple_fm_available", lambda: False)
    out = asyncio.run(utility_completion(_Gateway(), "ollama", "m", "sys", "user"))
    assert out == "session-answer"


# --------------------------------------------------------------------- CLI


def test_local_packs_cli():
    from click.testing import CliRunner

    from superqode.commands.local import local

    result = CliRunner().invoke(local, ["packs"])
    assert result.exit_code == 0
    assert "gemma4" in result.output
    assert "model-packs" in result.output


def test_local_doctor_cli_json(monkeypatch):
    from click.testing import CliRunner

    from superqode.local import doctor as doctor_mod
    from superqode.commands.local import local

    monkeypatch.setattr(doctor_mod, "detect_hardware", lambda: _apple(128))
    monkeypatch.setattr(
        doctor_mod,
        "detect_engines",
        lambda **kw: {"ollama": EngineStatus(engine="ollama", installed=True, running=True)},
    )
    monkeypatch.setattr(doctor_mod, "inventory_models", lambda: [])
    monkeypatch.setattr(doctor_mod, "_detect_apple_fm", lambda profile: None)

    monkeypatch.setattr(
        "superqode.local.guardrails.detect_power_state",
        lambda: PowerState(on_battery=False, source="test", detail="AC power"),
    )

    result = CliRunner().invoke(local, ["doctor", "--json", "--repo", ".", "--guardrails"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["tier"] == "apple_128"
    assert payload["recommendation"]["engine"] == "ollama"
    assert payload["repo"] is not None
    assert "recommended_context_tokens" in payload["repo"]
    assert payload["guardrails"] is not None
    assert "max_worker_concurrency" in payload["guardrails"]


def test_local_guardrails_cli_json(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from superqode.commands.local import local
    from superqode.local import guardrails as guardrails_mod

    monkeypatch.setattr("superqode.local.hardware.detect_hardware", lambda: _apple(32))
    monkeypatch.setattr(
        guardrails_mod,
        "detect_power_state",
        lambda: PowerState(on_battery=True, source="test", detail="battery power"),
    )
    monkeypatch.setattr(
        guardrails_mod,
        "detect_load_state",
        lambda: type("Load", (), {"load_1m": 0.1, "cpu_count": 8, "normalized_1m": 0.01})(),
    )
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")

    result = CliRunner().invoke(local, ["guardrails", "--repo", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["hardware_tier"] == "apple_32"
    assert payload["battery_mode"] == "conservative"
    assert payload["max_worker_concurrency"] == 1
    assert payload["repo"] is not None


def test_local_optimize_cli_json_and_generate(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from superqode.commands.local import local
    from superqode.local import optimize as optimize_mod

    def fake_bench(endpoint, model, max_tokens=384, api_key=""):
        return BenchResult(
            endpoint=endpoint,
            model=model,
            ok=True,
            ttft_s=0.2 if model == "tiny" else 0.8,
            decode_tps=80.0 if model == "tiny" else 35.0,
            mode="agentic",
            tool_call_success=model == "coder",
            edit_format_success=model == "coder",
            shell_call_success=model == "coder",
            context_recall_success=True,
            agentic_score=100.0 if model == "coder" else 25.0,
        )

    monkeypatch.setattr(optimize_mod, "run_agentic_bench", fake_bench)
    target = tmp_path / "optimized.yaml"

    result = CliRunner().invoke(
        local,
        [
            "optimize",
            "--endpoint",
            "http://localhost:11434/v1",
            "--model",
            "coder",
            "--model",
            "tiny",
            "--repo",
            str(tmp_path),
            "--generate",
            str(target),
            "--json",
        ],
    )

    assert result.exit_code == 0
    json_start = result.output.index("{")
    payload = json.loads(result.output[json_start:].split("\nWrote", 1)[0])
    by_role = {item["role"]: item for item in payload["recommendations"]}
    assert by_role["implementer"]["model"] == "coder"
    assert by_role["utility"]["model"] == "tiny"
    assert payload["repo"] is not None
    assert payload["repo"]["recommended_context_tokens"] >= 16384
    generated = target.read_text(encoding="utf-8")
    assert "agents:" in generated
    assert "model: coder" in generated
    assert "repo_context_tokens:" in generated
