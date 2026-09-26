"""Tests for the cached official ACP Registry integration."""

import asyncio
import json

from superqode.providers import acp_registry


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(acp_registry, "CACHE_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(acp_registry, "_cached_agents", None)
    monkeypatch.setattr(acp_registry, "_cache_time", None)
    monkeypatch.setattr(acp_registry, "_cached_catalog", None)


def test_registry_refresh_writes_cache(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    records = [{"id": "kilo", "name": "Kilo"}]

    async def fake_fetch():
        return records

    monkeypatch.setattr(acp_registry, "fetch_registry_from_cdn", fake_fetch)

    result = asyncio.run(acp_registry.get_acp_registry_agents(force_refresh=True))

    assert result == records
    payload = json.loads(acp_registry.CACHE_FILE.read_text())
    assert payload["agents"] == records


def test_registry_refresh_uses_stale_cache_when_offline(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    stale = [{"id": "devin", "name": "Devin"}]
    acp_registry.CACHE_FILE.write_text(
        json.dumps({"cached_at": "2020-01-01T00:00:00+00:00", "agents": stale})
    )

    async def unavailable():
        return None

    monkeypatch.setattr(acp_registry, "fetch_registry_from_cdn", unavailable)

    result = asyncio.run(acp_registry.get_acp_registry_agents(force_refresh=True))

    assert result == stale


def test_normal_registry_read_does_not_access_network(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)

    async def unexpected():
        raise AssertionError("normal catalog reads must remain offline")

    monkeypatch.setattr(acp_registry, "fetch_registry_from_cdn", unexpected)

    result = asyncio.run(acp_registry.get_acp_registry_agents())

    assert result
    assert all(record.get("source") == "bundled" for record in result)


def test_synchronous_ui_catalog_merges_live_and_bundled_agents(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    acp_registry.CACHE_FILE.write_text(
        json.dumps(
            {
                "cached_at": "2099-01-01T00:00:00+00:00",
                "agents": [
                    {
                        "id": "future-lab-agent",
                        "name": "Future Lab Agent",
                        "description": "Published after this SuperQode release",
                    }
                ],
            }
        )
    )

    catalog = acp_registry.get_cached_acp_catalog()
    names = {agent["short_name"] for agent in catalog}

    assert "future-lab-agent" in names
    assert "codex" in names
    assert "gemini" in names

def test_catalog_merge_unions_bundled_open_source_tags(monkeypatch, tmp_path):
    """Official-first merge must still keep bundled openness tags and run commands."""
    _reset(monkeypatch, tmp_path)
    acp_registry.CACHE_FILE.write_text(
        json.dumps(
            {
                "cached_at": "2099-01-01T00:00:00+00:00",
                "agents": [
                    {
                        "id": "bub",
                        "name": "Bub From Registry",
                        "description": "Official row without openness tags",
                    }
                ],
            }
        )
    )

    catalog = acp_registry.get_cached_acp_catalog()
    bub = next(agent for agent in catalog if agent.get("short_name") == "bub")

    assert bub["name"] == "Bub From Registry"
    assert "open-source" in bub["tags"]
    assert bub["run_command"]["*"] == "bub acp serve"
