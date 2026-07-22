from __future__ import annotations

import json

import pytest
import yaml

from superqode.harness.bench import (
    load_harness_bench_manifest,
    run_harness_bench,
    verify_harness_bench,
)


def _manifest(tmp_path):
    (tmp_path / "tasks.yaml").write_text("tasks: []\n")
    (tmp_path / "base.yaml").write_text("name: base\n")
    (tmp_path / "candidate.yaml").write_text("name: candidate\n")
    path = tmp_path / "bench.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "same-model-test",
                "tasks": "tasks.yaml",
                "specs": ["base.yaml", "candidate.yaml"],
                "provider": "test-provider",
                "model": "test-model",
                "working_dir": ".",
                "repetitions": 2,
            }
        )
    )
    return load_harness_bench_manifest(path)


@pytest.mark.asyncio
async def test_harness_bench_preserves_raw_runs_ranks_and_verifies(tmp_path):
    manifest = _manifest(tmp_path)
    calls = []

    async def fake_eval(**kwargs):
        calls.append(kwargs)
        repetition = len(calls)
        return {
            "status": "passed",
            "task_count": 2,
            "variants": [
                {
                    "harness": "base",
                    "score": 0.5,
                    "cost_usd": 0.20,
                    "total_tokens": 200,
                    "duration_seconds": 2.0,
                    "regressed": False,
                    "tasks": [
                        {"id": "one", "status": "passed"},
                        {"id": "two", "status": "failed"},
                    ],
                },
                {
                    "harness": "candidate",
                    "score": 1.0,
                    "cost_usd": 0.10 + repetition / 100,
                    "total_tokens": 150,
                    "duration_seconds": 1.0,
                    "regressed": False,
                    "tasks": [
                        {"id": "one", "status": "passed"},
                        {"id": "two", "status": "passed"},
                    ],
                },
            ],
        }

    output = tmp_path / "output"
    result = await run_harness_bench(
        manifest,
        output_dir=output,
        live=True,
        eval_runner=fake_eval,
    )
    scorecard = json.loads((output / "scorecard.json").read_text())

    assert len(calls) == 2
    assert all(call["provider"] == "test-provider" for call in calls)
    assert all(call["model"] == "test-model" for call in calls)
    assert result["winner"] == "candidate"
    assert scorecard["ranking"] == ["candidate", "base"]
    assert scorecard["variants"][0]["cost_usd"]["stdev"] > 0
    assert len(list((output / "raw").glob("*.json"))) == 2
    assert verify_harness_bench(output)["valid"]


@pytest.mark.asyncio
async def test_harness_bench_verifier_detects_tampered_raw_trace(tmp_path):
    manifest = _manifest(tmp_path)

    async def fake_eval(**kwargs):
        return {
            "status": "passed",
            "task_count": 1,
            "variants": [
                {
                    "harness": "base",
                    "score": 1,
                    "cost_usd": None,
                    "total_tokens": None,
                    "duration_seconds": 0.1,
                    "tasks": [{"id": "one", "status": "passed"}],
                },
                {
                    "harness": "candidate",
                    "score": 1,
                    "cost_usd": None,
                    "total_tokens": None,
                    "duration_seconds": 0.2,
                    "tasks": [{"id": "one", "status": "passed"}],
                },
            ],
        }

    output = tmp_path / "output"
    await run_harness_bench(manifest, output_dir=output, eval_runner=fake_eval)
    raw = output / "raw" / "run-001.json"
    raw.write_text(raw.read_text() + "tampered")

    verification = verify_harness_bench(output)

    assert not verification["valid"]
    assert verification["failures"][0]["error"] == "digest_mismatch"


def test_harness_bench_manifest_requires_multiple_specs_and_fixed_model(tmp_path):
    (tmp_path / "tasks.yaml").write_text("tasks: []\n")
    (tmp_path / "one.yaml").write_text("name: one\n")
    path = tmp_path / "invalid.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "tasks": "tasks.yaml",
                "specs": ["one.yaml"],
                "provider": "test",
                "model": "model",
            }
        )
    )

    with pytest.raises(ValueError, match="at least two"):
        load_harness_bench_manifest(path)
