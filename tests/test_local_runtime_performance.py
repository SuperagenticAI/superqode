"""Regressions for local setup latency and honest inference measurements."""

import io
import json
import threading
from types import SimpleNamespace

from superqode.desktop_service import local_models
from superqode.local import bench, servers, workbench


def test_engine_status_checks_overlap_and_keep_catalog_order(tmp_path, monkeypatch):
    barrier = threading.Barrier(len(workbench.ENGINES))

    class Manager:
        def __init__(self, **_kwargs):
            pass

        def precheck(self, engine):
            # A sequential implementation cannot pass this barrier. All five
            # independent engine checks must get a chance to run together.
            barrier.wait(timeout=3)
            return servers.LocalReadiness(
                engine, True, True, "http://127.0.0.1", "running", "", True
            )

        def _load(self, _engine):
            return None

    monkeypatch.setattr(servers, "ServerManager", Manager)
    monkeypatch.setattr(local_models, "ds4_configuration", lambda _service: {"binary": ""})
    result = local_models.servers(SimpleNamespace(root=tmp_path))
    assert [row["id"] for row in result] == list(workbench.ENGINES)
    assert all(row["running"] for row in result)
    assert all(not row["can_stop"] for row in result), "Unowned servers must remain unowned"


def test_benchmark_counts_reported_tokens_not_fragments_and_separates_thinking(monkeypatch):
    frames = [
        {"choices": [{"delta": {"reasoning_content": "Thinking"}}]},
        {"choices": [{"delta": {"content": "Many tokens fit in this one fragment"}}]},
        {"choices": [], "usage": {"completion_tokens": 101}},
    ]
    wire = (
        "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
    ).encode()
    requests = []

    def respond(request, timeout=None):
        requests.append(json.loads(request.data))
        return io.BytesIO(wire)

    ticks = iter([0, 1, 3, 8])
    monkeypatch.setattr(bench, "urlopen", respond)
    monkeypatch.setattr(bench, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    result = bench.run_bench("http://127.0.0.1:1234/v1", "fixture")
    assert result.ok
    assert result.completion_tokens == 101
    assert result.output_chunks == 2
    assert result.ttft_s == 1
    assert result.first_text_s == 3
    assert result.total_s == 8
    assert result.decode_tps == 50, "Final usage/connection delay must not count as decoding"
    assert requests[0]["stream_options"] == {"include_usage": True}


def test_missing_usage_does_not_invent_a_token_rate(monkeypatch):
    wire = (
        b'data: {"choices":[{"delta":{"content":"A long, many-token answer"}}]}\n\ndata: [DONE]\n\n'
    )
    monkeypatch.setattr(bench, "urlopen", lambda *args, **kwargs: io.BytesIO(wire))
    result = bench.run_bench("http://127.0.0.1:1234/v1", "fixture")
    assert result.ok
    assert result.completion_tokens is None
    assert result.decode_tps is None
    assert result.output_chunks == 1
    assert "n/a" in bench.render_bench([result])


def test_max_reasoning_keeps_ollama_thinking_enabled_through_real_litellm_mapping():
    from litellm.llms.ollama.chat.transformation import OllamaChatConfig
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    for model, expected in (("qwen3:8b", True), ("gpt-oss:20b", "high")):
        mapped = LiteLLMGateway()._resolve_reasoning_effort("ollama", model, "max")
        wire_options = OllamaChatConfig().map_openai_params(
            non_default_params=mapped, optional_params={}, model=model, drop_params=False
        )
        assert wire_options["think"] == expected
