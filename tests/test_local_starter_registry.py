"""Catalog-only defaults and explicit per-engine, per-Mac evidence scope."""

import copy
import json

import pytest

from superqode.local.hardware import HardwareProfile
from superqode.local.starter_registry import (
    SUITE_VERSION,
    TASK_IDS,
    load_evidence,
    memory_tier,
    promote,
    registry,
    suggestions,
    validate_report,
)


def mac(memory=16):
    return HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=memory)


def passing_report(engine="ollama", memory=16, context=8192):
    tag = "qwen3.5:4b" if engine == "ollama" else "qwen/qwen3.5-4b"
    return {
        "suite": SUITE_VERSION,
        "execution_mode": "local-model",
        "completed": True,
        "passed": True,
        "registry_model": "qwen3.5:4b",
        "engine": engine,
        "catalog_tag": tag,
        "runtime_model": tag,
        "identity_verified": True,
        "artifact": {"digest": "fixture-digest"} if engine == "ollama" else {"key": tag},
        "fit": {"rating": "Fits"},
        "endpoint": "http://127.0.0.1:11434",
        "context": context,
        "hardware": {"is_apple_silicon": True, "unified_memory_gb": memory},
        "memory_tier": memory_tier(memory),
        "tasks": [
            {
                "id": task,
                "passed": True,
                "tool_calls_valid": True,
                "tool_calls": 1,
                "elapsed_seconds": 0.1,
            }
            for task in TASK_IDS
        ],
    }


def write_evidence(path, *reports):
    path.write_text(json.dumps({"reports": reports}))


def test_shipped_models_are_catalog_only_with_both_verified_engine_tags():
    assert len(registry()) == 6
    for model in registry():
        assert model["status"] == "catalog-verified"
        assert set(model["engines"]) == {"ollama", "lmstudio"}
        assert all(model["engines"].values())
        assert all(url.startswith("https://") for url in model["sources"].values())


def test_tested_choices_preferred_for_engine_only(tmp_path):
    evidence = tmp_path / "registry.json"
    write_evidence(evidence, passing_report())
    rows = suggestions(mac(), evidence)
    ollama = [r for r in rows if r["engine"] == "ollama"]
    assert [r["model"] for r in ollama] == ["qwen3.5:4b"]
    assert ollama[0]["status"] == "tested"
    assert len([r for r in rows if r["engine"] == "lmstudio"]) == 2
    assert all(r["status"] == "catalog-verified" for r in rows if r["engine"] == "lmstudio")


@pytest.mark.parametrize("report", [passing_report(memory=32), passing_report(context=4096)])
def test_larger_mac_and_shorter_context_evidence_does_not_promote(tmp_path, report):
    path = tmp_path / "registry.json"
    write_evidence(path, report)
    assert all(r["status"] == "catalog-verified" for r in suggestions(mac(), path))


def test_unsafe_tested_entry_does_not_displace_safe_fallback(tmp_path):
    report = passing_report()
    report.update(registry_model="qwen3-coder-next:q4_K_M", catalog_tag="qwen3-coder-next:q4_K_M")
    path = tmp_path / "registry.json"
    write_evidence(path, report)
    rows = suggestions(mac(), path)
    assert rows and all("coder-next" not in r["model"] for r in rows)
    assert all(r["status"] == "catalog-verified" for r in rows)


def test_honest_24gb_and_64gb_fallbacks(tmp_path):
    path = tmp_path / "missing.json"
    assert all("24b" not in r["model"] for r in suggestions(mac(24), path))
    assert all("coder-next" not in r["model"] for r in suggestions(mac(64), path))
    assert any(r["model"] == "qwen3.6:35b" for r in suggestions(mac(64), path))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(execution_mode="simulated"),
        lambda r: r.update(completed=False),
        lambda r: r.update(identity_verified=False),
        lambda r: r.update(artifact=""),
        lambda r: r.update(engine="other"),
        lambda r: r.update(catalog_tag="wrong-model"),
        lambda r: r.update(memory_tier="96"),
        lambda r: r.update(tasks=r["tasks"][:-1]),
        lambda r: r["tasks"][0].update(passed=False),
        lambda r: r["tasks"][0].update(tool_calls_valid=False),
        lambda r: r["tasks"][0].update(tool_calls=0),
        lambda r: r["hardware"].update(is_apple_silicon=False),
    ],
)
def test_promotion_rejects_incomplete_simulated_failing_or_wrong_evidence(mutate):
    report = copy.deepcopy(passing_report())
    mutate(report)
    with pytest.raises(ValueError):
        validate_report(report)


def test_explicit_promotion_ingests_json_without_changing_shipped_status(tmp_path):
    source, target = tmp_path / "run.json", tmp_path / "local-evals.json"
    source.write_text(json.dumps(passing_report()))
    promote(source, target)
    promote(source, target)
    assert len(load_evidence(target)) == 1
    assert any(r["status"] == "tested" for r in suggestions(mac(), target))
    assert all(r["status"] == "catalog-verified" for r in registry())


def test_promotion_does_not_destroy_an_existing_corrupt_registry(tmp_path):
    source, target = tmp_path / "report.json", tmp_path / "registry.json"
    source.write_text(json.dumps(passing_report()))
    target.write_text("retain invalid evidence for inspection")
    with pytest.raises(ValueError):
        promote(source, target)
    assert target.read_text() == "retain invalid evidence for inspection"


@pytest.mark.parametrize(
    "field,value", [("endpoint", {}), ("hardware", []), ("artifact", "wrong"), ("fit", [])]
)
def test_malformed_report_fields_are_rejected_without_breaking_catalog(tmp_path, field, value):
    report = passing_report()
    report[field] = value
    with pytest.raises(ValueError):
        validate_report(report)
    path = tmp_path / "bad.json"
    write_evidence(path, report)
    assert all(row["status"] == "catalog-verified" for row in suggestions(mac(), path))
