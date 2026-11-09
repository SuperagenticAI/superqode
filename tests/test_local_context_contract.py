"""Focused tests for local memory/context contracts and safe request shaping."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.local import context_contract as cc
from superqode.local.hardware import HardwareProfile
from superqode.providers.local import context_probe as cp


def mac(memory):
    return HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=memory)


@pytest.mark.parametrize(
    "memory,model",
    [
        (16, "qwen3.5:4b"),
        (16, "qwen3.5:9b"),
        (32, "devstral-small-2:24b"),
        (48, "qwen3.6:35b"),
        (64, "qwen3.6:35b"),
        (96, "qwen3-coder-next:q4_K_M"),
    ],
)
def test_starters_fit_their_actual_working_set(memory, model):
    contract = cc.choose_contract(model, mac(memory))
    assert contract.fit["rating"] == "Fits"
    assert contract.fit["estimate_gb"] < contract.fit["budget_gb"]
    assert contract.fit["estimate_gb"] > contract.fit["weights_gb"]
    assert contract.max_tokens <= contract.context // 4


def test_large_weights_never_use_active_moe_parameter_size():
    fit = cc.memory_fit("qwen3-coder-next:q4_K_M", 64)
    assert fit["weights_gb"] == 52
    assert fit["rating"] == "Too large"
    assert cc.choose_contract("qwen3.6:27b", mac(32)).fit["rating"] == "Tight"
    assert cc.choose_contract("devstral-small-2:24b", mac(24)).fit["rating"] != "Fits"


def test_context_and_kv_quantization_change_memory_and_metadata_is_used():
    meta = {"num_hidden_layers": 32, "num_key_value_heads": 8, "head_dim": 128}
    small = cc.memory_fit("m", 32, 4096, weights_gb=4, metadata=meta, kv_cache="f16")
    large = cc.memory_fit("m", 32, 8192, weights_gb=4, metadata=meta, kv_cache="f16")
    quant = cc.memory_fit("m", 32, 8192, weights_gb=4, metadata=meta, kv_cache="q8_0")
    assert small["kv_gb"] == 0.5
    assert large["kv_gb"] == 1
    assert quant["kv_gb"] < large["kv_gb"]
    assert large["kv_source"] == "architecture metadata"
    assert cc.memory_fit("unknown", 16)["rating"] == "Unknown"


def test_contract_roundtrip_and_loaded_window_only_lowers_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_contract_path", lambda *args: tmp_path / "contract.json")
    contract = cc.choose_contract("qwen3.5:9b", mac(16))
    cc.save_contract("ollama", "qwen3.5:9b", contract)
    assert cc.requested_context("ollama", "qwen3.5:9b") == contract.context
    assert cc.output_limit("ollama", "qwen3.5:9b") == contract.max_tokens
    assert cc.effective_context("ollama", "qwen3.5:9b", 2048) == 2048
    assert cc.effective_context("ollama", "qwen3.5:9b", 262144) == contract.context
    (tmp_path / "contract.json").write_text("broken")
    assert 512 <= cc.requested_context("ollama", "m") <= 16384


def test_lmstudio_v1_parses_instances_not_unloaded_maxima_or_other_models():
    data = {
        "models": [
            {
                "key": "other",
                "loaded_instances": [{"id": "other", "config": {"context_length": 65536}}],
            },
            {
                "key": "wanted",
                "max_context_length": 262144,
                "loaded_instances": [
                    {"id": "instance-a", "config": {"context_length": 16384}},
                    {"id": "instance-b", "config": {"context_length": 8192}},
                ],
            },
            {"key": "unloaded", "max_context_length": 262144, "loaded_instances": []},
        ]
    }
    assert cp._parse_models_list(data, "wanted") == 8192
    assert cp._parse_models_list(data, "instance-a") == 16384
    assert cp._parse_models_list(data, "unloaded") is None
    assert cp._parse_models_list(data, "missing") is None
    assert (
        cp._parse_models_list({"data": [{"id": "other", "context_length": 8192}]}, "wanted") is None
    )


def test_guard_preserves_systems_latest_turn_and_tool_pairs_without_mutation():
    messages = [
        {"role": "system", "content": "Follow the rules"},
        {"role": "user", "content": "old " * 3000},
        {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "read"}}]},
        {"role": "tool", "tool_call_id": "a", "content": "old result"},
        {"role": "user", "content": "new question"},
        {"role": "assistant", "tool_calls": [{"id": "b", "function": {"name": "read"}}]},
        {"role": "tool", "tool_call_id": "b", "content": "current result"},
    ]
    before = copy.deepcopy(messages)
    kept, output = cc.guard_request(messages, [], 2048, 99999)
    assert kept == [0, 4, 5, 6]
    assert output <= 2048 - cc.estimate_tokens([messages[i] for i in kept]) - 256
    assert messages == before


def test_tool_schemas_and_structured_unicode_content_count_and_block_oversized_turn():
    messages = [{"role": "user", "content": [{"type": "text", "text": "你好" * 100}]}]
    tools = [{"type": "function", "function": {"name": "read", "description": "x" * 9000}}]
    assert cc.estimate_tokens(messages, tools) > cc.estimate_tokens(messages)
    with pytest.raises(ValueError, match="Nothing was sent"):
        cc.guard_request(messages, tools, 2048, 4096)
    kept, output = cc.guard_request([{"role": "user", "content": "hi"}], [], 2048, 99999)
    assert kept == [0]
    assert 128 <= output < 2048


@pytest.mark.asyncio
async def test_gateway_uses_actual_window_and_contract_output_not_family_default(monkeypatch):
    from superqode.providers.gateway.base import Message
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    async def probe(*args):
        return 2048, "/api/ps"

    monkeypatch.setattr(cp, "resolve_local_context_window", probe)
    monkeypatch.setattr(cc, "requested_context", lambda *args: 8192)
    monkeypatch.setattr(cc, "output_limit", lambda *args: 1024)
    gateway = LiteLLMGateway()
    kwargs = {"num_ctx": 131072}
    messages, output = await gateway._guard_local_request(
        [Message(role="user", content="hello")], "qwen3.5:9b", "ollama", 99999, None, kwargs
    )
    assert len(messages) == 1
    assert kwargs["num_ctx"] == 2048
    assert output == 1024
    assert gateway._ollama_num_ctx_for("qwen3.5:9b") == 8192


def test_install_detection_finds_app_binary_and_headless_cli(tmp_path, monkeypatch):
    from superqode.local import install

    monkeypatch.setattr(install.shutil, "which", lambda *args: None)
    real_is_file = Path.is_file
    app_binary = "/Applications/Ollama.app/Contents/Resources/ollama"
    monkeypatch.setattr(Path, "is_file", lambda p: str(p) == app_binary or real_is_file(p))
    monkeypatch.setattr(install.os, "access", lambda *args: True)
    assert install.runtime_executable("ollama") == app_binary
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    binary = tmp_path / ".lmstudio/bin/lms"
    binary.parent.mkdir(parents=True)
    binary.write_text("fixture")
    assert install.runtime_executable("lms") == str(binary)
    monkeypatch.setattr(Path, "is_dir", lambda p: str(p) == "/Applications/LM Studio.app")
    assert install.runtime_installed("lmstudio")


def test_lmstudio_download_progress_and_failure(monkeypatch):
    from superqode.local import lmstudio_api as api

    calls = []
    responses = iter(
        [
            {"status": "downloading", "job_id": "job_a", "total_size_bytes": 100},
            {"status": "completed", "downloaded_bytes": 100, "total_size_bytes": 100},
        ]
    )

    def request(path, payload=None, **kwargs):
        calls.append((path, payload))
        return next(responses)

    monkeypatch.setattr(api, "request", request)
    monkeypatch.setattr(api.time, "sleep", lambda _: None)
    events = []
    api.download("qwen/qwen3.5-4b", lambda kind, data: events.append(data))
    assert calls[0] == ("/models/download", {"model": "qwen/qwen3.5-4b"})
    assert calls[1][0] == "/models/download/status/job_a"
    assert events[-1]["completed"] == 100
    assert events[-1]["total"] == 100
    assert events[-1]["unit"] == "B"
    monkeypatch.setattr(api, "request", lambda *args, **kw: {"status": "failed"})
    with pytest.raises(ValueError, match="download failed"):
        api.download("m", lambda *args: None)


def test_lmstudio_load_requests_context_and_flash_attention(monkeypatch):
    from superqode.local import lmstudio_api as api

    seen = {}

    def request(path, payload, **kwargs):
        seen.update(path=path, payload=payload)
        return {"status": "loaded", "load_config": {"context_length": 8192}}

    monkeypatch.setattr(api, "request", request)
    api.load("qwen/qwen3.5-4b", 8192)
    assert seen["path"] == "/models/load"
    assert seen["payload"]["context_length"] == 8192
    assert seen["payload"]["flash_attention"] is True


def test_staged_metadata_replaces_stale_version_and_keeps_dependencies(tmp_path):
    script = Path(__file__).parents[1] / "apps/macos/scripts/refresh-engine-metadata.py"
    spec = importlib.util.spec_from_file_location("refresh_metadata", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = tmp_path / "runtime"
    package = payload / "backend/superqode"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "2.31.6"')
    for folder in [payload / "backend", payload / "python/lib/python3.12/site-packages"]:
        old = folder / "superqode-2.31.4.dist-info"
        old.mkdir(parents=True)
        (old / "METADATA").write_text("Name: superqode\nVersion: 2.31.4\n")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\nname="superqode"\nversion="2.31.6"\ndependencies=["httpx>=0.27"]\n[project.scripts]\nsuperqode="superqode.cli:main"\n'
    )
    assert module.refresh(payload, project) == "2.31.6"
    infos = list(payload.rglob("superqode-*.dist-info"))
    assert len(infos) == 1
    assert infos[0].name == "superqode-2.31.6.dist-info"
    assert "Requires-Dist: httpx>=0.27" in (infos[0] / "METADATA").read_text()
    assert "superqode.cli:main" in (infos[0] / "entry_points.txt").read_text()


def test_ollama_architecture_metadata_reaches_fit_math(monkeypatch):
    from superqode.local import model_metadata
    import io

    responses = iter(
        [
            {
                "model_info": {
                    "qwen.block_count": 32,
                    "qwen.attention.head_count_kv": 8,
                    "qwen.attention.head_count": 32,
                    "qwen.embedding_length": 4096,
                }
            },
            {"models": [{"name": "m", "size": 4 * 1024**3}]},
        ]
    )
    monkeypatch.setattr(
        model_metadata.urllib.request,
        "urlopen",
        lambda *a, **kw: io.BytesIO(json.dumps(next(responses)).encode()),
    )
    metadata = model_metadata.read_metadata("ollama", "m")
    fit = cc.memory_fit(
        "m", 32, 8192, metadata=metadata, weights_gb=metadata["size_bytes"] / 1024**3
    )
    assert fit["kv_source"] == "architecture metadata"
    assert fit["weights_gb"] == 4


def test_reviewed_lmstudio_stop_does_not_require_pid_and_preserves_ownership_on_error(
    tmp_path, monkeypatch
):
    from superqode.local import servers, workbench

    manager = servers.ServerManager(registry_dir=tmp_path)
    handle = servers.ServerHandle(
        engine="lmstudio",
        host="127.0.0.1",
        port=1234,
        base_url="http://127.0.0.1:1234/v1",
        started_at=123,
    )
    manager._save(handle)
    monkeypatch.setattr(servers.shutil, "which", lambda *a: "/fixture/lms")
    plan = workbench.prepare({"action": "stop", "engine": "lmstudio"}, tmp_path)
    assert plan["pid"] is None
    monkeypatch.setattr(servers.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    assert not manager.stop("lmstudio")
    assert manager._load("lmstudio") is not None
    monkeypatch.setattr(servers.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    assert workbench.run(plan, tmp_path, lambda *a: None)["stopped"]


@pytest.mark.parametrize("engine", ["ollama", "lmstudio"])
def test_unload_review_does_not_delete_weights_and_execution_uses_vendor_control(
    tmp_path, monkeypatch, engine
):
    from superqode.local import workbench
    import io

    plan = workbench.prepare({"action": "unload", "engine": engine, "model": "m"}, tmp_path)
    assert plan["action"] == "unload"
    seen = []
    if engine == "lmstudio":
        monkeypatch.setattr(workbench, "_command", lambda argv, emit: seen.append(argv))
    else:

        def request(req, **kwargs):
            seen.append(json.loads(req.data))
            return io.BytesIO(b"{}")

        monkeypatch.setattr("urllib.request.urlopen", request)
    assert workbench.run(plan, tmp_path, lambda *a: None)["unloaded"]
    if engine == "lmstudio":
        assert seen[0][1:] == ["unload", "m"]
    else:
        assert seen[0] == {"model": "m", "keep_alive": 0}


def test_reviewed_explicit_ollama_cache_reaches_server_start(tmp_path, monkeypatch):
    from superqode.local import workbench, model_metadata

    monkeypatch.setattr(model_metadata, "read_metadata", lambda *a: {})
    monkeypatch.setattr(cc, "save_contract", lambda *a: None)
    monkeypatch.setattr(workbench, "detect_hardware", lambda: mac(16))
    seen = {}

    def start(self, engine, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(to_dict=lambda: {}, notes=[])

    monkeypatch.setattr(workbench.ServerManager, "start", start)
    monkeypatch.setattr(workbench.ServerManager, "is_running", lambda *a, **kw: False)
    plan = workbench.prepare(
        {
            "action": "serve",
            "engine": "ollama",
            "model": "qwen3.5:4b",
            "context": 8192,
            "kv_cache": "f16",
        },
        tmp_path,
    )
    assert plan["contract"]["kv_cache"] == "f16"
    workbench.run(plan, tmp_path, lambda *a: None)
    assert seen["kv_cache"] == "f16"
    assert seen["ctx"] == plan["contract"]["context"]


def test_model_training_cap_can_lower_hardware_suggestion():
    contract = cc.choose_contract(
        "m", mac(32), context=16384, metadata={"max_context_length": 2048}, weights_gb=4
    )
    assert contract.context == 2048
    assert contract.max_tokens <= 512


@pytest.mark.parametrize("code,advice", [(404, "REST v1"), (401, "authentication")])
def test_lmstudio_api_capability_errors_are_actionable(monkeypatch, code, advice):
    from superqode.local import lmstudio_api as api
    import urllib.error

    def reject(*args, **kwargs):
        raise urllib.error.HTTPError(api.BASE, code, "fixture", {}, None)

    monkeypatch.setattr(api.urllib.request, "urlopen", reject)
    with pytest.raises(ValueError, match=advice):
        api.request("/models")
