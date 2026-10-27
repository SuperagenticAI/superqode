from __future__ import annotations

from pathlib import Path

from superqode.harness.eval import load_eval_tasks
from superqode.harness.omni import _HarnessOmniEvaluator, optimize_harness_with_omni
from superqode.harness.loader import load_harness_spec


def _write_tasks(path: Path) -> None:
    path.write_text(
        "tasks:\n"
        "  - id: train\n"
        "    split: held-in\n"
        "    prompt: Say ready\n"
        "    expect_contains: ready\n"
        "  - id: gate\n"
        "    split: held-out\n"
        "    prompt: Say ready\n"
        "    expect_contains: ready\n",
        encoding="utf-8",
    )


def _write_harness(path: Path) -> None:
    path.write_text(
        "name: demo\n"
        "execution_policy:\n"
        "  allow_shell: false\n"
        "optimization:\n"
        "  enabled: true\n"
        "  editable_surfaces: [context, workflow, model_policy, agents.tools]\n"
        "  protected_surfaces: [execution_policy, checks, approvals, sandbox]\n"
        "  max_candidate_edits: 3\n",
        encoding="utf-8",
    )


def test_tiny_omni_example_has_one_task_per_split():
    tasks = load_eval_tasks(
        Path(__file__).resolve().parents[1] / "examples" / "evals" / "omni-tiny.yaml"
    )

    assert tasks["split_counts"] == {"held-in": 1, "held-out": 1, "all": 2}


def test_release_omni_example_has_optimizer_and_sealed_cases():
    tasks = load_eval_tasks(
        Path(__file__).resolve().parents[1] / "examples" / "evals" / "omni-release.yaml"
    )

    assert tasks["split_counts"] == {"held-in": 3, "held-out": 2, "all": 5}


def test_tiny_omni_harness_is_local_and_bounded():
    spec = load_harness_spec(
        Path(__file__).resolve().parents[1] / "examples" / "harnesses" / "omni-tiny-local.yaml"
    )

    assert spec.model_policy.primary == "qwen3.5:9b"
    assert spec.model_policy.config["provider"] == "ollama"
    assert spec.execution_policy.allow_shell is False
    assert spec.optimization.enabled is True
    assert spec.optimization.max_candidate_edits == 3
    assert "agents" in spec.optimization.editable_surfaces


def test_tiny_runner_uses_uv_overlay_python_entrypoint():
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_tiny_omni_experiment.sh"
    ).read_text(encoding="utf-8")

    assert '--with "${GEPA_REQUIREMENT}"' in script
    assert "f919db0a622e2e9f9204779b81fe00cc1b2d808f" in script
    assert "\n  python\n  -m superqode.main\n" in script
    assert "--max-evals 24" in script
    assert "--max-token-cost 2.00" in script
    assert '[[ -n "${ANTHROPIC_API_KEY:-}" ]]' in script
    assert "claude auth status" not in script
    assert "-u ANTHROPIC_API_KEY" not in script


def test_harness_omni_evaluator_rejects_permission_widening_before_rollout(tmp_path, monkeypatch):
    baseline = tmp_path / "harness.yaml"
    tasks = tmp_path / "tasks.yaml"
    _write_harness(baseline)
    _write_tasks(tasks)
    evaluator = _HarnessOmniEvaluator(
        baseline_spec_path=baseline,
        tasks_path=tasks,
        tasks=[
            {
                "id": "train",
                "split": "held-in",
                "prompt": "Say ready",
                "expect_contains": "ready",
            }
        ],
        eval_dir=tmp_path / "evals",
        provider="openai",
        model="fake",
        runtime=None,
        working_dir=tmp_path,
        sandbox_backend="local",
        live=True,
    )
    rolled_out = False

    async def fail_if_called(**kwargs):
        nonlocal rolled_out
        rolled_out = True
        raise AssertionError("policy-rejected candidate must not run")

    monkeypatch.setattr("superqode.harness.omni.run_harness_eval", fail_if_called)
    candidate = (
        baseline.read_text(encoding="utf-8") + "execution_policy:\n" + "  allow_shell: true\n"
    )

    score, info = evaluator.evaluate(
        candidate,
        {"id": "train", "split": "held-in", "prompt": "Say ready"},
    )

    assert score == 0.0
    assert info["Feedback"]["Status"] == "policy_rejected", info
    assert info["scores"]["policy_compliance"] == 0.0
    assert rolled_out is False


def test_harness_omni_stages_candidate_and_runs_final_heldout_gate(tmp_path, monkeypatch):
    parent = tmp_path / "base.yaml"
    baseline = tmp_path / "harness.yaml"
    tasks = tmp_path / "tasks.yaml"
    _write_harness(parent)
    baseline.write_text("name: demo\ninherits: ./base.yaml\n", encoding="utf-8")
    _write_tasks(tasks)
    original = baseline.read_text(encoding="utf-8")

    class FakeResult:
        def __init__(self, candidate):
            self.best_candidate = candidate
            self.best_score = 1.0
            self.total_evals = 4
            self.metadata = {
                "engine": "gepa",
                "baseline_test_score": 1.0,
                "test_score": 1.0,
            }

    def fake_optimizer(**kwargs):
        assert kwargs["test_set"][0]["id"] == "gate"
        assert "inherits:" not in kwargs["seed_candidate"]
        return FakeResult(kwargs["seed_candidate"])

    async def fake_eval(**kwargs):
        assert kwargs["eval_split"] == "held-out"
        return {
            "live": True,
            "split": "held-out",
            "task_count": 1,
            "variants": [
                {
                    "harness": "demo",
                    "spec": str(kwargs["spec_paths"][0]),
                    "score": 1.0,
                    "regressed": False,
                    "tasks": [
                        {
                            "id": "gate",
                            "split": "held-out",
                            "status": "passed",
                            "evaluation": {"evaluator": "contains", "status": "passed"},
                        }
                    ],
                },
                {
                    "harness": "demo",
                    "spec": str(kwargs["spec_paths"][1]),
                    "score": 1.0,
                    "regressed": False,
                    "tasks": [
                        {
                            "id": "gate",
                            "split": "held-out",
                            "status": "passed",
                            "evaluation": {"evaluator": "contains", "status": "passed"},
                        }
                    ],
                },
            ],
        }

    monkeypatch.setattr("superqode.harness.omni._run_modern_optimizer", fake_optimizer)
    monkeypatch.setattr("superqode.harness.omni.run_harness_eval", fake_eval)

    result = optimize_harness_with_omni(
        spec_path=baseline,
        tasks_path=tasks,
        output_dir=tmp_path / "out",
        engine="gepa",
        live=True,
    )

    assert result.accepted is True
    assert load_harness_spec(result.staged_spec_path).name == "demo"
    assert baseline.read_text(encoding="utf-8") == original
    assert result.baseline_score == 1.0
    assert result.best_score == 1.0
    assert (result.output_dir / "candidate-ledger.jsonl").exists()
    assert result.report_json_path.exists()
    assert result.report_md_path.exists()
