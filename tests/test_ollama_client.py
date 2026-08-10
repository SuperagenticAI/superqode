"""Regression tests for the Ollama local provider client parsing."""

import pytest

from superqode.providers.local import OllamaClient
from superqode.providers.local.ollama import (
    _context_from_model_info,
    _tags_details_are_sparse,
)


def _tags_payload():
    # Mirrors a real /api/tags entry. Ollama returns "families": null for
    # many models — the parser must not crash on that.
    return {
        "name": "gemma4:31b-mlx-bf16",
        "model": "gemma4:31b-mlx-bf16",
        "modified_at": "2026-06-01T12:00:00.000000000Z",
        "size": 62_000_000_000,
        "digest": "abc123",
        "details": {
            "family": "gemma",
            "families": None,  # <-- the bug trigger
            "parameter_size": "31B",
            "quantization_level": "BF16",
        },
    }


def test_parse_model_handles_null_families():
    """A model whose details.families is null must still parse (not crash)."""
    client = OllamaClient()
    model = client._parse_model(_tags_payload())
    assert model.id == "gemma4:31b-mlx-bf16"
    assert model.supports_vision is False
    # Earlier this raised TypeError, making list_models() return [] silently.


def test_supports_vision_with_null_families():
    client = OllamaClient()
    assert client._supports_vision("gemma4:31b", {"families": None}) is False
    # Real vision signal still works.
    assert client._supports_vision("x", {"families": ["clip"]}) is True
    # And name-based detection is unaffected.
    assert client._supports_vision("llava:7b", {}) is True


def test_sparse_details_detected_only_for_native_format():
    # Ollama's safetensors models report the fields but leave them empty.
    assert _tags_details_are_sparse(
        {"format": "safetensors", "family": "", "parameter_size": "", "families": None}
    )
    # A GGUF entry is self-describing and needs no extra round-trip.
    assert not _tags_details_are_sparse(
        {"format": "gguf", "family": "qwen3", "parameter_size": "8.2B", "context_length": 40960}
    )


def test_context_is_read_from_architecture_scoped_key():
    assert (
        _context_from_model_info(
            {"general.architecture": "muse_glimmer", "muse_glimmer.context_length": 131072}
        )
        == 131072
    )
    # Unknown architecture still resolves via the suffix.
    assert _context_from_model_info({"whatever.context_length": 8192}) == 8192
    assert _context_from_model_info({}) is None


@pytest.mark.asyncio
async def test_list_models_enriches_native_format_from_show(monkeypatch):
    """A model Ollama serves in its native (non-GGUF) format lists with blank
    metadata; without /api/show it degrades to 4096 ctx and no tool support."""
    client = OllamaClient()
    calls = []

    async def fake_request(method, endpoint, data=None, **kwargs):
        calls.append(endpoint)
        if endpoint == "/api/tags":
            return {
                "models": [
                    {
                        "name": "muse-glimmer:30b-mlx",
                        "size": 21_000_000_000,
                        "details": {
                            "format": "safetensors",
                            "family": "",
                            "families": None,
                            "parameter_size": "",
                            "quantization_level": "",
                        },
                    }
                ]
            }
        return {
            "capabilities": ["completion", "vision", "tools", "thinking"],
            "details": {
                "family": "muse_glimmer",
                "parameter_size": "32.3B",
                "quantization_level": "nvfp4",
            },
            "model_info": {
                "general.architecture": "muse_glimmer",
                "muse_glimmer.context_length": 131072,
            },
        }

    monkeypatch.setattr(client, "_async_request", fake_request)

    model = (await client.list_models())[0]

    assert model.context_window == 131072
    assert model.supports_tools is True
    assert model.supports_vision is True
    assert model.family == "muse_glimmer"
    assert model.quantization == "nvfp4"
    assert model.parameter_count == "32.3B"
    assert calls == ["/api/tags", "/api/show"]


@pytest.mark.asyncio
async def test_list_models_skips_show_for_self_describing_gguf(monkeypatch):
    """GGUF entries already carry their metadata: no extra call per model."""
    client = OllamaClient()
    calls = []

    async def fake_request(method, endpoint, data=None, **kwargs):
        calls.append(endpoint)
        return {
            "models": [
                {
                    "name": "qwen3:8b",
                    "size": 5_225_374_496,
                    "details": {
                        "format": "gguf",
                        "family": "qwen3",
                        "families": ["qwen3"],
                        "parameter_size": "8.2B",
                        "quantization_level": "Q4_K_M",
                        "context_length": 40960,
                    },
                }
            ]
        }

    monkeypatch.setattr(client, "_async_request", fake_request)

    model = (await client.list_models())[0]

    assert model.context_window == 40960
    assert calls == ["/api/tags"]


@pytest.mark.asyncio
async def test_enrichment_failure_leaves_model_listed(monkeypatch):
    """A failing /api/show must not drop the model from the picker."""
    client = OllamaClient()

    async def fake_request(method, endpoint, data=None, **kwargs):
        if endpoint == "/api/tags":
            return {
                "models": [{"name": "muse-glimmer:30b-mlx", "details": {"format": "safetensors"}}]
            }
        raise OSError("show failed")

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert [m.id for m in models] == ["muse-glimmer:30b-mlx"]


def _show_payload():
    return {
        "capabilities": ["completion", "vision", "tools", "thinking"],
        "details": {
            "family": "muse_glimmer",
            "parameter_size": "32.3B",
            "quantization_level": "nvfp4",
        },
        "model_info": {
            "general.architecture": "muse_glimmer",
            "muse_glimmer.context_length": 131072,
        },
        "parameters": "top_k 64\ntop_p 0.95\ntemperature 1",
    }


def test_parse_model_show_trusts_declared_capabilities():
    """get_model_info() has the capability list in hand; an unrecognised family
    name must not override it back to 4096 tokens and no tools."""
    client = OllamaClient()

    model = client._parse_model_show(_show_payload(), "muse-glimmer:30b-mlx")

    assert model.context_window == 131072
    assert model.supports_tools is True
    assert model.supports_vision is True


def test_modelfile_num_ctx_beats_architecture_maximum():
    """num_ctx is what Ollama will actually serve, so it wins."""
    client = OllamaClient()
    payload = {**_show_payload(), "parameters": "num_ctx 8192\ntemperature 1"}

    model = client._parse_model_show(payload, "muse-glimmer:30b-mlx")

    assert model.context_window == 8192


def test_parse_model_show_falls_back_when_capabilities_absent():
    """Older Ollama builds omit the field; heuristics still apply."""
    client = OllamaClient()
    payload = {"details": {"family": "qwen3"}, "parameters": ""}

    model = client._parse_model_show(payload, "qwen3:8b")

    assert model.supports_tools is True  # via the name heuristic


@pytest.mark.asyncio
async def test_tool_test_runs_for_families_the_heuristic_rejects(monkeypatch):
    """An architecture absent from TOOL_CAPABLE_FAMILIES must still be probed
    when Ollama declares tool support, instead of being refused untested."""
    client = OllamaClient()
    posted = []

    async def fake_request(method, endpoint, data=None, **kwargs):
        posted.append(endpoint)
        if endpoint == "/api/show":
            return _show_payload()
        return {
            "message": {
                "tool_calls": [{"function": {"name": "get_weather", "arguments": {"city": "NYC"}}}]
            }
        }

    monkeypatch.setattr(client, "_async_request", fake_request)

    result = await client.test_tool_calling("muse-glimmer:30b-mlx")

    assert result.supports_tools is True
    assert "/api/chat" in posted  # actually probed, not short-circuited


@pytest.mark.asyncio
async def test_tool_test_declines_when_ollama_reports_no_tools(monkeypatch):
    client = OllamaClient()

    async def fake_request(method, endpoint, data=None, **kwargs):
        if endpoint == "/api/show":
            return {"capabilities": ["completion"]}
        raise AssertionError("must not probe a model without tool capability")

    monkeypatch.setattr(client, "_async_request", fake_request)

    result = await client.test_tool_calling("nomic-embed-text:latest")

    assert result.supports_tools is False
    assert "no tool capability" in result.notes
