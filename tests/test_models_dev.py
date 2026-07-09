"""Regression coverage for the live models.dev catalog client."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import superqode.providers.models_dev as models_dev_module
from superqode.providers.models import ModelCapability
from superqode.providers.models_dev import ModelsDev


def _model(name: str, *, input_price: float, output_price: float) -> dict:
    return {
        "name": name,
        "release_date": "2026-07-09",
        "tool_call": True,
        "reasoning": True,
        "modalities": {"input": ["text", "image", "pdf"]},
        "limit": {"context": 1_050_000, "output": 128_000},
        "cost": {"input": input_price, "output": output_price},
    }


def _catalog_payload() -> dict:
    return {
        "openai": {
            "name": "OpenAI",
            "env": ["OPENAI_API_KEY"],
            "models": {
                "gpt-5.6": _model("GPT-5.6", input_price=5, output_price=30),
                "gpt-5.6-luna": _model("GPT-5.6 Luna", input_price=1, output_price=6),
                "gpt-5.6-terra": _model("GPT-5.6 Terra", input_price=2.5, output_price=15),
                "gpt-5.6-sol": _model("GPT-5.6 Sol", input_price=5, output_price=30),
            },
        },
        "meta": {
            "name": "Meta",
            "env": ["META_MODEL_API_KEY"],
            "api": "https://api.meta.ai/v1",
            "models": {
                "muse-spark-1.1": {
                    **_model("Muse Spark 1.1", input_price=1.25, output_price=4.25),
                    "modalities": {"input": ["text", "image", "pdf", "video"]},
                    "limit": {"context": 1_000_000, "output": 32_000},
                }
            },
        },
    }


def test_models_dev_parses_current_openai_and_meta_models():
    client = ModelsDev()
    client._parse_data(_catalog_payload())

    assert {
        "gpt-5.6",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    } <= set(client.get_models_for_provider("openai"))

    meta = client.get_provider("meta")
    muse = client.get_model("meta", "muse-spark-1.1")
    assert meta is not None
    assert meta.env_vars == ["META_MODEL_API_KEY"]
    assert meta.api_url == "https://api.meta.ai/v1"
    assert muse is not None
    assert muse.provider == "meta"
    assert {
        ModelCapability.TOOLS,
        ModelCapability.REASONING,
        ModelCapability.VISION,
        ModelCapability.LONG_CONTEXT,
    } <= set(muse.capabilities)


@pytest.mark.asyncio
async def test_expired_cache_refreshes_instead_of_resetting_its_timestamp(monkeypatch, tmp_path):
    cache_file = tmp_path / "models_cache.json"
    stale_payload = _catalog_payload()
    cache_file.write_text(
        json.dumps(
            {
                **stale_payload,
                "_metadata": {
                    "fetched_at": (datetime.now() - timedelta(hours=2)).isoformat(),
                    "ttl_hours": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(models_dev_module, "CACHE_FILE", cache_file)

    refreshed_payload = _catalog_payload()
    refreshed_payload["openai"]["models"]["gpt-5.6-next"] = _model(
        "GPT-5.6 Next", input_price=4, output_price=24
    )
    client = ModelsDev()
    calls = 0

    async def fake_fetch():
        nonlocal calls
        calls += 1
        return refreshed_payload

    monkeypatch.setattr(client, "_fetch_api", fake_fetch)

    assert await client.ensure_loaded() is True
    assert calls == 1
    assert "gpt-5.6-next" in client.get_models_for_provider("openai")
    assert client.get_cache_info()["is_expired"] is False
