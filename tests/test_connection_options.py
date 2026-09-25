"""tool_choice_mode and reviewer_model connection options."""

from __future__ import annotations

from pathlib import Path

from superqode.config.loader import parse_provider_config
from superqode.providers.connection_options import (
    apply_tool_choice_mode,
    connection_options_for,
    resolve_reviewer_model,
)


def test_parse_provider_config_tool_choice_and_reviewer():
    cfg = parse_provider_config(
        {
            "base_url": "http://localhost:8000/v1",
            "tool_choice_mode": "omit",
            "reviewer_model": "qwen2.5-coder:7b",
        }
    )
    assert cfg.tool_choice_mode == "omit"
    assert cfg.reviewer_model == "qwen2.5-coder:7b"


def test_apply_tool_choice_mode_omit(monkeypatch):
    monkeypatch.setattr(
        "superqode.providers.connection_options.connection_options_for",
        lambda _pid: type("O", (), {"tool_choice_mode": "omit", "reviewer_model": ""})(),
    )
    request = {"tool_choice": "auto", "tools": []}
    apply_tool_choice_mode("vllm", request, tool_choice="auto")
    assert "tool_choice" not in request


def test_apply_tool_choice_mode_send_default(monkeypatch):
    monkeypatch.setattr(
        "superqode.providers.connection_options.connection_options_for",
        lambda _pid: type("O", (), {"tool_choice_mode": None, "reviewer_model": ""})(),
    )
    request: dict = {}
    apply_tool_choice_mode("vllm", request, tool_choice="auto")
    assert request["tool_choice"] == "auto"


def test_resolve_reviewer_model_from_config(tmp_path, monkeypatch):
    config_path = tmp_path / "superqode.yaml"
    config_path.write_text(
        "providers:\n  ollama:\n    reviewer_model: gemma4:e4b\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    # Clear any cached config if loader caches by cwd path.
    assert resolve_reviewer_model("ollama", "qwen3:8b") == "gemma4:e4b"
    assert resolve_reviewer_model("anthropic", "claude") == "claude"
