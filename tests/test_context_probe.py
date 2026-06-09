"""Tests for local context-window detection and adaptive budget hardening."""

import pytest

from superqode.providers.local import context_probe as cp
from superqode.agent.loop import AgentConfig, AgentLoop


# ── probe parsers ───────────────────────────────────────────────────────────


def test_parse_ollama_ps_reads_loaded_context():
    data = {"models": [{"name": "qwen3:32b", "context_length": 16384}]}
    assert cp._parse_ollama_ps(data, "qwen3:32b") == 16384


def test_parse_llamacpp_props_reads_n_ctx():
    data = {"default_generation_settings": {"n_ctx": 8192}}
    assert cp._parse_llamacpp_props(data, None) == 8192


def test_parse_models_list_prefers_loaded_over_max():
    data = {"data": [{"id": "qwen", "loaded_context_length": 12000, "max_context_length": 128000}]}
    assert cp._parse_models_list(data, "qwen") == 12000


def test_parse_models_list_vllm_max_model_len():
    data = {"data": [{"id": "meta/llama", "max_model_len": 32768}]}
    assert cp._parse_models_list(data, "llama") == 32768


def test_parse_rejects_insane_values():
    assert cp._parse_models_list({"data": [{"id": "x", "max_model_len": 10**12}]}, "x") is None
    assert cp._parse_models_list({"data": [{"id": "x", "max_model_len": 10}]}, "x") is None


def test_candidate_urls_use_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://box:9999/v1")
    urls = cp.candidate_base_urls("ollama")
    assert "http://box:9999" in urls  # trailing /v1 stripped for sibling probes
    assert "http://localhost:11434" in urls


def test_candidate_urls_per_backend():
    assert "http://localhost:1234" in cp.candidate_base_urls("lmstudio")
    assert "http://127.0.0.1:8000" in cp.candidate_base_urls("ds4")
    assert "http://localhost:8000" in cp.candidate_base_urls("vllm")


@pytest.mark.asyncio
async def test_probe_base_url_uses_first_answering_endpoint(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        # Only the OpenAI-compatible /v1/models answers (vLLM/DS4 style).
        if url.endswith("/api/v1/models"):
            return None
        if url.endswith("/v1/models"):
            return {"data": [{"id": "m", "max_model_len": 24000}]}
        return None

    monkeypatch.setattr(cp, "_http_get_json", fake_get)
    result = await cp.probe_base_url("http://localhost:8000", "m")
    assert result == (24000, "/v1/models")


# ── loop integration ────────────────────────────────────────────────────────


def _loop(provider, window=0, **kw):
    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(provider=provider, model="m", context_window=window, **kw)
    return loop


def test_local_providers_detected():
    for p in ("ollama", "ds4", "lmstudio", "vllm", "sglang", "mlx", "tgi", "llamacpp"):
        assert _loop(p)._provider_is_local() is True
    assert _loop("anthropic")._provider_is_local() is False
    assert _loop("openai")._provider_is_local() is False


def test_local_unprobed_window_is_conservative_not_catalog():
    # An unprobed local model must NOT inherit a huge catalog/model-card window.
    assert _loop("ollama")._effective_context_window() == 8192


def test_explicit_window_wins_for_local():
    loop = _loop("ollama", window=16384)
    assert loop._effective_context_window() == 16384
    threshold, keep_recent, window = loop._compaction_budgets()
    assert window == 16384
    # 20% reserve for the small-window safety margin.
    assert window - threshold == int(16384 * 0.20)


def test_reserve_floor_protects_tiny_windows():
    threshold, keep_recent, window = _loop("ollama", window=2048)._compaction_budgets()
    assert window - threshold >= 1024  # reserve never below the 1024 floor


@pytest.mark.asyncio
async def test_ensure_context_window_caches_explicit():
    loop = _loop("ollama", window=12000)
    assert await loop._ensure_context_window() == 12000
    assert loop._context_window_source == "configured"
