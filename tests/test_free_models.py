"""Tests for the generic free-model discovery pipeline."""

from __future__ import annotations

import json

import pytest

from superqode.agents.free_models import (
    FreeModel,
    FreeModelDiscovery,
    clear_cache,
    discover_all_free_models,
    discover_free_models_for_agent,
    get_parser,
    list_parsers,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


def _opencode_agent(extra=None) -> dict:
    """Build a minimal opencode-shaped Agent dict for tests."""
    agent = {
        "identity": "opencode.ai",
        "name": "OpenCode",
        "short_name": "opencode",
        "free_models": {
            "enabled": True,
            "discovery": {
                "command": "opencode models --verbose",
                "parser": "opencode_models_table",
                "timeout_seconds": 5.0,
            },
            "fallback": [
                {"id": "opencode/big-pickle", "name": "Big Pickle", "context": 200000},
                {"id": "opencode/qwen3.6-plus-free", "name": "Qwen", "context": 262144},
            ],
        },
    }
    if extra:
        agent.update(extra)
    return agent


def test_built_in_parsers_are_registered():
    """The two seed parsers must be discoverable by name; their absence
    would silently break every TOML in the catalog."""
    parsers = list_parsers()
    assert "opencode_models_table" in parsers
    assert "openai_models_endpoint" in parsers


def test_opencode_parser_handles_block_format():
    """Legacy OpenCode CLI output: ``opencode/<id>\\n<json>`` per block."""
    parser = get_parser("opencode_models_table")
    stdout = (
        "opencode/foo-free\n"
        '{"name": "Foo Free", "limit": {"context": 100000}, "pricing": {"input": 0, "output": 0}}\n'
        "opencode/bar-paid\n"
        '{"name": "Bar Paid", "pricing": {"input": 0.5, "output": 1.0}}\n'
        "opencode/baz-free\n"
        '{"name": "Baz Free", "context": 50000}\n'  # no pricing → -free name heuristic
    )
    models = parser(stdout, "opencode.ai")
    ids = {m.id for m in models}
    assert "opencode/foo-free" in ids
    assert "opencode/baz-free" in ids
    assert "opencode/bar-paid" not in ids, "paid model leaked into free list"


def test_opencode_parser_handles_json_document_format():
    """Newer OpenCode emits a single JSON document with a 'models' key."""
    parser = get_parser("opencode_models_table")
    payload = {
        "models": [
            {
                "id": "free-1",
                "name": "Free One",
                "limit": {"context": 1000},
                "pricing": {"input": 0},
            },
            {"id": "paid-1", "name": "Paid", "pricing": {"input": 1.0}},
        ]
    }
    models = parser(json.dumps(payload), "opencode.ai")
    assert [m.id for m in models] == ["opencode/free-1"]


def test_openai_models_endpoint_parser_round_trips():
    parser = get_parser("openai_models_endpoint")
    payload = {
        "data": [
            {"id": "gpt-x", "name": "GPT X", "context_window": 8000, "owned_by": "openai"},
            {"name": "anon", "context": 4000},
        ]
    }
    models = parser(json.dumps(payload), "fake-agent")
    assert {m.id for m in models} >= {"gpt-x"}


def test_opencode_parser_returns_empty_on_garbage():
    """Parsers must not raise on bad input — discovery falls back instead."""
    parser = get_parser("opencode_models_table")
    assert parser("not json, not blocks, just garbage", "opencode.ai") == []


@pytest.mark.asyncio
async def test_discovery_falls_back_when_command_not_installed(monkeypatch):
    """If the head of the discovery command isn't on PATH, the probe must
    skip the subprocess and return the fallback list — this is what makes
    `acp free-models` instant when an agent isn't installed."""
    import superqode.agents.free_models as fm

    monkeypatch.setattr(fm.shutil, "which", lambda _: None)

    agent = _opencode_agent()
    result = await discover_free_models_for_agent(agent)
    assert result.used_fallback is True
    assert result.error == "not installed"
    assert [m.id for m in result.models] == [
        "opencode/big-pickle",
        "opencode/qwen3.6-plus-free",
    ]
    assert all(m.source == "fallback" for m in result.models)


@pytest.mark.asyncio
async def test_discovery_falls_back_on_subprocess_timeout(monkeypatch):
    import asyncio as _asyncio
    import superqode.agents.free_models as fm

    monkeypatch.setattr(fm.shutil, "which", lambda _: "/usr/bin/opencode")

    class _HangingProc:
        async def communicate(self):
            await _asyncio.sleep(10)  # caller's wait_for(timeout=...) will fire

    async def fake_create(*args, **kwargs):
        return _HangingProc()

    monkeypatch.setattr(fm.asyncio, "create_subprocess_shell", fake_create)

    agent = _opencode_agent()
    agent["free_models"]["discovery"]["timeout_seconds"] = 0.05
    result = await discover_free_models_for_agent(agent)
    assert result.used_fallback is True
    assert "timeout" in (result.error or "").lower()
    assert result.models, "fallback list must surface when probe times out"


@pytest.mark.asyncio
async def test_discovery_falls_back_when_parser_returns_nothing(monkeypatch):
    import superqode.agents.free_models as fm

    monkeypatch.setattr(fm.shutil, "which", lambda _: "/usr/bin/opencode")

    class _OkProc:
        returncode = 0

        async def communicate(self):
            return b"garbage that no parser will accept", b""

    async def fake_create(*args, **kwargs):
        return _OkProc()

    monkeypatch.setattr(fm.asyncio, "create_subprocess_shell", fake_create)

    agent = _opencode_agent()
    result = await discover_free_models_for_agent(agent)
    assert result.used_fallback is True
    assert "parser returned no models" in (result.error or "")


@pytest.mark.asyncio
async def test_discovery_caches_within_ttl(monkeypatch):
    """Successive probes inside the TTL window must not re-run the subprocess.
    This is what keeps repeated `acp free-models` calls instant."""
    import superqode.agents.free_models as fm

    monkeypatch.setattr(fm.shutil, "which", lambda _: "/usr/bin/opencode")

    calls = {"n": 0}

    class _OkProc:
        returncode = 0

        async def communicate(self):
            calls["n"] += 1
            payload = {"models": [{"id": "x", "name": "X", "pricing": {"input": 0}}]}
            return json.dumps(payload).encode(), b""

    async def fake_create(*args, **kwargs):
        return _OkProc()

    monkeypatch.setattr(fm.asyncio, "create_subprocess_shell", fake_create)

    agent = _opencode_agent()
    first = await discover_free_models_for_agent(agent)
    second = await discover_free_models_for_agent(agent)
    third = await discover_free_models_for_agent(agent, force_refresh=True)

    assert first.models and second.models and third.models
    # First call + force_refresh = 2 subprocess invocations.
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_agent_without_free_models_section_returns_empty():
    """Agents that don't declare [free_models] should produce an empty
    result, not crash and not log noise."""
    agent = {"identity": "no-free.example", "name": "NoFree", "short_name": "nofree"}
    result = await discover_free_models_for_agent(agent)
    assert isinstance(result, FreeModelDiscovery)
    assert result.models == []
    assert result.used_fallback is False


@pytest.mark.asyncio
async def test_discover_all_runs_concurrently_and_preserves_order():
    agents = [
        _opencode_agent({"identity": "a.example", "short_name": "a"}),
        {"identity": "no-free.example", "name": "NoFree", "short_name": "nofree"},
        _opencode_agent({"identity": "c.example", "short_name": "c"}),
    ]
    # All three agents have either no free-models or a missing-binary
    # fallback path, so this test is portable.
    results = await discover_all_free_models(agents)
    assert [r.agent_id for r in results] == [
        "a.example",
        "no-free.example",
        "c.example",
    ]


@pytest.mark.asyncio
async def test_opencode_toml_round_trips_through_discovery(monkeypatch):
    """The shipped opencode.ai.toml is the working reference. Even when
    the binary isn't installed in the test env, the fallback list must
    surface so users still see free models."""
    from superqode.agents.discovery import read_agents
    import superqode.agents.free_models as fm

    monkeypatch.setattr(fm.shutil, "which", lambda _: None)

    agents = await read_agents()
    oc = agents["opencode.ai"]
    result = await discover_free_models_for_agent(oc)

    assert result.used_fallback is True
    ids = {m.id for m in result.models}
    assert "opencode/big-pickle" in ids
    assert any(m.context > 0 for m in result.models)


def test_freemodel_to_dict_shape():
    m = FreeModel(id="x/y", name="Y", agent_id="x.example", context=100, provider="x")
    d = m.to_dict()
    assert d["id"] == "x/y"
    assert d["agent_id"] == "x.example"
    assert d["context"] == 100
    assert d["source"] == "discovery"
