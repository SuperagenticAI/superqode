"""Tune refuses Start with clear credential guidance."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from superqode.systemone import tune


def test_missing_typesafe_and_reflection_keys(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    missing = tune.missing_tune_credentials(reflection_lm="")
    text = tune.format_missing_tune_credentials(missing)
    assert "TYPESAFE_API_KEY" in text
    assert "reflection model" in text.lower() or "OPENAI_API_KEY" in text


def test_missing_provider_key_for_chosen_model(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    missing = tune.missing_tune_credentials(reflection_lm="gemini/gemini-3.6-flash")
    text = tune.format_missing_tune_credentials(missing)
    assert "GEMINI_API_KEY" in text
    assert "gemini/gemini-3.6-flash" in text


def test_ready_when_keys_present(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    assert tune.missing_tune_credentials(reflection_lm="gemini/gemini-3.6-flash") == []


def test_preflight_surfaces_missing_keys(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    opts = tune.TuneOptions(
        reflection_lm="gemini/gemini-3.6-flash", max_evals=10, max_reflection_cost=1.0
    )
    manifest = {"options": asdict(opts), "examples": [], "harness": None}
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY|Cannot start"):
        tune.preflight(manifest, check_gepa=False)
