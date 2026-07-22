from __future__ import annotations

import hashlib
import json

import pytest

from superqode.harness.promotion import (
    activate_harness_promotion,
    harness_promotion_state,
    rollback_harness_promotion,
    select_harness_promotion,
    stage_harness_promotion,
    start_harness_canary,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage(tmp_path):
    base = tmp_path / "base.yaml"
    candidate = tmp_path / "candidate.yaml"
    base.write_text("version: 1\nname: coding\ndescription: stable\n")
    candidate.write_text("version: 1\nname: coding\ndescription: improved\n")
    registry = tmp_path / ".superqode" / "harnesses" / "promotions.jsonl"
    audit = {
        "accepted": True,
        "candidate_id": "cand_test",
        "candidate_spec": str(candidate.resolve()),
        "base_spec": str(base.resolve()),
        "diff_fingerprint": "diff-test",
        "changed_surfaces": ["description"],
        "eval_gates": {"gates": [{"split": "held-out", "status": "passed"}]},
    }
    staged = stage_harness_promotion(
        base_spec=base,
        candidate_spec=candidate,
        audit=audit,
        registry_path=registry,
        actor="maintainer",
    )
    return base, candidate, registry, staged


def _scorecard(tmp_path, base, candidate, staged, *, live=True, score=1.0):
    path = tmp_path / "scorecard.json"
    path.write_text(
        json.dumps(
            {
                "status": "passed",
                "live": live,
                "split": "held-out",
                "fingerprint": "bench-fingerprint",
                "repetitions": 3,
                "sources": {
                    "specs": {
                        str(base.resolve()): staged["base_digest"],
                        str(candidate.resolve()): staged["candidate_digest"],
                    }
                },
                "variants": [
                    {
                        "harness": "coding@base",
                        "spec": str(base.resolve()),
                        "score": {"mean": 0.8},
                        "regression_runs": 0,
                    },
                    {
                        "harness": "coding@candidate",
                        "spec": str(candidate.resolve()),
                        "score": {"mean": score},
                        "regression_runs": 0,
                    },
                ],
            }
        )
    )
    return path


def test_harness_promotion_canary_activation_and_verified_rollback(tmp_path):
    base, candidate, registry, staged = _stage(tmp_path)
    original = base.read_text()
    canary = start_harness_canary(
        staged["candidate_id"],
        percent=25,
        registry_path=registry,
        actor="maintainer",
    )
    evidence = _scorecard(tmp_path, base, candidate, staged)

    selected = None
    stable = None
    for index in range(1000):
        choice = select_harness_promotion(
            base, key=f"work-{index}", registry_path=registry
        )
        if choice["selected"] == "candidate":
            selected = choice
        else:
            stable = choice
        if selected and stable:
            break

    assert canary["canary_percent"] == 25
    assert selected["selected_spec"] == str(candidate.resolve())
    assert stable["selected_spec"] == str(base.resolve())

    activated = activate_harness_promotion(
        staged["candidate_id"],
        evidence_paths=(evidence,),
        registry_path=registry,
        actor="maintainer",
        repository=tmp_path,
    )

    assert base.read_text() == candidate.read_text()
    assert activated["activated_digest"] == _sha(base)
    assert harness_promotion_state(
        staged["candidate_id"], registry_path=registry
    )["status"] == "active"

    rolled_back = rollback_harness_promotion(
        staged["candidate_id"],
        registry_path=registry,
        actor="maintainer",
        reason="canary regression",
    )

    assert rolled_back["restored"]
    assert base.read_text() == original
    assert harness_promotion_state(
        staged["candidate_id"], registry_path=registry
    )["status"] == "rolled_back"


def test_harness_promotion_rejects_dry_or_regressing_evidence(tmp_path):
    base, candidate, registry, staged = _stage(tmp_path)
    start_harness_canary(
        staged["candidate_id"],
        percent=10,
        registry_path=registry,
        actor="maintainer",
    )
    dry = _scorecard(tmp_path, base, candidate, staged, live=False)

    with pytest.raises(ValueError, match="passing live"):
        activate_harness_promotion(
            staged["candidate_id"],
            evidence_paths=(dry,),
            registry_path=registry,
            actor="maintainer",
            repository=tmp_path,
        )

    regressing = _scorecard(tmp_path, base, candidate, staged, score=0.7)
    with pytest.raises(ValueError, match="does not meet"):
        activate_harness_promotion(
            staged["candidate_id"],
            evidence_paths=(regressing,),
            registry_path=registry,
            actor="maintainer",
            repository=tmp_path,
        )


def test_harness_rollback_refuses_to_overwrite_post_promotion_changes(tmp_path):
    base, candidate, registry, staged = _stage(tmp_path)
    start_harness_canary(
        staged["candidate_id"], percent=50, registry_path=registry, actor="maintainer"
    )
    evidence = _scorecard(tmp_path, base, candidate, staged)
    activate_harness_promotion(
        staged["candidate_id"],
        evidence_paths=(evidence,),
        registry_path=registry,
        actor="maintainer",
        repository=tmp_path,
    )
    base.write_text(base.read_text() + "metadata:\n  later: true\n")

    with pytest.raises(ValueError, match="changed after promotion"):
        rollback_harness_promotion(
            staged["candidate_id"],
            registry_path=registry,
            actor="maintainer",
            reason="rollback",
        )
