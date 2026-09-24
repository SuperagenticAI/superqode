"""A2A registry routes by URL, not remote Agent Card name."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from superqode.a2a.registry import A2AAgentEntry, A2ARegistry, AmbiguousAgentName


@dataclass
class _FakeSkill:
    id: str
    name: str
    description: str = ""


@dataclass
class _FakeCard:
    name: str
    description: str = ""
    version: str = "1.0"
    skills: list = None

    def __post_init__(self):
        if self.skills is None:
            self.skills = []


class _FakeClient:
    def __init__(self, url: str, card: _FakeCard):
        self.url = url
        self._card = card

    async def get_agent_card(self):
        return self._card

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_discover_from_url_keys_by_url_not_card_name(monkeypatch):
    cards = {
        "http://trusted.example": _FakeCard(name="Helper"),
        "http://attacker.example": _FakeCard(name="Helper"),
    }

    def fake_client(url: str):
        return _FakeClient(url, cards[url.rstrip("/")])

    monkeypatch.setattr("superqode.a2a.registry.A2AClient", fake_client)

    registry = A2ARegistry()
    first = await registry.discover_from_url("http://trusted.example")
    assert first is not None
    assert registry.get_by_url("http://trusted.example") is first

    # Second peer with the same card name must not overwrite the first URL.
    with pytest.raises(AmbiguousAgentName):
        await registry.discover_from_url("http://attacker.example")

    assert registry.get_by_url("http://trusted.example") is first
    assert registry.get_by_url("http://attacker.example") is None


@pytest.mark.asyncio
async def test_add_uses_local_alias_and_url_identity(monkeypatch):
    monkeypatch.setattr(
        "superqode.a2a.registry.A2AClient",
        lambda url: _FakeClient(url, _FakeCard(name="Remote Display Name")),
    )
    registry = A2ARegistry()
    ok = await registry.add("local-alias", "http://agent.example/")
    assert ok is True
    entry = registry.get("local-alias")
    assert entry is not None
    assert entry.url == "http://agent.example"
    assert entry.name == "local-alias"
    # URL lookup also works
    assert registry.get("http://agent.example") is entry


def test_get_rejects_ambiguous_presentational_name():
    registry = A2ARegistry()
    registry._agents["http://a.example"] = A2AAgentEntry(
        name="Dup", url="http://a.example"
    )
    registry._agents["http://b.example"] = A2AAgentEntry(
        name="Dup", url="http://b.example"
    )
    with pytest.raises(AmbiguousAgentName):
        registry.get("Dup")


def test_save_and_load_round_trip_url_keys(tmp_path: Path):
    path = tmp_path / "a2a_agents.json"
    registry = A2ARegistry(config_path=str(path))
    registry._put(
        A2AAgentEntry(name="alpha", url="http://alpha.example", description="a")
    )
    registry.save()

    loaded = A2ARegistry(config_path=str(path))
    loaded.load()
    entry = loaded.get_by_url("http://alpha.example")
    assert entry is not None
    assert entry.name == "alpha"
    assert loaded.get("alpha") is entry


def test_load_migrates_legacy_name_keyed_file(tmp_path: Path):
    path = tmp_path / "legacy.json"
    path.write_text(
        '{\n  "Helper": {"url": "http://trusted.example", "description": "ok"}\n}\n'
    )
    registry = A2ARegistry(config_path=str(path))
    registry.load()
    entry = registry.get_by_url("http://trusted.example")
    assert entry is not None
    assert entry.name == "Helper"
