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


def test_llamacpp_no_server_lists_cached_gguf_for_autolaunch(monkeypatch):
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
    log = _Log()
    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))
    # The picker arms selection with GGUF PATHS so selecting one asks before launch.
    assert app._local_model_list == ["/cache/qwen2.5-0.5b.gguf", "/cache/gemma.gguf"]
    assert app._awaiting_local_model is True
    assert app._local_selected_provider == "llamacpp"
    assert "ask before starting llama-server" in log.text
    # Display uses basenames, not full paths.
    assert "qwen2.5-0.5b.gguf" in log.text


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
    log = _Log()

    SuperQodeApp._connect_local_mode(app, "llamacpp", "/cache/qwen.gguf", log)
    assert app._started == []
    assert app._connected == []
    assert app._awaiting_local_connect_start["engine"] == "llama.cpp"
    assert ":local serve llama.cpp --model /cache/qwen.gguf" in log.text

    assert SuperQodeApp._handle_local_connect_start_input(app, "", log) is True
    assert len(app._started) == 1
    app._started[0].close()


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
    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))
    # embedding model filtered out
    assert app._local_model_list == ["my-gguf-model"]
    assert app._awaiting_local_model is True
    assert app._local_selected_provider == "llamacpp"
    assert app._reopened is False
