"""Tune UI preference persistence across restart."""

from __future__ import annotations

from pathlib import Path

from superqode.systemone import tune


def test_preferred_reflection_model_persists(tmp_path, monkeypatch):
    path = tmp_path / "tune-preferences.json"
    monkeypatch.setattr(tune, "tune_preferences_path", lambda: path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert tune.preferred_reflection_model() == ""
    tune.save_tune_preferences(reflection_lm="gemini/gemini-3.6-flash", max_evals=80)
    assert path.is_file()
    assert tune.load_tune_preferences()["reflection_lm"] == "gemini/gemini-3.6-flash"
    assert tune.preferred_reflection_model() == "gemini/gemini-3.6-flash"
    tune.save_tune_preferences(reflection_lm="")
    assert "reflection_lm" not in tune.load_tune_preferences()
