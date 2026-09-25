"""Read-only Fx settings inspection for agents doctor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superqode.providers.fx.settings import (
    describe_fx_custom_providers,
    read_fx_custom_providers,
)


def test_read_fx_custom_providers_missing(tmp_path):
    info = read_fx_custom_providers(tmp_path / "missing.json")
    assert info["ok"] is False
    assert info["exists"] is False


def test_read_fx_custom_providers_lists_openai_chat_completions(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "provider": "local",
                "providers": {
                    "local": {
                        "protocol": "openai-chat-completions",
                        "base_url": "http://localhost:11434/v1",
                        "auth": {"type": "none"},
                    },
                    "gateway": {"note": "not custom"},
                    "vllm": {
                        "protocol": "openai-chat-completions",
                        "base_url": "http://localhost:8000/v1",
                        "auth": {"type": "none"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    info = read_fx_custom_providers(path)
    assert info["ok"] is True
    assert info["provider_names"] == ["local", "vllm"]
    assert info["selected_provider"] == "local"
    hint = describe_fx_custom_providers(path)
    assert "local" in hint and "vllm" in hint
    assert "selected: local" in hint


@pytest.mark.asyncio
async def test_acp_doctor_fx_includes_custom_provider_hint(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "provider": "local",
                "providers": {
                    "local": {
                        "protocol": "openai-chat-completions",
                        "base_url": "http://localhost:11434/v1",
                        "auth": {"type": "none"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "superqode.providers.fx.settings.DEFAULT_FX_SETTINGS",
        path,
    )

    async def fake_agents():
        return {
            "fx.sh": {
                "short_name": "fx",
                "name": "fx",
                "protocol": "acp",
                "type": "coding",
                "run_command": {"*": "fx acp"},
                "actions": {},
            }
        }

    monkeypatch.setattr(
        "superqode.agents.registry.get_all_acp_agents",
        fake_agents,
    )
    from superqode.acp.doctor import acp_doctor

    results = await acp_doctor("fx")
    assert len(results) == 1
    assert "fx custom providers" in results[0].get("fx_custom_providers_hint", "")
    assert results[0]["fx_settings"]["provider_names"] == ["local"]
