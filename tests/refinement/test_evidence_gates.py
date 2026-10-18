from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from superqode.harness.self_improve import audit_harness_candidate
from superqode.harness.bench import HarnessBenchManifest, run_harness_bench
from superqode.harness.promotion import _validate_promotion_evidence


def specs(tmp_path):
    base, candidate = tmp_path / "base.yaml", tmp_path / "candidate.yaml"
    base.write_text("name: base\noptimization:\n  editable_surfaces: [description]\n")
    candidate.write_text("name: base\ndescription: candidate\n")
    return base, candidate


def test_empty_heldout_set_and_error_outcomes_rejected(tmp_path):
    base, candidate = specs(tmp_path)
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text("tasks:\n  - id: one\n    prompt: fix\n    split: held-in\n")
    audit = audit_harness_candidate(
        base_spec_path=base,
        candidate_spec_path=candidate,
        tasks_path=tasks,
        require_heldout=True,
        ledger_path=tmp_path / "ledger.jsonl",
    )
    assert not audit["accepted"]
    assert any(v["code"] == "empty_heldout_set" for v in audit["violations"])
    tasks.write_text(tasks.read_text().replace("held-in", "held-out"))
    evaluation = tmp_path / "eval.json"
    for status in ("error", "ungraded", "skipped", "abstained"):
        evaluation.write_text(
            json.dumps(
                {
                    "live": True,
                    "split": "held-out",
                    "variants": [
                        {
                            "harness": "base",
                            "spec": str(candidate),
                            "status": status,
                            "regressed": False,
                            "tasks": [{"id": "one", "status": status}],
                        }
                    ],
                }
            )
        )
        audit = audit_harness_candidate(
            base_spec_path=base,
            candidate_spec_path=candidate,
            tasks_path=tasks,
            require_heldout=True,
            eval_result_paths=(evaluation,),
            ledger_path=tmp_path / "ledger.jsonl",
        )
        assert not audit["accepted"], status


async def test_portable_scorecard_promotion_roundtrip(tmp_path, monkeypatch):
    import hashlib

    root = tmp_path / "project"
    root.mkdir()
    base, candidate = specs(root)
    tasks = root / "tasks.yaml"
    tasks.write_text("tasks:\n  - id: one\n    prompt: fix\n    split: held-out\n")

    async def evaluated(**kwargs):
        return {
            "status": "passed",
            "task_count": 1,
            "variants": [
                {
                    "harness": name,
                    "spec": str(path),
                    "score": 1.0,
                    "tasks": [{"id": "one", "status": "passed"}],
                }
                for name, path in (("base", base), ("candidate", candidate))
            ],
        }

    result = await run_harness_bench(
        HarnessBenchManifest(
            bench_id="fixture",
            tasks=str(tasks),
            specs=(str(base), str(candidate)),
            provider="fixture",
            model="fixture",
            split="held-out",
            manifest_dir=str(root),
        ),
        output_dir=root / "runs" / "roundtrip",
        live=True,
        eval_runner=evaluated,
    )
    state = {
        "base_spec": str(base),
        "candidate_spec": str(candidate),
        "base_digest": hashlib.sha256(base.read_bytes()).hexdigest(),
        "candidate_digest": hashlib.sha256(candidate.read_bytes()).hexdigest(),
    }
    monkeypatch.chdir(tmp_path)
    assert len(_validate_promotion_evidence(state, [result["scorecard"]])) == 1
    scorecard_path = Path(result["scorecard"])
    scorecard = json.loads(scorecard_path.read_text())
    scorecard["variants"][1]["score"]["mean"] = float("nan")
    scorecard_path.write_text(json.dumps(scorecard))
    with pytest.raises(ValueError, match="held-out score"):
        _validate_promotion_evidence(state, [scorecard_path])


def test_unmatched_candidate_does_not_fall_back_to_last_variant(tmp_path):
    from superqode.harness.self_improve import _candidate_eval_gates

    evaluation = tmp_path / "eval.json"
    evaluation.write_text(
        json.dumps(
            {
                "split": "held-out",
                "live": True,
                "variants": [
                    {
                        "spec": str(tmp_path / "other" / "candidate.yaml"),
                        "harness": "same-name",
                        "tasks": [{"id": "one", "status": "passed"}],
                    }
                ],
            }
        )
    )
    gates = _candidate_eval_gates(
        eval_result_paths=(evaluation,),
        candidate_spec_path=tmp_path / "candidate.yaml",
        candidate_name="same-name",
        required_splits=("held-out",),
        allow_ungated=False,
    )
    assert not gates["passed"]
    assert gates["gates"][0]["status"] == "missing_candidate"


@pytest.mark.parametrize("mismatch", ["task_id", "tasks_hash"])
def test_task_identity_mismatch_rejects_otherwise_passing_evidence(tmp_path, mismatch):
    base, candidate = specs(tmp_path)
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text("tasks:\n  - id: expected\n    prompt: fix\n    split: held-out\n")
    payload = {
        "split": "held-out",
        "live": True,
        "variants": [{"spec": str(candidate), "tasks": [{"id": "expected", "status": "passed"}]}],
    }
    if mismatch == "task_id":
        payload["variants"][0]["tasks"][0]["id"] = "unrelated"
    else:
        payload["tasks_hash"] = "sha256:stale"
    evidence = tmp_path / "eval.json"
    evidence.write_text(json.dumps(payload))
    audit = audit_harness_candidate(
        base_spec_path=base,
        candidate_spec_path=candidate,
        tasks_path=tasks,
        require_heldout=True,
        eval_result_paths=(evidence,),
        ledger_path=tmp_path / "ledger.jsonl",
    )
    assert not audit["accepted"]
    assert audit["eval_gates"]["gates"][0]["status"] == "mismatched_task_identity"
