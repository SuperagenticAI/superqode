"""Tests for `superqode connect setup` (provider connection guide)."""

from __future__ import annotations

import json

import click.testing
import pytest

from superqode.main import cli_main
from superqode.providers.models import ModelCapability, ModelInfo
from superqode.providers.models_dev import ProviderInfo, get_models_dev


@pytest.fixture
def fake_catalog(monkeypatch):
    client = get_models_dev()
    saved_p, saved_m = dict(client._providers), dict(client._models)
    client._providers = {
        "anthropic": ProviderInfo(id="anthropic", name="Anthropic", env_vars=["ANTHROPIC_API_KEY"]),
        "baseten": ProviderInfo(
            id="baseten",
            name="Baseten",
            env_vars=["BASETEN_API_KEY"],
            api_url="https://inference.baseten.co/v1",
            doc_url="https://docs.baseten.co",
        ),
    }
    client._models = {
        "baseten": {
            "llama-70b": ModelInfo(
                id="llama-70b",
                name="Llama 70B",
                provider="baseten",
                context_window=128000,
                capabilities=[ModelCapability.TOOLS],
            )
        }
    }
    monkeypatch.setattr(client, "ensure_cache_loaded", lambda: True)
    try:
        yield client
    finally:
        client._providers, client._models = saved_p, saved_m


def _run(args, env=None):
    return click.testing.CliRunner().invoke(cli_main, args, env=env or {})


def test_setup_dynamic_provider_json(fake_catalog):
    res = _run(["connect", "setup", "baseten", "--json"], env={"BASETEN_API_KEY": ""})
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["id"] == "baseten"
    assert data["curated"] is False and data["dynamic"] is True
    assert data["routing"] == "openai-compatible"
    assert data["env_vars"] == ["BASETEN_API_KEY"]
    assert data["default_base_url"] == "https://inference.baseten.co/v1"
    assert data["example_models"] == ["llama-70b"]
    assert data["connect_command"] == "superqode connect byok baseten <model>"


def test_setup_curated_provider_text(fake_catalog):
    res = _run(["connect", "setup", "anthropic"])
    assert res.exit_code == 0, res.output
    assert "curated / recommended" in res.output
    assert "ANTHROPIC_API_KEY" in res.output


def test_setup_unknown_provider_errors(fake_catalog):
    res = _run(["connect", "setup", "totally-bogus"])
    assert res.exit_code != 0
    assert "Unknown provider" in res.output


def test_setup_warns_when_key_missing(fake_catalog):
    res = _run(["connect", "setup", "baseten"], env={"BASETEN_API_KEY": ""})
    assert "Set BASETEN_API_KEY" in res.output


def test_setup_key_configured_no_warning(fake_catalog):
    res = _run(["connect", "setup", "baseten"], env={"BASETEN_API_KEY": "sk-xyz"})
    assert "✓ set" in res.output
    assert "⚠" not in res.output
