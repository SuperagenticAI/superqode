"""llama.cpp (provider id 'llamacpp') lists from its OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio

import pytest

import superqode.local.bench as bench
from superqode.app_main import SuperQodeApp


class _Log:
    def __init__(self):
        self.msgs = []

    def add_info(self, t):
        self.msgs.append(("info", t))

    def add_error(self, t):
        self.msgs.append(("error", t))

    def add_system(self, t):
        self.msgs.append(("system", t))

    def write(self, x):
        self.msgs.append(("write", getattr(x, "plain", str(x))))

    def clear(self):
        self.msgs.clear()

    @property
    def text(self):
        return "\n".join(m[1] for m in self.msgs)


def _app():
    app = SuperQodeApp.__new__(SuperQodeApp)
    app._reopened = False
    app._show_local_provider_picker = lambda log, **k: setattr(app, "_reopened", True)
    app._picker_link_style = lambda style, n: style
    app.set_timer = lambda *a, **k: None
    app._ensure_input_focus = lambda: None
    return app


def test_llamacpp_no_server_no_gguf_shows_stable_guidance_no_flash(monkeypatch):
    import superqode.local.servers as servers

    monkeypatch.setattr(bench, "list_endpoint_models", lambda *a, **k: [])
    monkeypatch.setattr(servers, "discover_gguf_models", lambda *a, **k: [])
    app = _app()
    log = _Log()
    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))
    # Guidance stays as the final state; we must NOT auto-reopen the picker
    # (that clears the log and looks like a flash where nothing appears).
    assert app._reopened is False
    assert app._awaiting_local_model is False
    assert "llama-server" in log.text
    assert ":connect" in log.text


def test_llamacpp_no_server_lists_cached_gguf_as_launchable_choices(monkeypatch):
    import superqode.local.servers as servers

    monkeypatch.setattr(bench, "list_endpoint_models", lambda *a, **k: [])
    monkeypatch.setattr(
        servers,
        "discover_gguf_models",
        lambda *a, **k: [
            {"id": "qwen2.5-0.5b.gguf", "path": "/cache/qwen2.5-0.5b.gguf"},
            {"id": "gemma.gguf", "path": "/cache/gemma.gguf"},
        ],
    )
    app = _app()
    pinned = []
    app._pin_local_prompt_to_input = lambda placeholder, log, **kwargs: pinned.append(
        (placeholder, kwargs)
    )
    log = _Log()
    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))
    assert app._local_model_list == ["/cache/gemma.gguf", "/cache/qwen2.5-0.5b.gguf"]
    assert app._awaiting_local_model is True
    assert "Select one to start llama.cpp" in log.text
    assert "qwen2.5-0.5b.gguf" in log.text
    assert pinned == []


def test_llamacpp_prioritizes_shared_laguna_gguf(monkeypatch):
    import superqode.local.servers as servers

    monkeypatch.setattr(bench, "list_endpoint_models", lambda *a, **k: [])
    monkeypatch.setattr(
        servers,
        "discover_gguf_models",
        lambda *a, **k: [
            {"id": "qwen.gguf", "path": "/cache/qwen.gguf"},
            {
                "id": "laguna-s-2.1-Q4_K_M.gguf",
                "path": "/models/laguna-s-2.1/laguna-s-2.1-Q4_K_M.gguf",
            },
        ],
    )
    app = _app()
    log = _Log()

    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))

    assert "Poolside Laguna S 2.1" in log.text
    assert app._local_model_list[0].endswith("laguna-s-2.1-Q4_K_M.gguf")
    assert "262,144 ctx" in log.text


def test_selecting_gguf_prompts_before_launch(monkeypatch):
    # Picking a GGUF when no server is up must ask before launching llama-server,
    # mapping provider id 'llamacpp' to the manager engine 'llama.cpp'.
    import superqode.local.servers as servers

    class _Mgr:
        def status(self, engine):
            assert engine == "llama.cpp"  # provider 'llamacpp' -> engine 'llama.cpp'
            return {"running": False}

    monkeypatch.setattr(servers, "get_manager", lambda: _Mgr())

    app = SuperQodeApp.__new__(SuperQodeApp)
    app._started = []
    app._connected = []
    app.run_worker = lambda coro: app._started.append(coro)
    app._connect_byok_mode = lambda p, m, log: app._connected.append((p, m))
    app._show_local_provider_picker = lambda log, **k: None
    app._pin_local_prompt_to_input = lambda placeholder, log, **kwargs: setattr(
        app, "_pinned_placeholder", placeholder
    )
    app._reset_input_placeholder = lambda: setattr(app, "_placeholder_reset", True)
    log = _Log()

    SuperQodeApp._connect_local_mode(app, "llamacpp", "/cache/qwen.gguf", log)
    assert app._started == []
    assert app._connected == []
    assert app._awaiting_local_connect_start["engine"] == "llama.cpp"
    assert "llama-server -m /cache/qwen.gguf --host 127.0.0.1 --port 8081" in log.text
    assert ":local serve llama.cpp --model /cache/qwen.gguf" in log.text
    assert "Start llama.cpp yourself" in app._pinned_placeholder

    assert SuperQodeApp._handle_local_connect_start_input(app, "", log) is True
    assert len(app._started) == 1
    assert app._placeholder_reset is True
    app._started[0].close()


def test_ds4_offline_picker_offers_downloaded_laguna(monkeypatch, tmp_path):
    import superqode.local.servers as servers
    from superqode.providers.local.ds4 import DS4Client

    model = tmp_path / "laguna-s-2.1-Q4_K_M.gguf"
    model.write_bytes(b"gguf")

    async def unavailable(_self):
        return False

    monkeypatch.setattr(DS4Client, "is_available", unavailable)
    monkeypatch.setattr(
        servers,
        "discover_gguf_models",
        lambda: [{"id": model.name, "path": str(model)}],
    )

    app = _app()
    log = _Log()
    asyncio.run(SuperQodeApp._show_local_provider_models(app, "ds4", log))

    assert app._local_selected_provider == "ds4"
    assert app._local_model_list == [str(model)]
    assert app._awaiting_local_model is True
    assert "Poolside Laguna S 2.1" in log.text
    assert "build/start DwarfStar" in log.text
    assert "llama.cpp" in log.text


def test_ds4_running_picker_names_all_laguna_api_variants(monkeypatch):
    from superqode.providers.local.ds4 import DS4Client

    async def models_response(_self, method, endpoint, data=None, timeout=10.0):
        return {
            "data": [
                {"id": "laguna-s-2.1", "name": "Laguna S 2.1"},
                {"id": "laguna-s-2.1-chat", "name": "Laguna S 2.1"},
                {"id": "laguna-s-2.1-reasoner", "name": "Laguna S 2.1"},
            ]
        }

    async def server_state(_provider_id, _log):
        return False

    monkeypatch.setattr(DS4Client, "_async_request", models_response)
    app = _app()
    app._render_local_server_state = server_state
    log = _Log()

    asyncio.run(SuperQodeApp._show_local_provider_models(app, "ds4", log))

    assert app._local_model_list == [
        "laguna-s-2.1",
        "laguna-s-2.1-chat",
        "laguna-s-2.1-reasoner",
    ]
    assert "Poolside Laguna S 2.1 (default)" in log.text
    assert "Poolside Laguna S 2.1 Chat (thinking off)" in log.text
    assert "Poolside Laguna S 2.1 Reasoner (thinking on)" in log.text


def test_laguna_tui_commands_resolve_shared_file_and_runtime_flags(monkeypatch, tmp_path):
    model = tmp_path / "laguna-s-2.1-Q4_K_M.gguf"
    model.write_bytes(b"gguf")
    monkeypatch.setenv("SUPERQODE_LAGUNA_GGUF", str(model))

    ds4_native = SuperQodeApp._native_local_server_command("ds4", model="laguna-s-2.1", ctx=32768)
    llama_native = SuperQodeApp._native_local_server_command(
        "llama.cpp", model="laguna-s-2.1", ctx=32768
    )

    assert f"-m {model}" in ds4_native
    assert "--ctx 32768" in ds4_native
    assert f"-m {model}" in llama_native
    assert "-c 32768" in llama_native
    assert "--jinja" in llama_native
    assert "--reasoning-preserve" in llama_native
    assert "--alias laguna-s-2.1" in llama_native
    assert (
        SuperQodeApp._local_serve_command("ds4", "laguna-s-2.1")
        == ":local serve ds4 --model laguna-s-2.1 --ctx 32768 --build"
    )


def test_selecting_ds4_laguna_prompts_before_build_and_launch(monkeypatch, tmp_path):
    import superqode.local.servers as servers

    model = tmp_path / "laguna-s-2.1-Q4_K_M.gguf"
    model.write_bytes(b"gguf")
    monkeypatch.setenv("SUPERQODE_LAGUNA_GGUF", str(model))

    class _Mgr:
        def status(self, engine):
            assert engine == "ds4"
            return {"running": False}

    monkeypatch.setattr(servers, "get_manager", lambda: _Mgr())

    app = _app()
    app._connected = []
    app._connect_byok_mode = lambda p, m, log: app._connected.append((p, m))
    app._pin_local_prompt_to_input = lambda *args, **kwargs: None
    log = _Log()

    SuperQodeApp._connect_local_mode(app, "ds4", "laguna-s-2.1", log)

    assert app._connected == []
    assert app._awaiting_local_connect_start["engine"] == "ds4"
    assert "--ctx 32768 --build" in app._awaiting_local_connect_start["command"]
    assert f"-m {model}" in app._awaiting_local_connect_start["native_command"]


def test_redraw_tolerates_string_model_entries():
    # Arrow-key navigation calls _redraw_local_provider_models, which used to
    # assume rich LocalModel objects and crashed on the plain id strings stored
    # for OpenAI-compatible / HF lists ('str' object has no attribute 'running').
    class _NavLog:
        auto_scroll = True

        def clear(self):
            pass

        def write(self, x):
            self._w = getattr(x, "plain", str(x))

        def scroll_home(self, *a, **k):
            pass

        def scroll_to(self, *a, **k):
            pass

    app = SuperQodeApp.__new__(SuperQodeApp)
    app._local_selected_provider = "llamacpp"
    app._local_cached_models = ["Qwen/Qwen3-30B-A3B", "microsoft/phi-2"]
    app._local_model_list = app._local_cached_models
    app._local_highlighted_model_index = 1
    app._picker_link_style = lambda style, n: style

    log = _NavLog()
    SuperQodeApp._redraw_local_provider_models(app, log)  # must not raise
    assert "phi-2" in log._w


def test_llamacpp_server_up_lists_models_and_arms_selection(monkeypatch):
    monkeypatch.setattr(
        bench, "list_endpoint_models", lambda *a, **k: ["my-gguf-model", "nomic-embed-text"]
    )
    app = _app()
    log = _Log()
    log.write("Local Providers\nAvailable (9)\n[7] llama.cpp Server")
    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))
    # embedding model filtered out
    assert app._local_model_list == ["my-gguf-model"]
    assert app._awaiting_local_model is True
    assert app._local_selected_provider == "llamacpp"
    assert app._reopened is False
    assert "Local Providers" not in log.text
    assert "Available (9)" not in log.text
    assert "llama.cpp Server" in log.text
