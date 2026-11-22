"""Real optional kernels with controlled inference, not model-quality evidence."""
# ruff: noqa: F401, F811

import importlib.util

import pytest

from test_factory_definition import project
from test_factory_improvement import prepared
from test_factory_search_metering import model, evaluator
from superqode.factory import improvement


@pytest.mark.parametrize("engine", ["gepa", "metaharness", "omni"])
def test_installed_kernels_use_only_shared_metered_heldin_calls(
    prepared, model, monkeypatch, engine
):
    if any(importlib.util.find_spec(package) is None for package in {"gepa", "metaharness"}):
        pytest.skip("Optional optimizer kernels not installed")
    root, old = prepared
    calls = evaluator(monkeypatch)
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=old["tasks"],
        fixture="fixture",
        max_evals=4,
        max_seconds=120,
        target_kind="workflow",
        stage="investigate",
        reflection_model="ollama/qwen3-coder",
        optimizer_engine=engine,
    )
    result = improvement.optimize(root, plan["id"], plan["digest"])
    assert not result.get("held"), result
    assert result["budget"]["request_count"] >= 1
    assert result["metric_calls"] <= 4
    assert all(call["eval_split"] == "held-in" for call in calls)
    assert not result["heldout_exposed"]
    summary = improvement.budget(root, plan).summary()
    assert summary["unknown_requests"] == 0 and not summary["pending_operations"]
    assert summary["request_count"] == len(model[0]) + len(calls)


def test_missing_kernel_does_not_silently_select_another_engine(prepared, monkeypatch):
    root, old = prepared
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=old["tasks"],
        fixture="fixture",
        max_evals=4,
        max_seconds=60,
        reflection_model="ollama/qwen3-coder",
        optimizer_engine="metaharness",
    )
    import sys

    monkeypatch.setitem(sys.modules, "metaharness", None)
    with pytest.raises(ModuleNotFoundError):
        improvement.optimize(root, plan["id"], plan["digest"])
    assert improvement.budget(root, plan).summary()["request_count"] == 0
