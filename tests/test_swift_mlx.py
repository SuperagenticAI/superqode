import json
import sys

import pytest

from superqode.local import apple_sessions, swift_mlx
from superqode.providers.gateway.base import Message
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


@pytest.fixture
def cached_qwen(tmp_path, monkeypatch):
    model = tmp_path / "models--mlx-community--Qwen3-0.6B-4bit"
    revision = "a" * 40
    snapshot = model / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (model / "refs").mkdir()
    (model / "refs" / "main").write_text(revision)
    (snapshot / "config.json").write_text(
        json.dumps({"model_type": "qwen3", "max_position_embeddings": 32768})
    )
    (snapshot / "tokenizer.json").write_text("{}")
    (snapshot / "tokenizer_config.json").write_text("{}")
    (snapshot / "model.safetensors").write_bytes(b"weights")
    monkeypatch.setattr(swift_mlx, "cache_directory", lambda: tmp_path)
    return snapshot


def test_swift_mlx_only_shows_complete_cached_text_models(cached_qwen, monkeypatch):
    monkeypatch.setattr(swift_mlx, "helper_path", lambda: "/fixture/SwiftMLX")
    assert [model["id"] for model in swift_mlx.status()["models"]] == [swift_mlx.STARTER]
    index = cached_qwen / "model.safetensors.index.json"
    index.write_text(json.dumps({"weight_map": {"weights": "missing.safetensors"}}))
    assert swift_mlx.status()["models"] == []
    index.write_text(json.dumps({"weight_map": {"weights": "model.safetensors"}}))
    assert [model["id"] for model in swift_mlx.status()["models"]] == [swift_mlx.STARTER]


@pytest.mark.asyncio
async def test_swift_mlx_comparison_observes_cached_revision_without_a_server(cached_qwen):
    from superqode.desktop_service.local_comparisons import observe_identity

    identity = await observe_identity(
        {"provider": swift_mlx.PROVIDER, "model": swift_mlx.STARTER}, None
    )
    assert identity["artifact"]["revision"] == cached_qwen.name
    assert identity["loaded_context"] == 8192


@pytest.mark.asyncio
async def test_swift_mlx_gateway_cancellation_terminates_the_helper(
    cached_qwen, monkeypatch, tmp_path
):
    from contextlib import aclosing

    helper = tmp_path / "model-bridge"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        "request = json.loads(sys.stdin.readline())\n"
        "assert request['context'] >= 512\n"
        "print(json.dumps({'event':'text', 'text':'started'}), flush=True)\n"
        "time.sleep(60)\n"
    )
    helper.chmod(0o700)
    monkeypatch.setattr(swift_mlx, "helper_path", lambda: str(helper))
    stopped = []
    stop = apple_sessions.stop

    async def record_stop(child):
        await stop(child)
        stopped.append(child.returncode)

    monkeypatch.setattr(apple_sessions, "stop", record_stop)
    async with aclosing(
        LiteLLMGateway().stream_completion(
            [Message("user", "Fixture")], swift_mlx.STARTER, provider=swift_mlx.PROVIDER
        )
    ) as events:
        assert (await anext(events)).content == "started"
    assert len(stopped) == 1 and stopped[0] is not None
