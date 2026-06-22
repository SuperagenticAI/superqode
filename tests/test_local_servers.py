"""Tests for the local server lifecycle manager (start/adopt/stop/registry).

Everything external (subprocess, HTTP probes, the registry directory) is mocked
or redirected to a tmp path; no test launches a real engine or model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superqode.local import servers
from superqode.local.servers import SPECS, ServerError, ServerHandle, ServerManager


@pytest.fixture()
def manager(tmp_path: Path) -> ServerManager:
    return ServerManager(registry_dir=tmp_path / "servers")


# -- spec table -------------------------------------------------------------


def test_spec_table_covers_all_five_engines():
    assert set(SPECS) == {"ollama", "lmstudio", "mlx", "ds4", "llama.cpp"}


def test_base_url_is_always_openai_v1(manager: ServerManager):
    # readiness path varies (/health vs /v1/models) but the OpenAI route is /v1
    assert manager.base_url("mlx", "127.0.0.1", 8080) == "http://127.0.0.1:8080/v1"
    assert manager.base_url("ds4", "127.0.0.1", 8000) == "http://127.0.0.1:8000/v1"


# -- command building -------------------------------------------------------


def test_build_command_ollama_sets_host_and_ctx_env(manager: ServerManager):
    cmd, env, cwd = manager.build_command("ollama", host="127.0.0.1", port=11434, ctx=8192)
    assert cmd[:2] == ["ollama", "serve"]
    assert env["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert env["OLLAMA_CONTEXT_LENGTH"] == "8192"
    assert cwd is None


def test_build_command_lmstudio_uses_lms_server_start(manager: ServerManager):
    cmd, _env, _cwd = manager.build_command("lmstudio", host="127.0.0.1", port=1234)
    assert cmd == ["lms", "server", "start", "-p", "1234"]


def test_build_command_mlx_uses_venv_interpreter_not_path(manager: ServerManager):
    cmd, _env, _cwd = manager.build_command("mlx", host="127.0.0.1", port=8080, model="org/model")
    # Must invoke `python -m mlx_lm server`, never a bare mlx_lm.server on PATH.
    assert cmd[0].endswith("python") or "python" in cmd[0]
    assert cmd[1:4] == ["-m", "mlx_lm", "server"]
    assert "--model" in cmd and "org/model" in cmd


def test_build_command_mlx_requires_model(manager: ServerManager):
    with pytest.raises(ServerError, match="needs a model"):
        manager.build_command("mlx", host="127.0.0.1", port=8080)


def test_build_command_llamacpp_maps_ctx_to_dash_c(manager: ServerManager):
    cmd, _env, _cwd = manager.build_command(
        "llama.cpp", host="127.0.0.1", port=8081, model="/m.gguf", ctx=4096
    )
    assert "-c" in cmd and "4096" in cmd


def test_build_command_ds4_maps_ctx_to_flag_and_sets_cwd(manager, monkeypatch, tmp_path):
    binary = tmp_path / "ds4-server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(manager, "_ds4_binary", lambda: binary)
    cmd, _env, cwd = manager.build_command("ds4", host="127.0.0.1", port=8000, ctx=100000)
    assert cmd[0] == str(binary)
    assert "--ctx" in cmd and "100000" in cmd
    assert "--kv-disk-dir" in cmd
    assert "--kv-disk-space-mb" in cmd and "8192" in cmd
    assert cwd == binary.parent


def test_build_command_ds4_defaults_safe_ctx_and_kv_cache(manager, monkeypatch, tmp_path):
    binary = tmp_path / "ds4-server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(manager, "_ds4_binary", lambda: binary)
    cmd, _env, cwd = manager.build_command("ds4", host="127.0.0.1", port=8000)
    assert cmd[0] == str(binary)
    assert "--ctx" in cmd and "32768" in cmd
    assert "--kv-disk-dir" in cmd
    assert "--kv-disk-space-mb" in cmd and "8192" in cmd
    assert cwd == binary.parent


def test_build_command_ds4_respects_custom_kv_cache_extra(manager, monkeypatch, tmp_path):
    binary = tmp_path / "ds4-server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(manager, "_ds4_binary", lambda: binary)
    cmd, _env, _cwd = manager.build_command(
        "ds4",
        host="127.0.0.1",
        port=8000,
        extra_args=["--kv-disk-dir", "/tmp/custom-kv", "--kv-disk-space-mb=4096"],
    )
    assert cmd.count("--kv-disk-dir") == 1
    assert "/tmp/custom-kv" in cmd
    assert "--kv-disk-space-mb=4096" in cmd


def test_build_command_ds4_errors_when_binary_missing(manager, monkeypatch):
    monkeypatch.setattr(manager, "_ds4_binary", lambda: None)
    with pytest.raises(ServerError, match="not built"):
        manager.build_command("ds4", host="127.0.0.1", port=8000)


# -- start / adopt ----------------------------------------------------------


def test_start_adopts_already_running_server(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: True)
    launched = {"called": False}

    def fail_popen(*a, **k):  # pragma: no cover - must not run
        launched["called"] = True
        raise AssertionError("should not launch when adopting")

    monkeypatch.setattr(servers.subprocess, "Popen", fail_popen)
    handle = manager.start("ollama")
    assert handle.adopted is True
    assert launched["called"] is False
    # registry persisted
    assert manager._registry_path("ollama").exists()


def test_start_raises_when_not_installed(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: False)
    with pytest.raises(ServerError, match="not installed"):
        manager.start("lmstudio")


def test_start_launches_and_waits_for_readiness(manager, monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    monkeypatch.setattr(servers, "_hf_model_cached", lambda m: True)
    # not running until after launch
    state = {"up": False}
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: state["up"])

    class FakeProc:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(cmd, **kwargs):
        assert kwargs.get("start_new_session") is True  # managed daemon
        state["up"] = True
        return FakeProc()

    monkeypatch.setattr(servers.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(servers, "_probe", lambda url, timeout=1.5: state["up"])

    handle = manager.start("mlx", model="org/m", port=8099, wait=True, timeout=5)
    assert handle.pid == 4242
    assert handle.adopted is False
    assert handle.base_url == "http://127.0.0.1:8099/v1"
    assert manager._registry_path("mlx").exists()


def test_start_lmstudio_runs_cli_and_captures_output(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    calls = []

    class Result:
        returncode = 0
        stdout = "server started"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr(servers.subprocess, "run", fake_run)
    monkeypatch.setattr(servers, "_probe", lambda url, timeout=1.5: True)

    handle = manager.start("lmstudio", wait=True, timeout=1)

    assert handle.engine == "lmstudio"
    assert handle.pid is None
    assert handle.base_url == "http://127.0.0.1:1234/v1"
    assert calls[0][0] == ["lms", "server", "start", "-p", "1234"]
    assert calls[0][1]["capture_output"] is True
    assert "server started" in Path(handle.log_path).read_text()


def test_start_lmstudio_surfaces_cli_failure(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)

    class Result:
        returncode = 1
        stdout = ""
        stderr = "LM Studio backend is not ready"

    monkeypatch.setattr(servers.subprocess, "run", lambda *a, **k: Result())

    with pytest.raises(ServerError, match="LM Studio backend is not ready"):
        manager.start("lmstudio", wait=True, timeout=1)


def test_start_times_out_when_never_ready(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(servers, "_hf_model_cached", lambda m: True)

    class FakeProc:
        pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(servers.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(servers, "_probe", lambda url, timeout=1.5: False)
    monkeypatch.setattr(servers.time, "sleep", lambda s: None)
    with pytest.raises(ServerError, match="did not become ready"):
        manager.start("mlx", model="org/m", timeout=0.5)


# -- stop -------------------------------------------------------------------


def test_stop_managed_terminates_pid(manager, monkeypatch):
    handle = ServerHandle(
        engine="mlx", host="127.0.0.1", port=8080, base_url="x", pid=9999, adopted=False
    )
    manager._save(handle)
    killed = {}

    def fake_terminate(pid, grace=5.0):
        killed["pid"] = pid
        return True

    monkeypatch.setattr(servers, "_terminate", fake_terminate)
    assert manager.stop("mlx") is True
    assert killed["pid"] == 9999
    assert not manager._registry_path("mlx").exists()


def test_stop_adopted_does_not_kill(manager, monkeypatch):
    handle = ServerHandle(
        engine="ollama", host="127.0.0.1", port=11434, base_url="x", pid=5, adopted=True
    )
    manager._save(handle)
    monkeypatch.setattr(servers, "_terminate", lambda *a, **k: pytest.fail("must not kill adopted"))
    assert manager.stop("ollama") is False


def test_stop_lmstudio_calls_lms_stop(manager, monkeypatch):
    monkeypatch.setattr(servers.shutil, "which", lambda name: "/usr/bin/lms")
    calls = []
    monkeypatch.setattr(servers.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    assert manager.stop("lmstudio") is True
    assert calls and calls[0] == ["lms", "server", "stop"]


# -- registry + status ------------------------------------------------------


def test_status_clears_stale_registry(manager, monkeypatch):
    manager._save(ServerHandle(engine="ds4", host="127.0.0.1", port=8000, base_url="x", pid=1))
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    status = manager.status("ds4")
    assert status["running"] is False
    assert not manager._registry_path("ds4").exists()  # forgotten


# -- context-window flexibility ---------------------------------------------


def test_ctx_notes_ollama_uses_env(manager):
    notes = manager._ctx_notes("ollama", 16384, None)
    assert any("OLLAMA_CONTEXT_LENGTH" in n for n in notes)


def test_ctx_notes_ds4_flag(manager):
    notes = manager._ctx_notes("ds4", 200000, None)
    assert any("200,000" in n for n in notes)


def test_ctx_notes_mlx_warns_unsupported(manager):
    notes = manager._ctx_notes("mlx", 8192, "org/m")
    assert any("fixed by the model" in n for n in notes)


def test_ctx_notes_lmstudio_without_model_hints_load(manager):
    notes = manager._ctx_notes("lmstudio", 8192, None)
    assert any("model load" in n for n in notes)
    # with a model, the load step (not the note) carries the context
    assert manager._ctx_notes("lmstudio", 8192, "qwen") == []


def test_ctx_notes_empty_when_no_ctx(manager):
    assert manager._ctx_notes("ds4", None, None) == []


def test_lms_load_builds_context_command(manager, monkeypatch):
    monkeypatch.setattr(servers.shutil, "which", lambda name: "/usr/bin/lms")
    captured = {}

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return R()

    monkeypatch.setattr(servers.subprocess, "run", fake_run)
    notes = manager._lms_load("qwen3-coder", 12000)
    assert captured["cmd"] == ["lms", "load", "qwen3-coder", "-y", "-c", "12000"]
    assert any("loaded qwen3-coder" in n and "12,000" in n for n in notes)


def test_start_passes_custom_port_into_handle(manager, monkeypatch, tmp_path):
    binary = tmp_path / "ds4-server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(manager, "_ds4_binary", lambda: binary)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)

    class FakeProc:
        pid = 1

        def poll(self):
            return None

    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(servers.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(servers, "_probe", lambda url, timeout=1.5: True)
    handle = manager.start("ds4", port=9001, ctx=123456, host="0.0.0.0")
    assert handle.port == 9001
    assert handle.base_url == "http://0.0.0.0:9001/v1"
    assert handle.ctx == 123456
    # ds4 puts both onto the argv
    assert "9001" in captured["cmd"] and "123456" in captured["cmd"]


def test_start_ds4_records_default_context(manager, monkeypatch, tmp_path):
    binary = tmp_path / "ds4-server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(manager, "_ds4_binary", lambda: binary)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)

    class FakeProc:
        pid = 1

        def poll(self):
            return None

    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(servers.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(servers, "_probe", lambda url, timeout=1.5: True)
    handle = manager.start("ds4", host="127.0.0.1")
    assert handle.ctx == 32768
    assert "32768" in captured["cmd"]


# -- precheck (the TUI gate) ------------------------------------------------


def test_precheck_running(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: True)
    r = manager.precheck("ollama")
    assert r.state == "running"
    assert r.running and r.installed
    assert r.base_url == "http://127.0.0.1:11434/v1"


def test_precheck_installed_but_stopped(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    monkeypatch.setattr(manager, "can_start", lambda e: True)
    monkeypatch.setattr(manager, "app_running", lambda e: True)
    r = manager.precheck("lmstudio")
    assert r.state == "stopped"
    assert r.installed and not r.running
    assert r.startable is True
    assert r.app_running is True
    assert r.start_hint == ":local serve lmstudio"


def test_precheck_lmstudio_app_only_is_not_startable(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(servers.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        servers.Path,
        "exists",
        lambda self: str(self) == "/Applications/LM Studio.app",
    )

    r = manager.precheck("lmstudio")

    assert r.state == "stopped"
    assert r.installed and not r.running
    assert r.startable is False
    assert r.cli_available is False
    assert "Open LM Studio" in r.start_hint


def test_precheck_lmstudio_cli_but_app_closed_is_not_startable(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(servers.shutil, "which", lambda name: "/usr/local/bin/lms")
    monkeypatch.setattr(manager, "app_running", lambda e: False)

    r = manager.precheck("lmstudio")

    assert r.state == "stopped"
    assert r.installed and not r.running
    assert r.cli_available is True
    assert r.app_running is False
    assert r.startable is False


def test_lmstudio_app_running_detects_process(manager, monkeypatch):
    calls = []

    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result(0 if cmd == ["pgrep", "-x", "LM Studio"] else 1)

    monkeypatch.setattr(servers.subprocess, "run", fake_run)

    assert manager.app_running("lmstudio") is True
    assert calls == [["pgrep", "-x", "LM Studio"]]


def test_lmstudio_app_running_falls_back_to_pattern(manager, monkeypatch):
    calls = []

    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result(0 if cmd == ["pgrep", "-f", "LM Studio"] else 1)

    monkeypatch.setattr(servers.subprocess, "run", fake_run)

    assert manager.app_running("lmstudio") is True
    assert calls == [["pgrep", "-x", "LM Studio"], ["pgrep", "-f", "LM Studio"]]


def test_precheck_missing_includes_install_guide(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: False)
    r = manager.precheck("mlx")
    assert r.state == "missing"
    assert r.install_guide  # non-empty
    assert any("superqode[mlx]" in line for line in r.install_guide)


def test_precheck_model_engine_start_hint_mentions_model(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    r = manager.precheck("mlx")
    assert r.needs_model is True
    assert "--model" in r.start_hint


def test_install_guide_for_every_engine():
    from superqode.local.servers import install_guide

    for engine in SPECS:
        assert install_guide(engine), f"missing install guide for {engine}"


# -- embedding filter + download guard --------------------------------------


def test_is_embedding_model_detects_common_embedders():
    from superqode.providers.local.base import is_embedding_model

    for mid in (
        "text-embedding-nomic-embed-text-v1.5",
        "nomic-ai/nomic-embed-text-v1",
        "BAAI/bge-large-en-v1.5",
        "intfloat/e5-mistral-7b",
        "mixedbread-ai/mxbai-rerank-large",
        "sentence-transformers/all-MiniLM-L6-v2",
    ):
        assert is_embedding_model(mid), mid


def test_is_embedding_model_keeps_chat_models():
    from superqode.providers.local.base import is_embedding_model

    for mid in (
        "qwen/qwen3-coder-30b",
        "mlx-community/Llama-3.2-3B-Instruct-4bit",
        "deepseek-v4-flash",
        "google/gemma-4-12B-it",
    ):
        assert not is_embedding_model(mid), mid


def test_hf_model_cached_true_for_local_path_and_bare_name(tmp_path):
    from superqode.local.servers import _hf_model_cached

    assert _hf_model_cached("llama3.2") is True  # bare name, nothing to download
    p = tmp_path / "model.gguf"
    p.write_text("x")
    assert _hf_model_cached(str(p)) is True  # explicit local path


def test_hf_model_cached_false_for_uncached_hf_id(monkeypatch, tmp_path):
    from superqode.local import servers

    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.setattr(servers.Path, "home", staticmethod(lambda: tmp_path))
    assert servers._hf_model_cached("org/never-downloaded-model") is False


def test_start_mlx_refuses_uncached_download_without_permission(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    monkeypatch.setattr(servers, "_hf_model_cached", lambda m: False)
    with pytest.raises(ServerError, match="not downloaded"):
        manager.start("mlx", model="org/huge-model")


def test_start_mlx_allows_download_when_permitted(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda *a, **k: False)
    monkeypatch.setattr(manager, "is_installed", lambda e: True)
    monkeypatch.setattr(servers, "_hf_model_cached", lambda m: False)

    class FakeProc:
        pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(servers.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(servers, "_probe", lambda url, timeout=1.5: True)
    handle = manager.start("mlx", model="org/huge-model", allow_download=True)
    assert handle.pid == 1  # got past the guard


# -- mlx-lm inline install --------------------------------------------------


def test_install_mlx_prefers_uv(monkeypatch):
    from superqode.local import servers
    import superqode.providers.env_introspect as env_introspect

    monkeypatch.setattr(
        env_introspect.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None
    )
    captured = {}

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return R()

    monkeypatch.setattr(servers.subprocess, "run", fake_run)
    monkeypatch.setattr(servers, "_mlx_importable", lambda python: True)
    ok, msg = servers.install_mlx(python="/x/py")
    assert ok is True
    assert captured["cmd"][:4] == ["uv", "pip", "install", "--python"]
    assert servers.MLX_REQUIREMENT in captured["cmd"]


def test_install_mlx_reports_failure_when_still_not_importable(monkeypatch):
    from superqode.local import servers
    import superqode.providers.env_introspect as env_introspect

    monkeypatch.setattr(env_introspect.shutil, "which", lambda name: None)  # no uv -> pip

    class R:
        returncode = 1
        stdout = ""
        stderr = "boom: no matching distribution"

    monkeypatch.setattr(servers.subprocess, "run", lambda cmd, **k: R())
    monkeypatch.setattr(servers, "_mlx_importable", lambda python: False)
    ok, msg = servers.install_mlx(python="/x/py")
    assert ok is False
    assert "boom" in msg


# -- inline start prompt parsing (the one-key TUI flow) ---------------------


def test_parse_inline_start_enter_means_defaults():
    from superqode.local.servers import parse_inline_start

    action, opts, err = parse_inline_start("")
    assert action == "start" and opts == {} and err == ""


def test_parse_inline_start_cancel_words():
    from superqode.local.servers import parse_inline_start

    for word in ("n", "no", "skip", "cancel", "q", "N"):
        assert parse_inline_start(word)[0] == "cancel"


def test_parse_inline_start_key_values():
    from superqode.local.servers import parse_inline_start

    action, opts, _ = parse_inline_start("port=8090 ctx=8192 model=qwen host=0.0.0.0")
    assert action == "start"
    assert opts == {"port": 8090, "ctx": 8192, "model": "qwen", "host": "0.0.0.0"}


def test_parse_inline_start_bare_number_is_port():
    from superqode.local.servers import parse_inline_start

    assert parse_inline_start("9001") == ("start", {"port": 9001}, "")


def test_parse_inline_start_yes_then_opts():
    from superqode.local.servers import parse_inline_start

    action, opts, _ = parse_inline_start("yes ctx=4096")
    assert action == "start" and opts == {"ctx": 4096}


def test_parse_inline_start_bad_number_errors():
    from superqode.local.servers import parse_inline_start

    action, _opts, err = parse_inline_start("port=abc")
    assert action == "error" and "port" in err


def test_parse_inline_start_unknown_token_errors():
    from superqode.local.servers import parse_inline_start

    assert parse_inline_start("frobnicate")[0] == "error"


def test_registry_roundtrips(manager):
    handle = ServerHandle(
        engine="mlx", host="127.0.0.1", port=8080, base_url="u", pid=7, model="org/m"
    )
    manager._save(handle)
    loaded = manager._load("mlx")
    assert loaded is not None
    assert loaded.pid == 7
    assert loaded.model == "org/m"
    data = json.loads(manager._registry_path("mlx").read_text())
    assert data["engine"] == "mlx"


def test_tui_parse_serve_args_accepts_quoted_model_path():
    from superqode.app_main import SuperQodeApp

    engine, opts = SuperQodeApp._parse_serve_args(
        'llama.cpp --model "/models/code model.gguf" --port 8090 --ctx 8192'
    )
    assert engine == "llama.cpp"
    assert opts == {"model": "/models/code model.gguf", "port": 8090, "ctx": 8192}


def test_tui_parse_serve_args_accepts_extra_passthrough():
    from superqode.app_main import SuperQodeApp

    engine, opts = SuperQodeApp._parse_serve_args(
        "ds4 --ctx 32768 --extra=--ssd-streaming --extra=--ssd-streaming-cache-experts --extra=32GB"
    )
    assert engine == "ds4"
    assert opts == {
        "ctx": 32768,
        "extra_args": ["--ssd-streaming", "--ssd-streaming-cache-experts", "32GB"],
    }


def test_local_models_cli_filters_embeddings(monkeypatch):
    from click.testing import CliRunner

    from superqode.commands import local as local_cmd
    from superqode.commands.local import local
    from superqode.providers.local.base import LocalModel

    class FakeManager:
        def list_all(self):
            return [{"engine": "lmstudio", "running": True}]

    class FakeClient:
        async def list_models(self):
            return [
                LocalModel(id="qwen3-coder", name="Qwen Coder", supports_tools=True),
                LocalModel(id="nomic-embed-text", name="Nomic Embed"),
            ]

    monkeypatch.setattr("superqode.local.servers.get_manager", lambda: FakeManager())
    monkeypatch.setattr(local_cmd, "_local_client_for", lambda engine: FakeClient)

    result = CliRunner().invoke(local, ["models"])
    assert result.exit_code == 0
    assert "qwen3-coder" in result.output
    assert "tools" in result.output
    assert "nomic-embed" not in result.output
